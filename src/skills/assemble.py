"""S14 assemble: ffmpeg assembly of the finished video (T029).

Turns T027's silent ``shots.mp4`` into the final 45-59 s cut: a 3 s title card, the
shots (each held to fit its narration via the ``hold_last_frame`` overrun), 0.5 s
crossfades between every segment, subtitles (the narration text), TTS narration, the
music bed, a 5 s closing "Based on: 5 sources" card, a small persistent
"AI-generated fiction" mark, and file metadata (FR-010, FR-013). All on-screen text is
composited by code — rendered to PNGs with Pillow here, then overlaid by ffmpeg — never
by a model (D5). Assembly is local and $0, so there is no budget line.

The timeline is the single source of truth and is shared with ``music_gen`` so the bed
and the cut agree on length (both use ``film_duration_s`` and the same card/transition
constants).
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from PIL import Image, ImageDraw, ImageFont

from src.permissions.media_guard import require_allowed_write_path
from src.skills.compose import AI_GENERATED_MARK, facts_cards
from src.skills.music_gen import CLOSING_CARD_S, TITLE_CARD_S, TRANSITION_S
from src.skills.tts_gen import NarrationClip

VIDEO_W = 1280
VIDEO_H = 720
FPS = 24
MUSIC_GAIN = 0.4  # bed ducked under narration
MUSIC_GAIN_SOLO = 1.0  # full bed when it is the only audio (FR-017 subtitles-only)
FADE_OUT_S = 2.0  # music fade at the end of the cut

_PAPER = "#f6f1e5"
_INK = "#17212b"
_INK_SOFT = "#5a6472"

_FONT_PATHS = (
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
)
_BOLD_PATHS = (
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
)
_font_cache: dict[tuple[int, bool], ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}


class AssembleError(RuntimeError):
    """Raised when the run cannot be assembled into a finished video."""


@dataclass(frozen=True)
class Segment:
    """One titled/shot/closing segment of the assembled timeline."""

    kind: str  # "title" | "shot" | "closing"
    duration_s: float
    start_s: float  # on-screen start time (fully visible) in the final cut
    shot_id: str | None = None
    narration: str = ""


@dataclass(frozen=True)
class Timeline:
    segments: tuple[Segment, ...]
    total_s: float


def timeline(
    storyboard: Mapping[str, Any],
    holds: Mapping[str, float] | None = None,
) -> Timeline:
    """Deterministic segment layout: title, shots (+holds), closing, with start times.

    A 0.5 s crossfade joins every adjacent pair, so a segment's fully-visible start is
    ``cumulative_duration - (index - 1) * TRANSITION_S`` and the total is the sum of all
    segment durations minus one crossfade per boundary.
    """
    shots = storyboard.get("shots")
    if not isinstance(shots, list) or not shots:
        raise AssembleError("storyboard must contain a non-empty shots array")
    holds = holds or {}
    segments: list[Segment] = [Segment("title", TITLE_CARD_S, 0.0)]
    cum = TITLE_CARD_S
    for shot in shots:
        if not isinstance(shot, Mapping):
            raise AssembleError("storyboard shot must be an object")
        shot_id = str(shot.get("shot_id") or "").strip()
        if not shot_id:
            raise AssembleError("storyboard shot is missing its shot_id")
        duration = float(shot.get("duration_s") or 0) + float(holds.get(shot_id, 0) or 0)
        start = round(cum - (len(segments) - 1) * TRANSITION_S, 3)
        segments.append(
            Segment("shot", duration, start, shot_id, str(shot.get("narration") or "").strip())
        )
        cum += duration
    start = round(cum - (len(segments) - 1) * TRANSITION_S, 3)
    segments.append(Segment("closing", CLOSING_CARD_S, start))
    total = round(cum + CLOSING_CARD_S - (len(segments) - 1) * TRANSITION_S, 3)
    return Timeline(tuple(segments), total)


def shot_segments(timeline_: Timeline) -> list[Segment]:
    """The shot segments in order (title and closing excluded)."""
    return [seg for seg in timeline_.segments if seg.kind == "shot"]


# --- deterministic Pillow rendering (all text is code-composited, D5) -------------


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    key = (size, bold)
    if key not in _font_cache:
        for candidate in (_BOLD_PATHS if bold else _FONT_PATHS):
            if Path(candidate).is_file():
                _font_cache[key] = ImageFont.truetype(candidate, size)
                break
        else:
            _font_cache[key] = ImageFont.load_default(size)
    return _font_cache[key]


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if not current or draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def render_title_card(story: Mapping[str, Any], output_path: Path) -> Path:
    """Render the 3 s title card: story title + fiction label on the paper ground."""
    image = Image.new("RGB", (VIDEO_W, VIDEO_H), _PAPER)
    draw = ImageDraw.Draw(image)
    title = str(story.get("title") or "").strip() or "Today's story"
    label = str(story.get("fiction_label") or "Fiction inspired by today's news").strip()
    draw.text((VIDEO_W / 2, VIDEO_H / 2 - 44), title, font=_font(54, bold=True), fill=_INK, anchor="mm")
    draw.text((VIDEO_W / 2, VIDEO_H / 2 + 24), label, font=_font(26), fill=_INK_SOFT, anchor="mm")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)
    return output_path


def render_closing_card(cards: Sequence[Mapping[str, Any]], output_path: Path) -> Path:
    """Render the 5 s closing card: "Based on: 5 sources" + each source title and link."""
    image = Image.new("RGB", (VIDEO_W, VIDEO_H), _PAPER)
    draw = ImageDraw.Draw(image)
    count = len(cards)
    draw.text((VIDEO_W / 2, 64), f"Based on: {count} sources", font=_font(40, bold=True), fill=_INK, anchor="ma")
    draw.text((VIDEO_W / 2, 116), "Today's news — the stories behind the comic", font=_font(20), fill=_INK_SOFT, anchor="ma")

    title_font = _font(22, bold=True)
    link_font = _font(16)
    max_w = VIDEO_W - 160
    y = 168
    line_step = 96
    for card in cards[:5]:
        source = int(card.get("source") or 0)
        title_lines = _wrap(draw, str(card.get("title") or ""), title_font, max_w)
        link = str(card.get("link") or "").strip()
        draw.text((80, y), f"{source}.", font=title_font, fill=_INK)
        ty = y
        for line in title_lines[:1]:  # one title line keeps five sources on one card
            draw.text((128, ty), line, font=title_font, fill=_INK)
            ty += title_font.size + 4
        draw.text((128, ty), link, font=link_font, fill=_INK_SOFT)
        y += line_step
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)
    return output_path


def render_subtitle(text: str, output_path: Path) -> Path:
    """Render one shot's narration as a transparent 1280x720 overlay with a bottom band."""
    image = Image.new("RGBA", (VIDEO_W, VIDEO_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    font = _font(34, bold=True)
    max_w = VIDEO_W - 200
    lines = _wrap(draw, text, font, max_w)[:2]
    if not lines:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(output_path)
        return output_path
    line_h = font.size + 10
    band_h = len(lines) * line_h + 48
    band_y = VIDEO_H - band_h - 40
    draw.rounded_rectangle(
        [0, band_y, VIDEO_W, VIDEO_H],
        radius=0,
        fill=(10, 12, 16, 170),
    )
    y = band_y + 24
    for line in lines:
        draw.text((VIDEO_W / 2, y), line, font=font, fill=(255, 255, 255, 255), anchor="ma")
        y += line_h
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)
    return output_path


def render_mark(output_path: Path) -> Path:
    """Render the small persistent "AI-generated fiction" watermark."""
    font = _font(20, bold=True)
    measurer = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    text_w = int(measurer.textlength(AI_GENERATED_MARK, font=font))
    pad_x, pad_y = 14, 8
    w = text_w + 2 * pad_x
    h = font.size + 2 * pad_y
    image = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle([0, 0, w - 1, h - 1], radius=6, fill=(10, 12, 16, 150))
    draw.text((pad_x, pad_y), AI_GENERATED_MARK, font=font, fill=(255, 255, 255, 230))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)
    return output_path


