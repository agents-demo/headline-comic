"""Tests for the S1-S9 pipeline runner (T018)."""

import tempfile
import unittest
from pathlib import Path

from src.flow.pipeline import (
    GENERATION_STAGES,
    PipelineError,
    TextPipeline,
    rerun_window,
    route_failures,
)
from src.flow.runlog import read_entries
from src.providers.llm import ChatResult


def _check(check_id: str, passed: bool, *, owner: str = "story") -> dict:
    return {"check_id": check_id, "passed": passed, "blocking": True, "message": check_id, "owner": owner}


def _doc(*checks: dict) -> dict:
    return {"schema_version": "1.0", "passed": all(c["passed"] for c in checks), "checks": list(checks)}


class RouteFailuresTests(unittest.TestCase):
    def test_maps_failures_to_owning_stage(self) -> None:
        checks_doc = _doc(
            _check("names-story", False, owner="story"),
            _check("citations", False, owner="summary"),
        )
        verifier_doc = _doc(_check("verify-causation", False, owner="story"))
        self.assertEqual(
            route_failures(checks_doc, verifier_doc),
            {"S4": ["citations"], "S5": ["names-story", "verify-causation"]},
        )

    def test_ignores_passed_and_non_blocking(self) -> None:
        checks_doc = _doc(
            _check("names-story", True, owner="story"),
            {"check_id": "optional", "passed": False, "blocking": False, "owner": "storyboard"},
        )
        self.assertEqual(route_failures(checks_doc, {}), {})

    def test_unknown_owner_defaults_to_checks_stage(self) -> None:
        checks_doc = _doc(_check("mystery", False, owner="made-up"))
        self.assertEqual(route_failures(checks_doc, {}), {"S7": ["mystery"]})


class RerunWindowTests(unittest.TestCase):
    def test_earliest_failure_drives_the_window(self) -> None:
        self.assertEqual(rerun_window({"S5": ["a"]}), ("S5", "S6"))
        self.assertEqual(rerun_window({"S3": ["a"], "S5": ["b"]}), GENERATION_STAGES)
        self.assertEqual(rerun_window({"S6": ["a"]}), ("S6",))

    def test_non_generation_failures_do_not_rerun(self) -> None:
        self.assertEqual(rerun_window({"S7": ["a"]}), ())
        self.assertEqual(rerun_window({}), ())


class _FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        self.t += 0.25
        return self.t


def _fake_chat(content: str):
    def chat(messages):
        return ChatResult(content=content, model="test", prompt_tokens=10, completion_tokens=5)
    return chat


class _RetryPipeline(TextPipeline):
    """A pipeline whose generation stages are faked so the retry loop is testable."""

    def __init__(self, root: Path, failures_remaining: list[int], **kwargs) -> None:
        self._failures_remaining = failures_remaining
        super().__init__(
            workspace_root=root,
            run_id="r1",
            selected_ids=["c1", "c2", "c3", "c4", "c5"],
            chat=_fake_chat("{}"),
            clock=_FakeClock(),
            **kwargs,
        )

    def _s1_fetch(self) -> None:
        self.state["tagged"] = []

    def _s2_pick(self) -> None:
        self.state["selected"] = [{"candidate_id": f"c{i}"} for i in range(1, 6)]

    def _s3_articles(self) -> None:
        self.state["articles"] = []

    def _generate(self, stage_id: str) -> None:
        if stage_id == "S7":
            failing = bool(self._failures_remaining and self._failures_remaining[0] > 0)
            if self._failures_remaining:
                self._failures_remaining[0] -= 1
            self.state["checks"] = _doc(
                _check("names-story", not failing, owner="story"),
            )
        elif stage_id == "S8":
            self.state["verifier"] = _doc(_check("verify-causation", True, owner="story"))
        # S3-S6 leave whatever is already in state untouched.

    def _finalize(self) -> None:
        pass

    def _s9_approval(self) -> None:
        from src.flow.hitl import Decision, evaluate_approval

        self.state["approval"] = evaluate_approval(
            self.state.get("checks", {}), self.state.get("verifier", {}), decision=Decision.APPROVE
        )


