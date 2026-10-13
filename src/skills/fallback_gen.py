"""S12 fallback_gen: pan-and-zoom over the keyframes, rendered in every run (T030).

Builds the fallback video (``runs/<run-id>/fallback.mp4``) so the demo never ends
without a video (FR-017, D6). It is the *same* finished cut as the generated video —
title card, per-shot footage, crossfades, subtitles, narration, music bed, closing
card and the persistent "AI-generated fiction" mark — but the silent footage comes
from the still keyframes instead of the AniDoodle render: each shot is a slow Ken
Burns pan/zoom over its keyframe (a horizontal pan for the overhead map shot) that is
centred on the shot's character focal point rather than the frame centre, and the zoom
direction alternates in/out so consecutive shots do not all move the same way, driven
by ffmpeg ``zoompan`` (pan and zoom only, no parallax or sprites). Everything after
the silent shots — holds, transitions, subtitles, audio, cards, metadata — is
delegated to the assembler (T029), so the fallback and the generated video can never
drift apart. Local and $0, so there is no budget line.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from src.permissions.media_guard import require_allowed_write_path
from src.skills.assemble import FPS, VIDEO_H, VIDEO_W, _find_tool, run as run_assembler
from src.skills.image_gen import H as KEYFRAME_H, W as KEYFRAME_W, scene_spec

# Slow, deterministic pan-and-zoom parameters (pan and zoom only, D6).
ZOOM_STEP = 0.0015  # zoom-in per output frame
ZOOM_MAX = 1.4
PAN_ZOOM = 1.3  # fixed zoom for the horizontal pan (overhead map)
UPSCALE_W = 2560  # 2x upscale before zoompan for smoother sub-pixel motion
UPSCALE_H = 1440


class FallbackError(RuntimeError):
    """Raised when the fallback video cannot be rendered from the keyframes."""


def fallback_frames(duration_s: float) -> int:
    """Frame count for one shot's pan/zoom segment (matching the 24 fps grid)."""
    return max(1, round(float(duration_s) * FPS))


def fallback_filter(
    duration_s: float,
    camera_mode: str,
    *,
    fx: float | None = None,
    fy: float | None = None,
    direction: str = "in",
) -> str:
    """The zoompan filter chain for one shot: a focal zoom-in/out, or a pan for overhead.

    Zoom shots centre the ``zoompan`` window on the shot's character focal point
    ``(fx, fy)`` (in 1280x720 keyframe space, from ``image_gen.scene_spec``) instead of
    the frame centre, and ``direction`` picks a zoom-in (``"in"``) or zoom-out
    (``"out"``). The overhead map keeps its horizontal pan. Pan and zoom only (D6).
    """
    frames = fallback_frames(duration_s)
    if camera_mode == "overhead":
        zoom = f"{PAN_ZOOM:g}"
        x = f"(iw-iw/zoom)*on/{frames}"
        y = "ih/2-(ih/zoom/2)"
    else:
        # Scale the keyframe-space focal point to the 2x-upscaled zoompan input.
        focal_x = (KEYFRAME_W / 2 if fx is None else float(fx)) * (UPSCALE_W / KEYFRAME_W)
        focal_y = (KEYFRAME_H / 2 if fy is None else float(fy)) * (UPSCALE_H / KEYFRAME_H)
        if direction == "out":
            zoom = f"max({ZOOM_MAX:g}-({ZOOM_STEP:g}*on),1)"
        else:
            zoom = f"min(1+({ZOOM_STEP:g}*on),{ZOOM_MAX:g})"
        # Window left/top edge such that its centre stays on the focal point; zoompan
        # clamps to the full frame at zoom == 1 (x/y land in [0, iw-iw/zoom]).
        x = f"{focal_x:g}-(iw/zoom/2)"
        y = f"{focal_y:g}-(ih/zoom/2)"
    return (
        f"scale={UPSCALE_W}:{UPSCALE_H},"
        f"zoompan=z='{zoom}':x='{x}':y='{y}':d={frames}:s={VIDEO_W}x{VIDEO_H}:fps={FPS},"
        f"format=yuv420p,setsar=1"
    )


