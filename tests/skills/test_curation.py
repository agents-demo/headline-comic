"""Tests for the LLM curation skill (T048)."""

import json
import tempfile
import unittest
from pathlib import Path

from src.providers.llm import ChatResult
from src.skills.curation import (
    CurationError,
    build_curation_document,
    curate,
    format_candidates,
    run,
    save_curation_document,
)


def _candidate(number: int, *, hidden: bool = False) -> dict:
    return {
        "candidate_id": f"c-{number:02d}",
        "title": f"Story {number}",
        "url": f"https://news.example.test/{number}",
        "publisher": "Example Wire",
        "published_at": "2026-10-10T09:00:00Z",
        "description": f"Description for story {number}",
        "source": "rss",
        "cluster_id": f"cl-{number}",
        "safety_tags": ["violence"] if hidden else [],
        "hidden_by_safety": hidden,
    }


def _candidates(count: int, *, hidden: tuple[int, ...] = ()) -> list[dict]:
    return [_candidate(i, hidden=i in hidden) for i in range(1, count + 1)]


def _chat_returning(ids: list[str]) -> object:
    def chat(messages):
        content = json.dumps({"picks": [{"candidate_id": cid, "reason": f"why {cid}"} for cid in ids]})
        return ChatResult(content=content, model="test", prompt_tokens=1, completion_tokens=1)

    return chat


def _chat_with_content(content: str) -> object:
    def chat(messages):
        return ChatResult(content=content, model="test", prompt_tokens=1, completion_tokens=1)

    return chat


class CurateTests(unittest.TestCase):
    def test_curate_returns_ranked_selection_in_llm_order(self) -> None:
        # The LLM intentionally returns a non-input order; that order must win.
        result = curate(_candidates(6), chat=_chat_returning([f"c-{i:02d}" for i in (5, 2, 6, 1, 3)]))
        self.assertEqual([c["candidate_id"] for c in result.selected], ["c-05", "c-02", "c-06", "c-01", "c-03"])
        self.assertEqual(result.reasons, tuple(f"why c-{i:02d}" for i in (5, 2, 6, 1, 3)))

    def test_curate_excludes_hidden_candidates(self) -> None:
        # c-03 is hidden, so the visible pool is exactly the other five.
        result = curate(_candidates(6, hidden=(3,)), chat=_chat_returning([f"c-{i:02d}" for i in (1, 2, 4, 5, 6)]))
        self.assertEqual([c["candidate_id"] for c in result.selected], ["c-01", "c-02", "c-04", "c-05", "c-06"])

    def test_curate_rejects_hidden_pick_as_unknown(self) -> None:
        with self.assertRaises(CurationError) as ctx:
            curate(_candidates(6, hidden=(3,)), chat=_chat_returning([f"c-{i:02d}" for i in (1, 2, 3, 4, 5)]))
        self.assertIn("unknown candidate ids", str(ctx.exception))

    def test_curate_rejects_wrong_count(self) -> None:
        with self.assertRaises(CurationError):
            curate(_candidates(6), chat=_chat_returning([f"c-{i:02d}" for i in (1, 2, 3, 4)]))

    def test_curate_rejects_duplicate_ids(self) -> None:
        with self.assertRaises(CurationError) as ctx:
            curate(_candidates(6), chat=_chat_returning(["c-01", "c-01", "c-03", "c-04", "c-05"]))
        self.assertIn("duplicate", str(ctx.exception))

    def test_curate_rejects_unknown_id(self) -> None:
        with self.assertRaises(CurationError) as ctx:
            curate(_candidates(6), chat=_chat_returning(["c-01", "c-02", "c-03", "c-04", "c-99"]))
        self.assertIn("unknown candidate ids", str(ctx.exception))

    def test_curate_rejects_non_json(self) -> None:
        with self.assertRaises(CurationError):
            curate(_candidates(6), chat=_chat_with_content("not json at all"))

    def test_curate_retries_then_succeeds(self) -> None:
        calls: list[int] = []

        def chat(messages):
            calls.append(1)
            if len(calls) == 1:
                return ChatResult(content="garbage", model="test", prompt_tokens=1, completion_tokens=1)
            return ChatResult(
                content=json.dumps({"picks": [{"candidate_id": f"c-{i:02d}", "reason": "r"} for i in range(1, 6)]}),
                model="test",
                prompt_tokens=1,
                completion_tokens=1,
            )

        result = curate(_candidates(6), chat=chat)
        self.assertEqual(len(calls), 2)
        self.assertEqual([c["candidate_id"] for c in result.selected], [f"c-{i:02d}" for i in range(1, 6)])

    def test_curate_fails_closed_when_too_few_visible(self) -> None:
        with self.assertRaises(CurationError) as ctx:
            curate(_candidates(3), chat=_chat_returning([]))
        self.assertIn("need 5", str(ctx.exception))


class FormatTests(unittest.TestCase):
    def test_format_includes_ids_and_truncates_long_descriptions(self) -> None:
        candidates = _candidates(1)
        candidates[0]["description"] = "x" * 500
        text = format_candidates(candidates)
        self.assertIn("c-01", text)
        self.assertNotIn("x" * 500, text)
        self.assertIn("...", text)


class DocumentTests(unittest.TestCase):
    def test_build_document_shape(self) -> None:
        result = curate(_candidates(6), chat=_chat_returning([f"c-{i:02d}" for i in (5, 2, 6, 1, 3)]))
        document = build_curation_document(result)
        self.assertEqual(document["schema_version"], "1.0")
        self.assertEqual(len(document["selection"]), 5)
        first = document["selection"][0]
        self.assertEqual(first, {"rank": 1, "candidate_id": "c-05", "title": "Story 5", "publisher": "Example Wire", "reason": "why c-05"})

    def test_save_writes_and_refuses_overwrite(self) -> None:
        result = curate(_candidates(6), chat=_chat_returning([f"c-{i:02d}" for i in (1, 2, 3, 4, 5)]))
        document = build_curation_document(result)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = save_curation_document(document, workspace_root=root, run_id="r1")
            self.assertTrue(path.exists())
            with self.assertRaises(FileExistsError):
                save_curation_document(document, workspace_root=root, run_id="r1")

    def test_run_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = run(_candidates(6), workspace_root=root, run_id="r1", chat=_chat_returning([f"c-{i:02d}" for i in (5, 4, 3, 2, 1)]))
            self.assertEqual([c["candidate_id"] for c in result["selected"]], ["c-05", "c-04", "c-03", "c-02", "c-01"])
            self.assertTrue((root / "runs" / "r1" / "curation.json").exists())


if __name__ == "__main__":
    unittest.main()
