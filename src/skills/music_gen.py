"""S15 music_gen: fit the royalty-free music-box bed to the film length (T028).

The bed is a committed local asset (``scripts/anidoodle/music/bed.ts``), a short
(~8.6 s) music-box phrase. ``--fit`` only stretches a score, so a short bed would pad
the rest of the film with silence; instead the bed is rendered through the AniDoodle
music engine as a **seamless loop** (``render --loop``), then repeated with ffmpeg to
exactly the film's assembled duration (the storyboard shots plus the 3 s title card
and the 5 s closing card, and any hold-last-frame overrun from narration) and verified
to be the expected length and normalised to -16 LUFS. Because the bed is local and $0
there is no provider call and no budget line; the deterministic verification below is
the whole of the "loudness normalise" requirement (FR-010). The assembler (T029)
reuses ``film_duration_s`` so the bed and the final cut agree on length.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from src.permissions.media_guard import require_allowed_write_path

TITLE_CARD_S = 3.0
CLOSING_CARD_S = 5.0
TRANSITION_S = 0.5  # crossfade between every adjacent segment (FR-010)
MAX_DURATION_S = 59.0  # strictly under one minute (FR-010)
TARGET_LUFS = -16.0  # the music engine's own master target
LUFS_TOLERANCE_DB = 1.0
DURATION_TOLERANCE_S = 0.25
BED_EXPORT = "townHallSteps"
BED_FILENAME = "bed.wav"

_EBUR128_INTEGRATED = re.compile(
    r"Integrated loudness:.*?I:\s+(-?\d+(?:\.\d+)?)\s+LUFS", re.S
)


class MusicGenError(RuntimeError):
    """Raised when the music bed cannot be rendered or verified."""


@dataclass(frozen=True)
class MusicBedResult:
    """The rendered bed and its verified length and loudness."""

    path: Path
    duration_s: float
    lufs: float


def film_duration_s(
    storyboard: Mapping[str, Any],
    holds: Mapping[str, float] | None = None,
) -> float:
    """Assembled film length: shot durations + hold overruns + the two cards, minus the
    crossfade overlap between adjacent segments (FR-010).

    ``holds`` is the ``hold_last_frame_s`` output — extra seconds a shot's last frame
    lingers when its narration runs longer than the shot. A narration that is shorter
    than its shot leaves the shot unchanged. There is one ``TRANSITION_S`` crossfade per
    segment boundary, so ``n_shots + 1`` of them in total (title→shot…→closing).
    """
    shots = storyboard.get("shots")
    if not isinstance(shots, list) or not shots:
        raise MusicGenError("storyboard must contain a non-empty shots array")
    holds = holds or {}
    total = 0.0
    n_shots = 0
    for shot in shots:
        if not isinstance(shot, Mapping):
            raise MusicGenError("storyboard shot must be an object")
        n_shots += 1
        total += float(shot.get("duration_s") or 0)
        total += float(holds.get(str(shot.get("shot_id") or ""), 0) or 0)
    total += TITLE_CARD_S + CLOSING_CARD_S
    total -= (n_shots + 1) * TRANSITION_S
    return round(total, 3)


def _find_tool(repo_root: Path, name: str) -> str:
    """Prefer the vendored binary under ``runs/_tools``; otherwise rely on PATH."""
    exe = f"{name}.exe" if os.name == "nt" else name
    tools_root = repo_root / "runs" / "_tools" / "ffmpeg"
    if tools_root.is_dir():
        for bin_dir in sorted(tools_root.glob("*/bin")):
            candidate = bin_dir / exe
            if candidate.is_file():
                return str(candidate)
    return name


def render_command(
    node: str,
    music_mjs: Path,
    bed_score: Path,
    loop_path: Path,
) -> list[str]:
    """The ``music.mjs render --loop`` invocation that renders the bed's seamless loop."""
    return [
        node,
        str(music_mjs),
        "render",
        f"{bed_score}#{BED_EXPORT}",
        str(loop_path),
        "--loop",
    ]


def loop_command(
    ffmpeg: str,
    loop_path: Path,
    duration_s: float,
    out_path: Path,
) -> list[str]:
    """Repeat the seamless loop to fill ``duration_s`` seconds (the mix fades the tail)."""
    return [
        ffmpeg,
        "-y",
        "-stream_loop",
        "-1",
        "-i",
        str(loop_path),
        "-t",
        f"{duration_s:g}",
        "-c:a",
        "pcm_s16le",
        str(out_path),
    ]