def fallback_shots_command(
    ffmpeg: str,
    keyframes: Sequence[Path],
    durations: Sequence[float],
    motions: Sequence[Mapping[str, Any]],
    output: Path,
) -> list[str]:
    """One ffmpeg command that pans/zooms every keyframe and concatenates the shots.

    ``motions`` carries one mapping per shot with ``mode`` (``"zoom"``/``"overhead"``),
    the optional focal point ``fx``/``fy`` and ``direction`` (``"in"``/``"out"``).
    """
    cmd = [ffmpeg, "-y"]
    for keyframe in keyframes:
        cmd += ["-i", str(keyframe)]
    filters: list[str] = []
    labels: list[str] = []
    for i, (duration, motion) in enumerate(zip(durations, motions)):
        filters.append(
            f"[{i}:v]"
            f"{fallback_filter(duration, str(motion.get('mode') or 'zoom'), fx=motion.get('fx'), fy=motion.get('fy'), direction=str(motion.get('direction') or 'in'))}"
            f"[v{i}]"
        )
        labels.append(f"[v{i}]")
    filters.append(
        f"{''.join(labels)}concat=n={len(keyframes)}:v=1:a=0[vout]"
    )
    cmd += [
        "-filter_complex", ";".join(filters),
        "-map", "[vout]",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-an", str(output),
    ]
    return cmd


def render_fallback_shots(
    storyboard: Mapping[str, Any],
    *,
    keyframes_dir: Path,
    output: Path,
    repo_root: Path,
    ffmpeg: str | None = None,
    run: Callable = subprocess.run,
) -> Path:
    """Render the silent pan/zoom shots video (one segment per keyframe, concatenated)."""
    shots = storyboard.get("shots")
    if not isinstance(shots, list) or not shots:
        raise FallbackError("storyboard must contain a non-empty shots array")

    keyframes: list[Path] = []
    durations: list[float] = []
    motions: list[dict[str, Any]] = []
    for index, shot in enumerate(shots):
        if not isinstance(shot, Mapping):
            raise FallbackError("storyboard shot must be an object")
        shot_id = str(shot.get("shot_id") or "").strip()
        if not shot_id:
            raise FallbackError("storyboard shot is missing its shot_id")
        keyframe = keyframes_dir / f"{shot_id}.png"
        if not keyframe.is_file():
            raise FallbackError(f"keyframe missing for {shot_id}: {keyframe}")
        keyframes.append(keyframe)
        durations.append(float(shot.get("duration_s") or 0))
        camera = scene_spec(shot).get("camera") or {}
        mode = str(camera.get("mode") or "zoom")
        motion: dict[str, Any] = {"mode": mode}
        if mode != "overhead":
            motion["fx"] = camera.get("fx")
            motion["fy"] = camera.get("fy")
            # Alternate zoom direction so consecutive shots do not all push in.
            motion["direction"] = "out" if index % 2 else "in"
        motions.append(motion)

    ffmpeg = ffmpeg or _find_tool(repo_root, "ffmpeg")
    output.parent.mkdir(parents=True, exist_ok=True)
    proc = run(
        fallback_shots_command(ffmpeg, keyframes, durations, motions, output),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise FallbackError(f"fallback pan/zoom render failed: {proc.stderr.strip()[-800:]}")
    if not output.is_file():
        raise FallbackError(f"fallback render completed without {output}")
    return output


def run(
    story: Mapping[str, Any],
    storyboard: Mapping[str, Any],
    candidates: Mapping[str, Any],
    summaries: Mapping[str, Any],
    *,
    workspace_root: Path,
    run_id: str,
    clips: Sequence[Any] | None = None,
    holds: Mapping[str, float] | None = None,
    ledger: Mapping[str, Any] | None = None,
    bed_path: Path | None = None,
    run_process: Callable = subprocess.run,
) -> Path:
    """Render ``runs/<run-id>/fallback.mp4``: pan/zoom shots, then the shared assembly."""
    root = workspace_root.resolve()
    run_dir = root / "runs" / run_id
    shots_video = require_allowed_write_path(
        run_dir / "cards" / "fallback-shots.mp4", workspace_root=root
    )
    render_fallback_shots(
        storyboard,
        keyframes_dir=run_dir / "keyframes",
        output=shots_video,
        repo_root=root,
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
        video_path=shots_video,
        bed_path=bed_path,
        output_name="fallback.mp4",
        run_process=run_process,
    )
