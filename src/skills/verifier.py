"""S8 Verifier: independent pass/fail review on a different model (FR-006).

The Verifier is a second opinion on the text half. It runs on a different model
from the Writer and Director (DeepSeek ``deepseek-reasoner`` by default, versus
``deepseek-chat`` for the generators) and sees only the ledger, summaries, story
and storyboard — never the other agents' reasoning. It judges five items and
returns pass/fail plus a reason for each:

* summaries are consistent with the ledger facts;
* the story does not state or imply causation between the real events;
* no real person is recognisable through description;
* no graphic content;
* the satire targets a situation, not a private individual.

Code fixes the five check ids and their owning stages; the model proposes the
pass/fail verdict and the reason text, and code coerce the booleans fail-closed
when an item is missing. The output is a checks-envelope document written as
``verifier.json`` (valid against the checks schema, with ``owner`` ``verifier``
items). Routing failures back to the owning agent and the two-loop limit live in
the T017/T018 wiring, not here.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable, Mapping, Sequence

from src.env import load_env
from src.permissions.media_guard import require_allowed_write_path
from src.providers.llm import ChatResult, DeepSeekChatProvider

Chat = Callable[[Sequence[tuple[str, str]]], ChatResult]

VERIFIER_MODEL = "deepseek-reasoner"
_PROJECT_ROOT = Path(__file__).resolve().parents[2]

# (check_id, owning stage, what the verifier must judge)
_ITEMS: tuple[tuple[str, str, str], ...] = (
    ("verify-summaries", "summary", "each summary is consistent with the ledger facts"),
    ("verify-causation", "story", "the story does not state or imply causation between the real events"),
    ("verify-real-people", "story", "no real person is recognisable through description"),
    ("verify-graphic", "story", "no graphic or violent content"),
    ("verify-satire", "story", "satire targets a situation, not a private individual"),
)

_SYSTEM_PROMPT = (
    "You are the Verifier for a family-friendly fictional news comic. You independently review a "
    "story and storyboard written by other agents. You see only the verified ledger facts, the "
    "summaries, the story and the storyboard. Judge these five items strictly and reply with one "
    'JSON object: {"items": [{"check_id": "...", "passed": true, "reason": "..."}]} with exactly '
    "these five check ids: verify-summaries, verify-causation, verify-real-people, verify-graphic, "
    "verify-satire. If anything is wrong or doubtful, set passed=false and explain briefly. "
    "Reply with the JSON object only; keep each reason to one short sentence."
)


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


def _coerce_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "1", "pass", "passed")
    return bool(value)


def _format_facts(ledger: Mapping[str, object]) -> str:
    lines: list[str] = ["## Ledger facts"]
    for story in ledger.get("stories") or []:
        if not isinstance(story, Mapping):
            continue
        lines.append(f"Story {story.get('story_id')}:")
        for fact in story.get("facts") or []:
            if isinstance(fact, Mapping):
                lines.append(f"- ({fact.get('kind')}) {fact.get('claim')}")
        people = story.get("people") or []
        if people:
            lines.append(f"People mentioned: {', '.join(str(p) for p in people)}")
    return "\n".join(lines)


def _format_summaries(summaries: Mapping[str, object]) -> str:
    lines = ["## Summaries"]
    for summary in summaries.get("summaries") or []:
        if not isinstance(summary, Mapping):
            continue
        lines.append(f"Story {summary.get('story_id')}:")
        for sentence in summary.get("sentences") or []:
            if isinstance(sentence, Mapping):
                lines.append(f"- {sentence.get('text')}")
    return "\n".join(lines)


def _format_story(story: Mapping[str, object]) -> str:
    lines = [f"## Story: {story.get('title')}"]
    for beat in story.get("beats") or []:
        if isinstance(beat, Mapping):
            lines.append(f"Beat {beat.get('beat_index')}: {beat.get('text')}")
    return "\n".join(lines)


def _format_storyboard(storyboard: Mapping[str, object]) -> str:
    lines = ["## Storyboard"]
    for shot in storyboard.get("shots") or []:
        if not isinstance(shot, Mapping):
            continue
        parts = [f"{shot.get('shot_id')} (beat {shot.get('beat')}):"]
        for field in ("narration", "dialogue", "comic_caption", "action", "gag", "scene_setting", "audio_cue"):
            value = str(shot.get(field) or "").strip()
            if value:
                parts.append(f"- {field}: {value}")
        lines.extend(parts)
    return "\n".join(lines)


def _format_input(
    ledger: Mapping[str, object],
    summaries: Mapping[str, object],
    story: Mapping[str, object],
    storyboard: Mapping[str, object],
) -> str:
    return "\n\n".join([
        _format_facts(ledger),
        _format_summaries(summaries),
        _format_story(story),
        _format_storyboard(storyboard),
    ])


def _verdicts_from(raw: Mapping[str, object]) -> list[dict]:
    """Map the model's items onto the five fixed check ids, fail-closed when absent."""

    reported: dict[str, tuple[bool, str]] = {}
    items = raw.get("items")
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, Mapping):
                continue
            check_id = str(item.get("check_id") or "").strip()
            if not check_id:
                continue
            passed = _coerce_bool(item.get("passed"))
            reason = str(item.get("reason") or "").strip()
            reported[check_id] = (passed, reason)

    verdicts: list[dict] = []
    for check_id, owner, description in _ITEMS:
        passed, reason = reported.get(check_id, (False, "verifier did not report this item"))
        verdicts.append({"check_id": check_id, "owner": owner, "passed": passed, "reason": reason})
    return verdicts


def build_verifier_document(verdicts: Sequence[Mapping[str, object]]) -> dict:
    """Wrap verdicts in the checks-envelope document shape."""

    checks = [
        {
            "check_id": str(verdict["check_id"]),
            "passed": bool(verdict["passed"]),
            "blocking": True,
            "message": str(verdict["reason"]),
            "owner": str(verdict["owner"]),
        }
        for verdict in verdicts
    ]
    return {
        "schema_version": "1.0",
        "passed": all(check["passed"] for check in checks),
        "checks": checks,
    }


def _verifier_model() -> str:
    load_env(_PROJECT_ROOT / ".env")
    return os.environ.get("LLM_VERIFIER_MODEL") or VERIFIER_MODEL


def _default_chat() -> Chat:
    provider = DeepSeekChatProvider(model=_verifier_model())

    def chat(messages: Sequence[tuple[str, str]]) -> ChatResult:
        return provider.complete(messages, json_mode=False, temperature=None)

    return chat


def save_verifier(document: Mapping[str, object], *, workspace_root: Path, run_id: str) -> Path:
    """Write ``verifier.json`` into the run folder."""

    path = require_allowed_write_path(
        workspace_root / "runs" / run_id / "verifier.json", workspace_root=workspace_root
    )
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite existing verifier: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return path


def run(
    ledger: Mapping[str, object],
    summaries: Mapping[str, object],
    story: Mapping[str, object],
    storyboard: Mapping[str, object],
    *,
    workspace_root: Path,
    run_id: str,
    chat: Chat | None = None,
) -> dict:
    """Verify, structure, save and return the verifier document plus overall pass."""

    do_chat = chat or _default_chat()
    result = do_chat([
        ("system", _SYSTEM_PROMPT),
        ("user", _format_input(ledger, summaries, story, storyboard)),
    ])
    verdicts = _verdicts_from(_parse_reply(result.content))
    document = build_verifier_document(verdicts)
    save_verifier(document, workspace_root=workspace_root, run_id=run_id)
    return {"document": document, "passed": document["passed"]}