def lufs_from_ebur128(stderr: str) -> float:
    """Integrated loudness from ffmpeg's ebur128 summary (``I:  -16.0 LUFS``).

    Anchored to the ``Integrated loudness:`` summary line so the filter's per-frame
    progress lines (which also print ``I: ... LUFS``, e.g. ``-70`` before the first
    note) cannot be mistaken for the final integrated value.
    """
    match = _EBUR128_INTEGRATED.search(stderr)
    if match is None:
        raise MusicGenError("ffmpeg ebur128 output did not report integrated loudness")
    return float(match.group(1))


def _probe_duration_s(path: Path, *, ffprobe: str, run: Callable) -> float:
    proc = run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise MusicGenError(f"ffprobe could not read {path}")
    try:
        return float(proc.stdout.strip())
    except ValueError as exc:
        raise MusicGenError(f"could not parse a duration from {path}") from exc


def _measure_lufs(path: Path, *, ffmpeg: str, run: Callable) -> float:
    proc = run(
        [
            ffmpeg,
            "-nostats",
            "-i",
            str(path),
            "-filter_complex",
            "ebur128=peak=true",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise MusicGenError(f"ffmpeg could not meter {path}: {proc.stderr.strip()[:200]}")
    return lufs_from_ebur128(proc.stderr)


def render_music_bed(
    *,
    out_path: Path,
    duration_s: float,
    bed_score: Path,
    scaffold_dir: Path,
    repo_root: Path,
    node: str = "node",
    run: Callable = subprocess.run,
) -> MusicBedResult:
    """Render the bed's seamless loop, repeat it to the film length, and verify (FR-010)."""
    music_mjs = scaffold_dir / "tools" / "music.mjs"
    if not music_mjs.is_file():
        raise MusicGenError(f"music engine not found in scaffold: {music_mjs}")
    if not bed_score.is_file():
        raise MusicGenError(f"music bed score not found: {bed_score}")

    ffmpeg = _find_tool(repo_root, "ffmpeg")
    ffprobe = _find_tool(repo_root, "ffprobe")
    env = os.environ.copy()
    if os.path.isabs(ffmpeg):
        # The engine's `decode` calls ``ffmpeg`` by name, so the vendored bin must
        # be on PATH for the node subprocess.
        env["PATH"] = str(Path(ffmpeg).parent) + os.pathsep + env.get("PATH", "")

    loop_path = out_path.with_name(out_path.stem + ".loop.wav")
    try:
        proc = run(
            render_command(node, music_mjs, bed_score, loop_path),
            cwd=str(scaffold_dir),
            env=env,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise MusicGenError(f"music render failed: {proc.stderr.strip()[-400:]}")
        if not loop_path.is_file():
            raise MusicGenError(f"music render completed without {loop_path}")

        proc = run(
            loop_command(ffmpeg, loop_path, duration_s, out_path),
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise MusicGenError(f"music loop repeat failed: {proc.stderr.strip()[-400:]}")
    finally:
        if loop_path.is_file():
            loop_path.unlink()

    if not out_path.is_file():
        raise MusicGenError(f"music render completed without {out_path}")

    actual = _probe_duration_s(out_path, ffprobe=ffprobe, run=run)
    if abs(actual - duration_s) > DURATION_TOLERANCE_S:
        raise MusicGenError(f"music bed is {actual:g}s, expected {duration_s:g}s")
    lufs = _measure_lufs(out_path, ffmpeg=ffmpeg, run=run)
    if abs(lufs - TARGET_LUFS) > LUFS_TOLERANCE_DB:
        raise MusicGenError(f"music bed loudness is {lufs:g} LUFS, expected {TARGET_LUFS:g} LUFS")
    return MusicBedResult(path=out_path, duration_s=actual, lufs=lufs)


def run(
    storyboard: Mapping[str, Any],
    *,
    workspace_root: Path,
    run_id: str,
    holds: Mapping[str, float] | None = None,
    bed_score: Path | None = None,
    node: str = "node",
    run_process: Callable = subprocess.run,
) -> MusicBedResult:
    """Render the run's music bed to ``runs/<run-id>/audio/bed.wav`` (T028)."""
    root = workspace_root.resolve()
    out_path = root / "runs" / run_id / "audio" / BED_FILENAME
    require_allowed_write_path(out_path, workspace_root=root)

    duration_s = film_duration_s(storyboard, holds)
    if duration_s >= MAX_DURATION_S:
        raise MusicGenError(
            f"assembled film is {duration_s:g}s; must stay under {MAX_DURATION_S:g}s (FR-010)"
        )

    bed_score = (bed_score or root / "scripts" / "anidoodle" / "music" / "bed.ts").resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    return render_music_bed(
        out_path=out_path,
        duration_s=duration_s,
        bed_score=bed_score,
        scaffold_dir=root / "runs" / run_id / "anidoodle",
        repo_root=root,
        node=node,
        run=run_process,
    )
