"""S2 article text + manual paths: Tavily Extract with per-article fallbacks (FR-002).

Deterministic fetch code. For each selected story it tries Tavily Extract, then
falls back to the feed's own description, then to text pasted by the presenter,
and records which source supplied the text plus the credits Tavily reported.
No model is called. The same path serves both the five feed-selected stories and
the five pasted-URL manual path.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence

from src.permissions.media_guard import require_allowed_write_path
from src.providers.tavily import ExtractResult, TavilyExtractError, TavilyExtractProvider

SOURCE_TAVILY = "tavily_extract"
SOURCE_DESCRIPTION = "feed_description"
SOURCE_PASTED = "pasted_text"
SOURCE_NONE = "none"

# An extractor takes a list of URLs and returns their batch outcome.
Extractor = Callable[[list[str]], ExtractResult]


@dataclass(frozen=True)
class StoryRequest:
    """One story whose text must be obtained. Feed-selected stories carry a
    description for fallback; pasted-URL stories may carry pasted text."""

    story_id: str
    url: str
    title: str = ""
    publisher: str = ""
    description: str = ""
    pasted_text: str | None = None


@dataclass(frozen=True)
class ArticleText:
    story_id: str
    title: str
    url: str
    publisher: str
    source: str
    text: str
    word_count: int


def story_request_from_candidate(candidate: Mapping[str, object]) -> StoryRequest:
    """Build a StoryRequest from one T008 candidate, keeping its description as fallback."""

    return StoryRequest(
        story_id=str(candidate["candidate_id"]),
        url=str(candidate["url"]),
        title=str(candidate.get("title") or ""),
        publisher=str(candidate.get("publisher") or ""),
        description=str(candidate.get("description") or ""),
    )


def _word_count(text: str) -> int:
    return len(text.split())


def _select_text(story: StoryRequest, extracted: Mapping[str, str]) -> tuple[str, str]:
    text = extracted.get(story.url)
    if text is not None:
        return SOURCE_TAVILY, text
    if story.description.strip():
        return SOURCE_DESCRIPTION, story.description
    if story.pasted_text and story.pasted_text.strip():
        return SOURCE_PASTED, story.pasted_text
    return SOURCE_NONE, ""


def fetch_article_text(
    stories: Sequence[StoryRequest],
    *,
    extractor: Extractor | None = None,
    extract_depth: str = "basic",
) -> tuple[list[ArticleText], float]:
    """Resolve text for every story through the FR-002 fallback chain.

    Returns the resolved articles and the total Tavily credits reported for the
    batch. A transport-level Extract error falls back every story rather than
    aborting; the per-story ``source`` field then shows the fallback.
    """

    provider = TavilyExtractProvider()
    do_extract = extractor if extractor is not None else provider.extract
    urls = [story.url for story in stories if story.url]

    extracted: Mapping[str, str] = {}
    credits = 0.0
    if urls:
        try:
            result = do_extract(urls, extract_depth=extract_depth)
        except TavilyExtractError:
            result = ExtractResult({}, {url: "extract request failed" for url in urls}, 0.0)
        extracted = result.extracted
        credits = result.credits_used

    articles: list[ArticleText] = []
    for story in stories:
        source, text = _select_text(story, extracted)
        articles.append(
            ArticleText(
                story_id=story.story_id,
                title=story.title,
                url=story.url,
                publisher=story.publisher,
                source=source,
                text=text,
                word_count=_word_count(text),
            )
        )
    return articles, credits


def build_articles_document(
    articles: Sequence[ArticleText],
    tavily_credits_used: float,
    generated_at: datetime | None = None,
) -> dict:
    """Wrap resolved article text in the run's article_text document envelope."""

    return {
        "schema_version": "1.0",
        "generated_at": (generated_at or datetime.now(timezone.utc)).isoformat(),
        "tavily_credits_used": tavily_credits_used,
        "articles": [asdict(article) for article in articles],
    }


def save_articles_document(
    document: dict,
    *,
    workspace_root: Path,
    run_id: str,
) -> Path:
    """Write articles.json into the run's own ``runs/<run-id>/article_text/``."""

    path = require_allowed_write_path(
        workspace_root / "runs" / run_id / "article_text" / "articles.json",
        workspace_root=workspace_root,
    )
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite existing article text file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return path


def run(
    stories: Sequence[StoryRequest],
    *,
    workspace_root: Path,
    run_id: str,
    extractor: Extractor | None = None,
) -> dict:
    """Resolve article text, save the document, and return it."""

    articles, credits = fetch_article_text(stories, extractor=extractor)
    document = build_articles_document(articles, credits)
    save_articles_document(document, workspace_root=workspace_root, run_id=run_id)
    return document
