"""Deterministic mapping + budget-guard tests for the T028 tts_gen skill."""

import json
from pathlib import Path
import tempfile
import unittest

from src.permissions.approval_guard import ApprovalRequired
from src.permissions.media_guard import (
    CostRecordError,
    MissingUnitPrice,
    UnitPrice,
    prepare_storyboard_quote,
)
from src.providers.contracts import TTSResult
from src.skills.tts_gen import (
    NarrationClip,
    TTSGenError,
    build_tts_requests,
    hold_last_frame_s,
    narration_shots,
    run as run_tts_gen,
    synthesize_narration,
    total_narration_chars,
)

STORYBOARD = {
    "schema_version": "1.0",
    "shots": [
        {
            "shot_id": "shot-01",
            "beat": 0,
            "narration": "Tonight, our little town takes the scenic route.",
            "duration_s": 5.0,
        },
        {
            "shot_id": "shot-02",
            "beat": 1,
            "narration": "New lamps brighten the harbor path.",
            "duration_s": 6.0,
        },
        {
            "shot_id": "shot-03",
            "beat": 1,
            "narration": "",
            "duration_s": 5.0,
        },
    ],
}


class _FakeTTSProvider:
    """Writes a fixed clip and returns a fixed duration; fails its first ``fail_times`` calls."""

    def __init__(self, fail_times: int = 0) -> None:
        self.fail_times = fail_times
        self.calls = 0
        self.requests = []

    def synthesize(self, request):
        self.calls += 1
        self.requests.append(request)
        if self.calls <= self.fail_times:
            raise RuntimeError("provider transient failure")
        request.output_path.parent.mkdir(parents=True, exist_ok=True)
        request.output_path.write_bytes(b"mp3-bytes")
        return TTSResult(audio_path=request.output_path, duration_s=6.0)


class _AlwaysFailProvider:
    def synthesize(self, request):
        raise RuntimeError("TTS down")


class NarrationMappingTests(unittest.TestCase):
    def test_narration_shots_skips_empty_and_preserves_order(self) -> None:
        self.assertEqual(
            narration_shots(STORYBOARD),
            [
                ("shot-01", "Tonight, our little town takes the scenic route."),
                ("shot-02", "New lamps brighten the harbor path."),
            ],
        )

    def test_narration_shots_requires_shots_array(self) -> None:
        with self.assertRaises(TTSGenError):
            narration_shots({"shots": []})

    def test_total_narration_chars_sums_shot_text(self) -> None:
        self.assertEqual(
            total_narration_chars(STORYBOARD),
            len("Tonight, our little town takes the scenic route.")
            + len("New lamps brighten the harbor path."),
        )

    def test_build_tts_requests_targets_audio_dir(self) -> None:
        requests = build_tts_requests(STORYBOARD, Path("audio"))
        self.assertEqual([r.output_path.name for r in requests], ["shot-01.mp3", "shot-02.mp3"])
        self.assertEqual([r.text for r in requests], [s[1] for s in narration_shots(STORYBOARD)])

    def test_hold_last_frame_computes_narration_overrun(self) -> None:
        clips = {
            "shot-01": NarrationClip("shot-01", "t", Path("a.mp3"), 7.2, True),
            "shot-02": NarrationClip("shot-02", "t", Path("b.mp3"), 4.0, True),
        }
        holds = hold_last_frame_s(STORYBOARD, clips)
        self.assertEqual(holds, {"shot-01": 2.2})

    def test_hold_last_frame_ignores_unspoken_clips(self) -> None:
        clips = {
            "shot-01": NarrationClip("shot-01", "t", Path("a.mp3"), 9.0, False),
        }
        self.assertEqual(hold_last_frame_s(STORYBOARD, clips), {})


class SynthesizeNarrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)

    def tearDown(self) -> None:
        self._temp.cleanup()

    def test_synthesize_success_writes_manifest_and_clips(self) -> None:
        provider = _FakeTTSProvider()
        audio_dir = self.root / "audio"
        audio_dir.mkdir(parents=True)
        clips = synthesize_narration(STORYBOARD, provider, audio_dir)
        self.assertEqual([c.shot_id for c in clips], ["shot-01", "shot-02"])
        self.assertTrue(all(c.spoken for c in clips))
        self.assertEqual([c.duration_s for c in clips], [6.0, 6.0])
        for clip in clips:
            self.assertTrue(clip.audio_path.is_file())
        manifest = json.loads((audio_dir / "narration.json").read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["clips"]), 2)

    def test_retries_then_succeeds(self) -> None:
        provider = _FakeTTSProvider(fail_times=1)
        audio_dir = self.root / "audio"
        audio_dir.mkdir(parents=True)
        single = {"shots": [STORYBOARD["shots"][0]]}
        clips = synthesize_narration(single, provider, audio_dir, max_attempts=2)
        self.assertEqual(provider.calls, 2)  # one failure, then the retry succeeds
        self.assertTrue(all(c.spoken for c in clips))

    def test_provider_failure_degrades_to_subtitles_only(self) -> None:
        audio_dir = self.root / "audio"
        audio_dir.mkdir(parents=True)
        clips = synthesize_narration(STORYBOARD, _AlwaysFailProvider(), audio_dir, max_attempts=2)
        self.assertTrue(all(not c.spoken for c in clips))
        self.assertTrue(all(c.error for c in clips))
        self.assertEqual([c.duration_s for c in clips], [0.0, 0.0])

    def test_second_run_reuses_cached_manifest(self) -> None:
        provider = _FakeTTSProvider()
        audio_dir = self.root / "audio"
        audio_dir.mkdir(parents=True)
        first = synthesize_narration(STORYBOARD, provider, audio_dir)
        provider.calls = 0  # a second run must not hit the provider again
        second = synthesize_narration(STORYBOARD, provider, audio_dir)
        self.assertEqual(provider.calls, 0)
        self.assertEqual([c.shot_id for c in first], [c.shot_id for c in second])
        self.assertEqual([c.duration_s for c in first], [c.duration_s for c in second])


class RunTTSGenTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)

    def tearDown(self) -> None:
        self._temp.cleanup()

    def _cost(self, run_id: str) -> dict:
        return json.loads((self.root / "runs" / run_id / "cost.json").read_text(encoding="utf-8"))

    def test_zero_cost_path_records_tts_line(self) -> None:
        clips = run_tts_gen(
            STORYBOARD,
            provider=_FakeTTSProvider(),
            workspace_root=self.root,
            run_id="t028-zero",
            unit_prices={"tts": UnitPrice.create("fishaudio", "1000_characters", "0")},
        )
        self.assertTrue(all(c.spoken for c in clips))
        cost = self._cost("t028-zero")
        self.assertFalse(cost["settled"])
        item = next(i for i in cost["items"] if i["category"] == "tts")
        self.assertEqual(item["actual_usd"], 0.0)

    def test_no_narration_is_a_noop(self) -> None:
        silent = {"shots": [dict(STORYBOARD["shots"][0], narration="")]}
        clips = run_tts_gen(
            silent,
            provider=_FakeTTSProvider(),
            workspace_root=self.root,
            run_id="t028-silent",
            unit_prices={"tts": UnitPrice.create("fishaudio", "1000_characters", "0")},
        )
        self.assertEqual(clips, [])
        self.assertFalse((self.root / "runs" / "t028-silent" / "cost.json").exists())

    def test_reuses_reserved_tts_line(self) -> None:
        prepare_storyboard_quote(
            STORYBOARD,
            {
                "image": UnitPrice.create("anidoodle", "keyframe", "0"),
                "video": UnitPrice.create("anidoodle", "shot", "0"),
                "tts": UnitPrice.create("fishaudio", "1000_characters", "0"),
            },
            workspace_root=self.root,
            run_id="t028-reuse",
            planned_categories=("image", "video", "tts"),
        )
        run_tts_gen(
            STORYBOARD,
            provider=_FakeTTSProvider(),
            workspace_root=self.root,
            run_id="t028-reuse",
            unit_prices={"tts": UnitPrice.create("fishaudio", "1000_characters", "0")},
        )
        cost = self._cost("t028-reuse")
        self.assertEqual(sorted(i["category"] for i in cost["items"]), ["image", "tts", "video"])

    def test_rejects_reservation_without_tts_line(self) -> None:
        prepare_storyboard_quote(
            STORYBOARD,
            {"image": UnitPrice.create("anidoodle", "keyframe", "0")},
            workspace_root=self.root,
            run_id="t028-image-only",
            planned_categories=("image",),
        )
        with self.assertRaises(CostRecordError):
            run_tts_gen(
                STORYBOARD,
                provider=_FakeTTSProvider(),
                workspace_root=self.root,
                run_id="t028-image-only",
                unit_prices={"tts": UnitPrice.create("fishaudio", "1000_characters", "0")},
            )

    def test_missing_price_fails_closed(self) -> None:
        with self.assertRaises(MissingUnitPrice):
            run_tts_gen(
                STORYBOARD,
                provider=_FakeTTSProvider(),
                workspace_root=self.root,
                run_id="t028-missing",
                unit_prices={},
            )

    def test_nonzero_price_requires_approval(self) -> None:
        with self.assertRaises(ApprovalRequired):
            run_tts_gen(
                STORYBOARD,
                provider=_FakeTTSProvider(),
                workspace_root=self.root,
                run_id="t028-paid",
                unit_prices={"tts": UnitPrice.create("paid", "1000_characters", "0.10")},
            )


if __name__ == "__main__":
    unittest.main()
