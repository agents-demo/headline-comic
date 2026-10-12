"""Tests for the deterministic Tavily Extract adapter (T010)."""

import json
import unittest

from src.providers.tavily import (
    ExtractResult,
    TavilyExtractError,
    TavilyExtractProvider,
)


class _FakeResponse:
    def __init__(self, payload: dict):
        self._bytes = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self) -> bytes:
        return self._bytes


class ParseTests(unittest.TestCase):
    def test_parse_successes_failures_and_usage(self) -> None:
        result = TavilyExtractProvider._parse(
            {
                "results": [
                    {"url": "https://a.example/1", "raw_content": "hello world"},
                    {"url": "https://a.example/2", "raw_content": "second"},
                ],
                "failed_results": [{"url": "https://b.example/3", "error": "Failed to fetch url"}],
                "usage": {"credits": 1},
                "request_id": "req-123",
            }
        )
        self.assertEqual(result.extracted["https://a.example/1"], "hello world")
        self.assertEqual(result.failed["https://b.example/3"], "Failed to fetch url")
        self.assertEqual(result.credits_used, 1.0)
        self.assertEqual(result.request_id, "req-123")

    def test_parse_tolerates_missing_usage(self) -> None:
        result = TavilyExtractProvider._parse({"results": [], "failed_results": []})
        self.assertEqual(result.credits_used, 0.0)
        self.assertEqual(result.extracted, {})
        self.assertEqual(result.failed, {})

    def test_parse_ignores_non_dict_payload(self) -> None:
        result = TavilyExtractProvider._parse(["not", "an", "object"])
        self.assertEqual(result.extracted, {})


class ExtractTests(unittest.TestCase):
    def _provider(self, payload: dict, api_key: str = "key") -> TavilyExtractProvider:
        captured: dict = {}

        def urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["method"] = req.get_method()
            captured["auth"] = req.get_header("Authorization")
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return _FakeResponse(payload)

        return TavilyExtractProvider(api_key=api_key, urlopen=urlopen), captured

    def test_empty_urls_returns_empty_without_network(self) -> None:
        provider, captured = self._provider({})
        result = provider.extract([])
        self.assertEqual(result, ExtractResult({}, {}, 0.0))
        self.assertEqual(captured, {})

    def test_rejects_over_twenty_urls(self) -> None:
        provider, _ = self._provider({})
        with self.assertRaises(ValueError):
            provider.extract([f"https://x/{i}" for i in range(21)])

    def test_requires_api_key(self) -> None:
        provider, _ = self._provider({}, api_key="")
        with self.assertRaises(ValueError):
            provider.extract(["https://a.example/1"])

    def test_post_builds_bearer_request_and_parses(self) -> None:
        provider, captured = self._provider(
            {
                "results": [{"url": "https://a.example/1", "raw_content": "text"}],
                "failed_results": [],
                "usage": {"credits": 1},
            }
        )
        result = provider.extract(["https://a.example/1"])
        self.assertEqual(result.extracted["https://a.example/1"], "text")
        self.assertEqual(result.credits_used, 1.0)
        self.assertEqual(captured["url"], "https://api.tavily.com/extract")
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["auth"], "Bearer key")
        self.assertEqual(captured["body"]["urls"], ["https://a.example/1"])
        self.assertEqual(captured["body"]["extract_depth"], "basic")
        self.assertEqual(captured["body"]["format"], "text")
        self.assertIs(captured["body"]["include_usage"], True)

    def test_http_error_raises_tavily_extract_error(self) -> None:
        from urllib.error import HTTPError

        def urlopen(req, timeout=None):
            raise HTTPError(req.full_url, 401, "unauthorized", {}, None)

        provider = TavilyExtractProvider(api_key="key", urlopen=urlopen)
        with self.assertRaises(TavilyExtractError):
            provider.extract(["https://a.example/1"])


if __name__ == "__main__":
    unittest.main()