# --- deterministic ffmpeg command construction -----------------------------------


def _find_tool(repo_root: Path, name: str) -> str:
    exe = f"{name}.exe" if os.name == "nt" else name
    tools_root = repo_root / "runs" / "_tools" / "ffmpeg"
    if tools_root.is_dir():
        for bin_dir in sorted(tools_root.glob("*/bin")):
            candidate = bin_dir / exe
            if candidate.is_file():
                return str(candidate)
    return name


def _shot_cut_starts(storyboard: Mapping[str, Any]) -> list[float]:
    """Cumulative start time of each shot inside the silent ``shots.mp4`` (no holds)."""
    shots = storyboard.get("shots")
    if not isinstance(shots, list):
        raise AssembleError("storyboard must contain a shots array")
    starts: list[float] = []
    cum = 0.0
    for shot in shots:
        starts.append(cum)
        cum += float(shot.get("duration_s") or 0)
    return starts


def segment_command(
    *,
    ffmpeg: str,
    kind: str,
    source: Path,
    duration_s: float,
    start_s: float,
    hold_s: float,
    output: Path,
) -> list[str]:
    """One silent 1280x720 segment MP4 (a looped card image or a trimmed video shot)."""
    if kind in ("title", "closing"):
        return [
            ffmpeg, "-y", "-loop", "1", "-t", f"{duration_s:g}", "-i", str(source),
            "-r", str(FPS), "-vf", f"scale={VIDEO_W}:{VIDEO_H},format=yuv420p,setsar=1",
            "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(output),
        ]
    tpad = f",tpad=stop_mode=clone:stop_duration={hold_s:g}" if hold_s > 0 else ""
    return [
        ffmpeg, "-y", "-i", str(source), "-ss", f"{start_s:g}", "-t", f"{duration_s:g}",
        "-vf", f"setpts=PTS-STARTPTS{tpad},format=yuv420p,setsar=1",
        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(output),
    ]


