"""S1 safety filter: deterministic candidate tagging and default-list logic (FR-015).

Tags each candidate story with the schema's five safety categories by matching a
curated keyword lexicon against its headline (title) only. Matching the feed
description instead proved noisy in a live check — descriptions bundle background
and aggregate text (e.g. an NPR blurb summarizing several stories). A story with
any tag is hidden from the default list, which shows the top 15 untagged stories;
the UI gets the hidden count and a fewer-than-8 message. No model is called.

This is a deterministic heuristic, not a factual review. It favours precision
(not hiding benign stories) over recall; the T016 Verifier and the human approval
stage remain the real accuracy gates. The lexicon is intentionally easy to extend
as T019/T020 planted-error runs reveal gaps.
"""

from __future__ import annotations

import re
from typing import Mapping, Sequence

SAFETY_TAGS = (
    "violence",
    "death",
    "disaster_casualties",
    "crime_against_individual",
    "minors",
)

DEFAULT_LIST_LIMIT = 15
FEWER_THAN = 8

# Keyword lexicon per tag. Single words match on whole-word boundaries; phrases
# containing a space match as substrings. Both are matched case-insensitively.
_LEXICON: dict[str, frozenset[str]] = {
    "violence": frozenset({
        "shoot", "shoots", "shooting", "shooter", "shooters", "shot",
        "gun", "guns", "gunman", "gunmen", "gunfire", "armed", "firearm", "firearms",
        "stab", "stabs", "stabbed", "stabbing", "stabbings",
        "attack", "attacks", "attacked", "attacker", "attackers",
        "assault", "assaults", "assaulted",
        "bomb", "bombs", "bombing", "bombed", "blast", "blasts",
        "explosion", "explosions", "explode", "explodes", "exploded",
        "missile", "missiles", "shelling", "shelled", "airstrike", "airstrikes",
        "war", "wars", "offensive", "clash", "clashes", "fighting",
        "wounded", "wounding", "injured", "injure", "injury", "injuries",
        "killed", "dead", "slain", "massacre", "massacred",
        "strike", "strikes",
    }),
    "death": frozenset({
        "death", "deaths", "died", "dies", "dying", "dead",
        "kill", "kills", "killed", "killing", "killer",
        "fatal", "fatality", "fatalities", "victim", "victims",
        "body", "bodies", "slain", "funeral", "funerals", "mourning", "obituary",
        "passes away", "passed away",
    }),
    "disaster_casualties": frozenset({
        "earthquake", "quake", "quakes",
        "flood", "floods", "flooding", "flooded",
        "hurricane", "hurricanes", "cyclone", "typhoon", "storm", "storms",
        "wildfire", "wildfires", "blaze", "blazes",
        "landslide", "landslides", "tsunami", "tsunamis", "drought",
        "collapse", "collapses", "collapsed",
        "crash", "crashes", "crashed", "sinking", "sank",
        "derail", "derailed", "derailment",
        "evacuate", "evacuated", "evacuation", "evacuees",
        "rescue", "rescued", "rescues",
        "devastation", "devastated", "devastating",
        "casualty", "casualties", "fire", "fires",
    }),
    "crime_against_individual": frozenset({
        "murder", "murders", "murdered", "homicide",
        "rape", "rapes", "raped", "sexual assault", "sexual abuse",
        "assault", "assaults", "assaulted",
        "kidnap", "kidnapped", "kidnapping", "kidnapper",
        "abduct", "abducted", "abduction",
        "robbery", "robberies", "robbed", "mugging", "mugged", "burglary",
        "stabbing", "stabbed", "shooting", "shot",
        "carjacking", "theft", "stolen", "home invasion",
    }),
    "minors": frozenset({
        "child", "children", "kid", "kids", "boy", "boys", "girl", "girls",
        "teen", "teens", "teenager", "teenagers", "teenage",
        "school", "schools", "student", "students", "pupil", "pupils",
        "kindergarten", "nursery", "baby", "babies", "infant", "infants",
        "toddler", "toddlers", "youth", "youths", "minor", "minors",
    }),
}


def _matches(text: str, patterns: frozenset[str]) -> bool:
    for pattern in patterns:
        if " " in pattern:
            if pattern in text:
                return True
        elif re.search(rf"\b{re.escape(pattern)}\b", text):
            return True
    return False


def classify(title: str) -> list[str]:
    """Return the safety tags matched by a candidate's headline."""

    text = title.lower()
    return [tag for tag in SAFETY_TAGS if _matches(text, _LEXICON[tag])]


def tag_candidate(candidate: Mapping[str, object]) -> dict:
    """Return a copy of the candidate with ``safety_tags`` and ``hidden_by_safety`` set."""

    result = dict(candidate)
    tags = classify(str(candidate.get("title") or ""))
    result["safety_tags"] = tags
    result["hidden_by_safety"] = bool(tags)
    return result


def tag_candidates(candidates: Sequence[Mapping[str, object]]) -> list[dict]:
    """Tag every candidate in ranked order."""

    return [tag_candidate(candidate) for candidate in candidates]


def default_view(
    candidates: Sequence[Mapping[str, object]],
    *,
    limit: int = DEFAULT_LIST_LIMIT,
    fewer_than: int = FEWER_THAN,
) -> dict:
    """Split tagged candidates into the default untagged list and a hidden count.

    ``candidates`` must already carry ``hidden_by_safety`` (use :func:`tag_candidates`).
    Returns the visible list capped at ``limit``, the hidden count, a
    ``fewer_than_8`` flag and a message when fewer than ``fewer_than`` remain.
    """

    visible = [dict(c) for c in candidates if not c.get("hidden_by_safety")][:limit]
    hidden_count = sum(1 for c in candidates if c.get("hidden_by_safety"))
    fewer = len(visible) < fewer_than
    message = (
        f"Fewer than {fewer_than} stories remain after safety filtering; "
        "use the manual path or a cached run."
        if fewer
        else ""
    )
    return {
        "visible": visible,
        "hidden_count": hidden_count,
        "fewer_than_8": fewer,
        "message": message,
    }
