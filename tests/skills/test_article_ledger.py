"""Tests for the article ledger skill: extraction, span check and file layout (T011)."""

import json
import tempfile
import unittest
from pathlib import Path

import jsonschema

from src.providers.llm import ChatResult
from src.skills.article_ledger import (
    LedgerSource,
    _parse_extraction,
    _span_verified,
    build_ledger_document,
    extract_ledgers,
    ledger_source_from,
    normalize_whitespace,
    run,
    save_ledger_document,
    span_check,
)

ARTICLE = (
    "A volunteer group installed three solar lamps along the harbor path on Friday. "
    "The lamps help evening walkers see the steps. The mayor praised the work."
)

VALID_CONTENT = json.dumps({
    "facts": [
        {"kind": "who", "claim": "A volunteer group installed the lamps.", "support_span": "A volunteer group installed three solar lamps"},
        {"kind": "what", "claim": "Three solar lamps were installed.", "support_span": "three solar lamps along the harbor path"},
    ],
    "quotes": [
        {"text": "The lamps help evening walkers.", "support_span": "The lamps help evening walkers see the steps."},
    ],
    "people": ["Ada Lovelace", "Ada Lovelace"],
})


def _source(story_id: str = "story-1", article_text: str = ARTICLE) -> LedgerSource:
    return LedgerSource(
        story_id=story_id,
        title="Harbor lamps",
        url="https://news.example.test/harbor-lights",
        publisher="Example Wire",
        published_at="2026-10-10T09:00:00Z",
        text_source="tavily_extract",
        article_text=article_text,
    )


def _fake_chat(content: str = VALID_CONTENT):
    def chat(messages):
        return ChatResult(content=content, model="deepseek-chat", prompt_tokens=1, completion_tokens=1)
    return chat


class NormalisationTests(unittest.TestCase):
    def test_whitespace_collapses(self) -> None:
        self.assertEqual(normalize_whitespace("a\t b\n  c  \r\n"), "a b c")

    def test_span_match_ignores_whitespace_only(self) -> None:
        self.assertTrue(_span_verified("three  solar\nlamps", ARTICLE))
        self.assertFalse(_span_verified("five solar lamps", ARTICLE))
        self.assertFalse(_span_verified("", ARTICLE))


class ParseExtractionTests(unittest.TestCase):
    def test_plain_json(self) -> None:
        self.assertEqual(_parse_extraction('{"facts": []}')["facts"], [])

    def test_fenced_json(self) -> None:
        self.assertEqual(_parse_extraction('```json\n{"facts": [1]}\n```')["facts"], [1])

    def test_invalid_returns_empty(self) -> None:
        self.assertEqual(_parse_extraction("not json at all"), {})


class SpanCheckTests(unittest.TestCase):
    def test_verified_facts_and_dropped_failures(self) -> None:
        extraction = {
            "facts": [
                {"kind": "who", "claim": "Volunteers installed lamps.", "support_span": "A volunteer group installed three solar lamps"},
                {"kind": "when", "claim": "It happened Friday.", "support_span": "not in the article"},
                {"kind": "bogus", "claim": "bad kind", "support_span": "A volunteer group"},
            ],
            "quotes": [
                {"text": "The lamps help walkers.", "support_span": "The lamps help evening walkers see the steps."},
                {"text": " ".join("word" for _ in range(26)), "support_span": "The lamps help"},
                {"text": "Fabricated quote.", "support_span": "no such span"},
            ],
            "people": ["Ada Lovelace", "Ada Lovelace", ""],
        }
        stories, dropped = span_check([_source()], [extraction])

        self.assertEqual(len(stories), 1)
        facts = stories[0]["facts"]
        self.assertEqual([f["fact_id"] for f in facts], ["f1-1"])
        self.assertEqual(facts[0]["kind"], "who")
        self.assertIs(facts[0]["verified"], True)

        quotes = stories[0]["quotes"]
        self.assertEqual([q["quote_id"] for q in quotes], ["q1-1"])

        self.assertEqual(stories[0]["people"], ["Ada Lovelace"])
        self.assertEqual(len(dropped), 4)  # bad span, bad kind, over-length quote, bad quote span

    def test_span_check_verifies_across_whitespace(self) -> None:
        extraction = {"facts": [{"kind": "what", "claim": "lamps", "support_span": "three  solar\nlamps along"}], "quotes": [], "people": []}
        stories, dropped = span_check([_source()], [extraction])
        self.assertEqual(len(stories[0]["facts"]), 1)
        self.assertEqual(dropped, [])


class DocumentTests(unittest.TestCase):
    def test_build_envelope(self) -> None:
        document = build_ledger_document([])
        self.assertEqual(document, {"schema_version": "1.0", "stories": []})

    def test_ledger_source_from_joins_article_and_candidate(self) -> None:
        article = {"story_id": "c-1", "title": "T", "url": "https://x/1", "publisher": "BBC", "source": "tavily_extract", "text": "hello"}
        candidate = {"candidate_id": "c-1", "published_at": "2026-10-12T00:00:00Z"}
        source = ledger_source_from(article, candidate)
        self.assertEqual(source.story_id, "c-1")
        self.assertEqual(source.published_at, "2026-10-12T00:00:00Z")
        self.assertEqual(source.text_source, "tavily_extract")

    def test_save_writes_ledger_and_dropped_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            document = build_ledger_document([])
            path = save_ledger_document(document, ["story-1: dropped fact"], workspace_root=root, run_id="r1")
            self.assertTrue(path.exists())
            self.assertTrue(path.parent.joinpath("ledger_dropped.json").exists())
            with self.assertRaises(FileExistsError):
                save_ledger_document(document, [], workspace_root=root, run_id="r1")


class ExtractLedgersTests(unittest.TestCase):
    def test_extract_in_parallel_returns_proposals(self) -> None:
        sources = [_source(f"story-{i}") for i in range(1, 6)]
        extractions = extract_ledgers(sources, chat=_fake_chat())
        self.assertEqual(len(extractions), 5)
        self.assertEqual(len(extractions[0]["facts"]), 2)

    def test_run_end_to_end_and_schema_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sources = [_source(f"story-{i}") for i in range(1, 6)]
            document = run(sources, workspace_root=root, run_id="r1", chat=_fake_chat())

            schema = json.loads((Path(__file__).resolve().parents[2] / "schemas" / "ledger.schema.json").read_text(encoding="utf-8"))
            jsonschema.Draft202012Validator(schema).validate(document)

            saved = root / "runs" / "r1" / "ledger.json"
            self.assertTrue(saved.exists())
            self.assertTrue((root / "runs" / "r1" / "ledger_dropped.json").exists())


if __name__ == "__main__":
    unittest.main()
