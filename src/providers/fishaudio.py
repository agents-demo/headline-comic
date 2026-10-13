"""Fish Audio text-to-speech adapter for narration (T028).

Confirmed against Fish Audio's quickstart docs (checked 2026-10-13):

- ``POST https://api.fish.audio/v1/tts`` with header ``Authorization: Bearer <key>``.
- The model is selected by an HTTP header ``model`` (default ``s2.1-pro-free``), not a
  body field.
- Body: ``text`` (required), ``format`` (default ``mp3``), and an optional
  ``reference_id`` voice; omit it for the default voice.
- Response ``200`` is the audio bytes directly — no URL, no base64.
- Errors: 401 invalid/missing key, 402 out of credits, 400 bad ``reference_id`` or
  parameters, 429 rate limit. Free-tier numeric limits are not documented.

``FISH_BASE_URL`` holds the full POST endpoint. The key is only ever sent to
``api.fish.audio`` (FR-014). Audio duration is read with ffprobe (vendored under
``runs/_tools`` when present).
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Callable
from urllib import request
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

from src.env import load_env
from src.permissions.media_guard import require_allowed_host

from .contracts import TTSRequest, TTSResult

DEFAULT_TTS_URL = "https://api.fish.audio/v1/tts"
FISH_HOST = "api.fish.audio"  # the only host the key may be sent to (FR-014)
DEFAULT_MODEL = "s2.1-pro-free"
DEFAULT_FORMAT = "mp3"
FORMATS = ("mp3",)  # the quickstart only confirms mp3
MAX_TEXT_CHARS = 1000  # defensive per-request cap; the free tier's real cap is undocumented
_TIMEOUT_S = 60.0

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class FishAudioError(RuntimeError):
    """Raised when a Fish Audio request itself fails (transport, auth, limits)."""


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


def _find_ffprobe(repo_root: Path) -> str:
    """Prefer the vendored ffprobe under ``runs/_tools``; otherwise rely on PATH."""
    name = "ffprobe.exe" if os.name == "nt" else "ffprobe"
    tools_root = repo_root / "runs" / "_tools" / "ffmpeg"
    if tools_root.is_dir():
        for bin_dir in sorted(tools_root.glob("*/bin")):
            candidate = bin_dir / name
            if candidate.is_file():
                return str(candidate)
    return name


class FishAudioProvider:
    """Synthesize one narration clip via Fish Audio and return it with its duration."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        model: str | None = None,
        output_format: str | None = None,
        reference_id: str | None = None,
        timeout: float = _TIMEOUT_S,
        urlopen: Callable[..., object] | None = None,
        probe_duration: Callable[[Path], float] | None = None,
    ) -> None:
        load_env(_PROJECT_ROOT / ".env")
        self.api_key = (api_key or os.environ.get("FISH_API_KEY") or "").strip()
        self.tts_url = (base_url or os.environ.get("FISH_BASE_URL") or DEFAULT_TTS_URL).rstrip("/")
        self.model = (model or os.environ.get("FISH_MODEL") or DEFAULT_MODEL).strip()
        self.output_format = (output_format or os.environ.get("FISH_FORMAT") or DEFAULT_FORMAT).strip()
        if self.output_format not in FORMATS:
            raise ValueError(f"format must be one of {FORMATS}")
        self.reference_id = (reference_id or os.environ.get("FISH_REFERENCE_ID") or "").strip() or None
        self.timeout = timeout
        self.repo_root = _PROJECT_ROOT
        self._urlopen = urlopen or request.urlopen
        self._probe_duration = probe_duration or self._ffprobe_duration

    def synthesize(self, request: TTSRequest) -> TTSResult:
        text = request.text.strip()
        if not text:
            raise ValueError("TTS text must not be empty")
        if len(text) > MAX_TEXT_CHARS:
            raise ValueError(
                f"TTS text is {len(text)} characters; the per-request cap is {MAX_TEXT_CHARS}"
            )
        if not self.api_key:
            raise ValueError("FISH_API_KEY is not set")

        if not urlsplit(self.tts_url).hostname:
            raise FishAudioError("FISH_BASE_URL must include a hostname")
        # The key may only go to the Fish Audio host, never a host from a tampered .env.
        require_allowed_host(self.tts_url, {FISH_HOST})
        audio = self._synthesize(text, request.voice)

        output_path = Path(request.output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(audio)
        return TTSResult(audio_path=output_path, duration_s=self._probe_duration(output_path))

    def _synthesize(self, text: str, voice: str | None) -> bytes:
        body: dict[str, str] = {"text": text, "format": self.output_format}
        reference_id = (voice or self.reference_id or "").strip()
        if reference_id:
            body["reference_id"] = reference_id
        req = request.Request(
            self.tts_url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "model": self.model,
            },
            method="POST",
        )
        try:
            with self._urlopen(req, timeout=self.timeout) as resp:
                return resp.read()
        except HTTPError as exc:
            raise FishAudioError(f"Fish Audio HTTP {exc.code}: {_error_detail(exc)}") from exc
        except URLError as exc:
            raise FishAudioError(f"Fish Audio network error: {exc.reason}") from exc

    def _ffprobe_duration(self, path: Path) -> float:
        probe = _find_ffprobe(self.repo_root)
        result = subprocess.run(
            [
                probe,
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
            check=True,
        )
        try:
            return float(result.stdout.strip())
        except ValueError as exc:
            raise FishAudioError(f"Could not read a duration from {path}") from exc
