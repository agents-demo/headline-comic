"""Deterministic failure-classification / retry / still-swap tests for T031 recovery."""

import json
import os
from pathlib import Path
import tempfile
import unittest

from src.flow.runlog import read_entries
from src.skills.video_recovery import (
    ShotOutcome,
    ShotRecoveryError,
    ShotRenderResult,
    classify_failure,
    concat_outcomes_command,
    concat_shots,
    recover_shots,
    render_shot_with_recovery,
    run as run_recovery,
    still_command,
)

STORY = {"title": "Test Story", "fiction_label": "Fiction inspired by today's news"}
STORYBOARD = {
    "shots": [
        {
            "shot_id": "shot-01",
            "beat": 0,
            "duration_s": 5.0,
            "narration": "First line.",
            "camera": "close",
            "action": "point",
            "characters": ["courier"],
        },
        {
            "shot_id": "shot-02",
            "beat": 1,
            "duration_s": 6.0,
            "narration": "Second line.",
            "camera": "overhead",
            "action": "stand",
            "characters": [],
        },
    ],
}


def _ok(duration_s: float = 5.0) -> ShotRenderResult:
    return ShotRenderResult(Path("clip.mp4"), duration_s, 1280, 720)


class _Proc:
    def __init__(self, returncode: int, stdout: str, stderr: str) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _FakeRun:
    """Routes ffmpeg/ffprobe; writes each ffmpeg output so post-conditions pass."""

    def __init__(self, *, duration: float = 17.5, fail: bool = False) -> None:
        self.duration = duration
        self.fail = fail
        self.calls: list[list[str]] = []

    def __call__(self, args, **kwargs):
        self.calls.append(list(args))
        base = os.path.basename(args[0])
        if base.startswith("ffprobe"):
            payload = json.dumps(
                {
                    "format": {"duration": str(self.duration)},
                    "streams": [
                        {"codec_type": "video", "width": 1280, "height": 720},
                        {"codec_type": "audio"},
                    ],
                }
            )
            return _Proc(0, payload, "")
        if base.startswith("ffmpeg"):
            out = Path(args[-1])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"mp4")
            return _Proc(1 if self.fail else 0, "", "ffmpeg stderr")
        raise AssertionError(f"unexpected subprocess: {args}")


class _Renderer:
    """A per-shot render whose next call yields the next result (or raises it)."""

    def __init__(self, *behaviors) -> None:
        self._behaviors = list(behaviors)
        self.calls = 0

    def __call__(self, shot):
        behavior = self._behaviors[self.calls]
        self.calls += 1
        if isinstance(behavior, BaseException):
            raise behavior
        return behavior


class ClassifyFailureTests(unittest.TestCase):
    def test_timeout_error(self) -> None:
        self.assertEqual(classify_failure(error=TimeoutError("slow"), expected_duration_s=5.0), "timeout")

    def test_api_error(self) -> None:
        self.assertEqual(classify_failure(error=RuntimeError("boom"), expected_duration_s=5.0), "api_error")

    def test_duration_mismatch(self) -> None:
        self.assertEqual(classify_failure(result=_ok(duration_s=9.0), expected_duration_s=5.0), "duration")

    def test_resolution_mismatch(self) -> None:
        self.assertEqual(
            classify_failure(result=ShotRenderResult(Path("c.mp4"), 5.0, 640, 360), expected_duration_s=5.0),
            "resolution",
        )

    def test_ok_result_is_none(self) -> None:
        self.assertIsNone(classify_failure(result=_ok(duration_s=5.0), expected_duration_s=5.0))


class StillCommandTests(unittest.TestCase):
    def test_still_command_uses_zoompan(self) -> None:
        args = still_command("ffmpeg", Path("k.png"), 5.0, "zoom", Path("o.mp4"))
        self.assertEqual(args[0], "ffmpeg")
        vf = args[args.index("-vf") + 1]
        self.assertIn("zoompan", vf)
        self.assertIn("-an", args)
        self.assertEqual(args[-1], str(Path("o.mp4")))


class RenderShotWithRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name).resolve()
        self.keyframe = self.root / "key.png"
        self.keyframe.write_bytes(b"png")
        self.out_dir = self.root / "shots"

    def tearDown(self) -> None:
        self._temp.cleanup()

    def _recover(self, render, *, ffmpeg: str = "ffmpeg", run=None) -> object:
        return render_shot_with_recovery(
            shot=STORYBOARD["shots"][0],
            keyframe=self.keyframe,
            output_dir=self.out_dir,
            render=render,
            ffmpeg=ffmpeg,
            run=run or _FakeRun(),
        )

    def test_success_on_first_attempt(self) -> None:
        outcome = self._recover(_Renderer(_ok()))
        self.assertEqual(outcome.kind, "generated")
        self.assertEqual(outcome.attempts, 1)
        self.assertIsNone(outcome.reason)

    def test_retry_then_success(self) -> None:
        outcome = self._recover(_Renderer(TimeoutError("slow"), _ok()))
        self.assertEqual(outcome.kind, "generated")
        self.assertEqual(outcome.attempts, 2)
        self.assertIsNone(outcome.reason)

    def test_fail_twice_swaps_to_still(self) -> None:
        outcome = self._recover(_Renderer(RuntimeError("api"), TimeoutError("slow")))
        self.assertEqual(outcome.kind, "still")
        self.assertEqual(outcome.attempts, 2)
        self.assertEqual(outcome.reason, "timeout")
        self.assertTrue(outcome.source_path.is_file())

    def test_duration_check_failure_swaps_to_still(self) -> None:
        bad = ShotRenderResult(Path("clip.mp4"), 99.0, 1280, 720)
        outcome = self._recover(_Renderer(bad, bad))
        self.assertEqual(outcome.kind, "still")
        self.assertEqual(outcome.reason, "duration")

    def test_missing_keyframe_raises(self) -> None:
        self.keyframe.unlink()
        with self.assertRaises(ShotRecoveryError):
            self._recover(_Renderer(_ok()))


class RecoverShotsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name).resolve()
        self.keyframes = self.root / "keyframes"
        self.keyframes.mkdir(parents=True)
        for sid in ("shot-01", "shot-02"):
            (self.keyframes / f"{sid}.png").write_bytes(b"png")

    def tearDown(self) -> None:
        self._temp.cleanup()

    def test_recovers_each_shot_in_order(self) -> None:
        outcomes = recover_shots(
            STORYBOARD,
            keyframes_dir=self.keyframes,
            output_dir=self.root / "shots",
            render=_Renderer(_ok(), _ok(6.0)),
            ffmpeg="ffmpeg",
            run=_FakeRun(),
        )
        self.assertEqual([o.shot_id for o in outcomes], ["shot-01", "shot-02"])
        self.assertEqual([o.kind for o in outcomes], ["generated", "generated"])


class ConcatTests(unittest.TestCase):
    def test_concat_outcomes_command(self) -> None:
        args = concat_outcomes_command("ffmpeg", [Path("a.mp4"), Path("b.mp4")], Path("out.mp4"))
        self.assertEqual(args[0], "ffmpeg")
        fc = args[args.index("-filter_complex") + 1]
        self.assertIn("concat=n=2:v=1:a=0", fc)
        self.assertIn("-an", args)
        self.assertEqual(args[-1], str(Path("out.mp4")))

    def test_concat_shots_writes_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "a.mp4").write_bytes(b"mp4")
            (root / "b.mp4").write_bytes(b"mp4")
            outcomes = [
                ShotOutcome("shot-01", "generated", root / "a.mp4", 1, None),
                ShotOutcome("shot-02", "still", root / "b.mp4", 2, "timeout"),
            ]
            fake = _FakeRun()
            out = concat_shots(outcomes=outcomes, output=root / "out.mp4", ffmpeg="ffmpeg", run=fake)
            self.assertEqual(out, root / "out.mp4")
            self.assertTrue(out.is_file())
            self.assertEqual(len(fake.calls), 1)


class RunRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name).resolve()
        (self.root / "runs" / "t031" / "keyframes").mkdir(parents=True)
        for sid in ("shot-01", "shot-02"):
            (self.root / "runs" / "t031" / "keyframes" / f"{sid}.png").write_bytes(b"png")
        self.candidates = {"candidates": [{"candidate_id": "c1", "title": "A headline", "url": "https://example.com/a"}]}
        self.summaries = {"summaries": [{"story_id": "c1", "sentences": [{"text": "One."}, {"text": "Two."}]}]}

    def tearDown(self) -> None:
        self._temp.cleanup()

    def test_run_writes_video_and_logs(self) -> None:
        fake = _FakeRun(duration=17.5)
        # shot-02 fails both attempts and swaps to a still, exercising the recovery path
        render = _Renderer(_ok(), RuntimeError("api"), RuntimeError("api"))
        out = run_recovery(
            STORY,
            STORYBOARD,
            self.candidates,
            self.summaries,
            workspace_root=self.root,
            run_id="t031",
            render=render,
            run_process=fake,
        )
        self.assertEqual(out, self.root / "runs" / "t031" / "video.mp4")
        self.assertTrue(out.is_file())
        self.assertEqual(render.calls, 3)  # shot-01 x1 + shot-02 x2 retries

        entries = read_entries(self.root, "t031")
        recovery = [e for e in entries if e["event"] == "shot_recovery"]
        self.assertEqual(len(recovery), 2)
        self.assertEqual(recovery[0]["outcome"], "generated")
        self.assertEqual(recovery[1]["outcome"], "still")
        summary = [e for e in entries if e["event"] == "recovery_summary"]
        self.assertEqual(summary[0]["generated"], 1)
        self.assertEqual(summary[0]["stills"], 1)


if __name__ == "__main__":
    unittest.main()
