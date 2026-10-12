"""Tests for the DeepSeek chat adapter (T011)."""

import json
import unittest
from io import BytesIO
from unittest import mock
from urllib.error import HTTPError

from src.permissions.media_guard import PolicyDenied
from src.providers.llm import ChatError, ChatResult, DeepSeekChatProvider


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self) -> bytes:
        return self._payload


def _ok_payload(content: str = "{\"facts\": []}") -> dict:
    return {
        "choices": [{"message": {"content": content}}],
        "model": "deepseek-chat",
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }


class DeepSeekChatProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch("src.providers.llm.load_env")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_complete_builds_request_and_parses_reply(self) -> None:
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["req"] = req
            return _FakeResponse(_ok_payload())

        provider = DeepSeekChatProvider(
            api_key="sk-test", base_url="https://api.deepseek.com", model="deepseek-chat", urlopen=fake_urlopen
        )
        result = provider.complete(
            [("system", "be brief"), ("user", "hi")], json_mode=True, temperature=0.2
        )

        req = captured["req"]
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(req.full_url, "https://api.deepseek.com/chat/completions")
        self.assertEqual(req.get_header("Authorization"), "Bearer sk-test")
        body = json.loads(req.data)
        self.assertEqual(body["model"], "deepseek-chat")
        self.assertEqual(body["messages"], [{"role": "system", "content": "be brief"}, {"role": "user", "content": "hi"}])
        self.assertEqual(body["temperature"], 0.2)
        self.assertEqual(body["response_format"], {"type": "json_object"})

        self.assertEqual(result.content, "{\"facts\": []}")
        self.assertEqual(result.model, "deepseek-chat")
        self.assertEqual(result.prompt_tokens, 10)
        self.assertEqual(result.completion_tokens, 5)

    def test_trailing_slash_in_base_url_is_normalised(self) -> None:
        provider = DeepSeekChatProvider(api_key="k", base_url="https://api.deepseek.com/", model="m")
        self.assertEqual(provider.endpoint, "https://api.deepseek.com/chat/completions")

    def test_default_model(self) -> None:
        provider = DeepSeekChatProvider(api_key="k", base_url="https://api.deepseek.com")
        self.assertEqual(provider.model, "deepseek-chat")

    def test_complete_requires_api_key(self) -> None:
        provider = DeepSeekChatProvider(api_key="k", base_url="https://api.deepseek.com", model="m")
        provider.api_key = ""
        with self.assertRaises(ValueError):
            provider.complete([("user", "hi")])

    def test_non_https_base_url_is_rejected(self) -> None:
        provider = DeepSeekChatProvider(api_key="k", base_url="http://api.deepseek.com", model="m")
        with self.assertRaises(PolicyDenied):
            provider.complete([("user", "hi")])

    def test_http_error_becomes_chat_error(self) -> None:
        def fake_urlopen(req, timeout=None):
            body = b'{"error": {"message": "invalid api key"}}'
            raise HTTPError("https://api.deepseek.com/chat/completions", 401, "Unauthorized", {}, BytesIO(body))

        provider = DeepSeekChatProvider(
            api_key="bad", base_url="https://api.deepseek.com", model="m", urlopen=fake_urlopen
        )
        with self.assertRaises(ChatError) as ctx:
            provider.complete([("user", "hi")])
        self.assertIn("invalid api key", str(ctx.exception))


class ChatResultTests(unittest.TestCase):
    def test_parse_missing_choices_yields_empty_content(self) -> None:
        result = DeepSeekChatProvider._parse({})
        self.assertEqual(result.content, "")
        self.assertEqual(result.prompt_tokens, 0)


if __name__ == "__main__":
    unittest.main()
