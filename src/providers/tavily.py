"""Tavily Extract adapter for FR-002 article text (T010).

Confirmed against Tavily's Extract docs on 2026-10-12:

- ``POST https://api.tavily.com/extract`` with bearer auth; a batch of up to 20 URLs.
- Response: ``results[]`` ``{url, raw_content}``, ``failed_results[]`` ``{url, error}``,
  ``response_time`` (seconds), ``usage`` ``{credits}`` (only with ``include_usage=true``),
  and ``request_id``.
- Basic depth bills 1 credit per 5 successful extractions; failed URLs are free.

The article URL is sent as request data, never fetched by us (FR-014). Only the
Tavily API host is allowlisted; the adapter enforces that exact HTTPS host.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Callable
from urllib import request
from urllib.error import HTTPError, URLError

from src.permissions.media_guard import require_allowed_host

TAVILY_EXTRACT_URL = "https://api.tavily.com/extract"
TAVILY_EXTRACT_HOST = "api.tavily.com"
_EXTRACT_TIMEOUT_S = 30.0
_MAX_URLS_PER_CALL = 20


class TavilyExtractError(RuntimeError):
    """Raised when the Extract request itself fails (transport, auth, limits)."""


@dataclass(frozen=True)
class ExtractResult:
    """Outcome of one batch Extract call, keyed by URL."""

    extracted: dict[str, str]  # url -> raw_content for successes
    failed: dict[str, str]  # url -> error message for failures
    credits_used: float
    request_id: str | None = None


def _as_float(value: object, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _error_detail(exc: HTTPError) -> str:
    try:
        payload = json.loads(exc.read().decode("utf-8"))
        detail = payload.get("detail") or {}
        if isinstance(detail, dict):
            message = detail.get("error") or detail.get("message")
            if message:
                return str(message)
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    return exc.reason or ""


class TavilyExtractProvider:
    """Submit a URL batch to Tavily Extract and return per-URL outcomes."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        timeout: float = _EXTRACT_TIMEOUT_S,
        urlopen: Callable[..., object] | None = None,
    ) -> None:
        self.api_key = (api_key or os.environ.get("TAVILY_API_KEY") or "").strip()
        self.timeout = timeout
        self._urlopen = urlopen or request.urlopen

    def extract(
        self,
        urls: list[str],
        *,
        extract_depth: str = "basic",
        include_usage: bool = True,
    ) -> ExtractResult:
        urls = [url for url in urls if url]
        if not urls:
            return ExtractResult({}, {}, 0.0)
        if len(urls) > _MAX_URLS_PER_CALL:
            raise ValueError(f"At most {_MAX_URLS_PER_CALL} URLs per Extract call")
        if not self.api_key:
            raise ValueError("TAVILY_API_KEY is not set")
        require_allowed_host(TAVILY_EXTRACT_URL, {TAVILY_EXTRACT_HOST})
        payload = self._post(urls, extract_depth=extract_depth, include_usage=include_usage)
        return self._parse(payload)

    def _post(self, urls: list[str], *, extract_depth: str, include_usage: bool) -> dict:
        body = json.dumps(
            {
                "urls": urls,
                "extract_depth": extract_depth,
                "format": "text",
                "include_usage": include_usage,
            }
        ).encode("utf-8")
        req = request.Request(
            TAVILY_EXTRACT_URL,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with self._urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
        except HTTPError as exc:
            raise TavilyExtractError(f"Tavily Extract HTTP {exc.code}: {_error_detail(exc)}") from exc
        except URLError as exc:
            raise TavilyExtractError(f"Tavily Extract network error: {exc.reason}") from exc
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TavilyExtractError("Tavily Extract returned invalid JSON") from exc

    @staticmethod
    def _parse(payload: object) -> ExtractResult:
        data = payload if isinstance(payload, dict) else {}
        extracted: dict[str, str] = {}
        for item in data.get("results") or []:
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            if url:
                extracted[url] = item.get("raw_content") or ""
        failed: dict[str, str] = {}
        for item in data.get("failed_results") or []:
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            if url:
                failed[url] = item.get("error") or "unknown error"
        usage = data.get("usage") or {}
        credits = _as_float(usage.get("credits"), 0.0)
        request_id = data.get("request_id")
        return ExtractResult(extracted, failed, credits, request_id)
