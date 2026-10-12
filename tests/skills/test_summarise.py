"""Tests for the summariser skill and its citation checker (T012)."""

import json
import re
import tempfile
import unittest
from pathlib import Path

import jsonschema

from src.providers.llm import ChatResult
from src.skills.summarise import (
    _parse_reply,
    build_summaries_document,
    check_citations,
    render_summaries_markdown,
    run,
    save_summaries_document,
    sources_from_ledger,
    summarise,
)


def _story(number: int) -> dict:
    return {
        "story_id": f"story-{number}",
        "url": f"https://news.example.test/{number}",
        "publisher": "Example Wire",
        "published_at": "2026-10-10T09:00:00Z",
        "text_source": "tavily_extract",
        "article_text": "unused by the summariser",
        "facts": [
            {"fact_id": f"f{number}-1", "kind": "who", "claim": f"Claim {number}a", "support_span": "x", "verified": True},
            {"fact_id": f"f{number}-2", "kind": "what", "claim": f"Claim {number}b", "support_span": "x", "verified": True},
        ],
        "quotes": [],
        "people": [],
    }


def _ledger(count: int = 5) -> dict:
    return {"schema_version": "1.0", "stories": [_story(i) for i in range(1, count + 1)]}


def _chat_from_message(messages):
    user = messages[-1][1]
    ids = re.findall(r"\[(f\d+-\d+)\]", user)
    first = ids[0] if ids else "f1-1"
    second = ids[1] if len(ids) > 1 else first
    content = json.dumps({
        "sentences": [
            {"text": "First sentence.", "ledger_fact_ids": [first]},
            {"text": "Second sentence.", "ledger_fact_ids": [second]},
        ],
    })
    return ChatResult(content=content, model="deepseek-chat", prompt_tokens=1, completion_tokens=1)


class ParseReplyTests(unittest.TestCase):
    def test_plain_json(self) -> None:
        self.assertEqual(_parse_reply('{"sentences": []}')["sentences"], [])

    def test_fenced_json(self) -> None:
        self.assertEqual(_parse_reply('```json\n{"sentences": [1]}\n```')["sentences"], [1])

    def test_invalid_returns_empty(self) -> None:
        self.assertEqual(_parse_reply("not json"), {})


class SourcesTests(unittest.TestCase):
    def test_sources_from_ledger(self) -> None:
        sources = sources_from_ledger(_ledger(1))
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0].story_id, "story-1")
        self.assertEqual(sources[0].publisher, "Example Wire")
        self.assertEqual(sources[0].facts, (("f1-1", "Claim 1a"), ("f1-2", "Claim 1b")))


class SummariseTests(unittest.TestCase):
    def test_summarise_injects_story_id_and_keeps_sentences(self) -> None:
        summaries = summarise(_ledger(2), chat=_chat_from_message)
        self.assertEqual([s["story_id"] for s in summaries], ["story-1", "story-2"])
        for summary in summaries:
            self.assertEqual(len(summary["sentences"]), 2)


class CitationCheckerTests(unittest.TestCase):
    def test_valid_citations_pass(self) -> None:
        summaries = summarise(_ledger(2), chat=_chat_from_message)
        self.assertEqual(check_citations(summaries, _ledger(2)), [])

    def test_uncited_sentence_rejected(self) -> None:
        summaries = [{"story_id": "story-1", "sentences": [{"text": "no citation", "ledger_fact_ids": []}]}]
        violations = check_citations(summaries, _ledger(1))
        self.assertEqual(violations, [{"story_id": "story-1", "sentence_index": 0, "reason": "uncited"}])

    def test_unknown_id_rejected(self) -> None:
        summaries = [{"story_id": "story-1", "sentences": [{"text": "bad id", "ledger_fact_ids": ["f9-9"]}]}]
        violations = check_citations(summaries, _ledger(1))
        self.assertEqual(violations[0]["reason"], "unknown_id")
        self.assertEqual(violations[0]["unknown_ids"], ["f9-9"])


class DocumentTests(unittest.TestCase):
    def test_build_envelope(self) -> None:
        self.assertEqual(build_summaries_document([]), {"schema_version": "1.0", "summaries": []})

    def test_render_markdown(self) -> None:
        summaries = [{"story_id": "story-1", "sentences": [{"text": "A.", "ledger_fact_ids": ["f1-1"]}, {"text": "B.", "ledger_fact_ids": ["f1-2"]}]}]
        md = render_summaries_markdown(summaries)
        self.assertIn("# Summaries", md)
        self.assertIn("## Story 1", md)
        self.assertIn("- A.", md)
        self.assertIn("- B.", md)

    def test_save_writes_json_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            document = build_summaries_document([])
            path = save_summaries_document(document, "# Summaries\n", workspace_root=root, run_id="r1")
            self.assertTrue(path.exists())
            self.assertTrue(path.with_name("summaries.md").exists())
            with self.assertRaises(FileExistsError):
                save_summaries_document(document, "# Summaries\n", workspace_root=root, run_id="r1")

    def test_run_end_to_end_and_schema_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = run(_ledger(5), workspace_root=root, run_id="r1", chat=_chat_from_message)
            self.assertEqual(result["citation_errors"], [])

            schema = json.loads((Path(__file__).resolve().parents[2] / "schemas" / "summaries.schema.json").read_text(encoding="utf-8"))
            jsonschema.Draft202012Validator(schema).validate(result["document"])

            self.assertTrue((root / "runs" / "r1" / "summaries.json").exists())
            self.assertTrue((root / "runs" / "r1" / "summaries.md").exists())


if __name__ == "__main__":
    unittest.main()
