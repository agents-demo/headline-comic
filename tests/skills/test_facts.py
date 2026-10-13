"""Deterministic facts-strip tests (T026)."""

import json
import os
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from src.skills.compose import STRIP_W, ComposeError, facts_cards, render_facts_strip, run_facts

FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "t006-sample"


def _load(name: str) -> dict:
    return json.loads((FIXTURE / name).read_text(encoding="utf-8"))


class FactsCardsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.summaries = _load("summaries.json")
        cls.candidates = _load("candidates.json")
        cls.ledger = _load("ledger.json")

    def test_builds_five_ordered_source_linked_cards(self) -> None:
        cards = facts_cards(self.summaries, self.candidates)
        self.assertEqual([c["source"] for c in cards], [1, 2, 3, 4, 5])
        self.assertEqual(cards[0]["title"], "Harbor path gains three solar lamps")
        self.assertIn("three solar lamps", cards[0]["summary"])
        self.assertEqual(cards[0]["link"], "https://news.example.test/harbor-lights")
        # every card carries all three required fields
        for card in cards:
            self.assertTrue(card["title"])
            self.assertTrue(card["summary"])
            self.assertTrue(card["link"])

    def test_link_falls_back_to_ledger_url(self) -> None:
        candidates = {"candidates": [{"candidate_id": "story-1", "title": "T"}]}
        cards = facts_cards(self.summaries, candidates, ledger=self.ledger)
        self.assertEqual(cards[0]["link"], "https://news.example.test/harbor-lights")

    def test_missing_candidates_array_raises(self) -> None:
        with self.assertRaises(ComposeError):
            facts_cards(self.summaries, {"candidates": "nope"})


class RenderFactsStripTests(unittest.TestCase):
    def test_renders_strip_with_ink(self) -> None:
        cards = facts_cards(_load("summaries.json"), _load("candidates.json"))
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "facts.png"
            result = render_facts_strip(cards, output_path=output)
            self.assertEqual(result, output)
            with Image.open(output) as image:
                self.assertEqual(image.size[0], STRIP_W)
                self.assertGreater(image.size[1], 400)
                data = image.convert("RGB").tobytes()
            dark = sum(1 for i in range(0, len(data), 3) if data[i] < 100 and data[i + 1] < 100 and data[i + 2] < 100)
            self.assertGreater(dark, 300)  # header, chips, titles, summaries, links

    def test_empty_cards_raises(self) -> None:
        with self.assertRaises(ComposeError):
            render_facts_strip([], output_path=Path(tempfile.mkdtemp()) / "facts.png")


class RunFactsTests(unittest.TestCase):
    def test_run_facts_writes_under_run_dir_and_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run_facts(
                _load("summaries.json"),
                _load("candidates.json"),
                workspace_root=root,
                run_id="demo",
                ledger=_load("ledger.json"),
            )
            facts = root / "runs" / "demo" / "facts.png"
            self.assertTrue(facts.is_file())
            with self.assertRaises(FileExistsError):
                run_facts(
                    _load("summaries.json"),
                    _load("candidates.json"),
                    workspace_root=root,
                    run_id="demo",
                )


if __name__ == "__main__":
    unittest.main()