class GenerationWiringTests(unittest.TestCase):
    """Smoke-test the pipeline's generation wiring against the T006 fixture."""

    def _fixture(self) -> tuple[dict, dict, dict]:
        fixtures = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "t006-sample"
        import json as _json

        ledger = _json.loads((fixtures / "ledger.json").read_text(encoding="utf-8"))
        story = _json.loads((fixtures / "story.json").read_text(encoding="utf-8"))
        storyboard = _json.loads((fixtures / "storyboard.json").read_text(encoding="utf-8"))
        return ledger, story, storyboard

    def _summaries(self) -> dict:
        return {
            "schema_version": "1.0",
            "summaries": [
                {
                    "story_id": f"story-{i}",
                    "sentences": [
                        {"text": f"{i} first.", "ledger_fact_ids": [f"f{i}-1"]},
                        {"text": f"{i} second.", "ledger_fact_ids": [f"f{i}-1"]},
                    ],
                }
                for i in range(1, 6)
            ],
        }

    def test_generate_checks_runs_over_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger, story_doc, storyboard_doc = self._fixture()
            pipeline = TextPipeline(
                workspace_root=Path(tmp),
                run_id="r1",
                selected_ids=["c1", "c2", "c3", "c4", "c5"],
                chat=_fake_chat("{}"),
                verify_chat=_fake_chat("{}"),
            )
            pipeline.state["ledger"] = ledger
            pipeline.state["summaries"] = self._summaries()
            pipeline.state["story"] = story_doc
            pipeline.state["storyboard"] = storyboard_doc
            pipeline._generate_checks()
            self.assertIn("checks", pipeline.state["checks"])
            self.assertTrue(pipeline.state["checks"]["passed"])

    def test_generate_verifier_runs_over_fixture(self) -> None:
        import json as _json

        def verify_chat(messages):
            items = [
                {"check_id": cid, "passed": True, "reason": "ok"}
                for cid in ["verify-summaries", "verify-causation", "verify-real-people", "verify-graphic", "verify-satire"]
            ]
            return ChatResult(content=_json.dumps({"items": items}), model="test", prompt_tokens=1, completion_tokens=1)

        with tempfile.TemporaryDirectory() as tmp:
            ledger, story_doc, storyboard_doc = self._fixture()
            pipeline = TextPipeline(
                workspace_root=Path(tmp),
                run_id="r1",
                selected_ids=["c1", "c2", "c3", "c4", "c5"],
                chat=_fake_chat("{}"),
                verify_chat=verify_chat,
            )
            pipeline.state["ledger"] = ledger
            pipeline.state["summaries"] = self._summaries()
            pipeline.state["story"] = story_doc
            pipeline.state["storyboard"] = storyboard_doc
            pipeline._generate_verifier()
            self.assertTrue(pipeline.state["verifier"]["passed"])
            self.assertEqual(len(pipeline.state["verifier"]["checks"]), 5)


class RetryLoopTests(unittest.TestCase):
    def test_recovers_on_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            # First S7 run fails once, then passes.
            pipeline = _RetryPipeline(Path(tmp), failures_remaining=[1])
            result = pipeline.run()
            self.assertTrue(result.passed)
            self.assertEqual(result.loops, 1)
            self.assertEqual(result.failures, {})

            events = [e["event"] for e in read_entries(Path(tmp), "r1")]
            self.assertIn("retry", events)
            self.assertIn("stage", events)
            self.assertIn("run_end", events)

    def test_stops_after_max_loops_with_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            # Always fails; the loop must stop after max_loops (2).
            pipeline = _RetryPipeline(Path(tmp), failures_remaining=[10])
            result = pipeline.run()
            self.assertFalse(result.passed)
            self.assertEqual(result.loops, 2)
            self.assertEqual(result.failures, {"S5": ("names-story",)})

    def test_stage_failure_aborts_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pipeline = TextPipeline(
                workspace_root=Path(tmp),
                run_id="r1",
                selected_ids=["c1", "c2", "c3", "c4", "c5"],
                chat=_fake_chat("{}"),
                clock=_FakeClock(),
            )
            # No config_path means S1 raises.
            result = pipeline.run()
            self.assertFalse(result.passed)
            self.assertIn("config_path", result.message)

            entries = read_entries(Path(tmp), "r1")
            self.assertIn("run_end", [e["event"] for e in entries])
            self.assertTrue(any(e["event"] == "stage_error" for e in entries))


if __name__ == "__main__":
    unittest.main()
