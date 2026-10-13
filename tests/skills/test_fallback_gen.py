"""Deterministic pan/zoom / command / orchestration tests for the T030 fallback skill."""

import json
import os
from pathlib import Path
import tempfile
import unittest

from src.skills.fallback_gen import (
    FallbackError,
    fallback_filter,
    fallback_frames,
    fallback_shots_command,
    render_fallback_shots,
    run as run_fallback,
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


class FallbackFramesTests(unittest.TestCase):
    def test_frames_at_24fps(self) -> None:
        self.assertEqual(fallback_frames(5.0), 120)
        self.assertEqual(fallback_frames(6.0), 144)

    def test_zero_duration_floors_to_one_frame(self) -> None:
        self.assertEqual(fallback_frames(0.0), 1)


class FallbackFilterTests(unittest.TestCase):
    def test_zoom_in_filter(self) -> None:
        vf = fallback_filter(5.0, "zoom")
        self.assertIn("scale=2560:1440", vf)
        self.assertIn("min(1+(0.0015*on),1.4)", vf)
        self.assertIn("d=120", vf)
        self.assertIn("s=1280x720", vf)
        self.assertIn("fps=24", vf)
        self.assertIn("1280-(iw/zoom/2)", vf)  # default focal = frame centre (2x)

    def test_zoom_out_filter(self) -> None:
        vf = fallback_filter(5.0, "zoom", direction="out")
        self.assertIn("max(1.4-(0.0015*on),1)", vf)

    def test_focal_zoom_centres_on_characters(self) -> None:
        vf = fallback_filter(5.0, "zoom", fx=480.0, fy=470.0)
        self.assertIn("960-(iw/zoom/2)", vf)  # 480 * 2
        self.assertIn("940-(ih/zoom/2)", vf)  # 470 * 2

    def test_overhead_pan_filter(self) -> None:
        vf = fallback_filter(6.0, "overhead")
        self.assertIn("z='1.3'", vf)
        self.assertIn("(iw-iw/zoom)*on/144", vf)
        self.assertIn("d=144", vf)


class FallbackShotsCommandTests(unittest.TestCase):
    def test_builds_single_concat_command(self) -> None:
        args = fallback_shots_command(
            "ffmpeg",
            [Path("k1.png"), Path("k2.png")],
            [5.0, 6.0],
            [
                {"mode": "zoom", "fx": 480.0, "fy": 470.0, "direction": "in"},
                {"mode": "overhead"},
            ],
            Path("out.mp4"),
        )
        self.assertEqual(args[0], "ffmpeg")
        self.assertIn("-filter_complex", args)
        fc = args[args.index("-filter_complex") + 1]
        self.assertIn("[0:v]", fc)
        self.assertIn("[1:v]", fc)
        self.assertIn("concat=n=2:v=1:a=0[vout]", fc)
        self.assertIn("-an", args)
        self.assertEqual(args[-1], str(Path("out.mp4")))


class RenderFallbackShotsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name).resolve()
        self.keyframes = self.root / "keyframes"
        self.keyframes.mkdir(parents=True)
        for sid in ("shot-01", "shot-02"):
            (self.keyframes / f"{sid}.png").write_bytes(b"png")

    def tearDown(self) -> None:
        self._temp.cleanup()

    def test_renders_shots_video(self) -> None:
        out = self.root / "out.mp4"
        fake = _FakeRun()
        result = render_fallback_shots(
            STORYBOARD, keyframes_dir=self.keyframes, output=out, repo_root=self.root, run=fake
        )
        self.assertEqual(result, out)
        self.assertTrue(out.is_file())
        self.assertEqual(len(fake.calls), 1)
        fc = fake.calls[0][fake.calls[0].index("-filter_complex") + 1]
        self.assertIn("zoompan", fc)

    def test_missing_keyframe_raises(self) -> None:
        (self.keyframes / "shot-02.png").unlink()
        with self.assertRaises(FallbackError):
            render_fallback_shots(
                STORYBOARD,
                keyframes_dir=self.keyframes,
                output=self.root / "out.mp4",
                repo_root=self.root,
                run=_FakeRun(),
            )

    def test_ffmpeg_failure_raises(self) -> None:
        with self.assertRaises(FallbackError):
            render_fallback_shots(
                STORYBOARD,
                keyframes_dir=self.keyframes,
                output=self.root / "out.mp4",
                repo_root=self.root,
                run=_FakeRun(fail=True),
            )


class RunFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name).resolve()
        (self.root / "runs" / "t030" / "keyframes").mkdir(parents=True)
        for sid in ("shot-01", "shot-02"):
            (self.root / "runs" / "t030" / "keyframes" / f"{sid}.png").write_bytes(b"png")
        self.candidates = {"candidates": [{"candidate_id": "c1", "title": "A headline", "url": "https://example.com/a"}]}
        self.summaries = {"summaries": [{"story_id": "c1", "sentences": [{"text": "One."}, {"text": "Two."}]}]}

    def tearDown(self) -> None:
        self._temp.cleanup()

    def test_run_writes_fallback(self) -> None:
        fake = _FakeRun(duration=17.5)
        out = run_fallback(
            STORY,
            STORYBOARD,
            self.candidates,
            self.summaries,
            workspace_root=self.root,
            run_id="t030",
            run_process=fake,
        )
        self.assertEqual(out, self.root / "runs" / "t030" / "fallback.mp4")
        self.assertTrue(out.is_file())
        # the first ffmpeg call is the pan/zoom shots render; the last call verifies
        fc = fake.calls[0][fake.calls[0].index("-filter_complex") + 1]
        self.assertIn("zoompan", fc)
        self.assertEqual(os.path.basename(fake.calls[-1][0]), "ffprobe")


if __name__ == "__main__":
    unittest.main()
