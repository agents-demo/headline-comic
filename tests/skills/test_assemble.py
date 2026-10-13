"""Deterministic timeline / command / rendering tests for the T029 assemble skill."""

import json
import os
from pathlib import Path
import tempfile
import unittest

from src.skills.assemble import (
    AssembleError,
    Segment,
    assemble,
    audio_command,
    concat_command,
    mux_command,
    render_closing_card,
    render_mark,
    render_subtitle,
    render_title_card,
    run as run_assembler,
    segment_command,
    shot_segments,
    timeline,
)

STORYBOARD = {
    "schema_version": "1.0",
    "shots": [
        {"shot_id": "shot-01", "beat": 0, "duration_s": 5.0, "narration": "First line."},
        {"shot_id": "shot-02", "beat": 1, "duration_s": 6.0, "narration": "Second line."},
    ],
}

STORY = {"title": "Test Story", "fiction_label": "Fiction inspired by today's news"}
CARDS = [{"source": 1, "title": "A headline", "summary": "A summary.", "link": "https://example.com/a"}]


class _Proc:
    def __init__(self, returncode: int, stdout: str, stderr: str) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _FakeRun:
    """Routes ffmpeg/ffprobe subprocess calls and records argv."""

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
            return _Proc(1 if self.fail else 0, "", "ffmpeg stderr")
        raise AssertionError(f"unexpected subprocess: {args}")


class TimelineTests(unittest.TestCase):
    def test_segments_and_total(self) -> None:
        # title 3 + shot 5 + shot 6 + closing 5 = 19, minus 3 boundaries x 0.5 = 17.5
        tl = timeline(STORYBOARD)
        self.assertEqual([seg.kind for seg in tl.segments], ["title", "shot", "shot", "closing"])
        self.assertEqual(tl.total_s, 17.5)

    def test_start_times(self) -> None:
        tl = timeline(STORYBOARD)
        starts = [seg.start_s for seg in tl.segments]
        self.assertEqual(starts, [0.0, 3.0, 7.5, 13.0])

    def test_holds_extend_shot(self) -> None:
        tl = timeline(STORYBOARD, {"shot-01": 2.2})
        # title 3 + (5 + 2.2) + 6 + closing 5 = 21.2 - 1.5 = 19.7
        self.assertEqual(tl.total_s, 19.7)
        self.assertEqual(tl.segments[1].duration_s, 7.2)

    def test_empty_storyboard_raises(self) -> None:
        with self.assertRaises(AssembleError):
            timeline({"shots": []})

    def test_missing_shot_id_raises(self) -> None:
        with self.assertRaises(AssembleError):
            timeline({"shots": [{"duration_s": 5.0}]})

    def test_shot_segments_only(self) -> None:
        tl = timeline(STORYBOARD)
        self.assertEqual([s.shot_id for s in shot_segments(tl)], ["shot-01", "shot-02"])


class CommandBuilderTests(unittest.TestCase):
    def test_segment_command_card(self) -> None:
        args = segment_command(
            ffmpeg="ffmpeg", kind="title", source=Path("t.png"), duration_s=3.0, start_s=0.0, hold_s=0.0, output=Path("o.mp4")
        )
        self.assertIn("-loop", args)
        self.assertIn("1", args)
        self.assertIn("-t", args)
        self.assertIn("3", args)

    def test_segment_command_shot_with_hold(self) -> None:
        args = segment_command(
            ffmpeg="ffmpeg", kind="shot", source=Path("v.mp4"), duration_s=6.0, start_s=5.0, hold_s=1.5, output=Path("o.mp4")
        )
        self.assertIn("-ss", args)
        self.assertIn("5", args)
        vf = [a for a in args if a.startswith("setpts=PTS-STARTPTS")][0]
        self.assertIn("tpad=stop_mode=clone:stop_duration=1.5", vf)

    def test_segment_command_shot_without_hold(self) -> None:
        args = segment_command(
            ffmpeg="ffmpeg", kind="shot", source=Path("v.mp4"), duration_s=6.0, start_s=5.0, hold_s=0.0, output=Path("o.mp4")
        )
        vf = [a for a in args if a.startswith("setpts=PTS-STARTPTS")][0]
        self.assertNotIn("tpad", vf)

    def test_concat_command_offsets(self) -> None:
        segs = [Path(f"{i}.mp4") for i in range(4)]
        args = concat_command(ffmpeg="ffmpeg", segments=segs, durations=[3.0, 5.0, 6.0, 5.0], output=Path("o.mp4"))
        fc = args[args.index("-filter_complex") + 1]
        self.assertIn("xfade=transition=fade:duration=0.5:offset=2.5[x0]", fc)
        self.assertIn("[x0][2:v]xfade=transition=fade:duration=0.5:offset=7[x1]", fc)
        self.assertIn("[x1][3:v]xfade=transition=fade:duration=0.5:offset=12.5[vout]", fc)

    def test_audio_command_mixes_narration(self) -> None:
        args = audio_command(
            ffmpeg="ffmpeg",
            narration=[(Path("a.mp3"), 3.0), (Path("b.mp3"), 7.5)],
            bed=Path("bed.wav"),
            total_s=17.5,
            output=Path("mix.wav"),
        )
        fc = args[args.index("-filter_complex") + 1]
        self.assertIn("[0:a]adelay=3000:all=1[a0]", fc)
        self.assertIn("[1:a]adelay=7500:all=1[a1]", fc)
        self.assertIn("amix=inputs=2:duration=longest:normalize=0[narr]", fc)
        self.assertIn("volume=0.4,afade=t=out:st=15.5:d=2[music]", fc)
        self.assertIn("[narr][music]amix=inputs=2:duration=longest:normalize=0,alimiter=limit=0.98[aout]", fc)

    def test_audio_command_music_only(self) -> None:
        args = audio_command(ffmpeg="ffmpeg", narration=[], bed=Path("bed.wav"), total_s=17.5, output=Path("mix.wav"))
        fc = args[args.index("-filter_complex") + 1]
        self.assertNotIn("adelay", fc)
        self.assertIn("[0:a]volume=1,afade=t=out:st=15.5:d=2[music]", fc)
        self.assertIn("[music]alimiter=limit=0.98[aout]", fc)

    def test_mux_command_overlays_and_metadata(self) -> None:
        args = mux_command(
            ffmpeg="ffmpeg",
            video=Path("v.mp4"),
            audio=Path("a.wav"),
            subtitles=[(Path("s.png"), 3.0, 7.5)],
            mark=Path("mark.png"),
            title="Test Story",
            output=Path("video.mp4"),
        )
        fc = args[args.index("-filter_complex") + 1]
        self.assertIn("overlay=0:0:enable='between(t,3,7.5)'", fc)
        self.assertIn("overlay=W-w-16:16[ov]", fc)
        self.assertIn("title=Test Story", args)
        self.assertIn("comment=AI-generated fiction", args)


class RenderTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)

    def tearDown(self) -> None:
        self._temp.cleanup()

    def test_title_card_dimensions(self) -> None:
        out = self.root / "title.png"
        render_title_card(STORY, out)
        from PIL import Image

        with Image.open(out) as im:
            self.assertEqual(im.size, (1280, 720))

    def test_closing_card_dimensions(self) -> None:
        out = self.root / "closing.png"
        render_closing_card(CARDS, out)
        from PIL import Image

        with Image.open(out) as im:
            self.assertEqual(im.size, (1280, 720))

    def test_subtitle_has_alpha(self) -> None:
        out = self.root / "sub.png"
        render_subtitle("A caption.", out)
        from PIL import Image

        with Image.open(out) as im:
            self.assertEqual(im.size, (1280, 720))
            self.assertEqual(im.mode, "RGBA")

    def test_mark_is_small_rgba(self) -> None:
        out = self.root / "mark.png"
        render_mark(out)
        from PIL import Image

        with Image.open(out) as im:
            self.assertEqual(im.mode, "RGBA")
            self.assertLess(im.size[0], 400)


class AssembleTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name).resolve()

    def tearDown(self) -> None:
        self._temp.cleanup()

    def test_assemble_runs_full_pipeline_and_verifies(self) -> None:
        fake = _FakeRun(duration=17.5)
        tl = timeline(STORYBOARD)
        final = assemble(
            timeline_=tl,
            storyboard=STORYBOARD,
            video_path=self.root / "shots.mp4",
            clips=None,
            bed_path=self.root / "bed.wav",
            cards_dir=self.root / "cards",
            story=STORY,
            cards=CARDS,
            final_path=self.root / "video.mp4",
            repo_root=self.root,
            run=fake,
        )
        self.assertEqual(final, self.root / "video.mp4")
        names = [os.path.basename(c[0]) for c in fake.calls]
        self.assertEqual(names.count("ffmpeg"), 7)  # 4 segments + concat + audio + mux
        self.assertEqual(names[-1], "ffprobe")

    def test_assemble_duration_out_of_range_raises(self) -> None:
        fake = _FakeRun(duration=62.0)
        with self.assertRaises(AssembleError):
            assemble(
                timeline_=timeline(STORYBOARD),
                storyboard=STORYBOARD,
                video_path=self.root / "shots.mp4",
                clips=None,
                bed_path=self.root / "bed.wav",
                cards_dir=self.root / "cards",
                story=STORY,
                cards=CARDS,
                final_path=self.root / "video.mp4",
                repo_root=self.root,
                run=fake,
            )

    def test_assemble_step_failure_raises(self) -> None:
        fake = _FakeRun(duration=17.5, fail=True)
        with self.assertRaises(AssembleError):
            assemble(
                timeline_=timeline(STORYBOARD),
                storyboard=STORYBOARD,
                video_path=self.root / "shots.mp4",
                clips=None,
                bed_path=self.root / "bed.wav",
                cards_dir=self.root / "cards",
                story=STORY,
                cards=CARDS,
                final_path=self.root / "video.mp4",
                repo_root=self.root,
                run=fake,
            )


class RunAssemblerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name).resolve()
        self.candidates = {"candidates": [{"candidate_id": "c1", "title": "A headline", "url": "https://example.com/a"}]}
        self.summaries = {"summaries": [{"story_id": "c1", "sentences": [{"text": "One."}, {"text": "Two."}]}]}

    def tearDown(self) -> None:
        self._temp.cleanup()

    def test_run_writes_final(self) -> None:
        fake = _FakeRun(duration=17.5)
        final = run_assembler(
            STORY,
            STORYBOARD,
            self.candidates,
            self.summaries,
            workspace_root=self.root,
            run_id="t029",
            run_process=fake,
        )
        self.assertEqual(final, self.root / "runs" / "t029" / "video.mp4")

    def test_run_refuses_overwrite(self) -> None:
        final_path = self.root / "runs" / "t029" / "video.mp4"
        final_path.parent.mkdir(parents=True)
        final_path.write_bytes(b"existing")
        with self.assertRaises(FileExistsError):
            run_assembler(
                STORY,
                STORYBOARD,
                self.candidates,
                self.summaries,
                workspace_root=self.root,
                run_id="t029",
                run_process=_FakeRun(),
            )


if __name__ == "__main__":
    unittest.main()
