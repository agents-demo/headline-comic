"""Deterministic duration/loudness/command tests for the T028 music_gen skill."""

import os
from pathlib import Path
import tempfile
import unittest

from src.skills.music_gen import (
    BED_EXPORT,
    MusicGenError,
    film_duration_s,
    loop_command,
    lufs_from_ebur128,
    render_command,
    render_music_bed,
    run as run_music_gen,
)

STORYBOARD = {
    "schema_version": "1.0",
    "shots": [
        {"shot_id": "shot-01", "beat": 0, "duration_s": 5.0},
        {"shot_id": "shot-02", "beat": 1, "duration_s": 6.0},
    ],
}


class _Proc:
    def __init__(self, returncode: int, stdout: str, stderr: str) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _FakeRun:
    """Routes node/ffprobe/ffmpeg subprocess calls and records them."""

    def __init__(
        self,
        *,
        duration_s: float = 52.0,
        lufs: float = -16.0,
        render_rc: int = 0,
        write_out: bool = True,
    ) -> None:
        self.duration_s = duration_s
        self.lufs = lufs
        self.render_rc = render_rc
        self.write_out = write_out
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        cmd = os.path.basename(args[0])
        if cmd == "node":
            if self.write_out:
                out = Path(args[4])
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(b"RIFF")
            return _Proc(self.render_rc, "", "render stderr")
        if cmd.startswith("ffprobe"):
            return _Proc(0, f"{self.duration_s}\n", "")
        if cmd.startswith("ffmpeg"):
            if "-stream_loop" in args:
                if self.write_out:
                    out = Path(args[-1])
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_bytes(b"RIFF")
                return _Proc(0, "", "")
            return _Proc(0, "", f"\nIntegrated loudness:\n  I:  {self.lufs} LUFS\n")
        raise AssertionError(f"unexpected subprocess: {args}")


def _tool_name(base: str) -> str:
    return f"{base}.exe" if os.name == "nt" else base


class FilmDurationTests(unittest.TestCase):
    def test_shots_plus_cards_minus_transitions(self) -> None:
        # 5 + 6 + 3 + 5 = 19, minus (2 shots + 1) * 0.5 = 1.5 crossfade overlap
        self.assertEqual(film_duration_s(STORYBOARD), 17.5)

    def test_adds_hold_overruns(self) -> None:
        self.assertEqual(film_duration_s(STORYBOARD, {"shot-01": 2.2}), 19.7)

    def test_ignores_unreferenced_holds(self) -> None:
        self.assertEqual(film_duration_s(STORYBOARD, {"shot-09": 4.0}), 17.5)

    def test_empty_storyboard_raises(self) -> None:
        with self.assertRaises(MusicGenError):
            film_duration_s({"shots": []})


class LufsParseTests(unittest.TestCase):
    def test_parses_integrated_loudness(self) -> None:
        stderr = "  Integrated loudness:\n    I:         -16.0 LUFS\n    Threshold: -26.9 LUFS"
        self.assertEqual(lufs_from_ebur128(stderr), -16.0)

    def test_missing_summary_raises(self) -> None:
        with self.assertRaises(MusicGenError):
            lufs_from_ebur128("no ebur128 output")

    def test_ignores_per_frame_lines(self) -> None:
        stderr = (
            "[Parsed_ebur128_0 @ 0x1] t: 0.0999792  TARGET:-23 LUFS  M:-120.7 S:-120.7"
            "  I: -70.0 LUFS  LRA: 0.0 LU  FTPK: -15.0 -14.0 dBFS\n"
            "[Parsed_ebur128_0 @ 0x1] t: 0.399979  M: -20.4  I: -20.4 LUFS\n"
            "  Integrated loudness:\n"
            "    I:         -16.0 LUFS\n"
            "    Threshold: -26.9 LUFS\n"
        )
        self.assertEqual(lufs_from_ebur128(stderr), -16.0)


class RenderCommandTests(unittest.TestCase):
    def test_renders_seamless_loop(self) -> None:
        args = render_command("node", Path("m.mjs"), Path("bed.ts"), Path("loop.wav"))
        self.assertEqual(args[0], "node")
        self.assertEqual(args[2], "render")
        self.assertEqual(args[3], f"{Path('bed.ts')}#{BED_EXPORT}")
        self.assertEqual(args[4], str(Path("loop.wav")))
        self.assertEqual(args[5], "--loop")

    def test_loop_command_fills_duration(self) -> None:
        args = loop_command("ffmpeg", Path("loop.wav"), 47.5, Path("bed.wav"))
        self.assertEqual(args[0], "ffmpeg")
        self.assertEqual(args[1], "-y")
        self.assertIn("-stream_loop", args)
        self.assertIn("-1", args)
        self.assertEqual(args[args.index("-t") + 1], "47.5")
        self.assertEqual(args[-1], str(Path("bed.wav")))


class RenderMusicBedTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.scaffold = self.root / "run" / "anidoodle"
        (self.scaffold / "tools").mkdir(parents=True)
        (self.scaffold / "tools" / "music.mjs").write_text("// music engine", encoding="utf-8")
        self.bed = self.root / "bed.ts"
        self.bed.write_text("export const townHallSteps = () => ({});\n", encoding="utf-8")
        self.out = self.root / "audio" / "bed.wav"

    def tearDown(self) -> None:
        self._temp.cleanup()

    def test_render_and_verify_success(self) -> None:
        fake = _FakeRun(duration_s=52.0, lufs=-16.0)
        result = render_music_bed(
            out_path=self.out,
            duration_s=52.0,
            bed_score=self.bed,
            scaffold_dir=self.scaffold,
            repo_root=self.root,
            run=fake,
        )
        self.assertEqual(result.path, self.out)
        self.assertEqual(result.duration_s, 52.0)
        self.assertEqual(result.lufs, -16.0)
        self.assertEqual([os.path.basename(c[0][0]) for c in fake.calls], ["node", "ffmpeg", "ffprobe", "ffmpeg"])

    def test_prepends_vendored_bin_to_path(self) -> None:
        bin_dir = self.root / "runs" / "_tools" / "ffmpeg" / "9.0" / "bin"
        bin_dir.mkdir(parents=True)
        (bin_dir / _tool_name("ffmpeg")).write_bytes(b"")
        (bin_dir / _tool_name("ffprobe")).write_bytes(b"")
        fake = _FakeRun(duration_s=52.0, lufs=-16.0)
        render_music_bed(
            out_path=self.out,
            duration_s=52.0,
            bed_score=self.bed,
            scaffold_dir=self.scaffold,
            repo_root=self.root,
            run=fake,
        )
        render_call = fake.calls[0]
        self.assertEqual(render_call[1]["cwd"], str(self.scaffold))
        self.assertEqual(render_call[1]["env"]["PATH"].split(os.pathsep)[0], str(bin_dir))

    def test_render_failure_raises(self) -> None:
        with self.assertRaises(MusicGenError):
            render_music_bed(
                out_path=self.out,
                duration_s=52.0,
                bed_score=self.bed,
                scaffold_dir=self.scaffold,
                repo_root=self.root,
                run=_FakeRun(render_rc=1),
            )

    def test_missing_output_raises(self) -> None:
        with self.assertRaises(MusicGenError):
            render_music_bed(
                out_path=self.out,
                duration_s=52.0,
                bed_score=self.bed,
                scaffold_dir=self.scaffold,
                repo_root=self.root,
                run=_FakeRun(write_out=False),
            )

    def test_duration_mismatch_raises(self) -> None:
        with self.assertRaises(MusicGenError):
            render_music_bed(
                out_path=self.out,
                duration_s=52.0,
                bed_score=self.bed,
                scaffold_dir=self.scaffold,
                repo_root=self.root,
                run=_FakeRun(duration_s=53.0),
            )

    def test_loudness_mismatch_raises(self) -> None:
        with self.assertRaises(MusicGenError):
            render_music_bed(
                out_path=self.out,
                duration_s=52.0,
                bed_score=self.bed,
                scaffold_dir=self.scaffold,
                repo_root=self.root,
                run=_FakeRun(lufs=-14.0),
            )

    def test_missing_scaffold_engine_raises(self) -> None:
        with self.assertRaises(MusicGenError):
            render_music_bed(
                out_path=self.out,
                duration_s=52.0,
                bed_score=self.bed,
                scaffold_dir=self.root / "nope",
                repo_root=self.root,
                run=_FakeRun(),
            )


class RunMusicGenTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name).resolve()
        self.bed = self.root / "bed.ts"
        self.bed.write_text("export const townHallSteps = () => ({});\n", encoding="utf-8")
        scaffold = self.root / "runs" / "t028" / "anidoodle" / "tools"
        scaffold.mkdir(parents=True)
        (scaffold / "music.mjs").write_text("// music engine", encoding="utf-8")

    def tearDown(self) -> None:
        self._temp.cleanup()

    def test_writes_bed_into_audio_dir(self) -> None:
        fake = _FakeRun(duration_s=17.5, lufs=-16.0)
        result = run_music_gen(
            STORYBOARD,
            workspace_root=self.root,
            run_id="t028",
            bed_score=self.bed,
            run_process=fake,
        )
        self.assertEqual(result.path, self.root / "runs" / "t028" / "audio" / "bed.wav")
        self.assertEqual(result.duration_s, 17.5)
        self.assertTrue(result.path.is_file())

    def test_film_too_long_raises(self) -> None:
        long_storyboard = {
            "shots": [
                {"shot_id": "s1", "duration_s": 30.0},
                {"shot_id": "s2", "duration_s": 30.0},
            ]
        }
        with self.assertRaises(MusicGenError):
            run_music_gen(
                long_storyboard,
                workspace_root=self.root,
                run_id="t028-long",
                bed_score=self.bed,
                run_process=_FakeRun(),
            )


if __name__ == "__main__":
    unittest.main()
