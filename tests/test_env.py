"""Tests for the encoding-tolerant .env loader."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.env import load_env


class LoadEnvTests(unittest.TestCase):
    def _load(self, text: str, encoding: str) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_bytes(text.encode(encoding))
            with mock.patch.dict(os.environ, {}, clear=True):
                load_env(path)
                return dict(os.environ)

    def test_utf8_key_value(self) -> None:
        env = self._load("LLM_API_KEY=abc123\nLLM_MODEL=deepseek-chat\n", "utf-8")
        self.assertEqual(env["LLM_API_KEY"], "abc123")
        self.assertEqual(env["LLM_MODEL"], "deepseek-chat")

    def test_utf16_le_with_bom(self) -> None:
        env = self._load("LLM_API_KEY=abc123\n", "utf-16")
        self.assertEqual(env["LLM_API_KEY"], "abc123")

    def test_comments_and_blanks_skipped(self) -> None:
        env = self._load("# a comment\n\nLLM_MODEL=deepseek-chat\n", "utf-8")
        self.assertEqual(set(env), {"LLM_MODEL"})

    def test_quotes_are_stripped(self) -> None:
        env = self._load('LLM_BASE_URL="https://api.deepseek.com"\n', "utf-8")
        self.assertEqual(env["LLM_BASE_URL"], "https://api.deepseek.com")

    def test_existing_environment_wins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("LLM_API_KEY=from_file\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {"LLM_API_KEY": "from_shell"}):
                load_env(path)
                self.assertEqual(os.environ["LLM_API_KEY"], "from_shell")


if __name__ == "__main__":
    unittest.main()
