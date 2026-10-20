"""MiniMax-H3 (Hailuo 3.0) image-to-video adapter with native audio (T043).

MiniMax-H3 is the presenter's self-hosted 33B omni-modal video model, served over
**vLLM-Omni** (not SGLang). Confirmed against the vLLM-Omni recipe
(``recipes/MiniMaxAI/MiniMax-H3``), the server launcher ``minimax_h3/run_minimax_h3.sh``,
and the benchmark ``minimax_h3/benchmark_minimax_h3.py`` (checked 2026-10-20):

- ``POST {base}/v1/videos/sync`` with a **multipart/form-data** body returns the
  finished MP4 directly (HTTP 200). There is also an async ``POST /v1/videos``, but
  the recipe does not document its job-id/polling schema, so the synchronous endpoint
  is the confirmed path (and what the benchmark drives).
- Form fields: ``prompt``, ``fps`` (fixed 24), ``num_inference_steps``,
  ``flow_shift``, ``seed``, ``extra_params`` (a JSON string), and ``width`` /
  ``height`` (multiples of 32) with an optional ``aspect_ratio``.
- ``extra_params`` JSON: ``{"task": "fl2va", "duration": <s>, "audio_flow_shift": 3.0}``.
  ``task`` is ``fl2va`` (text / first-last-frame -> video) or ``ref2va``; we use
  ``fl2va`` with a single first-frame keyframe.
- The keyframe is **uploaded as the ``input_reference`` file's bytes** — not a
  ``file://`` URI and not base64 — so no server-side mount is required. (The
  ``input_references`` plural field is only for the two-image first/last form with
  ``frame_indices``, which we do not use.)
- Output is H.264 at 24 fps with native stereo AAC audio (32 kHz). ``duration`` is
  4-15 s, quantised to H3's ``17n+5`` frame schedule. The adapter re-encodes to the
  assembler's 1280x720 / 24 fps / AAC 48 kHz before returning, so the recovery
  resolution check and the ffmpeg assembly stay unchanged.

The adapter returns a ``ShotRenderResult`` per shot through the recovery seam
(``renderer(storyboard, keyframes_dir) -> Callable[[shot], ShotRenderResult]``), so
the retry-once + animated-still swap in ``video_recovery`` drives it unchanged. H3 is
self-hosted, so each call costs $0: no T007 approval record is required. This module
follows the same conventions as ``fishaudio.py`` — ``urllib.request`` with an
injectable ``urlopen``, ``load_env``, and ffprobe/ffmpeg via the vendored tools.

Two gates are kept for the MiniMax-H3 video path:

1. ``MiniMaxH3VideoProvider`` — self-hosted vLLM-Omni on the presenter's GPU server
   (no API key; just ``MINIMAX_H3_BASE_URL``). This is the implemented gate.
2. ``MiniMaxH3CloudProvider`` — reserved for a future MiniMax-hosted cloud API
   (API key + URL). Its contract is unconfirmed and it would be a paid call, so it
   raises until T007's guards exist and the cost is approved. It only reserves the
   gate so the path is not lost.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib import request
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit, urlunsplit

from src.env import load_env

from .contracts import ShotRenderResult

DEFAULT_BASE_URL = "http://127.0.0.1:8000"  # vLLM-Omni default port
DEFAULT_VARIANT = "fl2va"
VARIANTS = ("fl2va", "ref2va")
DEFAULT_WIDTH = 1024  # 16:9, multiple of 32; A6000-safe (see api-notes)
DEFAULT_HEIGHT = 576
DEFAULT_ASPECT_RATIO = "16:9"
DEFAULT_FPS = 24.0
DEFAULT_NUM_INFERENCE_STEPS = 50
DEFAULT_FLOW_SHIFT = 12.0
DEFAULT_AUDIO_FLOW_SHIFT = 3.0
MIN_SECONDS = 4.0
MAX_SECONDS = 15.0
GENERATION_TIMEOUT_S = 3600.0  # /v1/videos/sync blocks for the whole render

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


def extra_params(*, task: str, duration: float, audio_flow_shift: float) -> str:
    """The ``extra_params`` JSON string vLLM-Omni expects for a MiniMax-H3 request."""
    return json.dumps(
        {"task": task, "duration": duration, "audio_flow_shift": audio_flow_shift},
        separators=(",", ":"),
    )


def build_request_fields(
    *,
    prompt: str,
    seconds: float,
    keyframe_bytes: bytes,
    task: str = DEFAULT_VARIANT,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    aspect_ratio: str = DEFAULT_ASPECT_RATIO,
    fps: float = DEFAULT_FPS,
    num_inference_steps: int = DEFAULT_NUM_INFERENCE_STEPS,
    flow_shift: float = DEFAULT_FLOW_SHIFT,
    audio_flow_shift: float = DEFAULT_AUDIO_FLOW_SHIFT,
    seed: int,
) -> tuple[dict[str, str], dict[str, tuple[str, bytes, str]]]:
    """The confirmed vLLM-Omni multipart fields + files for a first-frame fl2va shot."""
    fields: dict[str, str] = {
        "prompt": prompt,
        "fps": str(fps),
        "num_inference_steps": str(num_inference_steps),
        "flow_shift": str(flow_shift),
        "seed": str(seed),
        "extra_params": extra_params(task=task, duration=seconds, audio_flow_shift=audio_flow_shift),
        "width": str(width),
        "height": str(height),
        "aspect_ratio": aspect_ratio,
    }
    # Single first-frame conditioning uses the singular ``input_reference`` (the plural
    # ``input_references`` + ``frame_indices`` form is only for first/last two-image).
    files: dict[str, tuple[str, bytes, str]] = {
        "input_reference": ("keyframe.png", keyframe_bytes, "image/png"),
    }
    return fields, files


def encode_multipart(
    fields: Mapping[str, str],
    files: Mapping[str, tuple[str, bytes, str]],
) -> tuple[bytes, str]:
    """Encode a multipart/form-data body (RFC 7578) and return (body, Content-Type)."""
    boundary = "----headline-comic-minimax-h3-" + uuid.uuid4().hex
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(f"--{boundary}\r\n".encode("utf-8"))
        parts.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        parts.append(f"{value}\r\n".encode("utf-8"))
    for name, (filename, data, ctype) in files.items():
        parts.append(f"--{boundary}\r\n".encode("utf-8"))
        parts.append(
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode("utf-8")
        )
        parts.append(f"Content-Type: {ctype}\r\n\r\n".encode("utf-8"))
        parts.append(data)
        parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _split_auth(base_url: str) -> tuple[str, str | None, str | None]:
    """Split ``user:pass@`` userinfo out of ``base_url`` into a Basic-auth pair.

    Returns ``(clean_url, username, password)``. When the URL carries no userinfo,
    ``username`` (and ``password``) is ``None``, so the caller can tell "no auth
    configured" apart from "auth with an empty password".
    """
    parts = urlsplit(base_url)
    if parts.username is None:
        return base_url.rstrip("/"), None, None
    username = unquote(parts.username)
    password = unquote(parts.password) if parts.password is not None else ""
    netloc = parts.netloc.rsplit("@", 1)[1]
    clean = urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    return clean.rstrip("/"), username, password


def _basic_auth(username: str, password: str) -> str:
    """The ``Authorization: Basic ...`` header value for ``username:password``."""
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


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
    """Render one shot at a time through MiniMax-H3 over vLLM-Omni, returning its clip.

    Env config (all optional, with local-device defaults): ``MINIMAX_H3_BASE_URL``
    (may carry ``user:pass@`` userinfo for HTTP Basic auth, or set
    ``MINIMAX_H3_USERNAME``/``MINIMAX_H3_PASSWORD`` instead), ``MINIMAX_H3_VARIANT``,
    ``MINIMAX_H3_WIDTH``, ``MINIMAX_H3_HEIGHT``, ``MINIMAX_H3_ASPECT_RATIO``,
    ``MINIMAX_H3_NUM_INFERENCE_STEPS``.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        variant: str | None = None,
        width: int | None = None,
        height: int | None = None,
        aspect_ratio: str | None = None,
        fps: float | None = None,
        num_inference_steps: int | None = None,
        flow_shift: float | None = None,
        audio_flow_shift: float | None = None,
        seed: int | None = None,
        timeout: float = GENERATION_TIMEOUT_S,
        urlopen: Callable[..., Any] | None = None,
        probe: Callable[[Path], tuple[float, int, int]] | None = None,
        run: Callable = subprocess.run,
    ) -> None:
        load_env(_PROJECT_ROOT / ".env")
        raw_base_url = base_url or os.environ.get("MINIMAX_H3_BASE_URL") or DEFAULT_BASE_URL
        self.base_url, url_user, url_pass = _split_auth(raw_base_url)
        env_user = os.environ.get("MINIMAX_H3_USERNAME")
        env_pass = os.environ.get("MINIMAX_H3_PASSWORD")
        self._username = env_user if env_user is not None else url_user
        self._password = env_pass if env_pass is not None else (url_pass or "")
        self.variant = (variant or os.environ.get("MINIMAX_H3_VARIANT") or DEFAULT_VARIANT).strip()
        if self.variant not in VARIANTS:
            raise ValueError(f"variant must be one of {VARIANTS}")
        self.width = int(width or os.environ.get("MINIMAX_H3_WIDTH") or DEFAULT_WIDTH)
        self.height = int(height or os.environ.get("MINIMAX_H3_HEIGHT") or DEFAULT_HEIGHT)
        self.aspect_ratio = (
            aspect_ratio or os.environ.get("MINIMAX_H3_ASPECT_RATIO") or DEFAULT_ASPECT_RATIO
        ).strip()
        self.fps = float(fps or os.environ.get("MINIMAX_H3_FPS") or DEFAULT_FPS)
        self.num_inference_steps = int(
            num_inference_steps or os.environ.get("MINIMAX_H3_NUM_INFERENCE_STEPS") or DEFAULT_NUM_INFERENCE_STEPS
        )
        self.flow_shift = float(flow_shift or os.environ.get("MINIMAX_H3_FLOW_SHIFT") or DEFAULT_FLOW_SHIFT)
        self.audio_flow_shift = float(
            audio_flow_shift or os.environ.get("MINIMAX_H3_AUDIO_FLOW_SHIFT") or DEFAULT_AUDIO_FLOW_SHIFT
        )
        self.seed = seed
        self.timeout = timeout
        self.repo_root = _PROJECT_ROOT
        self._urlopen = urlopen or request.urlopen
        self._probe = probe or self._probe_ffprobe
        self._run = run

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
        shots_dir = keyframes_dir.parent / "shots"
        shots_dir.mkdir(parents=True, exist_ok=True)

        def render(shot: Mapping[str, Any]) -> ShotRenderResult:
            return self._render_shot(shot, keyframes_dir=keyframes_dir, shots_dir=shots_dir)

        return render

    def _render_shot(
        self,
        shot: Mapping[str, Any],
        *,
        keyframes_dir: Path,
        shots_dir: Path,
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
        fields, files = build_request_fields(
            prompt=compile_prompt(shot),
            seconds=seconds,
            keyframe_bytes=keyframe.read_bytes(),
            task=self.variant,
            width=self.width,
            height=self.height,
            aspect_ratio=self.aspect_ratio,
            fps=self.fps,
            num_inference_steps=self.num_inference_steps,
            flow_shift=self.flow_shift,
            audio_flow_shift=self.audio_flow_shift,
            seed=self.seed if self.seed is not None else _stable_seed(shot_id),
        )
        body, content_type = encode_multipart(fields, files)
        raw = shots_dir / f"{shot_id}-raw.mp4"
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_bytes(self._submit_sync(body, content_type))
        final = shots_dir / f"{shot_id}.mp4"
        self._normalize(raw, final)
        duration_s, width, height = self._probe(final)
        return ShotRenderResult(path=final, duration_s=duration_s, width=width, height=height)

    def _submit_sync(self, body: bytes, content_type: str) -> bytes:
        headers = {"Content-Type": content_type}
        if self._username is not None:
            headers["Authorization"] = _basic_auth(self._username, self._password or "")
        req = request.Request(
            f"{self.base_url}/v1/videos/sync",
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with self._urlopen(req, timeout=self.timeout) as resp:
                data = resp.read()
        except HTTPError as exc:
            raise MiniMaxH3Error(f"H3 sync HTTP {exc.code}: {_error_detail(exc)}") from exc
        except TimeoutError as exc:
            raise MiniMaxH3TimeoutError(f"H3 sync timed out after {self.timeout}s") from exc
        except URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise MiniMaxH3TimeoutError(f"H3 sync timed out after {self.timeout}s") from exc
            raise MiniMaxH3Error(f"H3 sync network error: {exc.reason}") from exc
        if not data:
            raise MiniMaxH3Error("H3 sync returned empty content")
        return data

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


class MiniMaxH3CloudProvider:
    """Reserved gate for the future MiniMax-hosted cloud API (API key + URL).

    NOT IMPLEMENTED: the hosted endpoint contract is unconfirmed and, per the project
    rules, no paid video call may be made until T007's guards exist and the expected
    cost is approved. This class only reserves the gate and documents the intended env
    vars (``MINIMAX_H3_API_URL``, ``MINIMAX_H3_API_KEY``) so the path is not lost.
    """

    def __init__(self, *, api_url: str | None = None, api_key: str | None = None) -> None:
        load_env(_PROJECT_ROOT / ".env")
        self.api_url = (api_url or os.environ.get("MINIMAX_H3_API_URL") or "").strip()
        self.api_key = (api_key or os.environ.get("MINIMAX_H3_API_KEY") or "").strip()

    def renderer(self, storyboard: Mapping[str, Any], keyframes_dir: Path | str) -> Callable:
        raise MiniMaxH3Error(
            "MiniMax-H3 cloud API is not implemented yet: the hosted endpoint contract "
            "is unconfirmed and a paid video call requires T007 approval. Use the "
            "self-hosted --video minimax-h3 gate instead."
        )
