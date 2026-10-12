"""Tests for the deterministic article_text fallback-chain skill (T010)."""

import json
import tempfile
import unittest
from pathlib import Path

from src.permissions.media_guard import PolicyDenied
from src.providers.tavily import ExtractResult, TavilyExtractError
from src.skills.article_text import (
    SOURCE_DESCRIPTION,
    SOURCE_NONE,
    SOURCE_PASTED,
    SOURCE_TAVILY,
    ArticleText,
    StoryRequest,
    build_articles_document,
    fetch_article_text,
    run,
    save_articles_document,
    story_request_from_candidate,
)


def _story(story_id: str, url: str, **kwargs: str) -> StoryRequest:
    defaults = {
        "title": f"Title {story_id}",
        "publisher": "BBC",
        "description": f"Feed description for {story_id}",
        "pasted_text": None,
    }
    defaults.update(kwargs)
    return StoryRequest(story_id=story_id, url=url, **defaults)


def _extractor(extracted, failed=(), credits=1.0):
    def extract(urls, extract_depth="basic"):
        return ExtractResult(
            {u: extracted[u] for u in urls if u in extracted},
            {u: "Failed to fetch url" for u in urls if u in failed},
            credits,
            "req-test",
        )

    return extract


class FetchTests(unittest.TestCase):
    def test_extract_success_uses_tavily_source(self) -> None:
        stories = [_story("s1", "https://a/1")]
        articles, credits = fetch_article_text(
            stories,
            extractor=_extractor({"https://a/1": "full article text here"}),
        )
        self.assertEqual(articles[0].source, SOURCE_TAVILY)
        self.assertEqual(articles[0].text, "full article text here")
        self.assertEqual(articles[0].word_count, 4)
        self.assertEqual(credits, 1.0)

    def test_extract_failure_falls_back_to_description(self) -> None:
        stories = [_story("s1", "https://a/1")]
        articles, _ = fetch_article_text(stories, extractor=_extractor({}, failed=("https://a/1",)))
        self.assertEqual(articles[0].source, SOURCE_DESCRIPTION)
        self.assertEqual(articles[0].text, "Feed description for s1")

    def test_no_description_falls_back_to_pasted_text(self) -> None:
        stories = [_story("s1", "https://a/1", description="", pasted_text="pasted body")]
        articles, _ = fetch_article_text(stories, extractor=_extractor({}, failed=("https://a/1",)))
        self.assertEqual(articles[0].source, SOURCE_PASTED)
        self.assertEqual(articles[0].text, "pasted body")

    def test_no_source_at_all_records_none(self) -> None:
        stories = [_story("s1", "https://a/1", description="", pasted_text=None)]
        articles, _ = fetch_article_text(stories, extractor=_extractor({}, failed=("https://a/1",)))
        self.assertEqual(articles[0].source, SOURCE_NONE)
        self.assertEqual(articles[0].text, "")
        self.assertEqual(articles[0].word_count, 0)

    def test_transport_error_falls_back_every_story(self) -> None:
        def broken(urls, extract_depth="basic"):
            raise TavilyExtractError("network down")

        stories = [_story("s1", "https://a/1"), _story("s2", "https://a/2")]
        articles, credits = fetch_article_text(stories, extractor=broken)
        self.assertEqual([a.source for a in articles], [SOURCE_DESCRIPTION, SOURCE_DESCRIPTION])
        self.assertEqual(credits, 0.0)

    def test_credits_come_from_batch_result(self) -> None:
        articles, credits = fetch_article_text(
            [_story("s1", "https://a/1")],
            extractor=_extractor({"https://a/1": "text"}, credits=2.5),
        )
        self.assertEqual(articles[0].source, SOURCE_TAVILY)
        self.assertEqual(credits, 2.5)


class DocumentAndSaveTests(unittest.TestCase):
    def test_build_document_envelope(self) -> None:
        article = ArticleText("s1", "T", "https://a/1", "BBC", SOURCE_TAVILY, "hello world", 2)
        doc = build_articles_document([article], 3.0)
        self.assertEqual(doc["schema_version"], "1.0")
        self.assertEqual(doc["tavily_credits_used"], 3.0)
        self.assertEqual(doc["articles"][0]["text"], "hello world")
        self.assertEqual(doc["articles"][0]["word_count"], 2)

    def test_save_writes_inside_run_article_text_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = save_articles_document(
                build_articles_document([], 0.0), workspace_root=root, run_id="r1"
            )
            self.assertTrue(path.is_file())
            self.assertEqual(path.parent.name, "article_text")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["articles"], [])

    def test_save_refuses_outside_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(PolicyDenied):
                save_articles_document(
                    build_articles_document([], 0.0), workspace_root=root, run_id="../../escape"
                )

    def test_run_resolves_and_saves(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = run(
                [_story("s1", "https://a/1")],
                workspace_root=root,
                run_id="r1",
                extractor=_extractor({"https://a/1": "body text"}),
            )
            self.assertEqual(doc["articles"][0]["source"], SOURCE_TAVILY)
            self.assertTrue((root / "runs" / "r1" / "article_text" / "articles.json").is_file())


class CandidateMappingTests(unittest.TestCase):
    def test_story_request_from_candidate_keeps_description(self) -> None:
        candidate = {
            "candidate_id": "c-abc",
            "title": "A headline",
            "url": "https://a/1",
            "publisher": "NPR",
            "description": "feed summary",
        }
        story = story_request_from_candidate(candidate)
        self.assertEqual(story.story_id, "c-abc")
        self.assertEqual(story.description, "feed summary")
        self.assertEqual(story.pasted_text, None)

    def test_story_request_tolerates_missing_optionals(self) -> None:
        story = story_request_from_candidate({"candidate_id": "c-1", "url": "https://a/1"})
        self.assertEqual(story.title, "")
        self.assertEqual(story.description, "")


if __name__ == "__main__":
    unittest.main()