def concat_command(*, ffmpeg: str, segments: Sequence[Path], durations: Sequence[float], output: Path) -> list[str]:
    """xfade-chain the segment files into one silent timeline video."""
    labels = [f"[{i}:v]" for i in range(len(segments))]
    filters: list[str] = []
    prev = labels[0]
    cum = durations[0]
    for i in range(1, len(segments)):
        offset = cum - i * TRANSITION_S
        out = f"[x{i - 1}]" if i < len(segments) - 1 else "[vout]"
        filters.append(f"{prev}{labels[i]}xfade=transition=fade:duration={TRANSITION_S:g}:offset={offset:g}{out}")
        prev = out
        cum += durations[i]
    cmd = [ffmpeg, "-y"]
    for seg in segments:
        cmd += ["-i", str(seg)]
    cmd += ["-filter_complex", ";".join(filters), "-map", "[vout]", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(output)]
    return cmd


def audio_command(
    *,
    ffmpeg: str,
    narration: Sequence[tuple[Path, float]],
    bed: Path,
    total_s: float,
    output: Path,
) -> list[str]:
    """Mix delayed narration clips over the (gained, faded) music bed."""
    cmd = [ffmpeg, "-y"]
    for path, _ in narration:
        cmd += ["-i", str(path)]
    bed_index = len(narration)
    cmd += ["-i", str(bed)]

    filters: list[str] = []
    narr_labels: list[str] = []
    for i, (_, start_s) in enumerate(narration):
        ms = round(start_s * 1000)
        filters.append(f"[{i}:a]adelay={ms}:all=1[a{i}]")
        narr_labels.append(f"[a{i}]")
    if len(narr_labels) > 1:
        filters.append(f"{''.join(narr_labels)}amix=inputs={len(narr_labels)}:duration=longest:normalize=0[narr]")
        narr_label = "[narr]"
    elif len(narr_labels) == 1:
        narr_label = narr_labels[0]
    else:
        narr_label = None

    fade_start = max(0.0, total_s - FADE_OUT_S)
    gain = MUSIC_GAIN if narration else MUSIC_GAIN_SOLO
    filters.append(f"[{bed_index}:a]volume={gain:g},afade=t=out:st={fade_start:g}:d={FADE_OUT_S:g}[music]")

    if narr_label is not None:
        filters.append(f"{narr_label}[music]amix=inputs=2:duration=longest:normalize=0,alimiter=limit=0.98[aout]")
    else:
        filters.append("[music]alimiter=limit=0.98[aout]")

    cmd += ["-filter_complex", ";".join(filters), "-map", "[aout]", "-t", f"{total_s:g}", "-c:a", "pcm_s16le", str(output)]
    return cmd


