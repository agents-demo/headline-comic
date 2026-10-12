"""S3 evidence ledger: one LLM extraction per article plus a deterministic span check (FR-003).

For each selected story the skill calls the LLM once (in parallel across
stories) to propose facts (who/what/when/where), short quotes and the names of
real people mentioned, with every fact and quote carrying a verbatim support
span from the article text. Code then verifies each span by exact match against
the stored text after whitespace normalisation, drops the failures and logs
them. Fact/quote ids, verification, the 25-word quote limit and the file layout
are deterministic code; the model proposes text and structure only. Later
stages may use only verified facts.
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

from src.permissions.media_guard import require_allowed_write_path
from src.providers.llm import ChatResult, DeepSeekChatProvider

FACT_KINDS = ("who", "what", "when", "where")
MAX_QUOTE_WORDS = 25

# A chat callable takes a list of (role, content) messages and returns a reply.
Chat = Callable[[Sequence[tuple[str, str]]], ChatResult]

_SYSTEM_PROMPT = (
    "You extract a factual evidence ledger from a single news article. "
    "Reply with one JSON object containing exactly these keys:\n"
    '- "facts": a list of objects, each {"kind": one of "who","what","when","where", '
    '"claim": a short factual claim, "support_span": the verbatim substring of the article that supports it}.\n'
    '- "quotes": a list of objects, each {"text": a short direct quote of 25 words or fewer, '
    '"support_span": the verbatim substring of the article containing it}.\n'
    '- "people": a list of the full names of real individuals mentioned in the article.\n'
    "Every support_span must be copied character-for-character from the article text. "
    "Do not paraphrase, shorten or expand a span. If the article has no quotes or no named people, "
    "return an empty list for that key."
)


@dataclass(frozen=True)
class LedgerSource:
    """One selected story with its resolved article text (T010 output joined with the candidate)."""

    story_id: str
    title: str
    url: str
    publisher: str
    published_at: str
    text_source: str
    article_text: str


def ledger_source_from(article: Mapping[str, object], candidate: Mapping[str, object]) -> LedgerSource:
    """Join a resolved article (article_text document entry) with its candidate metadata."""

    return LedgerSource(
        story_id=str(article["story_id"]),
        title=str(article.get("title") or candidate.get("title") or ""),
        url=str(article["url"]),
        publisher=str(article.get("publisher") or candidate.get("publisher") or ""),
        published_at=str(candidate.get("published_at") or ""),
        text_source=str(article["source"]),
        article_text=str(article.get("text") or ""),
    )


def normalize_whitespace(text: str) -> str:
    """Collapse every whitespace run to a single space, as FR-003 span matching requires."""

    return re.sub(r"\s+", " ", text).strip()


def _span_verified(span: str, article_text: str) -> bool:
    normalized_span = normalize_whitespace(span)
    if not normalized_span:
        return False
    return normalized_span in normalize_whitespace(article_text)


def _parse_extraction(content: str) -> Mapping[str, object]:
    """Parse the model's JSON reply, tolerating markdown fences and stray prose."""

    text = content.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.lstrip().lower().startswith("json"):
            text = text.lstrip()[4:]
    text = text.strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end <= start:
            return {}
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return {}
    return data if isinstance(data, dict) else {}


