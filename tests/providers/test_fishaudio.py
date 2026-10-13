"""Tests for the Fish Audio adapter (T028) with no live network calls."""

import json
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError, URLError

from src.permissions.media_guard import PolicyDenied
from src.providers.contracts import TTSRequest
from src.providers.fishaudio import (
    DEFAULT_TTS_URL,
    FishAudioError,
    FishAudioProvider,
    MAX_TEXT_CHARS,
)


class _BytesResponse:
    def __init__(self, payload: bytes) -> None:
        self._bytes = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self) -> bytes:
        return self._bytes


class FishAudioProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch("src.providers.fishaudio.load_env")
        patcher.start()
        self.addCleanup(patcher.stop)

    def _provider(self, urlopen, api_key: str = "key", **kwargs) -> FishAudioProvider:
        return FishAudioProvider(
            api_key=api_key,
            urlopen=urlopen,
            probe_duration=lambda path: 2.5,
            **kwargs,
        )

    def test_synthesize_posts_then_writes_audio_bytes_directly(self) -> None:
        captured = []

        def urlopen(req, timeout=None):
            captured.append(req)
            return _BytesResponse(b"mp3-bytes")

        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "narration" / "shot-01.mp3"
            result = self._provider(urlopen).synthesize(TTSRequest(text="Hello world", output_path=out))
            self.assertTrue(out.is_file())
            self.assertEqual(out.read_bytes(), b"mp3-bytes")
            self.assertEqual(result.duration_s, 2.5)
            self.assertEqual(result.audio_path, out)

        self.assertEqual(len(captured), 1)  # a single POST; the audio is the response body
        req = captured[0]
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(req.full_url, DEFAULT_TTS_URL)
        headers = {k.lower(): v for k, v in req.headers.items()}
        self.assertEqual(headers["authorization"], "Bearer key")
        self.assertEqual(headers["model"], "s2.1-pro-free")
        body = json.loads(req.data)
        self.assertEqual(body, {"text": "Hello world", "format": "mp3"})

    def test_reference_id_is_sent_from_request_voice(self) -> None:
        captured = []

        def urlopen(req, timeout=None):
            captured.append(req)
            return _BytesResponse(b"x")

        self._provider(urlopen).synthesize(
            TTSRequest(text="hi", output_path=Path("out.mp3"), voice="ref-123")
        )
        body = json.loads(captured[0].data)
        self.assertEqual(body["reference_id"], "ref-123")

    def test_reference_id_is_omitted_for_default_voice(self) -> None:
        captured = []

        def urlopen(req, timeout=None):
            captured.append(req)
            return _BytesResponse(b"x")

        self._provider(urlopen).synthesize(TTSRequest(text="hi", output_path=Path("out.mp3")))
        body = json.loads(captured[0].data)
        self.assertNotIn("reference_id", body)

    def test_reference_id_falls_back_to_env_default(self) -> None:
        captured = []

        def urlopen(req, timeout=None):
            captured.append(req)
            return _BytesResponse(b"x")

        self._provider(urlopen, reference_id="env-ref").synthesize(
            TTSRequest(text="hi", output_path=Path("out.mp3"))
        )
        body = json.loads(captured[0].data)
        self.assertEqual(body["reference_id"], "env-ref")

    def test_empty_text_is_rejected(self) -> None:
        provider = self._provider(lambda req, timeout=None: _BytesResponse(b"x"))
        with self.assertRaises(ValueError):
            provider.synthesize(TTSRequest(text="   ", output_path=Path("out.mp3")))

    def test_over_limit_text_is_rejected(self) -> None:
        provider = self._provider(lambda req, timeout=None: _BytesResponse(b"x"))
        with self.assertRaises(ValueError):
            provider.synthesize(TTSRequest(text="a" * (MAX_TEXT_CHARS + 1), output_path=Path("out.mp3")))

    def test_missing_api_key_is_rejected(self) -> None:
        provider = self._provider(lambda req, timeout=None: _BytesResponse(b"x"), api_key="")
        with self.assertRaises(ValueError):
            provider.synthesize(TTSRequest(text="hi", output_path=Path("out.mp3")))

    def test_unconfirmed_format_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            FishAudioProvider(api_key="k", output_format="wav")  # quickstart confirms mp3 only

    def test_non_allowlisted_host_is_rejected(self) -> None:
        provider = self._provider(
            lambda req, timeout=None: _BytesResponse(b"x"),
            base_url="https://evil.example/v1/tts",
        )
        with self.assertRaises(PolicyDenied):
            provider.synthesize(TTSRequest(text="hi", output_path=Path("out.mp3")))

    def test_http_error_becomes_fish_audio_error_with_detail(self) -> None:
        def urlopen(req, timeout=None):
            raise HTTPError(req.full_url, 429, "Too many requests", {}, BytesIO(b'{"detail": "rate limited"}'))

        provider = self._provider(urlopen)
        with self.assertRaises(FishAudioError) as ctx:
            provider.synthesize(TTSRequest(text="hi", output_path=Path("out.mp3")))
        self.assertIn("429", str(ctx.exception))
        self.assertIn("rate limited", str(ctx.exception))

    def test_network_error_becomes_fish_audio_error(self) -> None:
        def urlopen(req, timeout=None):
            raise URLError("connection reset")

        provider = self._provider(urlopen)
        with self.assertRaises(FishAudioError):
            provider.synthesize(TTSRequest(text="hi", output_path=Path("out.mp3")))


if __name__ == "__main__":
    unittest.main()
