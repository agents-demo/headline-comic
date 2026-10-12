"""Tests for T007 media budget, host, write, and dispatch policies."""

import json
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from src.permissions.media_guard import (
    BudgetExceeded,
    MissingUnitPrice,
    PolicyDenied,
    UnitPrice,
    estimate_storyboard_cost,
    guarded_storyboard_call,
    project_actual_spend,
    prepare_storyboard_quote,
    project_committed_spend,
    record_actual_cost,
    require_allowed_host,
    require_allowed_write_path,
    settle_run_cost,
)


class PaidProvider:
    def __init__(self):
        self.calls = 0
        self.output_path = None

    def generate(self, *, output_path, **kwargs):
        self.calls += 1
        self.output_path = output_path
        return "generated"


class MediaGuardTests(unittest.TestCase):
    def setUp(self):
        self.storyboard = {"shots": [{"narration": "Hello town"}, {"narration": "A longer route"}]}
        self.prices = {
            "image": UnitPrice.create("image-provider", "keyframe", "0.01"),
            "video": UnitPrice.create("AniDoodle", "shot", "0"),
            "tts": UnitPrice.create("tts-provider", "1000_characters", "0.002"),
        }

    def test_storyboard_quote_reserves_retry_and_tracks_projected_cost(self):
        quote = estimate_storyboard_cost(
            self.storyboard,
            self.prices,
            planned_categories=("image", "video", "tts"),
            project_actual_usd="2.50",
        )
        self.assertAlmostEqual(quote["run_estimate_usd"], 0.040096)
        self.assertAlmostEqual(quote["project_total_usd"], 2.540096)
        self.assertEqual([item["category"] for item in quote["items"]], ["image", "video", "tts"])

    def test_missing_price_fails_closed(self):
        with self.assertRaises(MissingUnitPrice):
            estimate_storyboard_cost(
                self.storyboard,
                {"video": self.prices["video"]},
                planned_categories=("image",),
            )

    def test_run_and_project_budgets_hard_stop(self):
        with self.assertRaises(BudgetExceeded):
            estimate_storyboard_cost(
                self.storyboard, self.prices, planned_categories=("image",), run_budget_usd="0.01"
            )
        with self.assertRaises(BudgetExceeded):
            estimate_storyboard_cost(
                self.storyboard,
                self.prices,
                planned_categories=("image",),
                project_actual_usd="299.99",
                project_budget_usd="300",
            )

    def test_domain_policy_uses_exact_https_host_matching(self):
        self.assertEqual(
            require_allowed_host("https://api.tavily.com/search", {"api.tavily.com"}),
            "api.tavily.com",
        )
        for url in ("http://api.tavily.com/search", "https://api.tavily.com.attacker.test/", "https://api.tavily.com:444/"):
            with self.subTest(url=url), self.assertRaises(PolicyDenied):
                require_allowed_host(url, {"api.tavily.com"})

    def test_write_policy_allows_run_artifacts_and_gates_cast_setup(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.assertEqual(
                require_allowed_write_path(root / "runs" / "r1" / "video.mp4", workspace_root=root),
                (root / "runs" / "r1" / "video.mp4").resolve(),
            )
            with self.assertRaises(PolicyDenied):
                require_allowed_write_path(root / "assets" / "cast" / "pigeon.png", workspace_root=root)
            self.assertEqual(
                require_allowed_write_path(
                    root / "assets" / "cast" / "pigeon.png", workspace_root=root, allow_cast_setup=True
                ),
                (root / "assets" / "cast" / "pigeon.png").resolve(),
            )
            with self.assertRaises(PolicyDenied):
                require_allowed_write_path(root / "docs" / "leak.txt", workspace_root=root)

    def test_project_total_reads_actual_costs_and_fails_on_malformed_state(self):
        with tempfile.TemporaryDirectory() as temp:
            runs = Path(temp) / "runs"
            (runs / "r1").mkdir(parents=True)
            (runs / "r1" / "cost.json").write_text(json.dumps({"run_actual_usd": 1.25}), encoding="utf-8")
            self.assertEqual(project_actual_spend(runs), Decimal("1.25"))
            (runs / "r2").mkdir()
            (runs / "r2" / "cost.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError):
                project_actual_spend(runs)

    def test_composite_guard_requires_approval_quote_and_policy_before_call(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            provider = PaidProvider()
            runs = root / "runs" / "r1"
            runs.mkdir(parents=True)
            quote = prepare_storyboard_quote(
                self.storyboard, self.prices, workspace_root=root, run_id="r1",
                planned_categories=("image", "video")
            )
            approval_path = runs / "approval.json"
            approval_path.write_text(json.dumps({
                "run_id": "r1",
                "approved_actions": ["image.generate"],
                "approved_estimate_usd": quote["run_estimate_usd"],
            }), encoding="utf-8")
            output = runs / "keyframe.png"
            result = guarded_storyboard_call(
                provider,
                action="image.generate",
                approval_path=approval_path,
                run_id="r1",
                storyboard=self.storyboard,
                unit_prices=self.prices,
                planned_categories=("image", "video"),
                target_url="https://images.example.test/generate",
                allowed_hosts={"images.example.test"},
                output_path=output,
                workspace_root=root,
            )
            self.assertEqual(result, "generated")
            self.assertEqual(provider.calls, 1)
            self.assertEqual(provider.output_path, output.resolve())
            record = json.loads((runs / "cost.json").read_text(encoding="utf-8"))
            self.assertEqual(record["run_estimate_usd"], 0.04)
            self.assertEqual(project_committed_spend(root / "runs"), Decimal("0.04"))
            updated = record_actual_cost(workspace_root=root, run_id="r1", category="image", actual_usd="0.02")
            self.assertEqual(updated["run_actual_usd"], 0.02)
            self.assertEqual(project_committed_spend(root / "runs"), Decimal("0.04"))
            self.assertEqual(json.loads((runs / "cost.json").read_text(encoding="utf-8"))["run_actual_usd"], 0.02)
            again = guarded_storyboard_call(
                provider, action="image.generate", approval_path=approval_path, run_id="r1",
                storyboard=self.storyboard, unit_prices=self.prices, planned_categories=("image", "video"),
                target_url="https://images.example.test/generate", allowed_hosts={"images.example.test"},
                output_path=output, workspace_root=root
            )
            self.assertEqual(again, "generated")
            self.assertEqual(json.loads((runs / "cost.json").read_text(encoding="utf-8"))["run_actual_usd"], 0.02)
            settled = settle_run_cost(workspace_root=root, run_id="r1")
            self.assertTrue(settled["settled"])
            self.assertEqual(project_committed_spend(root / "runs"), Decimal("0.02"))
            with self.assertRaises(PolicyDenied):
                guarded_storyboard_call(
                    provider, action="image.generate", approval_path=approval_path, run_id="r1",
                    storyboard=self.storyboard, unit_prices=self.prices, planned_categories=("image", "video"),
                    target_url="https://images.example.test/generate", allowed_hosts={"images.example.test"},
                    output_path=output, workspace_root=root
                )

    def test_quote_blocks_before_call_when_project_budget_is_exceeded(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            prior = root / "runs" / "old-run"
            prior.mkdir(parents=True)
            (prior / "cost.json").write_text(json.dumps({
                "run_estimate_usd": 300, "run_actual_usd": 299.99, "settled": True
            }), encoding="utf-8")
            with self.assertRaises(BudgetExceeded):
                prepare_storyboard_quote(
                    self.storyboard, self.prices, workspace_root=root, run_id="r1",
                    planned_categories=("image", "video")
                )
    def test_quote_blocks_before_call_when_run_budget_is_exceeded(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            expensive = {"image": UnitPrice.create("image-provider", "keyframe", "100")}
            with self.assertRaises(BudgetExceeded):
                prepare_storyboard_quote(
                    self.storyboard, expensive, workspace_root=root, run_id="r1",
                    planned_categories=("image",)
                )
    def test_composite_guard_blocks_missing_cost_confirmation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            provider = PaidProvider()
            runs = root / "runs" / "r1"
            runs.mkdir(parents=True)
            prepare_storyboard_quote(
                self.storyboard, self.prices, workspace_root=root, run_id="r1",
                planned_categories=("image", "video")
            )
            approval_path = runs / "approval.json"
            approval_path.write_text(json.dumps({
                "run_id": "r1", "approved_actions": ["image.generate"], "approved_estimate_usd": 999
            }), encoding="utf-8")
            with self.assertRaisesRegex(PermissionError, "does not match"):
                guarded_storyboard_call(
                    provider,
                    action="image.generate",
                    approval_path=approval_path,
                    run_id="r1",
                    storyboard=self.storyboard,
                    unit_prices=self.prices,
                    planned_categories=("image", "video"),
                    target_url="https://images.example.test/generate",
                    allowed_hosts={"images.example.test"},
                    output_path=runs / "keyframe.png",
                    workspace_root=root,
                )
            self.assertEqual(provider.calls, 0)


if __name__ == "__main__":
    unittest.main()