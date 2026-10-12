"""Tests for the LLM token budget (T018, FR-012)."""

import unittest

from src.flow.token_budget import (
    TokenAccountingChat,
    TokenBudget,
    TokenBudgetExceeded,
)
from src.providers.llm import ChatResult


class TokenBudgetTests(unittest.TestCase):
    def test_consume_adds_tokens(self) -> None:
        budget = TokenBudget(limit=1000)
        budget.consume(100, 50)
        self.assertEqual(budget.used, 150)
        self.assertEqual(budget.remaining, 850)

    def test_exceeded_raises_before_charging(self) -> None:
        budget = TokenBudget(limit=100)
        budget.consume(90)
        with self.assertRaises(TokenBudgetExceeded):
            budget.consume(11)
        self.assertEqual(budget.used, 90)

    def test_negative_or_garbage_counts_as_zero(self) -> None:
        budget = TokenBudget(limit=100)
        budget.consume("12", -5)
        self.assertEqual(budget.used, 12)
        budget.consume(None, None)
        self.assertEqual(budget.used, 12)


class TokenAccountingChatTests(unittest.TestCase):
    def test_charges_each_call(self) -> None:
        budget = TokenBudget(limit=1000)

        def chat(messages):
            return ChatResult(content="ok", model="test", prompt_tokens=40, completion_tokens=10)

        wrapped = TokenAccountingChat(chat, budget)
        wrapped([("user", "hi")])
        self.assertEqual(budget.used, 50)

    def test_exceeded_propagates(self) -> None:
        budget = TokenBudget(limit=10)

        def chat(messages):
            return ChatResult(content="ok", model="test", prompt_tokens=20, completion_tokens=0)

        wrapped = TokenAccountingChat(chat, budget)
        with self.assertRaises(TokenBudgetExceeded):
            wrapped([("user", "hi")])


if __name__ == "__main__":
    unittest.main()
