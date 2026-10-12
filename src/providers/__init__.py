"""Provider contracts and initial local implementation."""

from .contracts import (
    ImageProvider,
    ImageRequest,
    ImageResult,
    TTSProvider,
    TTSRequest,
    TTSResult,
    VideoProvider,
    VideoRequest,
    VideoResult,
)
from .anidoodle import AniDoodleVideoProvider

__all__ = [
    "AniDoodleVideoProvider",
    "ImageProvider",
    "ImageRequest",
    "ImageResult",
    "TTSProvider",
    "TTSRequest",
    "TTSResult",
    "VideoProvider",
    "VideoRequest",
    "VideoResult",
]