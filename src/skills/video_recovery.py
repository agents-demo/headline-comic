"""S13b video recovery: per-shot retry-once and animated-still swap (T031, FR-017).

FR-017's recovery half: a shot counts as failed on an **API error**, a **timeout**,
or an **output that fails a duration or resolution check**; a failed shot is retried
once and then replaced by its animated still (the same slow pan/zoom over its keyframe
the fallback uses). This module is the deterministic core of the Leader's video-phase
recovery — it classifies failures, drives the retry, and swaps in the still — and is
provider-agnostic: the per-shot video call is injected as ``render`` so the same code
drives the local AniDoodle whole-run render today and a per-shot paid provider in T043.
Every recovered shot and its outcome are written to ``run.log``, and the recovered
per-shot footage (generated clips plus any stills) is concatenated and assembled into
``runs/<run-id>/video.mp4`` through the shared assembler, so at most two shots may be
stills without losing the whole generated video (SC-1). Local and $0, so the recovery
itself carries no budget line.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from src.flow.runlog import append_entry, log_entry
from src.permissions.media_guard import require_allowed_write_path
from src.skills.assemble import VIDEO_H, VIDEO_W, _find_tool, run as run_assembler
from src.skills.fallback_gen import fallback_filter
from src.skills.image_gen import scene_spec

MAX_ATTEMPTS = 2  # FR-017: one retry, then the animated still
DURATION_TOLERANCE_S = 0.25
EXPECTED_SIZE = (VIDEO_W, VIDEO_H)

_TIMEOUT_ERRORS = (TimeoutError, subprocess.TimeoutExpired)


class ShotRecoveryError(RuntimeError):
    """Raised when a shot's recovery cannot complete (e.g. its still fails to render)."""


@dataclass(frozen=True)
class ShotRenderResult:
    """The per-shot video provider's output: a clip and the checks we run on it."""

    path: Path
    duration_s: float
    width: int
    height: int


@dataclass(frozen=True)
class ShotOutcome:
    """One shot's recovery outcome: a generated clip, or an animated still."""

    shot_id: str
    kind: str  # "generated" | "still"
    source_path: Path
    attempts: int
    reason: str | None  # timeout | api_error | duration | resolution, when "still"


def classify_failure(
    *,
    error: BaseException | None = None,
    result: ShotRenderResult | None = None,
    expected_duration_s: float,
    tolerance_s: float = DURATION_TOLERANCE_S,
    expected_size: tuple[int, int] = EXPECTED_SIZE,
) -> str | None:
    """Deterministic failed-shot classification (FR-017): the failure reason or ``None``.

    An exception is a timeout (``TimeoutError``/``subprocess.TimeoutExpired``) or an
    API error (anything else). A returned result is checked against the shot's
    expected duration and the 1280x720 resolution.
    """
    if error is not None:
        return "timeout" if isinstance(error, _TIMEOUT_ERRORS) else "api_error"
    if result is not None:
        if abs(float(result.duration_s) - float(expected_duration_s)) > tolerance_s:
            return "duration"
        if (int(result.width), int(result.height)) != (int(expected_size[0]), int(expected_size[1])):
            return "resolution"
    return None


def _shot_id(shot: Mapping[str, Any]) -> str:
    shot_id = str(shot.get("shot_id") or "").strip()
    if not shot_id:
        raise ShotRecoveryError("storyboard shot is missing its shot_id")
    return shot_id


def _duration_s(shot: Mapping[str, Any]) -> float:
    duration = float(shot.get("duration_s") or 0)
    if duration <= 0:
        raise ShotRecoveryError(f"shot {_shot_id(shot)} has invalid duration {duration}")
    return duration


def _camera_mode(shot: Mapping[str, Any]) -> str:
    camera = scene_spec(shot).get("camera")
    return str((camera or {}).get("mode") or "zoom")


def still_command(
    ffmpeg: str,
    keyframe: Path,
    duration_s: float,
    camera_mode: str,
    output: Path,
) -> list[str]:
    """One animated still: the fallback's pan/zoom ``zoompan`` chain over a keyframe."""
    return [
        ffmpeg, "-y", "-i", str(keyframe),
        "-vf", fallback_filter(duration_s, camera_mode),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(output),
    ]


