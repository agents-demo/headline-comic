"""S5 Writer: one six-beat fictional story from the five summaries (FR-005).

The Writer makes a single LLM call that turns the five neutral summaries into
one fictional story set in the little town with the fixed cast. The model
proposes a title and six beat texts only; code injects the deterministic
structure (schema version, fiction label, characters, ``beat_index``,
``source_ref`` and the closing ``ending`` flag) and validates the result
against the story schema. Beat 0 is an intro with no source; beats 1-5 map to
sources 1-5 in order and beat 5 closes the story. The prompt forbids real
names and forbids implying that one real-world story caused another.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Mapping, Sequence

import jsonschema

from src.permissions.media_guard import require_allowed_write_path
from src.providers.llm import ChatResult, DeepSeekChatProvider

Chat = Callable[[Sequence[tuple[str, str]]], ChatResult]

FICTION_LABEL = "Fiction inspired by today's news"
DEFAULT_CAST = ("courier", "mayor", "pigeon")
BEAT_COUNT = 6

_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "story.schema.json"

_SYSTEM_PROMPT = (
    "You are the Writer for a family-friendly comic. Turn five neutral news summaries into one "
    "short fictional story set in a little town, told through its three recurring characters: "
    "courier, mayor, and pigeon. Use only these characters and the little town; do not add real "
    "people, and never use a real person's full name or surname. Write fiction, not reporting: "
    "do not imply that one real news event caused another. Beat 0 introduces the town and the "
    "situation with no news source. Beats 1 through 5 are inspired, in order, by sources 1 "
    "through 5, and beat 5 closes the story warmly. "
    'Reply with one JSON object: {"title": "...", "beats": [{"text": "..."}, {"text": "..."}, '
    '{"text": "..."}, {"text": "..."}, {"text": "..."}, {"text": "..."}]}. '
    "Exactly six beats. Keep each beat to one or two sentences and suitable for all ages."
)


class StoryError(RuntimeError):
    """Raised when the model's reply cannot be turned into a schema-valid story."""


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


def _format_summaries(summaries: Sequence[Mapping[str, object]]) -> str:
    lines = ["Here are the five neutral news summaries, in order."]
    for number, summary in enumerate(summaries, start=1):
        lines.append(f"Source {number}:")
        for sentence in summary.get("sentences") or []:
            text = sentence.get("text") if isinstance(sentence, Mapping) else None
            if text:
                lines.append(f"- {text}")
    return "\n".join(lines)


def _write_story(summaries: Sequence[Mapping[str, object]], chat: Chat) -> Mapping[str, object]:
    result = chat([("system", _SYSTEM_PROMPT), ("user", _format_summaries(summaries))])
    return _parse_reply(result.content)


def build_story(
    raw: Mapping[str, object],
    characters: Sequence[str] = DEFAULT_CAST,
) -> dict:
    """Turn the model's title + six beat texts into a schema-shaped story document."""

    title = str(raw.get("title") or "").strip()
    if not title:
        raise StoryError("Writer returned no story title")

    raw_beats = raw.get("beats")
    if not isinstance(raw_beats, list) or len(raw_beats) != BEAT_COUNT:
        count = len(raw_beats) if isinstance(raw_beats, list) else "none"
        raise StoryError(f"Writer must return exactly {BEAT_COUNT} beats, got {count}")

    texts: list[str] = []
    for beat in raw_beats:
        if not isinstance(beat, Mapping):
            raise StoryError("Each beat must be an object with a text field")
        text = str(beat.get("text") or "").strip()
        if not text:
            raise StoryError("Each beat needs non-empty text")
        texts.append(text)

    beats: list[dict] = []
    for index, text in enumerate(texts):
        beat: dict = {"beat_index": index, "source_ref": index, "text": text}
        if index == BEAT_COUNT - 1:
            beat["ending"] = True
        beats.append(beat)

    return {
        "schema_version": "1.0",
        "title": title,
        "fiction_label": FICTION_LABEL,
        "characters": list(characters),
        "beats": beats,
    }


def validate_story(story: Mapping[str, object]) -> list[str]:
    """Validate a story document against the story schema; return human errors."""

    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    errors: list[str] = []
    for error in jsonschema.Draft202012Validator(schema).iter_errors(story):
        path = "/".join(str(part) for part in error.absolute_path)
        errors.append(f"{path or '<root>'}: {error.message}")
    return errors


def _default_chat() -> Chat:
    provider = DeepSeekChatProvider()

    def chat(messages: Sequence[tuple[str, str]]) -> ChatResult:
        return provider.complete(messages, json_mode=True)

    return chat


def save_story(story: Mapping[str, object], *, workspace_root: Path, run_id: str) -> Path:
    """Write ``story.json`` into the run folder."""

    path = require_allowed_write_path(
        workspace_root / "runs" / run_id / "story.json", workspace_root=workspace_root
    )
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite existing story: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(story, indent=2) + "\n", encoding="utf-8")
    return path


def run(
    summaries: Sequence[Mapping[str, object]],
    *,
    workspace_root: Path,
    run_id: str,
    chat: Chat | None = None,
    characters: Sequence[str] = DEFAULT_CAST,
) -> dict:
    """Write, structure, validate and save the story; return document plus errors."""

    raw = _write_story(summaries, chat or _default_chat())
    story = build_story(raw, characters=characters)
    errors = validate_story(story)
    save_story(story, workspace_root=workspace_root, run_id=run_id)
    return {"document": story, "errors": errors}
