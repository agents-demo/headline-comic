"""S2 curation: the LLM ranks the top stories and formats the selection (Step 3).

The deterministic ``news_fetch.rank_clusters`` ordering (cross-source coverage,
then recency) does not reliably surface the most *relevant / important* stories,
so this skill lets the LLM re-rank the deduplicated candidate pool and pick the
five to feature. The model proposes candidate ids and one-line reasons only;
code validates every pick against the visible candidate set (fail-closed) and
shapes the ``curation.json`` selection document. No new provider: it reuses the
existing ``DeepSeekChatProvider`` (``LLM_API_KEY``) in ``json_mode``, charged
against the pipeline's token budget like every other model call.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence

from src.permissions.media_guard import require_allowed_write_path
from src.providers.llm import ChatResult, DeepSeekChatProvider

Chat = Callable[[Sequence[tuple[str, str]]], ChatResult]

COUNT = 5
_MAX_ATTEMPTS = 2
_DESCRIPTION_CHARS = 200

_SYSTEM_PROMPT = (
    "You are a news editor choosing which stories to feature for a general audience. "
    "Rank the given candidate stories by newsworthiness, importance and broad relevance. "
    "Prefer genuinely significant events over trivia, and avoid near-duplicate stories. "
    "Choose only candidate ids that appear in the list, using the exact id string."
)


class CurationError(RuntimeError):
    """Raised when the model's reply cannot be turned into a valid top-N selection."""


@dataclass(frozen=True)
class CurationResult:
    """The curated selection: full candidate dicts in rank order plus one reason each."""

    selected: tuple[dict, ...]
    reasons: tuple[str, ...]


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


def format_candidates(candidates: Sequence[Mapping[str, object]], count: int = COUNT) -> str:
    """Render the visible candidate pool as a compact prompt listing."""

    lines = [
        f"Select the {count} most important, relevant and impactful stories for a general audience.",
        'Reply with one JSON object: {"picks": [{"candidate_id": "...", "reason": "one short sentence"}, ...]} '
        f"with exactly {count} entries, every candidate_id copied verbatim from the list below.",
        "",
    ]
    for candidate in candidates:
        cid = str(candidate.get("candidate_id") or "?")
        publisher = str(candidate.get("publisher") or "?")
        published = str(candidate.get("published_at") or "")
        title = str(candidate.get("title") or "")
        description = str(candidate.get("description") or "").strip()
        if len(description) > _DESCRIPTION_CHARS:
            description = description[:_DESCRIPTION_CHARS].rstrip() + "..."
        lines.append(f"- {cid} | {publisher} | {published} | {title}")
        if description:
            lines.append(f"  {description}")
    return "\n".join(lines)


def _parse_picks(content: str) -> list[tuple[str, str]]:
    """Extract an ordered list of (candidate_id, reason) from the model reply."""

    data = _parse_reply(content)
    raw = data.get("picks")
    if not isinstance(raw, list):
        return []
    picks: list[tuple[str, str]] = []
    for entry in raw:
        if not isinstance(entry, Mapping):
            continue
        cid = str(entry.get("candidate_id") or "").strip()
        reason = str(entry.get("reason") or "").strip()
        if cid:
            picks.append((cid, reason))
    return picks


def _validate_picks(picks: Sequence[tuple[str, str]], by_id: Mapping[str, dict], count: int) -> None:
    """Reject selections that are not exactly ``count`` distinct known ids (fail-closed)."""

    ids = [cid for cid, _ in picks]
    if len(ids) != count:
        raise CurationError(f"Curation must return exactly {count} picks, got {len(ids)}")
    if len(set(ids)) != len(ids):
        raise CurationError("Curation returned duplicate candidate ids")
    unknown = [cid for cid in ids if cid not in by_id]
    if unknown:
        raise CurationError("Curation returned unknown candidate ids: " + ", ".join(unknown))


def _default_chat() -> Chat:
    provider = DeepSeekChatProvider()

    def chat(messages: Sequence[tuple[str, str]]) -> ChatResult:
        return provider.complete(messages, json_mode=True)

    return chat


def curate(
    candidates: Sequence[Mapping[str, object]],
    *,
    chat: Chat | None = None,
    count: int = COUNT,
    max_attempts: int = _MAX_ATTEMPTS,
) -> CurationResult:
    """Ask the LLM to rank the visible candidates and return the top ``count``.

    Hidden candidates are excluded before the call; every returned id is checked
    against the visible set so a malformed reply can never inject an unknown id.
    """

    visible = [dict(c) for c in candidates if not c.get("hidden_by_safety")]
    by_id = {str(c["candidate_id"]): c for c in visible}
    if len(visible) < count:
        raise CurationError(f"Only {len(visible)} visible candidates; need {count}")

    do_chat = chat or _default_chat()
    user_message = format_candidates(visible, count=count)

    last_error: Exception | None = None
    for _ in range(max_attempts):
        try:
            result = do_chat([("system", _SYSTEM_PROMPT), ("user", user_message)])
            picks = _parse_picks(result.content)
            _validate_picks(picks, by_id, count)
            return CurationResult(
                selected=tuple(by_id[cid] for cid, _ in picks),
                reasons=tuple(reason for _, reason in picks),
            )
        except Exception as exc:  # noqa: BLE001 - a provider failure is retried, then surfaced
            last_error = exc
    raise CurationError(f"Curation failed after {max_attempts} attempts: {last_error}") from last_error


def build_curation_document(
    result: CurationResult,
    generated_at: datetime | None = None,
) -> dict:
    """Wrap the curated selection in the curation.json document envelope."""

    selection: list[dict] = []
    for rank, (candidate, reason) in enumerate(zip(result.selected, result.reasons), start=1):
        selection.append({
            "rank": rank,
            "candidate_id": str(candidate["candidate_id"]),
            "title": str(candidate.get("title") or ""),
            "publisher": str(candidate.get("publisher") or ""),
            "reason": reason,
        })
    return {
        "schema_version": "1.0",
        "generated_at": (generated_at or datetime.now(timezone.utc)).isoformat(),
        "selection": selection,
    }


def save_curation_document(
    document: dict,
    *,
    workspace_root: Path,
    run_id: str,
) -> Path:
    """Write ``curation.json`` into the run folder."""

    path = require_allowed_write_path(
        workspace_root / "runs" / run_id / "curation.json", workspace_root=workspace_root
    )
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite existing curation file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return path


def run(
    candidates: Sequence[Mapping[str, object]],
    *,
    workspace_root: Path,
    run_id: str,
    chat: Chat | None = None,
    count: int = COUNT,
) -> dict:
    """Curate, save ``curation.json`` and return the document plus selected candidates."""

    result = curate(candidates, chat=chat, count=count)
    document = build_curation_document(result)
    save_curation_document(document, workspace_root=workspace_root, run_id=run_id)
    return {"document": document, "selected": list(result.selected)}
