"""MiniMax-H3 (Hailuo 3.0) image-to-video adapter with native audio (T043).

MiniMax-H3 is the presenter's self-hosted 33B omni-modal video model, served over
SGLang's HTTP video API. Confirmed against the SGLang ``minimax_h3`` serving script
and the MiniMax community checkpoint notes (checked 2026-10-19):

- ``POST {base}/v1/videos`` with body ``{model, prompt, seconds, task, conditions,
  target, quality, num_outputs_per_prompt, num_inference_steps, flow_shift,
  audio_flow_shift, seed}`` -> a JSON job id (async).
- Poll ``GET {base}/v1/videos/{id}`` for ``status`` (``pending``/``running``/
  ``completed``/``failed``); ``GET {base}/v1/videos/{id}/content`` -> the MP4 bytes.
- ``task`` is ``fl2va`` (text / first-last-frame -> video) or ``ref2va``; we use
  ``fl2va`` with a single first-frame keyframe condition so each shot's AniDoodle
  keyframe pins the look (comic<->video alignment, FR-010).
- A keyframe condition references a **server-visible** ``file://`` URI — not bytes,
  base64, or a URL: ``{"type": "image", "uri": "file:///data/minimax-h3/<run>/
  keyframes/<shot>.png", "role": "keyframe", "frame_index": 0}``. The presenter
  mounts this repo's ``runs/`` directory at the server path behind
  ``MINIMAX_H3_MEDIA_BASE_URI`` (default ``file:///data/minimax-h3``), so
  ``runs/<run-id>/keyframes/<shot-id>.png`` is visible to SGLang.
- ``target.short_edge 768`` at 16:9 renders 1344x768 (dimensions are /32), 24 fps,
  4-15 s, with **native stereo audio** (32 kHz). The adapter re-encodes to the
  assembler's 1280x720 / 24 fps / AAC 48 kHz before returning, so the recovery
  resolution check and the ffmpeg assembly stay unchanged.

The adapter returns a ``ShotRenderResult`` per shot through the recovery seam
(``renderer(storyboard, keyframes_dir) -> Callable[[shot], ShotRenderResult]``), so
the retry-once + animated-still swap in ``video_recovery`` drives it unchanged. H3 is
self-hosted, so each call costs $0: no T007 approval record is required. This module
follows the same conventions as ``fishaudio.py`` — ``urllib.request`` with an
injectable ``urlopen``, ``load_env``, and ffprobe/ffmpeg via the vendored tools.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib import request
from urllib.error import HTTPError, URLError

from src.env import load_env

from .contracts import ShotRenderResult

DEFAULT_BASE_URL = "http://127.0.0.1:30010"
DEFAULT_MODEL = "MiniMaxAI/MiniMax-H3"
DEFAULT_VARIANT = "fl2va"
VARIANTS = ("fl2va", "ref2va")
DEFAULT_MEDIA_BASE_URI = "file:///data/minimax-h3"
DEFAULT_SHORT_EDGE = 768
DEFAULT_ASPECT_RATIO = "16:9"
DEFAULT_NUM_INFERENCE_STEPS = 50
MIN_SECONDS = 4.0
MAX_SECONDS = 15.0
GENERATION_TIMEOUT_S = 600.0
POLL_INTERVAL_S = 3.0

# The assembler's fixed timeline resolution/frame-rate; H3 output is re-encoded to
# this before the recovery resolution check and ffmpeg assembly run against it.
OUTPUT_W = 1280
OUTPUT_H = 720
OUTPUT_FPS = 24

_STYLE_BLOCK = (
    "Miniature tilt-shift comedy set in a 1-inch toy diorama town. "
    "Clay and plastic figurines with oversized glossy round eyes and soft bokeh, "
    "filmed with a macro lens and a shallow depth of field. "
    "Playful, family-friendly, tiny but expressive performances."
)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class MiniMaxH3Error(RuntimeError):
    """Raised when an H3 request itself fails (transport, submission, generation)."""


class MiniMaxH3TimeoutError(TimeoutError):
    """Raised when H3 generation does not complete within its deadline.

    Subclasses ``TimeoutError`` so the recovery's ``classify_failure`` maps it to the
    ``timeout`` outcome (FR-017) rather than a generic API error.
    """


def compile_prompt(shot: Mapping[str, Any]) -> str:
    """Deterministically assemble one shot's H3 prompt from the storyboard fields."""
    parts = [_STYLE_BLOCK]
    for label, field in (
        ("Scene", "scene_setting"),
        ("Action", "action"),
        ("Visual gag", "gag"),
        ("Camera", "camera"),
        ("Audio", "audio_cue"),
    ):
        value = str(shot.get(field) or "").strip()
        if value:
            parts.append(f"{label}: {value}.")
    return " ".join(parts)


