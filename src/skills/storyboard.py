"""S6 Director: an 8-10 shot storyboard from the six-beat story (FR-016).

The Director makes a single LLM call that turns the six story beats into a
storyboard of 8 to 10 shots. The model proposes the creative content of each
shot (beat, characters, camera, action, narration, dialogue, comic caption,
duration and panel flag); code injects the deterministic structure — ``shot_id``
and ``source_ref`` (always equal to ``beat``) — clamps each duration into the
4-8 second range, keeps at most two cast characters, forces exactly one comic
panel per beat and validates the result against the storyboard schema. The
aggregate narration word-rate and 37-51 second duration-sum rules are enforced
by the T015 checks skill, not here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Mapping, Sequence

import jsonschema

from src.permissions.media_guard import require_allowed_write_path
from src.providers.llm import ChatResult, DeepSeekChatProvider

Chat = Callable[[Sequence[tuple[str, str]]], ChatResult]

DEFAULT_CAST = ("courier", "mayor", "pigeon")
MIN_SHOTS = 8
MAX_SHOTS = 10
MIN_DURATION_S = 4.0
MAX_DURATION_S = 8.0

_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "storyboard.schema.json"

_SYSTEM_PROMPT = (
    "You are the Director for a family-friendly comic and short video. Turn the six story beats "
    "into a storyboard of 8 to 10 shots. Use only the fixed cast (courier, mayor, pigeon) and at "
    "most two characters per shot. For each shot give: beat (0-5), characters, camera, action, "
    "narration, optional dialogue, optional comic_caption, duration_s (4 to 8), and comic_panel "
    "(true or false). Exactly one shot per beat 0-5 must be a comic panel. Beat 0 is the intro. "
    "Keep narration to at most two words per second of its shot, and make the shot durations sum "
    "to between 37 and 51 seconds. Do not use real names. "
    'Reply with one JSON object: {"shots": [{"beat": 0, "characters": ["courier"], "camera": "...", '
    '"action": "...", "narration": "...", "dialogue": "...", "comic_caption": "...", '
    '"duration_s": 5, "comic_panel": true}, ...]}.'
)


class StoryboardError(RuntimeError):
    """Raised when the model's reply cannot be turned into a schema-valid storyboard."""


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


def _format_story(story: Mapping[str, object]) -> str:
    lines = ["Here are the six story beats, in order."]
    for beat in story.get("beats") or []:
        if not isinstance(beat, Mapping):
            continue
        lines.append(f"Beat {beat.get('beat_index')}: {beat.get('text')}")
    return "\n".join(lines)


def _coerce_duration(value: object) -> float:
    try:
        duration = float(value)
    except (TypeError, ValueError):
        duration = 5.0
    duration = max(MIN_DURATION_S, min(MAX_DURATION_S, duration))
    return round(duration, 1)


def _normalize_characters(value: object, cast: Sequence[str]) -> list[str]:
    cast_set = set(cast)
    result: list[str] = []
    for item in value or []:
        name = str(item).strip()
        if name in cast_set and name not in result:
            result.append(name)
        if len(result) == 2:
            break
    if not result:
        result = [cast[0]]
    return result


def _normalize_shot(raw: object, cast: Sequence[str]) -> dict:
    if not isinstance(raw, Mapping):
        raise StoryboardError("each shot must be an object")
    beat = raw.get("beat")
    if isinstance(beat, bool) or not isinstance(beat, int) or not 0 <= beat <= 5:
        raise StoryboardError(f"shot has invalid beat: {beat!r}")
    camera = str(raw.get("camera") or "").strip()
    action = str(raw.get("action") or "").strip()
    if not camera or not action:
        raise StoryboardError("each shot needs a camera and an action")

    shot: dict = {
        "beat": beat,
        "characters": _normalize_characters(raw.get("characters"), cast),
        "camera": camera,
        "action": action,
        "narration": str(raw.get("narration") or "").strip(),
        "duration_s": _coerce_duration(raw.get("duration_s")),
        "comic_panel": bool(raw.get("comic_panel")),
    }
    dialogue = str(raw.get("dialogue") or "").strip()
    if dialogue:
        shot["dialogue"] = dialogue
    caption = str(raw.get("comic_caption") or "").strip()
    if caption:
        shot["comic_caption"] = caption
    return shot


