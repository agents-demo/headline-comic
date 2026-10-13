"""Deterministic mapping + budget-guard tests for the T027 video_gen skill."""

import json
from pathlib import Path
import tempfile
import unittest

from src.permissions.approval_guard import ApprovalRequired
from src.permissions.media_guard import CostRecordError, MissingUnitPrice, UnitPrice, prepare_storyboard_quote
from src.providers.contracts import VideoResult
from src.skills.video_gen import (
    MAX_DURATION_S,
    VideoGenError,
    run as run_video_gen,
    serialize_video_scenes,
    total_duration_s,
    video_specs,
)

STORYBOARD = {
    "schema_version": "1.0",
    "shots": [
        {
            "shot_id": "shot-01",
            "beat": 0,
            "source_ref": 0,
            "characters": ["courier", "pigeon"],
            "camera": "wide establishing view",
            "action": "The courier points toward a winding town path.",
            "narration": "Tonight, our little town takes the scenic route.",
            "duration_s": 5,
        },
        {
            "shot_id": "shot-02",
            "beat": 1,
            "source_ref": 1,
            "characters": ["courier"],
            "camera": "slow pan across the harbor path",
            "action": "The courier follows the newly installed lamps.",
            "narration": "New lamps brighten the harbor path.",
            "duration_s": 6,
        },
    ],
}


class _FakeVideoProvider:
    """In-memory provider; fails its first `fail_times` calls, then succeeds."""

    def __init__(self, fail_times: int = 0) -> None:
        self.fail_times = fail_times
        self.calls = 0
        self.requests = []

    def render(self, request):
        self.calls += 1
        self.requests.append(request)
        if self.calls <= self.fail_times:
            raise RuntimeError("provider transient failure")
        return VideoResult(
            video_path=Path(request.run_id) / "video.mp4",
            manifest_path=Path(request.run_id) / "manifest.json",
            duration_s=11.0,
            has_audio=False,
        )


class VideoSpecsTests(unittest.TestCase):
    def test_specs_carry_scene_spec_plus_duration(self) -> None:
        specs = video_specs(STORYBOARD)
        self.assertEqual([s["shot_id"] for s in specs], ["shot-01", "shot-02"])
        for spec in specs:
            self.assertIn(spec["camera"]["mode"], ("zoom", "overhead"))
            self.assertIn("duration_s", spec)
        self.assertEqual(specs[0]["duration_s"], 5.0)

    def test_missing_shots_fails_closed(self) -> None:
        with self.assertRaises(VideoGenError):
            video_specs({"shots": []})

    def test_out_of_range_duration_is_rejected(self) -> None:
        bad = {"shots": [dict(STORYBOARD["shots"][0], duration_s=0)]}
        with self.assertRaises(VideoGenError):
            video_specs(bad)

    def test_total_duration_sums(self) -> None:
        self.assertEqual(total_duration_s(video_specs(STORYBOARD)), 11.0)


class SerializeVideoScenesTests(unittest.TestCase):
    def test_serializes_export_const_video_scenes(self) -> None:
        text = serialize_video_scenes(video_specs(STORYBOARD))
        self.assertIn("export const videoScenes =", text)
        self.assertIn('"shot_id": "shot-01"', text)
        self.assertTrue(text.rstrip().endswith(";"))


class RunVideoGenTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)

    def tearDown(self) -> None:
        self._temp.cleanup()

    def _cost(self, run_id: str) -> dict:
        return json.loads((self.root / "runs" / run_id / "cost.json").read_text(encoding="utf-8"))

    def _scenes(self, run_id: str) -> str:
        return (self.root / "runs" / run_id / "video_scenes.ts").read_text(encoding="utf-8")

    def test_zero_cost_path_records_without_settling(self) -> None:
        provider = _FakeVideoProvider()
        result = run_video_gen(
            STORYBOARD,
            provider=provider,
            workspace_root=self.root,
            run_id="t027-zero",
            unit_prices={"video": UnitPrice.create("anidoodle", "shot", "0")},
        )
        self.assertFalse(result.has_audio)
        self.assertIn("videoScenes", self._scenes("t027-zero"))
        cost = self._cost("t027-zero")
        # settlement is deferred to the end of the media phase
        self.assertFalse(cost["settled"])
        self.assertEqual(cost["run_actual_usd"], 0.0)
        item = next(i for i in cost["items"] if i["category"] == "video")
        self.assertEqual(item["actual_usd"], 0.0)

    def test_standalone_run_reserves_video_line(self) -> None:
        run_video_gen(
            STORYBOARD,
            provider=_FakeVideoProvider(),
            workspace_root=self.root,
            run_id="t027-standalone",
            unit_prices={"video": UnitPrice.create("anidoodle", "shot", "0")},
        )
        cost = self._cost("t027-standalone")
        self.assertEqual([i["category"] for i in cost["items"]], ["video"])

    def test_reuses_image_and_video_reservation(self) -> None:
        prepare_storyboard_quote(
            STORYBOARD,
            {
                "image": UnitPrice.create("anidoodle", "keyframe", "0"),
                "video": UnitPrice.create("anidoodle", "shot", "0"),
            },
            workspace_root=self.root,
            run_id="t027-reuse",
            planned_categories=("image", "video"),
        )
        result = run_video_gen(
            STORYBOARD,
            provider=_FakeVideoProvider(),
            workspace_root=self.root,
            run_id="t027-reuse",
            unit_prices={"video": UnitPrice.create("anidoodle", "shot", "0")},
        )
        self.assertEqual(result.duration_s, 11.0)
        cost = self._cost("t027-reuse")
        self.assertEqual(sorted(i["category"] for i in cost["items"]), ["image", "video"])
        self.assertFalse(cost["settled"])

    def test_rejects_reservation_without_video_line(self) -> None:
        prepare_storyboard_quote(
            STORYBOARD,
            {"image": UnitPrice.create("anidoodle", "keyframe", "0")},
            workspace_root=self.root,
            run_id="t027-image-only",
            planned_categories=("image",),
        )
        with self.assertRaises(CostRecordError):
            run_video_gen(
                STORYBOARD,
                provider=_FakeVideoProvider(),
                workspace_root=self.root,
                run_id="t027-image-only",
                unit_prices={"video": UnitPrice.create("anidoodle", "shot", "0")},
            )

    def test_retries_then_succeeds(self) -> None:
        provider = _FakeVideoProvider(fail_times=1)
        run_video_gen(
            STORYBOARD,
            provider=provider,
            workspace_root=self.root,
            run_id="t027-retry",
            unit_prices={"video": UnitPrice.create("anidoodle", "shot", "0")},
            max_attempts=2,
        )
        self.assertEqual(provider.calls, 2)

    def test_missing_price_fails_closed(self) -> None:
        with self.assertRaises(MissingUnitPrice):
            run_video_gen(
                STORYBOARD,
                provider=_FakeVideoProvider(),
                workspace_root=self.root,
                run_id="t027-missing",
                unit_prices={},
            )

    def test_nonzero_price_requires_approval(self) -> None:
        with self.assertRaises(ApprovalRequired):
            run_video_gen(
                STORYBOARD,
                provider=_FakeVideoProvider(),
                workspace_root=self.root,
                run_id="t027-paid",
                unit_prices={"video": UnitPrice.create("paid", "shot", "0.50")},
            )

    def test_nonzero_price_with_approval_records_actual(self) -> None:
        approval = self.root / "approval.json"
        approval.write_text(
            json.dumps({"run_id": "t027-paid-ok", "approved_actions": ["video"]}), encoding="utf-8"
        )
        run_video_gen(
            STORYBOARD,
            provider=_FakeVideoProvider(),
            workspace_root=self.root,
            run_id="t027-paid-ok",
            unit_prices={"video": UnitPrice.create("paid", "shot", "0.50")},
            approval_path=approval,
        )
        cost = self._cost("t027-paid-ok")
        self.assertEqual(cost["run_actual_usd"], 1.0)

    def test_total_at_cap_is_rejected(self) -> None:
        long_shots = [
            dict(STORYBOARD["shots"][0], shot_id="shot-long", duration_s=MAX_DURATION_S),
        ]
        with self.assertRaises(VideoGenError):
            run_video_gen(
                {"shots": long_shots},
                provider=_FakeVideoProvider(),
                workspace_root=self.root,
                run_id="t027-long",
                unit_prices={"video": UnitPrice.create("anidoodle", "shot", "0")},
            )


if __name__ == "__main__":
    unittest.main()