def mux_command(
    *,
    ffmpeg: str,
    video: Path,
    audio: Path,
    subtitles: Sequence[tuple[Path, float, float]],
    mark: Path,
    title: str,
    output: Path,
) -> list[str]:
    """Mux the timeline video + audio, overlay subtitles and the mark, and set metadata."""
    cmd = [ffmpeg, "-y", "-i", str(video), "-i", str(audio)]
    for path, _, _ in subtitles:
        cmd += ["-i", str(path)]
    mark_index = 2 + len(subtitles)
    cmd += ["-i", str(mark)]

    filters: list[str] = []
    prev = "[0:v]"
    for i, (_, start_s, end_s) in enumerate(subtitles):
        label = f"[s{i}]"
        filters.append(f"[{2 + i}:v]null{label}")
        out = f"[o{i}]"
        filters.append(f"{prev}{label}overlay=0:0:enable='between(t,{start_s:g},{end_s:g})'{out}")
        prev = out
    filters.append(f"{prev}[{mark_index}:v]overlay=W-w-16:16[ov]")

    cmd += [
        "-filter_complex", ";".join(filters),
        "-map", "[ov]", "-map", "1:a",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
        "-metadata", f"title={title}",
        "-metadata", "comment=AI-generated fiction",
        "-movflags", "+faststart",
        str(output),
    ]
    return cmd