def keyframe_condition(uri: str, frame_index: int = 0) -> dict[str, Any]:
    """One image-to-video keyframe condition (first frame pins the shot's look)."""
    return {"type": "image", "uri": uri, "role": "keyframe", "frame_index": frame_index}


def keyframe_uri(media_base_uri: str, run_id: str, shot_id: str) -> str:
    """The server-visible ``file://`` URI for a shot's keyframe under the mount."""
    return f"{media_base_uri.rstrip('/')}/{run_id}/keyframes/{shot_id}.png"


def build_request_body(
    *,
    model: str,
    prompt: str,
    seconds: float,
    keyframe_uri: str,
    task: str = DEFAULT_VARIANT,
    short_edge: int = DEFAULT_SHORT_EDGE,
    aspect_ratio: str = DEFAULT_ASPECT_RATIO,
    num_inference_steps: int = DEFAULT_NUM_INFERENCE_STEPS,
    seed: int,
) -> dict[str, Any]:
    """The confirmed SGLang ``POST /v1/videos`` body for a first-frame fl2va shot."""
    return {
        "model": model,
        "prompt": prompt,
        "seconds": seconds,
        "task": task,
        "conditions": [keyframe_condition(keyframe_uri, 0)],
        "target": {"short_edge": short_edge, "aspect_ratio": aspect_ratio, "duration_seconds": seconds},
        "quality": "exact",
        "num_outputs_per_prompt": 1,
        "num_inference_steps": num_inference_steps,
        "flow_shift": 12.0,
        "audio_flow_shift": 3.0,
        "seed": seed,
    }


def _stable_seed(shot_id: str) -> int:
    """A deterministic per-shot seed (Python's ``hash`` is salted per process)."""
    value = 0
    for char in shot_id:
        value = (value * 31 + ord(char)) & 0xFFFFFFFF
    return value or 2101


def _find_tool(repo_root: Path, name: str) -> str:
    exe = f"{name}.exe" if os.name == "nt" else name
    tools_root = repo_root / "runs" / "_tools" / "ffmpeg"
    if tools_root.is_dir():
        for bin_dir in sorted(tools_root.glob("*/bin")):
            candidate = bin_dir / exe
            if candidate.is_file():
                return str(candidate)
    return name


def _error_detail(exc: HTTPError) -> str:
    try:
        payload = json.loads(exc.read().decode("utf-8"))
        if isinstance(payload, dict):
            for key in ("detail", "error", "message"):
                value = payload.get(key)
                if isinstance(value, str) and value:
                    return value
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    return exc.reason or ""