def build_storyboard(
    raw: Mapping[str, object],
    cast: Sequence[str] = DEFAULT_CAST,
) -> dict:
    """Turn the model's shot list into a schema-shaped storyboard document."""

    cast_list = list(cast)
    raw_shots = raw.get("shots")
    if not isinstance(raw_shots, list):
        raise StoryboardError("Director must return a shots list")
    if not MIN_SHOTS <= len(raw_shots) <= MAX_SHOTS:
        raise StoryboardError(
            f"Director must return {MIN_SHOTS}-{MAX_SHOTS} shots, got {len(raw_shots)}"
        )

    shots = [_normalize_shot(shot, cast_list) for shot in raw_shots]

    missing = [beat for beat in range(6) if not any(s["beat"] == beat for s in shots)]
    if missing:
        raise StoryboardError(f"no shot covers beat(s) {missing}")

    # Exactly one comic panel per beat: prefer the first shot the model marked,
    # otherwise fall back to the first shot of that beat.
    panel_index: dict[int, int] = {}
    for index, shot in enumerate(shots):
        if shot["beat"] not in panel_index and shot["comic_panel"]:
            panel_index[shot["beat"]] = index
    for index, shot in enumerate(shots):
        panel_index.setdefault(shot["beat"], index)

    final_shots: list[dict] = []
    for index, shot in enumerate(shots):
        beat = shot["beat"]
        is_panel = panel_index[beat] == index
        final: dict = {
            "shot_id": f"shot-{index + 1:02d}",
            "beat": beat,
            "source_ref": beat,
            "characters": shot["characters"],
            "camera": shot["camera"],
            "action": shot["action"],
            "narration": shot["narration"],
            "duration_s": shot["duration_s"],
            "comic_panel": is_panel,
        }
        if shot.get("dialogue"):
            final["dialogue"] = shot["dialogue"]
        if is_panel:
            final["comic_caption"] = shot.get("comic_caption") or shot["narration"]
        final_shots.append(final)

    return {"schema_version": "1.0", "shots": final_shots}


def validate_storyboard(storyboard: Mapping[str, object]) -> list[str]:
    """Validate a storyboard document against the storyboard schema."""

    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    errors: list[str] = []
    for error in jsonschema.Draft202012Validator(schema).iter_errors(storyboard):
        path = "/".join(str(part) for part in error.absolute_path)
        errors.append(f"{path or '<root>'}: {error.message}")
    return errors


def _default_chat() -> Chat:
    provider = DeepSeekChatProvider()

    def chat(messages: Sequence[tuple[str, str]]) -> ChatResult:
        return provider.complete(messages, json_mode=True)

    return chat


def save_storyboard(
    storyboard: Mapping[str, object],
    *,
    workspace_root: Path,
    run_id: str,
) -> Path:
    """Write ``storyboard.json`` into the run folder."""

    path = require_allowed_write_path(
        workspace_root / "runs" / run_id / "storyboard.json", workspace_root=workspace_root
    )
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite existing storyboard: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(storyboard, indent=2) + "\n", encoding="utf-8")
    return path


def run(
    story: Mapping[str, object],
    *,
    workspace_root: Path,
    run_id: str,
    chat: Chat | None = None,
    cast: Sequence[str] = DEFAULT_CAST,
) -> dict:
    """Direct, structure, validate and save the storyboard; return document plus errors."""

    result = (chat or _default_chat())([("system", _SYSTEM_PROMPT), ("user", _format_story(story))])
    storyboard = build_storyboard(_parse_reply(result.content), cast=cast)
    errors = validate_storyboard(storyboard)
    save_storyboard(storyboard, workspace_root=workspace_root, run_id=run_id)
    return {"document": storyboard, "errors": errors}