def _probe(path: Path, *, ffprobe: str, run: Callable) -> dict[str, Any]:
    proc = run(
        [
            ffprobe, "-v", "error",
            "-show_entries", "format=duration:stream=width,height,codec_type",
            "-of", "json", str(path),
        ],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise AssembleError(f"ffprobe could not read {path}: {proc.stderr.strip()[:200]}")
    return json.loads(proc.stdout)


# --- orchestration ---------------------------------------------------------------


def assemble(
    *,
    timeline_: Timeline,
    storyboard: Mapping[str, Any],
    video_path: Path,
    clips: Sequence[NarrationClip] | None,
    bed_path: Path,
    cards_dir: Path,
    story: Mapping[str, Any],
    cards: Sequence[Mapping[str, Any]],
    final_path: Path,
    repo_root: Path,
    run: Callable = subprocess.run,
) -> Path:
    """Render cards, then run the ffmpeg segment/concat/audio/mux steps and verify."""
    ffmpeg = _find_tool(repo_root, "ffmpeg")
    ffprobe = _find_tool(repo_root, "ffprobe")

    cards_dir.mkdir(parents=True, exist_ok=True)
    render_title_card(story, cards_dir / "title.png")
    render_closing_card(cards, cards_dir / "closing.png")
    render_mark(cards_dir / "mark.png")

    shots = shot_segments(timeline_)
    cut_starts = _shot_cut_starts(storyboard)

    # subtitle PNGs for every narrated shot (subtitles always come from the storyboard)
    subtitles: list[tuple[Path, float, float]] = []
    for i, seg in enumerate(shots):
        if not seg.narration:
            continue
        png = cards_dir / f"subtitle-{seg.shot_id}.png"
        render_subtitle(seg.narration, png)
        end_s = seg.start_s + seg.duration_s - TRANSITION_S
        subtitles.append((png, seg.start_s, max(seg.start_s, end_s)))

    # narration audio: only spoken clips with an existing file, matched to shot start
    spoken = {clip.shot_id: clip for clip in (clips or []) if clip.spoken}
    narration: list[tuple[Path, float]] = []
    for seg in shots:
        clip = spoken.get(seg.shot_id)
        if clip is not None and Path(clip.audio_path).is_file():
            narration.append((Path(clip.audio_path), seg.start_s))

    # per-segment silent files -> xfade concat
    seg_files: list[Path] = []
    seg_durations: list[float] = []
    for index, seg in enumerate(timeline_.segments):
        out = cards_dir / f"seg-{index:02d}.mp4"
        if seg.kind == "title":
            source = cards_dir / "title.png"
            start_s, hold_s = 0.0, 0.0
        elif seg.kind == "closing":
            source = cards_dir / "closing.png"
            start_s, hold_s = 0.0, 0.0
        else:
            source = video_path
            shot_index = shots.index(seg)
            start_s = cut_starts[shot_index]
            hold_s = max(0.0, seg.duration_s - float(storyboard["shots"][shot_index]["duration_s"] or 0))
        _run_checked(
            segment_command(ffmpeg=ffmpeg, kind=seg.kind, source=source, duration_s=seg.duration_s,
                            start_s=start_s, hold_s=hold_s, output=out),
            run,
        )
        seg_files.append(out)
        seg_durations.append(seg.duration_s)

    timeline_video = cards_dir / "timeline.mp4"
    _run_checked(concat_command(ffmpeg=ffmpeg, segments=seg_files, durations=seg_durations, output=timeline_video), run)

    mix = cards_dir / "mix.wav"
    _run_checked(audio_command(ffmpeg=ffmpeg, narration=narration, bed=bed_path, total_s=timeline_.total_s, output=mix), run)

    final_path.parent.mkdir(parents=True, exist_ok=True)
    title = str(story.get("title") or "Today's story")
    _run_checked(
        mux_command(ffmpeg=ffmpeg, video=timeline_video, audio=mix, subtitles=subtitles,
                    mark=cards_dir / "mark.png", title=title, output=final_path),
        run,
    )

    info = _probe(final_path, ffprobe=ffprobe, run=run)
    _verify(info, timeline_.total_s)
    return final_path


def _run_checked(cmd: list[str], run: Callable) -> None:
    proc = run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise AssembleError(f"ffmpeg step failed: {' '.join(cmd)}\n{proc.stderr.strip()[-800:]}")


def _verify(info: Mapping[str, Any], expected_s: float) -> None:
    fmt = info.get("format") if isinstance(info, Mapping) else None
    streams = info.get("streams") if isinstance(info, Mapping) else None
    if not isinstance(fmt, Mapping) or not isinstance(streams, list) or not streams:
        raise AssembleError("video probe returned no format/streams")
    duration = float(fmt.get("duration") or 0)
    if duration <= 0 or duration >= 60.0:
        raise AssembleError(f"video duration {duration:g}s is outside 0-60s")
    if abs(duration - expected_s) > 0.5:
        raise AssembleError(f"video is {duration:g}s, expected ~{expected_s:g}s")
    video = [s for s in streams if s.get("codec_type") == "video"]
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    if not video:
        raise AssembleError("video has no video stream")
    if not audio:
        raise AssembleError("video has no audio stream")
    width = int(video[0].get("width") or 0)
    height = int(video[0].get("height") or 0)
    if (width, height) != (VIDEO_W, VIDEO_H):
        raise AssembleError(f"video is {width}x{height}, expected {VIDEO_W}x{VIDEO_H}")


def run(
    story: Mapping[str, Any],
    storyboard: Mapping[str, Any],
    candidates: Mapping[str, Any],
    summaries: Mapping[str, Any],
    *,
    workspace_root: Path,
    run_id: str,
    clips: Sequence[NarrationClip] | None = None,
    holds: Mapping[str, float] | None = None,
    ledger: Mapping[str, Any] | None = None,
    video_path: Path | None = None,
    bed_path: Path | None = None,
    output_name: str = "video.mp4",
    run_process: Callable = subprocess.run,
) -> Path:
    """Assemble ``runs/<run-id>/<output_name>`` from a finished story, storyboard and sources."""
    root = workspace_root.resolve()
    run_dir = root / "runs" / run_id
    final_path = require_allowed_write_path(run_dir / output_name, workspace_root=root)
    if final_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing video: {final_path}")

    tl = timeline(storyboard, holds)
    cards = facts_cards(summaries, candidates, ledger=ledger)
    return assemble(
        timeline_=tl,
        storyboard=storyboard,
        video_path=(video_path or run_dir / "shots.mp4").resolve(),
        clips=clips,
        bed_path=(bed_path or run_dir / "audio" / "bed.wav").resolve(),
        cards_dir=run_dir / "cards",
        story=story,
        cards=cards,
        final_path=final_path,
        repo_root=root,
        run=run_process,
    )
