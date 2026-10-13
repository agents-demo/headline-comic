"""One-line Fish Audio smoke test (T028).

Synthesizes a single short clip through FishAudioProvider and prints its duration,
so the real API call can be verified end-to-end from a network that can reach
api.fish.audio:

    .venv/Scripts/python.exe scripts/tts_smoke.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.providers.contracts import TTSRequest
from src.providers.fishaudio import FishAudioProvider

out = Path(tempfile.mkdtemp()) / "smoke.mp3"
result = FishAudioProvider().synthesize(TTSRequest(text="Hello town.", output_path=out))
print("OK", out, "duration_s =", result.duration_s)
