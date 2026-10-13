"""Deterministic mapping + budget-guard tests for the T023 image_gen skill."""

import json
from pathlib import Path
import tempfile
import unittest

from src.permissions.approval_guard import ApprovalRequired
from src.permissions.media_guard import MissingUnitPrice, UnitPrice
from src.providers.contracts import ImageResult
from src.skills.image_gen import (
    build_image_requests,
    generate_keyframes,
    normalize_action,
    normalize_camera,
    scene_spec,
    view_for,
)

FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "t006-sample" / "storyboard.json"

STORYBOARD = {
    "schema_version": "1.0",
    "shots": [
        {
            "shot_id": "shot-01",
            "beat": 0,
            "source_ref": 0,
            "characters": ["courier", "pigeon"],
            "camera": "wide establishing view",
            "action": "The courier points toward a winding town path as neighbors gather.",
            "narration": "Tonight, our little town takes the scenic route.",
        },
        {
            "shot_id": "shot-02",
            "beat": 1,
            "source_ref": 1,
            "characters": ["courier"],
            "camera": "slow pan across the harbor path",
            "action": "The courier follows the newly installed lamps along the water.",
            "narration": "New lamps brighten the harbor path.",
        },
    ],
}


class _FakeProvider:
    """In-memory provider; fails its first `fail_times` batch calls, then succeeds."""

    def __init__(self, fail_times: int = 0) -> None:
        self.fail_times = fail_times
        self.calls = 0
        self.batches: list[list] = []

    def generate_batch(self, requests):
        self.calls += 1
        self.batches.append(requests)
        if self.calls <= self.fail_times:
            raise RuntimeError("provider transient failure")
        results = []
        for request in requests:
            request.output_path.parent.mkdir(parents=True, exist_ok=True)
            request.output_path.write_bytes(b"\x89PNG\r\n")
            results.append(ImageResult(image_path=request.output_path, width=1280, height=720))
        return results


class NormalizeTests(unittest.TestCase):
    def test_normalize_camera_priorities(self) -> None:
        self.assertEqual(normalize_camera("overhead view of a printed map"), "overhead")
        self.assertEqual(normalize_camera("close view of seed packets"), "close")
        self.assertEqual(normalize_camera("wide establishing view"), "wide")
        self.assertEqual(normalize_camera("gentle push-in on the blue canopy"), "medium")
        self.assertEqual(normalize_camera(""), "medium")

    def test_normalize_action_priorities(self) -> None:
        self.assertEqual(normalize_action("The pigeon flutters from one lamp post"), "flutter")
        self.assertEqual(normalize_action("The courier points toward a path"), "point")
        self.assertEqual(normalize_action("The group waves outside the workshop"), "wave")
        self.assertEqual(normalize_action("The courier ties bright seed packets"), "work")
        self.assertEqual(normalize_action("The courier follows the newly installed lamps"), "walk")
        self.assertEqual(normalize_action("Neighbors gather"), "gather")
        self.assertEqual(normalize_action(""), "stand")

    def test_view_for_never_back(self) -> None:
        self.assertEqual(view_for("pigeon", "flutter"), "front")
        self.assertEqual(view_for("pigeon", "walk"), "side")
        self.assertEqual(view_for("pigeon", "stand"), "threeQuarter")
        self.assertEqual(view_for("courier", "walk"), "side")
        self.assertEqual(view_for("courier", "wave"), "front")
        self.assertEqual(view_for("courier", "stand"), "threeQuarter")
        self.assertEqual(view_for("mayor", "walk"), "side")


class SceneSpecTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def _shot(self, shot_id: str) -> dict:
        return next(s for s in self.fixture["shots"] if s["shot_id"] == shot_id)

    def test_spec_shape_and_bounded_fields(self) -> None:
        spec = scene_spec(self._shot("shot-01"))
        self.assertEqual(spec["shot_id"], "shot-01")
        self.assertIn(spec["camera"]["mode"], ("zoom", "overhead"))
        self.assertLessEqual(len(spec["characters"]), 2)
        for char in spec["characters"]:
            self.assertIn(char["name"], ("courier", "mayor", "pigeon"))
            self.assertIn(char["view"], ("front", "threeQuarter", "side", "back"))
            self.assertNotEqual(char["view"], "back")

    def test_wide_shot_uses_identity_zoom(self) -> None:
        spec = scene_spec(self._shot("shot-01"))
        self.assertEqual(spec["camera"], {"mode": "zoom", "scale": 1.0, "fx": 640.0, "fy": 360.0})
        self.assertEqual(spec["props"], [])

    def test_overhead_shot(self) -> None:
        spec = scene_spec(self._shot("shot-04"))
        self.assertEqual(spec["camera"], {"mode": "overhead"})
        self.assertEqual([c["name"] for c in spec["characters"]], ["courier", "mayor"])

    def test_close_shot_zooms_and_adds_beat_prop(self) -> None:
        spec = scene_spec(self._shot("shot-06"))
        self.assertEqual(spec["camera"]["mode"], "zoom")
        self.assertEqual(spec["camera"]["scale"], 3.0)
        self.assertEqual(spec["props"], ["fence"])