def _story_ledger(source: LedgerSource, extraction: Mapping[str, object], story_number: int) -> tuple[dict, list[str]]:
    """Build one verified story ledger entry, dropping and logging any failed span."""

    dropped: list[str] = []
    facts: list[dict] = []
    for raw in extraction.get("facts") or []:
        if not isinstance(raw, Mapping):
            continue
        kind = raw.get("kind")
        claim = str(raw.get("claim") or "").strip()
        span = str(raw.get("support_span") or "")
        if kind not in FACT_KINDS or not claim:
            dropped.append(f"story {source.story_id}: dropped fact with invalid kind or empty claim")
            continue
        if not _span_verified(span, source.article_text):
            dropped.append(f"story {source.story_id}: dropped fact, support span not found in article text")
            continue
        facts.append({
            "fact_id": f"f{story_number}-{len(facts) + 1}",
            "kind": kind,
            "claim": claim,
            "support_span": span,
            "verified": True,
        })

    quotes: list[dict] = []
    for raw in extraction.get("quotes") or []:
        if not isinstance(raw, Mapping):
            continue
        text = str(raw.get("text") or "").strip()
        span = str(raw.get("support_span") or "")
        if not text:
            dropped.append(f"story {source.story_id}: dropped empty quote")
            continue
        if len(text.split()) > MAX_QUOTE_WORDS:
            dropped.append(f"story {source.story_id}: dropped quote over {MAX_QUOTE_WORDS} words")
            continue
        if not _span_verified(span, source.article_text):
            dropped.append(f"story {source.story_id}: dropped quote, support span not found in article text")
            continue
        quotes.append({
            "quote_id": f"q{story_number}-{len(quotes) + 1}",
            "text": text,
            "support_span": span,
            "verified": True,
        })

    people = list(dict.fromkeys(str(name).strip() for name in extraction.get("people") or [] if str(name).strip()))

    return {
        "story_id": source.story_id,
        "url": source.url,
        "publisher": source.publisher,
        "published_at": source.published_at,
        "text_source": source.text_source,
        "article_text": source.article_text,
        "facts": facts,
        "quotes": quotes,
        "people": people,
    }, dropped


def _default_chat() -> Chat:
    provider = DeepSeekChatProvider()

    def chat(messages: Sequence[tuple[str, str]]) -> ChatResult:
        return provider.complete(messages, json_mode=True)

    return chat


def extract_ledgers(
    sources: Sequence[LedgerSource],
    *,
    chat: Chat | None = None,
    max_workers: int | None = None,
) -> list[Mapping[str, object]]:
    """Run one ledger extraction per article in parallel and return raw proposals."""

    do_chat = chat or _default_chat()
    workers = max_workers if max_workers is not None else len(sources)
    workers = max(1, workers)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda source: _extract_one(source, do_chat), sources))


def _extract_one(source: LedgerSource, chat: Chat) -> Mapping[str, object]:
    result = chat([
        ("system", _SYSTEM_PROMPT),
        ("user", f"Publisher: {source.publisher}\nTitle: {source.title}\n\n{source.article_text}"),
    ])
    return _parse_extraction(result.content)


def span_check(
    sources: Sequence[LedgerSource],
    extractions: Sequence[Mapping[str, object]],
) -> tuple[list[dict], list[str]]:
    """Verify every proposed span and return verified stories plus the dropped-fact log."""

    stories: list[dict] = []
    dropped: list[str] = []
    for number, (source, extraction) in enumerate(zip(sources, extractions), start=1):
        ledger, failures = _story_ledger(source, extraction, number)
        stories.append(ledger)
        dropped.extend(failures)
    return stories, dropped


def build_ledger_document(stories: Sequence[dict]) -> dict:
    """Wrap verified story ledgers in the schema's ledger document envelope.

    The ledger schema (``additionalProperties: false``) allows only
    ``schema_version`` and ``stories``, so no timestamp is added here.
    """

    return {
        "schema_version": "1.0",
        "stories": list(stories),
    }


def save_ledger_document(
    document: dict,
    dropped: Sequence[str],
    *,
    workspace_root: Path,
    run_id: str,
) -> Path:
    """Write ``ledger.json`` and a ``ledger_dropped.json`` sidecar log into the run folder."""

    path = require_allowed_write_path(
        workspace_root / "runs" / run_id / "ledger.json", workspace_root=workspace_root
    )
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite existing ledger: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    dropped_path = path.with_name("ledger_dropped.json")
    dropped_path.write_text(
        json.dumps({"schema_version": "1.0", "dropped": list(dropped)}, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def run(
    sources: Sequence[LedgerSource],
    *,
    workspace_root: Path,
    run_id: str,
    chat: Chat | None = None,
) -> dict:
    """Extract, span-check, save and return the verified ledger document."""

    extractions = extract_ledgers(sources, chat=chat)
    stories, dropped = span_check(sources, extractions)
    document = build_ledger_document(stories)
    save_ledger_document(document, dropped, workspace_root=workspace_root, run_id=run_id)
    return document