class MiniMaxH3VideoProvider:
    """Render one shot at a time through MiniMax-H3 over SGLang, returning its clip.

    Env config (all optional, with local-device defaults): ``MINIMAX_H3_BASE_URL``,
    ``MINIMAX_H3_MODEL``, ``MINIMAX_H3_VARIANT``, ``MINIMAX_H3_MEDIA_BASE_URI``,
    ``MINIMAX_H3_SHORT_EDGE``, ``MINIMAX_H3_ASPECT_RATIO``,
    ``MINIMAX_H3_NUM_INFERENCE_STEPS``.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        variant: str | None = None,
        media_base_uri: str | None = None,
        short_edge: int | None = None,
        aspect_ratio: str | None = None,
        num_inference_steps: int | None = None,
        seed: int | None = None,
        timeout: float = GENERATION_TIMEOUT_S,
        poll_interval: float = POLL_INTERVAL_S,
        urlopen: Callable[..., Any] | None = None,
        probe: Callable[[Path], tuple[float, int, int]] | None = None,
        run: Callable = subprocess.run,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        load_env(_PROJECT_ROOT / ".env")
        self.base_url = (base_url or os.environ.get("MINIMAX_H3_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.model = (model or os.environ.get("MINIMAX_H3_MODEL") or DEFAULT_MODEL).strip()
        self.variant = (variant or os.environ.get("MINIMAX_H3_VARIANT") or DEFAULT_VARIANT).strip()
        if self.variant not in VARIANTS:
            raise ValueError(f"variant must be one of {VARIANTS}")
        self.media_base_uri = (
            media_base_uri or os.environ.get("MINIMAX_H3_MEDIA_BASE_URI") or DEFAULT_MEDIA_BASE_URI
        ).rstrip("/")
        self.short_edge = int(short_edge or os.environ.get("MINIMAX_H3_SHORT_EDGE") or DEFAULT_SHORT_EDGE)
        self.aspect_ratio = (aspect_ratio or os.environ.get("MINIMAX_H3_ASPECT_RATIO") or DEFAULT_ASPECT_RATIO).strip()
        self.num_inference_steps = int(
            num_inference_steps or os.environ.get("MINIMAX_H3_NUM_INFERENCE_STEPS") or DEFAULT_NUM_INFERENCE_STEPS
        )
        self.seed = seed
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.repo_root = _PROJECT_ROOT
        self._urlopen = urlopen or request.urlopen
        self._probe = probe or self._probe_ffprobe
        self._run = run
        self._sleep = sleep

    def renderer(
        self,
        storyboard: Mapping[str, Any],
        keyframes_dir: Path | str,
    ) -> Callable[[Mapping[str, Any]], ShotRenderResult]:
        """Return a per-shot ``render`` callable for the recovery seam.

        The run id and shots output directory are derived from ``keyframes_dir``
        (``runs/<run-id>/keyframes``), matching where the recovery stage writes its
        per-shot clips.
        """
        if not isinstance(storyboard.get("shots"), list):
            raise MiniMaxH3Error("storyboard must contain a shots array")
        keyframes_dir = Path(keyframes_dir)
        run_id = keyframes_dir.parent.name
        shots_dir = keyframes_dir.parent / "shots"
        shots_dir.mkdir(parents=True, exist_ok=True)

        def render(shot: Mapping[str, Any]) -> ShotRenderResult:
            return self._render_shot(shot, keyframes_dir=keyframes_dir, shots_dir=shots_dir, run_id=run_id)

        return render

    def _render_shot(
        self,
        shot: Mapping[str, Any],
        *,
        keyframes_dir: Path,
        shots_dir: Path,
        run_id: str,
    ) -> ShotRenderResult:
        shot_id = str(shot.get("shot_id") or "").strip()
        if not shot_id:
            raise MiniMaxH3Error("storyboard shot is missing its shot_id")
        duration = float(shot.get("duration_s") or 0)
        if duration <= 0:
            raise MiniMaxH3Error(f"shot {shot_id} has invalid duration {duration}")
        keyframe = keyframes_dir / f"{shot_id}.png"
        if not keyframe.is_file():
            raise MiniMaxH3Error(f"keyframe missing for {shot_id}: {keyframe}")

        seconds = round(min(max(duration, MIN_SECONDS), MAX_SECONDS), 1)
        body = build_request_body(
            model=self.model,
            prompt=compile_prompt(shot),
            seconds=seconds,
            keyframe_uri=keyframe_uri(self.media_base_uri, run_id, shot_id),
            task=self.variant,
            short_edge=self.short_edge,
            aspect_ratio=self.aspect_ratio,
            num_inference_steps=self.num_inference_steps,
            seed=self.seed if self.seed is not None else _stable_seed(shot_id),
        )

        job_id = self._submit(body)
        raw = shots_dir / f"{shot_id}-raw.mp4"
        self._await(job_id, raw)
        final = shots_dir / f"{shot_id}.mp4"
        self._normalize(raw, final)
        duration_s, width, height = self._probe(final)
        return ShotRenderResult(path=final, duration_s=duration_s, width=width, height=height)

    def _submit(self, body: Mapping[str, Any]) -> str:
        req = request.Request(
            f"{self.base_url}/v1/videos",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._urlopen(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            raise MiniMaxH3Error(f"H3 submit HTTP {exc.code}: {_error_detail(exc)}") from exc
        except URLError as exc:
            raise MiniMaxH3Error(f"H3 submit network error: {exc.reason}") from exc
        job_id = payload.get("id") or payload.get("request_id") or payload.get("video_id")
        if not job_id:
            raise MiniMaxH3Error(f"H3 submit returned no job id: {payload}")
        return str(job_id)

    def _status(self, job_id: str) -> str:
        req = request.Request(f"{self.base_url}/v1/videos/{job_id}", method="GET")
        try:
            with self._urlopen(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            raise MiniMaxH3Error(f"H3 status HTTP {exc.code}: {_error_detail(exc)}") from exc
        except URLError as exc:
            raise MiniMaxH3Error(f"H3 status network error: {exc.reason}") from exc
        status = str(payload.get("status") or "").strip().lower()
        if not status:
            raise MiniMaxH3Error(f"H3 status returned no status: {payload}")
        return status

    def _await(self, job_id: str, output: Path) -> None:
        deadline = time.monotonic() + self.timeout
        while True:
            status = self._status(job_id)
            if status in ("completed", "succeeded", "success"):
                self._download(job_id, output)
                return
            if status in ("failed", "error", "cancelled", "canceled"):
                raise MiniMaxH3Error(f"H3 generation failed: {status}")
            if time.monotonic() >= deadline:
                raise MiniMaxH3TimeoutError(f"H3 generation timed out for job {job_id}")
            self._sleep(self.poll_interval)

    def _download(self, job_id: str, output: Path) -> None:
        req = request.Request(f"{self.base_url}/v1/videos/{job_id}/content", method="GET")
        try:
            with self._urlopen(req, timeout=self.timeout) as resp:
                data = resp.read()
        except HTTPError as exc:
            raise MiniMaxH3Error(f"H3 content HTTP {exc.code}: {_error_detail(exc)}") from exc
        except URLError as exc:
            raise MiniMaxH3Error(f"H3 content network error: {exc.reason}") from exc
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(data)

    def _normalize(self, source: Path, output: Path) -> None:
        ffmpeg = _find_tool(self.repo_root, "ffmpeg")
        cmd = [
            ffmpeg, "-y", "-i", str(source),
            "-vf", f"scale={OUTPUT_W}:{OUTPUT_H},fps={OUTPUT_FPS},format=yuv420p,setsar=1",
            "-c:v", "libx264", "-preset", "fast",
            "-c:a", "aac", "-ar", "48000", "-ac", "2",
            str(output),
        ]
        proc = self._run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise MiniMaxH3Error(f"H3 clip re-encode failed: {proc.stderr.strip()[-400:]}")
        if not output.is_file():
            raise MiniMaxH3Error(f"H3 clip re-encode completed without {output}")

    def _probe_ffprobe(self, path: Path) -> tuple[float, int, int]:
        probe = _find_tool(self.repo_root, "ffprobe")
        proc = self._run(
            [
                probe, "-v", "error",
                "-show_entries", "format=duration:stream=width,height,codec_type",
                "-of", "json", str(path),
            ],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise MiniMaxH3Error(f"ffprobe could not read {path}: {proc.stderr.strip()[:200]}")
        info = json.loads(proc.stdout)
        streams = info.get("streams") or []
        video = [s for s in streams if s.get("codec_type") == "video"]
        if not video:
            raise MiniMaxH3Error(f"{path} has no video stream")
        duration = float((info.get("format") or {}).get("duration") or 0)
        width = int(video[0].get("width") or 0)
        height = int(video[0].get("height") or 0)
        return duration, width, height
