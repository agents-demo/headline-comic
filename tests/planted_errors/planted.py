"""Planted-error set for measuring the verification catch rate (T019, SC-4).

Ten errors are seeded on top of the T006 fixture run. Each :class:`PlantedError`
is a pure mutation of the base artifacts (ledger, summaries, story, storyboard)
plus the check id that must fail for the error to count as caught. Six errors
are code-checkable — the deterministic T015 checks catch them — and four are
Verifier-only — only the T016 independent review catches them.

The base artifacts are the T006 fixture (``tests/fixtures/t006-sample``) plus a
deterministic two-sentence-per-story summaries document built from the ledger's
verified facts, because the fixture predates the T012 summariser and so has no
``summaries.json`` yet. Every mutation deep-copies, so the base is never
modified and the ten errors are independent of one another.

Error list (matches the examples in ``tasks.md`` T019):

    code layer       uncited_sentence, real_person_name_in_story, swapped_name,
                     narration_over_word_cap, missing_beat, shot_three_characters
    Verifier layer   fabricated_number, implied_causation, graphic_detail,
                     satire_private_individual
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "t006-sample"

# (story_id, sentence 0, fact ids 0, sentence 1, fact ids 1). Sentences stay
# strictly grounded in the ledger's verified fact claims so the base passes the
# Verifier's summaries-vs-ledger item and each planted error is attributable to
# its mutation alone.
_SUMMARY_ROWS = (
    ("story-1",
     "A volunteer group installed three solar lamps along the harbor path.", ["f1-1"],
     "The lamps were installed along the harbor path.", ["f1-2"]),
    ("story-2",
     "The public library posted a printed walking map.", ["f2-1"],
     "The library posted the map on its notice board.", ["f2-1"]),
    ("story-3",
     "Market vendors put up a blue canopy for Saturday's stalls.", ["f3-1"],
     "The blue canopy shades the outdoor stalls.", ["f3-1"]),
    ("story-4",
     "A neighborhood garden shared packets of native flower seeds.", ["f4-1"],
     "Visitors could take one seed packet while supplies lasted.", ["f4-1"]),
    ("story-5",
     "A repair shop reopened its clock workshop.", ["f5-1"],
     "The reopened workshop will host a free demonstration.", ["f5-1"]),
)

BASE_SUMMARIES: dict = {
    "schema_version": "1.0",
    "summaries": [
        {
            "story_id": story_id,
            "sentences": [
                {"text": text0, "ledger_fact_ids": list(ids0)},
                {"text": text1, "ledger_fact_ids": list(ids1)},
            ],
        }
        for story_id, text0, ids0, text1, ids1 in _SUMMARY_ROWS
    ],
}

# An artifacts bundle: one mapping per text artifact, keyed by artifact name.
Artifacts = dict[str, Mapping[str, object]]
Apply = Callable[[Artifacts], Artifacts]


@dataclass(frozen=True)
class PlantedError:
    """One seeded error plus the check id that proves the system caught it."""

    error_id: str
    description: str
    layer: str  # "checks" (deterministic) or "verifier" (T016 review)
    check_ids: tuple[str, ...]
    apply: Apply


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_base() -> Artifacts:
    """Return deep copies of the base artifacts (never shared between callers)."""

    return {
        "ledger": _load(FIXTURE_DIR / "ledger.json"),
        "summaries": copy.deepcopy(BASE_SUMMARIES),
        "story": _load(FIXTURE_DIR / "story.json"),
        "storyboard": _load(FIXTURE_DIR / "storyboard.json"),
    }


def _mutate(
    base: Artifacts,
    *,
    ledger: Mapping[str, object] | None = None,
    summaries: Mapping[str, object] | None = None,
    story: Mapping[str, object] | None = None,
    storyboard: Mapping[str, object] | None = None,
) -> Artifacts:
    """Return a bundle that deep-copies every artifact except the mutated ones."""

    return {
        "ledger": ledger if ledger is not None else copy.deepcopy(base["ledger"]),
        "summaries": summaries if summaries is not None else copy.deepcopy(base["summaries"]),
        "story": story if story is not None else copy.deepcopy(base["story"]),
        "storyboard": storyboard if storyboard is not None else copy.deepcopy(base["storyboard"]),
    }


# ---- code-layer mutations (caught by the deterministic T015 checks) ----

def _uncited_sentence(base: Artifacts) -> Artifacts:
    summaries = copy.deepcopy(base["summaries"])
    summaries["summaries"][0]["sentences"][0]["ledger_fact_ids"] = []
    return _mutate(base, summaries=summaries)


def _real_person_name(base: Artifacts) -> Artifacts:
    ledger = copy.deepcopy(base["ledger"])
    story = copy.deepcopy(base["story"])
    ledger["stories"][0]["people"] = ["Maya Chen"]
    story["beats"][0]["text"] = "A courier and Maya Chen invite neighbors to a lantern walk."
    return _mutate(base, ledger=ledger, story=story)


def _swapped_name(base: Artifacts) -> Artifacts:
    ledger = copy.deepcopy(base["ledger"])
    storyboard = copy.deepcopy(base["storyboard"])
    ledger["stories"][1]["people"] = ["Jordan Lee"]
    storyboard["shots"][0]["narration"] = "Jordan Lee invites the neighbors to the walk."
    return _mutate(base, ledger=ledger, storyboard=storyboard)


def _narration_over_cap(base: Artifacts) -> Artifacts:
    storyboard = copy.deepcopy(base["storyboard"])
    storyboard["shots"][0]["narration"] = (
        "The courier walks the harbor path and points out each of the newly installed lamps "
        "while the neighbors follow along and the pigeon flutters ahead toward the water."
    )
    return _mutate(base, storyboard=storyboard)


def _missing_beat(base: Artifacts) -> Artifacts:
    story = copy.deepcopy(base["story"])
    story["beats"] = story["beats"][:-1]
    return _mutate(base, story=story)


def _shot_three_characters(base: Artifacts) -> Artifacts:
    storyboard = copy.deepcopy(base["storyboard"])
    storyboard["shots"][0]["characters"] = ["courier", "mayor", "pigeon"]
    return _mutate(base, storyboard=storyboard)


# ---- Verifier-layer mutations (caught only by the T016 independent review) ----

def _fabricated_number(base: Artifacts) -> Artifacts:
    summaries = copy.deepcopy(base["summaries"])
    summaries["summaries"][0]["sentences"][0]["text"] = (
        "Volunteers installed forty solar lamps along the harbor path."
    )
    return _mutate(base, summaries=summaries)


def _implied_causation(base: Artifacts) -> Artifacts:
    story = copy.deepcopy(base["story"])
    story["beats"][1]["text"] = (
        "Because the harbor lamps were installed, the library had to redraw its walking map."
    )
    return _mutate(base, story=story)


def _graphic_detail(base: Artifacts) -> Artifacts:
    story = copy.deepcopy(base["story"])
    story["beats"][3]["text"] = (
        "A bloody brawl erupts under the market canopy, and a body is left on the cobblestones."
    )
    return _mutate(base, story=story)


def _satire_private_individual(base: Artifacts) -> Artifacts:
    story = copy.deepcopy(base["story"])
    story["beats"][4]["text"] = (
        "The walkers mock old Mr. Harper, the seed hoarder, for keeping every packet to himself."
    )
    return _mutate(base, story=story)


ERRORS: tuple[PlantedError, ...] = (
    PlantedError(
        "uncited_sentence",
        "A summary sentence carries no ledger fact ids.",
        "checks",
        ("citations",),
        _uncited_sentence,
    ),
    PlantedError(
        "real_person_name_in_story",
        "A real person's name appears in the fictional story text.",
        "checks",
        ("names-story",),
        _real_person_name,
    ),
    PlantedError(
        "swapped_name",
        "A real person's name is swapped into the storyboard narration.",
        "checks",
        ("names-storyboard",),
        _swapped_name,
    ),
    PlantedError(
        "narration_over_word_cap",
        "A shot's narration exceeds two words per second.",
        "checks",
        ("storyboard-narration",),
        _narration_over_cap,
    ),
    PlantedError(
        "missing_beat",
        "The story is missing its closing beat (only five beats).",
        "checks",
        ("story-beats",),
        _missing_beat,
    ),
    PlantedError(
        "shot_three_characters",
        "One shot lists three cast characters.",
        "checks",
        ("storyboard-characters",),
        _shot_three_characters,
    ),
    PlantedError(
        "fabricated_number",
        "A summary invents a number the ledger does not support.",
        "verifier",
        ("verify-summaries",),
        _fabricated_number,
    ),
    PlantedError(
        "implied_causation",
        "The story states one real event caused another.",
        "verifier",
        ("verify-causation",),
        _implied_causation,
    ),
    PlantedError(
        "graphic_detail",
        "The story includes graphic violence.",
        "verifier",
        ("verify-graphic",),
        _graphic_detail,
    ),
    PlantedError(
        "satire_private_individual",
        "The story mocks a named private individual.",
        "verifier",
        ("verify-satire",),
        _satire_private_individual,
    ),
)