def render_still(
    *,
    shot: Mapping[str, Any],
    keyframe: Path,
    output_dir: Path,
    ffmpeg: str,
    run: Callable,
) -> Path:
    """Render a shot's animated still (pan/zoom over its keyframe) and return its path."""
    shot_id = _shot_id(shot)
    duration = _duration_s(shot)
    output = output_dir / f"{shot_id}.mp4"
    output.parent.mkdir(parents=True, exist_ok=True)
    proc = run(
        still_command(ffmpeg, keyframe, duration, _camera_mode(shot), output),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise ShotRecoveryError(f"animated still render failed for {shot_id}: {proc.stderr.strip()[-400:]}")
    if not output.is_file():
        raise ShotRecoveryError(f"animated still render completed without {output}")
    return output


def render_shot_with_recovery(
    *,
    shot: Mapping[str, Any],
    keyframe: Path,
    output_dir: Path,
    render: Callable[[Mapping[str, Any]], ShotRenderResult],
    ffmpeg: str,
    run: Callable,
    max_attempts: int = MAX_ATTEMPTS,
) -> ShotOutcome:
    """Render one shot, retrying once, then swapping to its animated still (FR-017)."""
    shot_id = _shot_id(shot)
    duration = _duration_s(shot)
    if not keyframe.is_file():
        raise ShotRecoveryError(f"keyframe missing for {shot_id}: {keyframe}")

    reason: str | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            result = render(shot)
        except Exception as exc:  # noqa: BLE001 - any provider failure is classified, then retried
            reason = classify_failure(error=exc, expected_duration_s=duration)
        else:
            reason = classify_failure(result=result, expected_duration_s=duration)
            if reason is None:
                return ShotOutcome(shot_id, "generated", result.path, attempt, None)

    still = render_still(shot=shot, keyframe=keyframe, output_dir=output_dir, ffmpeg=ffmpeg, run=run)
    return ShotOutcome(shot_id, "still", still, max_attempts, reason)


def recover_shots(
    storyboard: Mapping[str, Any],
    *,
    keyframes_dir: Path,
    output_dir: Path,
    render: Callable[[Mapping[str, Any]], ShotRenderResult],
    ffmpeg: str,
    run: Callable,
    max_attempts: int = MAX_ATTEMPTS,
) -> list[ShotOutcome]:
    """Recover every shot: render (retry once) or swap to its animated still."""
    shots = storyboard.get("shots")
    if not isinstance(shots, list) or not shots:
        raise ShotRecoveryError("storyboard must contain a non-empty shots array")

    outcomes: list[ShotOutcome] = []
    for shot in shots:
        if not isinstance(shot, Mapping):
            raise ShotRecoveryError("storyboard shot must be an object")
        shot_id = _shot_id(shot)
        outcomes.append(
            render_shot_with_recovery(
                shot=shot,
                keyframe=keyframes_dir / f"{shot_id}.png",
                output_dir=output_dir,
                render=render,
                ffmpeg=ffmpeg,
                run=run,
                max_attempts=max_attempts,
            )
        )
    return outcomes


def concat_outcomes_command(ffmpeg: str, sources: Sequence[Path], output: Path) -> list[str]:
    """Concatenate the recovered per-shot clips into one silent shots video."""
    cmd = [ffmpeg, "-y"]
    for source in sources:
        cmd += ["-i", str(source)]
    filters: list[str] = []
    labels: list[str] = []
    for i, _ in enumerate(sources):
        filters.append(f"[{i}:v]format=yuv420p,setsar=1[v{i}]")
        labels.append(f"[v{i}]")
    filters.append(f"{''.join(labels)}concat=n={len(sources)}:v=1:a=0,format=yuv420p[vout]")
    cmd += [
        "-filter_complex", ";".join(filters),
        "-map", "[vout]",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-an", str(output),
    ]
    return cmd


def concat_shots(
    *,
    outcomes: Sequence[ShotOutcome],
    output: Path,
    ffmpeg: str,
    run: Callable,
) -> Path:
    """Write the mixed shots video (generated clips + stills) for the assembler."""
    if not outcomes:
        raise ShotRecoveryError("no shot outcomes to concatenate")
    output.parent.mkdir(parents=True, exist_ok=True)
    sources = [outcome.source_path for outcome in outcomes]
    proc = run(concat_outcomes_command(ffmpeg, sources, output), capture_output=True, text=True)
    if proc.returncode != 0:
        raise ShotRecoveryError(f"recovered shots concat failed: {proc.stderr.strip()[-400:]}")
    if not output.is_file():
        raise ShotRecoveryError(f"recovered shots concat completed without {output}")
    return output


def run(
    story: Mapping[str, Any],
    storyboard: Mapping[str, Any],
    candidates: Mapping[str, Any],
    summaries: Mapping[str, Any],
    *,
    workspace_root: Path,
    run_id: str,
    render: Callable[[Mapping[str, Any]], ShotRenderResult],
    clips: Sequence[Any] | None = None,
    holds: Mapping[str, float] | None = None,
    ledger: Mapping[str, Any] | None = None,
    bed_path: Path | None = None,
    ffmpeg: str | None = None,
    run_process: Callable = subprocess.run,
) -> Path:
    """Leader recovery: render every shot (retry once), swap failures to stills,
    concatenate the recovered footage, assemble ``runs/<run-id>/video.mp4`` (FR-017)."""
    root = workspace_root.resolve()
    run_dir = root / "runs" / run_id
    shots_dir = require_allowed_write_path(run_dir / "shots", workspace_root=root)
    ffmpeg = ffmpeg or _find_tool(root, "ffmpeg")

    outcomes = recover_shots(
        storyboard,
        keyframes_dir=run_dir / "keyframes",
        output_dir=shots_dir,
        render=render,
        ffmpeg=ffmpeg,
        run=run_process,
    )
    for outcome in outcomes:
        append_entry(
            root,
            run_id,
            log_entry(
                "shot_recovery",
                shot_id=outcome.shot_id,
                outcome=outcome.kind,
                attempts=outcome.attempts,
                reason=outcome.reason,
            ),
        )
    generated = sum(1 for o in outcomes if o.kind == "generated")
    append_entry(
        root,
        run_id,
        log_entry("recovery_summary", generated=generated, stills=len(outcomes) - generated),
    )

    mixed = concat_shots(
        outcomes=outcomes,
        output=run_dir / "cards" / "recovered-shots.mp4",
        ffmpeg=ffmpeg,
        run=run_process,
    )
    return run_assembler(
        story,
        storyboard,
        candidates,
        summaries,
        workspace_root=root,
        run_id=run_id,
        clips=clips,
        holds=holds,
        ledger=ledger,
        video_path=mixed,
        bed_path=bed_path,
        output_name="video.mp4",
        run_process=run_process,
    )
