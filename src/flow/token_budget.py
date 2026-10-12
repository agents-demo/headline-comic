"""FR-012 LLM token budget.

The DeepSeek adapter reports ``prompt_tokens`` and ``completion_tokens`` on every
``ChatResult``. The pipeline wraps every model call in a :class:`TokenAccountingChat`
so total usage is capped before it exceeds the run's token budget and is written
to ``run.log``. Tavily credits are tracked separately (FR-002), not through this
budget.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from src.providers.llm import ChatResult

Chat = Callable[[Sequence[tuple[str, str]]], ChatResult]

DEFAULT_TOKEN_LIMIT = 200_000


class TokenBudgetExceeded(RuntimeError):
    """Raised before a model call that would exceed the run token budget."""


def _tokens(value: object) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


@dataclass
class TokenBudget:
    """A mutable counter with a hard limit, shared across every model call."""

    limit: int
    used: int = 0

    def consume(self, prompt_tokens: object = 0, completion_tokens: object = 0) -> int:
        """Charge a call's tokens; raise :class:`TokenBudgetExceeded` if over."""

        delta = _tokens(prompt_tokens) + _tokens(completion_tokens)
        if self.used + delta > self.limit:
            raise TokenBudgetExceeded(
                f"Token budget exceeded: {self.used + delta} > {self.limit}"
            )
        self.used += delta
        return self.used

    @property
    def remaining(self) -> int:
        return self.limit - self.used


class TokenAccountingChat:
    """Wrap a ``Chat`` callable and charge every call against a budget."""

    def __init__(self, chat: Chat, budget: TokenBudget):
        self._chat = chat
        self.budget = budget

    def __call__(self, messages: Sequence[tuple[str, str]]) -> ChatResult:
        result = self._chat(messages)
        self.budget.consume(result.prompt_tokens, result.completion_tokens)
        return result
