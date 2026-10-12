"""Tests for the provider-neutral request/result contracts."""

from dataclasses import FrozenInstanceError
from pathlib import Path
import unittest

from src.providers.contracts import (
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


class ContractTests(unittest.TestCase):
    def test_request_and_result_values_are_immutable(self) -> None:
        image = ImageRequest("town square", Path("runs/r1/keyframe.png"))
        image_result = ImageResult(image.output_path, 1280, 720)
        video = VideoRequest("r1")
        video_result = VideoResult(Path("runs/r1/video.mp4"), Path("runs/r1/manifest.json"), 8, False)
        speech = TTSRequest("Hello", Path("runs/r1/audio/shot.wav"))
        speech_result = TTSResult(speech.output_path, 1.5)

        self.assertEqual(image.reference_images, ())
        self.assertEqual((image_result.width, image_result.height), (1280, 720))
        self.assertEqual(video.max_duration_s, 59.0)
        self.assertFalse(video_result.has_audio)
        self.assertIsNone(speech.voice)
        self.assertEqual(speech_result.duration_s, 1.5)
        with self.assertRaises(FrozenInstanceError):
            video.run_id = "changed"  # type: ignore[misc]

    def test_provider_protocols_accept_structural_implementations(self) -> None:
        class Images:
            def generate(self, request: ImageRequest) -> ImageResult:
                return ImageResult(request.output_path, 1, 1)

        class Video:
            def render(self, request: VideoRequest) -> VideoResult:
                return VideoResult(Path("video.mp4"), Path("manifest.json"), 1, False)

        class Speech:
            def synthesize(self, request: TTSRequest) -> TTSResult:
                return TTSResult(request.output_path, 1)

        self.assertIsInstance(Images(), ImageProvider)
        self.assertIsInstance(Video(), VideoProvider)
        self.assertIsInstance(Speech(), TTSProvider)


if __name__ == "__main__":
    unittest.main()