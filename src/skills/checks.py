"""S7 checks: deterministic blocking checks that write ``checks.json`` (FR-006).

These are the code layer of the two-layer verification in FR-006. They run over
the four text artifacts (ledger, summaries, story, storyboard) and emit one
result per check with an owning stage, so a failure can be routed back to the
agent that owns it. Every check here is blocking. The checks are:

* each artifact validates against its JSON schema;
* the story maps six beats in order (FR-005) and beat 5 closes;
* the storyboard meets the FR-016 constraints (exactly one comic panel per beat,
  at most two cast characters per shot, narration at most two words per second,
  shot durations summing to 37-51 s);
* every summary sentence cites a known verified fact id (FR-004);
* no person name from the ledger appears in the story or the storyboard, by
  whole-word match on full names and surnames (FR-006).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

import jsonschema

from src.permissions.media_guard import require_allowed_write_path

DEFAULT_CAST = ("courier", "mayor", "pigeon")
BEAT_COUNT = 6
NARRATION_MAX_WORDS_PER_SECOND = 2.0
DURATION_MIN_S = 37.0
DURATION_MAX_S = 51.0

_SCHEMAS_DIR = Path(__file__).resolve().parents[2] / "schemas"


@dataclass(frozen=True)
class Check:
    """One deterministic check result, routable to its owning stage."""

    check_id: str
    passed: bool
    message: str
    owner: str
    path: str | None = None
    blocking: bool = True

    def as_dict(self) -> dict:
        result: dict = {
            "check_id": self.check_id,
            "passed": self.passed,
            "blocking": self.blocking,
            "message": self.message,
        }
        if self.path:
            result["path"] = self.path
        result["owner"] = self.owner
        return result


def _load_schema(name: str) -> dict:
    return json.loads((_SCHEMAS_DIR / name).read_text(encoding="utf-8"))


def _schema_errors(document: Mapping[str, object], schema_file: str) -> list[str]:
    schema = _load_schema(schema_file)
    errors: list[str] = []
    for error in jsonschema.Draft202012Validator(schema).iter_errors(document):
        path = "/".join(str(part) for part in error.absolute_path)
        errors.append(f"{path or '<root>'}: {error.message}")
    return errors


def _check_schema(check_id: str, owner: str, document: Mapping[str, object], schema_file: str, path: str) -> Check:
    errors = _schema_errors(document, schema_file)
    if errors:
        return Check(check_id, False, "; ".join(errors[:5]), owner, path)
    return Check(check_id, True, f"valid against {schema_file}", owner, path)


def check_beats(story: Mapping[str, object]) -> Check:
    beats = story.get("beats") or []
    if len(beats) != BEAT_COUNT:
        return Check("story-beats", False, f"expected {BEAT_COUNT} beats, got {len(beats)}", "story", "story.json")
    problems: list[str] = []
    for index, beat in enumerate(beats):
        if not isinstance(beat, Mapping):
            problems.append(f"beat {index} is not an object")
            continue
        if beat.get("beat_index") != index or beat.get("source_ref") != index:
            problems.append(f"beat {index} maps to {beat.get('beat_index')}/{beat.get('source_ref')}")
    if not beats or beats[-1].get("ending") is not True:
        problems.append("beat 5 is missing ending=true")
    if problems:
        return Check("story-beats", False, "; ".join(problems), "story", "story.json")
    return Check("story-beats", True, "six beats mapped in order and beat 5 closes", "story", "story.json")


def _shots(storyboard: Mapping[str, object]) -> list[Mapping[str, object]]:
    return [shot for shot in storyboard.get("shots") or [] if isinstance(shot, Mapping)]


def check_storyboard_panels(storyboard: Mapping[str, object]) -> Check:
    counts = {beat: 0 for beat in range(BEAT_COUNT)}
    for shot in _shots(storyboard):
        beat = shot.get("beat")
        if shot.get("comic_panel") and beat in counts:
            counts[beat] += 1
    bad = [f"beat {beat} has {count}" for beat, count in counts.items() if count != 1]
    if bad:
        return Check("storyboard-panels", False, "exactly one panel per beat required; " + ", ".join(bad), "storyboard", "storyboard.json")
    return Check("storyboard-panels", True, "exactly one comic panel per beat", "storyboard", "storyboard.json")


def check_storyboard_characters(
    storyboard: Mapping[str, object],
    cast: Sequence[str] = DEFAULT_CAST,
) -> Check:
    cast_set = set(cast)
    problems: list[str] = []
    for shot in _shots(storyboard):
        shot_id = shot.get("shot_id", "?")
        characters = [c for c in shot.get("characters") or []]
        if len(characters) > 2:
            problems.append(f"{shot_id} has {len(characters)} characters")
        for name in characters:
            if name not in cast_set:
                problems.append(f"{shot_id} uses non-cast character {name!r}")
    if problems:
        return Check("storyboard-characters", False, "; ".join(problems), "storyboard", "storyboard.json")
    return Check("storyboard-characters", True, "at most two cast characters per shot", "storyboard", "storyboard.json")


def check_storyboard_narration(storyboard: Mapping[str, object]) -> Check:
    problems: list[str] = []
    for shot in _shots(storyboard):
        shot_id = shot.get("shot_id", "?")
        words = len(str(shot.get("narration") or "").split())
        duration = shot.get("duration_s")
        if isinstance(duration, (int, float)) and duration > 0 and words / duration > NARRATION_MAX_WORDS_PER_SECOND:
            problems.append(f"{shot_id} narration {words} words over {duration}s")
    if problems:
        return Check("storyboard-narration", False, "narration above 2 words/second; " + "; ".join(problems), "storyboard", "storyboard.json")
    return Check("storyboard-narration", True, "narration at most 2 words per second", "storyboard", "storyboard.json")


def check_storyboard_duration(storyboard: Mapping[str, object]) -> Check:
    total = sum(float(shot.get("duration_s") or 0) for shot in _shots(storyboard))
    if not DURATION_MIN_S <= total <= DURATION_MAX_S:
        return Check(
            "storyboard-duration",
            False,
            f"shot durations sum to {total}s, must be {DURATION_MIN_S}-{DURATION_MAX_S}s",
            "storyboard",
            "storyboard.json",
        )
    return Check("storyboard-duration", True, f"shot durations sum to {total}s (37-51s)", "storyboard", "storyboard.json")


def check_citations(ledger: Mapping[str, object], summaries: Mapping[str, object]) -> Check:
    valid_ids: dict[str, set[str]] = {}
    for story in ledger.get("stories") or []:
        valid_ids[str(story["story_id"])] = {
            str(fact["fact_id"]) for fact in story.get("facts") or [] if isinstance(fact, Mapping)
        }

    problems: list[str] = []
    for summary in summaries.get("summaries") or []:
        story_id = str(summary.get("story_id") or "")
        sentences = summary.get("sentences") or []
        if len(sentences) != 2:
            problems.append(f"{story_id} has {len(sentences)} sentences (needs 2)")
        valid = valid_ids.get(story_id, set())
        for index, sentence in enumerate(sentences):
            ids = sentence.get("ledger_fact_ids") or []
            if not ids:
                problems.append(f"{story_id} sentence {index} is uncited")
                continue
            unknown = [fid for fid in ids if fid not in valid]
            if unknown:
                problems.append(f"{story_id} sentence {index} cites unknown ids {unknown}")
    if problems:
        return Check("citations", False, "; ".join(problems), "summary", "summaries.json")
    return Check("citations", True, "every summary sentence cites known fact ids", "summary", "summaries.json")


def ledger_names(ledger: Mapping[str, object]) -> set[str]:
    names: set[str] = set()
    for story in ledger.get("stories") or []:
        for name in story.get("people") or []:
            name = str(name).strip()
            if name:
                names.add(name)
    return names


def _name_patterns(name: str) -> list[str]:
    tokens = [token for token in name.lower().split() if token]
    patterns: list[str] = []
    if len(tokens) >= 2:
        patterns.append(r"\b" + r"\s+".join(re.escape(token) for token in tokens) + r"\b")
    surname = tokens[-1] if tokens else ""
    if len(surname) >= 2:
        patterns.append(r"\b" + re.escape(surname) + r"\b")
    return patterns


def _contains_any_name(text: str, names: set[str]) -> list[str]:
    lowered = text.lower()
    found: list[str] = []
    for name in sorted(names):
        if any(re.search(pattern, lowered) for pattern in _name_patterns(name)):
            found.append(name)
    return found


def _story_text(story: Mapping[str, object]) -> str:
    parts = [str(story.get("title") or "")]
    for beat in story.get("beats") or []:
        if isinstance(beat, Mapping):
            parts.append(str(beat.get("text") or ""))
    return "\n".join(parts)


def _storyboard_text(storyboard: Mapping[str, object]) -> str:
    parts: list[str] = []
    for shot in _shots(storyboard):
        for field in ("narration", "dialogue", "comic_caption", "action", "camera"):
            value = str(shot.get(field) or "").strip()
            if value:
                parts.append(value)
    return "\n".join(parts)


def _check_names(check_id: str, owner: str, path: str, text: str, names: set[str]) -> Check:
    found = _contains_any_name(text, names)
    if found:
        return Check(check_id, False, f"ledger person name(s) found: {', '.join(found)}", owner, path)
    return Check(check_id, True, "no ledger person name found", owner, path)


def run_checks(
    ledger: Mapping[str, object],
    summaries: Mapping[str, object],
    story: Mapping[str, object],
    storyboard: Mapping[str, object],
    cast: Sequence[str] = DEFAULT_CAST,
) -> list[Check]:
    """Run every deterministic FR-006 code check and return the results."""

    names = ledger_names(ledger)
    return [
        _check_schema("schema-ledger", "ledger", ledger, "ledger.schema.json", "ledger.json"),
        _check_schema("schema-summaries", "summary", summaries, "summaries.schema.json", "summaries.json"),
        _check_schema("schema-story", "story", story, "story.schema.json", "story.json"),
        _check_schema("schema-storyboard", "storyboard", storyboard, "storyboard.schema.json", "storyboard.json"),
        check_beats(story),
        check_storyboard_panels(storyboard),
        check_storyboard_characters(storyboard, cast=cast),
        check_storyboard_narration(storyboard),
        check_storyboard_duration(storyboard),
        check_citations(ledger, summaries),
        _check_names("names-story", "story", "story.json", _story_text(story), names),
        _check_names("names-storyboard", "storyboard", "storyboard.json", _storyboard_text(storyboard), names),
    ]


def build_checks_document(checks: Sequence[Check]) -> dict:
    """Wrap check results in the schema's checks document envelope."""

    return {
        "schema_version": "1.0",
        "passed": all(check.passed for check in checks),
        "checks": [check.as_dict() for check in checks],
    }


def save_checks(document: Mapping[str, object], *, workspace_root: Path, run_id: str) -> Path:
    """Write ``checks.json`` into the run folder."""

    path = require_allowed_write_path(
        workspace_root / "runs" / run_id / "checks.json", workspace_root=workspace_root
    )
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite existing checks: {path}")
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
    cast: Sequence[str] = DEFAULT_CAST,
) -> dict:
    """Run the checks, save ``checks.json``, and return document plus overall pass."""

    checks = run_checks(ledger, summaries, story, storyboard, cast=cast)
    document = build_checks_document(checks)
    save_checks(document, workspace_root=workspace_root, run_id=run_id)
    return {"document": document, "passed": document["passed"]}
