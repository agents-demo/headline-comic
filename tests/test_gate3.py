"""Deterministic tests for the gate3 driver's narration wiring (T044)."""

import unittest
from unittest import mock

from scripts.gate3 import render_narration


class RenderNarrationTests(unittest.TestCase):
    def test_missing_key_degrades_to_subtitles_only(self) -> None:
        provider = mock.Mock()
        provider.api_key = ""
        tts = mock.Mock()
        clips = render_narration({"shots": []}, "t044", provider=provider, tts_runner=tts)
        self.assertEqual(clips, [])
        tts.assert_not_called()

    def test_with_key_calls_tts_with_zero_price(self) -> None:
        provider = mock.Mock()
        provider.api_key = "k"
        tts = mock.Mock(return_value=["clip-a"])
        clips = render_narration(
            {"shots": [{"shot_id": "s1", "narration": "Hi."}]},
            "t044",
            provider=provider,
            tts_runner=tts,
        )
        self.assertEqual(clips, ["clip-a"])
        tts.assert_called_once()
        kwargs = tts.call_args.kwargs
        self.assertIs(kwargs["provider"], provider)
        self.assertEqual(kwargs["run_id"], "t044")
        self.assertEqual(kwargs["unit_prices"]["tts"].provider, "fishaudio")
        self.assertEqual(kwargs["unit_prices"]["tts"].unit, "1000_characters")
        self.assertEqual(kwargs["unit_prices"]["tts"].usd_per_unit, 0)


if __name__ == "__main__":
    unittest.main()
