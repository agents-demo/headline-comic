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
from .fishaudio import FishAudioError, FishAudioProvider
from .llm import ChatError, ChatResult, DeepSeekChatProvider
from .tavily import ExtractResult, TavilyExtractError, TavilyExtractProvider

__all__ = [
    "AniDoodleVideoProvider",
    "ChatError",
    "ChatResult",
    "DeepSeekChatProvider",
    "ExtractResult",
    "FishAudioError",
    "FishAudioProvider",
    "ImageProvider",
    "ImageRequest",
    "ImageResult",
    "TTSProvider",
    "TTSRequest",
    "TTSResult",
    "TavilyExtractError",
    "TavilyExtractProvider",
    "VideoProvider",
    "VideoRequest",
    "VideoResult",
]