class BuildImageRequestsTests(unittest.TestCase):
    def test_requests_match_shots_and_cap_references(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            cast_dir = Path(temp) / "cast"
            output_dir = Path(temp) / "out"
            requests = build_image_requests(STORYBOARD, cast_dir, output_dir)
            self.assertEqual([r.output_path.name for r in requests], ["shot-01.png", "shot-02.png"])
            for request in requests:
                self.assertLessEqual(len(request.reference_images), 3)
                # Prompt carries the scene spec and round-trips.
                spec = json.loads(request.prompt)
                self.assertEqual(spec["shot_id"], request.output_path.stem)
            # shot-01 has two characters + town = 3 references, deduped.
            self.assertEqual(len(requests[0].reference_images), 3)


class GenerateKeyframesTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)

    def tearDown(self) -> None:
        self._temp.cleanup()

    def _cost(self, run_id: str) -> dict:
        return json.loads((self.root / "runs" / run_id / "cost.json").read_text(encoding="utf-8"))

    def test_zero_cost_path_records_without_settling(self) -> None:
        provider = _FakeProvider()
        results = generate_keyframes(
            STORYBOARD,
            provider=provider,
            workspace_root=self.root,
            run_id="t023-zero",
            unit_prices={"image": UnitPrice.create("anidoodle", "keyframe", "0")},
        )
        self.assertEqual(len(results), 2)
        for result in results:
            self.assertTrue(result.image_path.is_file())
        cost = self._cost("t023-zero")
        # settlement is deferred to the end of the media phase, so a later video
        # stage can still record against the same run quote
        self.assertFalse(cost["settled"])
        self.assertEqual(cost["run_actual_usd"], 0.0)
        item = next(i for i in cost["items"] if i["category"] == "image")
        self.assertEqual(item["actual_usd"], 0.0)

    def test_combined_quote_reserves_image_and_video(self) -> None:
        provider = _FakeProvider()
        generate_keyframes(
            STORYBOARD,
            provider=provider,
            workspace_root=self.root,
            run_id="t023-combined",
            unit_prices={
                "image": UnitPrice.create("anidoodle", "keyframe", "0"),
                "video": UnitPrice.create("anidoodle", "shot", "0"),
            },
            planned_categories=("image", "video"),
        )
        cost = self._cost("t023-combined")
        self.assertEqual(sorted(i["category"] for i in cost["items"]), ["image", "video"])

    def test_retries_then_succeeds(self) -> None:
        provider = _FakeProvider(fail_times=1)
        results = generate_keyframes(
            STORYBOARD,
            provider=provider,
            workspace_root=self.root,
            run_id="t023-retry",
            unit_prices={"image": UnitPrice.create("anidoodle", "keyframe", "0")},
            max_attempts=2,
        )
        self.assertEqual(provider.calls, 2)
        self.assertEqual(len(results), 2)

    def test_missing_price_fails_closed(self) -> None:
        with self.assertRaises(MissingUnitPrice):
            generate_keyframes(
                STORYBOARD,
                provider=_FakeProvider(),
                workspace_root=self.root,
                run_id="t023-missing",
                unit_prices={},
            )

    def test_nonzero_price_requires_approval(self) -> None:
        with self.assertRaises(ApprovalRequired):
            generate_keyframes(
                STORYBOARD,
                provider=_FakeProvider(),
                workspace_root=self.root,
                run_id="t023-paid",
                unit_prices={"image": UnitPrice.create("paid", "keyframe", "0.50")},
            )

    def test_nonzero_price_with_approval_records_actual(self) -> None:
        approval = self.root / "approval.json"
        approval.write_text(
            json.dumps({"run_id": "t023-paid-ok", "approved_actions": ["image"]}), encoding="utf-8"
        )
        results = generate_keyframes(
            STORYBOARD,
            provider=_FakeProvider(),
            workspace_root=self.root,
            run_id="t023-paid-ok",
            unit_prices={"image": UnitPrice.create("paid", "keyframe", "0.50")},
            approval_path=approval,
        )
        self.assertEqual(len(results), 2)
        cost = self._cost("t023-paid-ok")
        self.assertEqual(cost["run_actual_usd"], 1.0)


if __name__ == "__main__":
    unittest.main()
