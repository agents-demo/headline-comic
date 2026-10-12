"""S4 summariser: two cited sentences per story plus a code citation checker (FR-004).

For each story the skill calls the LLM once (in parallel across stories) to
write a neutral two-sentence summary using only the verified ledger facts,
every sentence citing at least one fact id. Code then runs a deterministic
citation checker that rejects sentences citing nothing and sentences citing an
unknown id. The model proposes text and ids; story ids, citation checking and
the file layout are deterministic code. Outputs are schema-valid ``summaries.json``
plus a human-readable ``summaries.md`` (FR-011 names the markdown).
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

from src.permissions.media_guard import require_allowed_write_path
from src.providers.llm import ChatResult, DeepSeekChatProvider

Chat = Callable[[Sequence[tuple[str, str]]], ChatResult]

_SYSTEM_PROMPT = (
    "You write a neutral two-sentence summary of one news story, using only the verified facts given. "
    'Reply with one JSON object: {"sentences": [{"text": "...", "ledger_fact_ids": ["f1-1"]}, '
    '{"text": "...", "ledger_fact_ids": ["f1-3"]}]}. '
    "Write exactly two sentences. Every sentence must cite at least one fact id from the list, using the exact id string. "
    "Do not invent facts, names, numbers or ids."
)


@dataclass(frozen=True)
class SummariserSource:
    """One story's verified facts, the only input the summariser may use."""

    story_id: str
    publisher: str
    facts: tuple[tuple[str, str], ...]  # (fact_id, claim)


def sources_from_ledger(ledger: Mapping[str, object]) -> list[SummariserSource]:
    """Build summariser inputs from a verified ledger document."""

    sources: list[SummariserSource] = []
    for story in ledger.get("stories") or []:
        facts = tuple(
            (str(fact["fact_id"]), str(fact["claim"]))
            for fact in story.get("facts") or []
            if isinstance(fact, Mapping)
        )
        sources.append(SummariserSource(
            story_id=str(story["story_id"]),
            publisher=str(story.get("publisher") or ""),
            facts=facts,
        ))
    return sources


def _format_story(source: SummariserSource) -> str:
    lines = [f"Story id: {source.story_id}", f"Publisher: {source.publisher}", "Verified facts:"]
    for fact_id, claim in source.facts:
        lines.append(f"- [{fact_id}] {claim}")
    return "\n".join(lines)


def _parse_reply(content: str) -> Mapping[str, object]:
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


def _summarise_one(source: SummariserSource, chat: Chat) -> dict:
    result = chat([("system", _SYSTEM_PROMPT), ("user", _format_story(source))])
    data = _parse_reply(result.content)
    sentences = data.get("sentences")
    if not isinstance(sentences, list):
        sentences = []
    cleaned: list[dict] = []
    for sentence in sentences:
        if not isinstance(sentence, Mapping):
            continue
        text = str(sentence.get("text") or "").strip()
        ids = [str(i) for i in (sentence.get("ledger_fact_ids") or []) if str(i)]
        if text:
            cleaned.append({"text": text, "ledger_fact_ids": list(dict.fromkeys(ids))})
    return {"story_id": source.story_id, "sentences": cleaned}


def _default_chat() -> Chat:
    provider = DeepSeekChatProvider()

    def chat(messages: Sequence[tuple[str, str]]) -> ChatResult:
        return provider.complete(messages, json_mode=True)

    return chat


def summarise(
    ledger: Mapping[str, object],
    *,
    chat: Chat | None = None,
    max_workers: int | None = None,
) -> list[dict]:
    """Write two cited sentences per story, one call per story in parallel."""

    sources = sources_from_ledger(ledger)
    do_chat = chat or _default_chat()
    workers = max_workers if max_workers is not None else len(sources)
    workers = max(1, workers)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda source: _summarise_one(source, do_chat), sources))


def check_citations(summaries: Sequence[Mapping[str, object]], ledger: Mapping[str, object]) -> list[dict]:
    """Reject uncited sentences and unknown ids (FR-004); return the violations."""

    valid_ids: dict[str, set[str]] = {}
    for story in ledger.get("stories") or []:
        valid_ids[str(story["story_id"])] = {
            str(fact["fact_id"]) for fact in story.get("facts") or [] if isinstance(fact, Mapping)
        }

    violations: list[dict] = []
    for summary in summaries:
        story_id = str(summary.get("story_id") or "")
        valid = valid_ids.get(story_id, set())
        for index, sentence in enumerate(summary.get("sentences") or []):
            ids = sentence.get("ledger_fact_ids") or []
            if not ids:
                violations.append({"story_id": story_id, "sentence_index": index, "reason": "uncited"})
                continue
            unknown = [fid for fid in ids if fid not in valid]
            if unknown:
                violations.append({
                    "story_id": story_id,
                    "sentence_index": index,
                    "reason": "unknown_id",
                    "unknown_ids": unknown,
                })
    return violations


def build_summaries_document(summaries: Sequence[dict]) -> dict:
    """Wrap summaries in the schema's summaries document envelope."""

    return {"schema_version": "1.0", "summaries": list(summaries)}


def render_summaries_markdown(summaries: Sequence[Mapping[str, object]]) -> str:
    """Render summaries as the FR-011 ``summaries.md`` file."""

    lines = ["# Summaries", ""]
    for number, summary in enumerate(summaries, start=1):
        lines.append(f"## Story {number}")
        lines.append("")
        for sentence in summary.get("sentences") or []:
            lines.append(f"- {sentence.get('text', '')}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def save_summaries_document(
    document: dict,
    markdown: str,
    *,
    workspace_root: Path,
    run_id: str,
) -> Path:
    """Write ``summaries.json`` and ``summaries.md`` into the run folder."""

    path = require_allowed_write_path(
        workspace_root / "runs" / run_id / "summaries.json", workspace_root=workspace_root
    )
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite existing summaries: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    path.with_name("summaries.md").write_text(markdown, encoding="utf-8")
    return path


def run(
    ledger: Mapping[str, object],
    *,
    workspace_root: Path,
    run_id: str,
    chat: Chat | None = None,
) -> dict:
    """Summarise, run the citation check, save both files, and return document plus errors."""

    summaries = summarise(ledger, chat=chat)
    document = build_summaries_document(summaries)
    citation_errors = check_citations(summaries, ledger)
    markdown = render_summaries_markdown(summaries)
    save_summaries_document(document, markdown, workspace_root=workspace_root, run_id=run_id)
    return {"document": document, "citation_errors": citation_errors}
