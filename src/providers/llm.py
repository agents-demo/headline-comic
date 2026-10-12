"""DeepSeek chat adapter for the article ledger and later Teammate stages (T011+).

DeepSeek exposes an OpenAI-compatible chat completions endpoint. This adapter is
the first real LLM provider: it posts ``{base}/chat/completions`` with the
configured model and returns the assistant message plus token usage. The host
derived from ``LLM_BASE_URL`` is allowlisted per FR-014; the key, base URL and
model come from ``.env`` via :func:`src.env.load_env`.

Defaults are ``https://api.deepseek.com`` and ``deepseek-chat``. Override with
``LLM_BASE_URL`` and ``LLM_MODEL``. Requests use ``urllib`` only, like the Tavily
adapter, so no extra client dependency is introduced.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence
from urllib import request
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

from src.env import load_env
from src.permissions.media_guard import require_allowed_host

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"
_TIMEOUT_S = 120.0

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

Message = tuple[str, str]  # (role, content)


class ChatError(RuntimeError):
    """Raised when a chat completion request itself fails (transport, auth, limits)."""


@dataclass(frozen=True)
class ChatResult:
    """One completed assistant turn."""

    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int


def _as_int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _error_detail(exc: HTTPError) -> str:
    try:
        payload = json.loads(exc.read().decode("utf-8"))
        error = payload.get("error") or {}
        if isinstance(error, dict):
            message = error.get("message")
            if message:
                return str(message)
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    return exc.reason or ""


class DeepSeekChatProvider:
    """Submit chat messages to an OpenAI-compatible endpoint and parse the reply."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = _TIMEOUT_S,
        urlopen: Callable[..., object] | None = None,
    ) -> None:
        load_env(_PROJECT_ROOT / ".env")
        self.api_key = (api_key or os.environ.get("LLM_API_KEY") or "").strip()
        self.base_url = (base_url or os.environ.get("LLM_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.model = (model or os.environ.get("LLM_MODEL") or DEFAULT_MODEL).strip()
        self.timeout = timeout
        self._urlopen = urlopen or request.urlopen

    @property
    def endpoint(self) -> str:
        return f"{self.base_url}/chat/completions"

    def complete(
        self,
        messages: Sequence[Message],
        *,
        json_mode: bool = False,
        temperature: float | None = 0.0,
    ) -> ChatResult:
        if not self.api_key:
            raise ValueError("LLM_API_KEY is not set")
        host = urlsplit(self.base_url).hostname
        if not host:
            raise ChatError("LLM_BASE_URL must include a hostname")
        require_allowed_host(self.endpoint, {host})
        payload: dict = {
            "model": self.model,
            "messages": [{"role": role, "content": content} for role, content in messages],
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        return self._parse(self._post(payload))

    def _post(self, payload: dict) -> dict:
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            self.endpoint,
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
            raise ChatError(f"Chat HTTP {exc.code}: {_error_detail(exc)}") from exc
        except URLError as exc:
            raise ChatError(f"Chat network error: {exc.reason}") from exc
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ChatError("Chat completion returned invalid JSON") from exc

    @staticmethod
    def _parse(payload: object) -> ChatResult:
        data = payload if isinstance(payload, dict) else {}
        content = ""
        choices = data.get("choices") or []
        if choices and isinstance(choices[0], dict):
            message = choices[0].get("message") or {}
            if isinstance(message, dict):
                content = message.get("content") or ""
        usage = data.get("usage") or {}
        return ChatResult(
            content=content,
            model=str(data.get("model") or ""),
            prompt_tokens=_as_int(usage.get("prompt_tokens")),
            completion_tokens=_as_int(usage.get("completion_tokens")),
        )
