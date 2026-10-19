"""Provider-neutral media contracts shared by workflow stages and adapters."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class ImageRequest:
    prompt: str
    output_path: Path
    reference_images: tuple[Path, ...] = ()


@dataclass(frozen=True)
class ImageResult:
    image_path: Path
    width: int
    height: int


@runtime_checkable
class ImageProvider(Protocol):
    """Generate a still image; concrete providers arrive with T023."""

    def generate(self, request: ImageRequest) -> ImageResult: ...


@dataclass(frozen=True)
class VideoRequest:
    run_id: str
    max_duration_s: float = 59.0


@dataclass(frozen=True)
class VideoResult:
    video_path: Path
    manifest_path: Path
    duration_s: float
    has_audio: bool


@dataclass(frozen=True)
class ShotRenderResult:
    """A per-shot video provider's output: the clip and the checks recovery runs on it."""

    path: Path
    duration_s: float
    width: int
    height: int


@runtime_checkable
class VideoProvider(Protocol):
    """Render a run's video through a local or remote implementation."""

    def render(self, request: VideoRequest) -> VideoResult: ...


@dataclass(frozen=True)
class TTSRequest:
    text: str
    output_path: Path
    voice: str | None = None


@dataclass(frozen=True)
class TTSResult:
    audio_path: Path
    duration_s: float


@runtime_checkable
class TTSProvider(Protocol):
    """Synthesize narration; concrete providers remain deferred."""

    def synthesize(self, request: TTSRequest) -> TTSResult: ...