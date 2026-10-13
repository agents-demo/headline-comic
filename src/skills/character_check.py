"""SC-2 character-check protocol (T025).

Builds the shuffled labelling deck and answer key from a run's clean keyframes,
and scores a completed labelling sheet. Deterministic: the shuffle is seeded, the
deck is one clean frame per shot (the six comic panels are the six ``comic_panel``
shots), and every item carries its ground-truth character set from the storyboard.

The deck contains **one clean frame per shot** (8-10 images). Each item is tagged
``kind`` ``"panel"`` when it is also a comic panel (the six), else ``"frame"``.
Scoring therefore reports two numbers, matching spec SC-2: panel accuracy over
the six panels (>= 90%) and frame accuracy over one frame per shot (>= 80%). In
the still-only pipeline (T023) a shot's frame *is* its keyframe, so panel and
frame images coincide for panel shots; when T027 renders real video frames the
frame set becomes distinct mid-shot frames and this protocol is unchanged.

Accuracy is the appearance-correct rate: for every item, correctly labelled
appearances divided by (true appearances plus any spurious labels). A missed
character and an invented character both count against the score.
"""

from __future__ import annotations

import hashlib
import json
import random
import shutil
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.permissions.media_guard import require_allowed_write_path

CAST_NAMES = ("courier", "mayor", "pigeon")
PANEL_TARGET = 0.9
FRAME_TARGET = 0.8


class CharacterCheckError(RuntimeError):
    """Raised when the deck cannot be built or a sheet cannot be scored."""


def _seed_from(run_id: str) -> int:
    digest = hashlib.sha256(run_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big")


def deck_items(storyboard: Mapping[str, Any], keyframes_dir: Path) -> list[dict]:
    """One clean frame per shot, in storyboard order, with ground-truth labels."""
    shots = storyboard.get("shots")
    if not isinstance(shots, list) or not shots:
        raise CharacterCheckError("storyboard must contain a non-empty shots array")
    keyframes_dir = keyframes_dir.resolve()
    items: list[dict] = []
    for shot in shots:
        if not isinstance(shot, Mapping):
            raise CharacterCheckError("storyboard shot must be an object")
        shot_id = str(shot.get("shot_id") or "")
        if not shot_id:
            raise CharacterCheckError("every shot needs a shot_id")
        if not (keyframes_dir / f"{shot_id}.png").is_file():
            raise CharacterCheckError(f"missing keyframe for shot {shot_id}")
        characters = sorted(str(c) for c in shot.get("characters", []))
        unknown = set(characters) - set(CAST_NAMES)
        if unknown:
            raise CharacterCheckError(f"unknown cast member(s) in {shot_id}: {sorted(unknown)}")
        items.append(
            {
                "shot_id": shot_id,
                "beat": shot.get("beat"),
                "source_ref": shot.get("source_ref"),
                "kind": "panel" if shot.get("comic_panel") is True else "frame",
                "characters": characters,
            }
        )
    if len(items) < 6:
        raise CharacterCheckError("storyboard must cover at least six shots")
    return items


def _sheet_md(items: Sequence[dict]) -> str:
    lines = [
        "# Character labelling sheet",
        "",
        "For each image, tick every character that appears (courier, mayor, pigeon).",
        "Leave the box empty when that character is absent.",
        "",
    ]
    for item in items:
        lines.append(f"## {item['item_id']}")
        for name in CAST_NAMES:
            lines.append(f"- [ ] {name}")
        lines.append("")
    return "\n".join(lines)


def build_deck(
    storyboard: Mapping[str, Any],
    keyframes_dir: Path,
    *,
    output_dir: Path,
    run_id: str = "",
    seed: int | None = None,
) -> dict:
    """Shuffle the clean frames into ``output_dir`` and write deck + answer key + sheet.

    Returns the deck document (``deck.json`` content). Writes:
      ``deck/item-01.png ...``  the shuffled, renamed clean frames;
      ``deck.json``             the machine-readable deck with ground truth;
      ``answer-key.json``       item id -> shot id, kind and expected characters;
      ``sheet.md``              the human-fillable labelling sheet.
    """
    items = deck_items(storyboard, keyframes_dir)
    resolved_seed = seed if seed is not None else _seed_from(run_id)
    rng = random.Random(resolved_seed)
    order = list(range(len(items)))
    rng.shuffle(order)

    output_dir = output_dir.resolve()
    deck_json = output_dir / "deck.json"
    if deck_json.exists():
        raise FileExistsError(f"Refusing to overwrite existing deck: {deck_json}")
    deck_dir = output_dir / "deck"
    deck_dir.mkdir(parents=True, exist_ok=True)

    shuffled: list[dict] = []
    for position, index in enumerate(order):
        item = items[index]
        item_id = f"item-{position + 1:02d}"
        source = keyframes_dir / f"{item['shot_id']}.png"
        shutil.copyfile(source, deck_dir / f"{item_id}.png")
        shuffled.append({"item_id": item_id, **item})

    document: dict[str, Any] = {
        "schema_version": "1.0",
        "run_id": run_id,
        "seed": resolved_seed,
        "cast": list(CAST_NAMES),
        "targets": {"panel": PANEL_TARGET, "frame": FRAME_TARGET},
        "items": shuffled,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    deck_json.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    (output_dir / "answer-key.json").write_text(
        json.dumps(
            {item["item_id"]: {
                "shot_id": item["shot_id"],
                "kind": item["kind"],
                "characters": item["characters"],
            } for item in shuffled},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "sheet.md").write_text(_sheet_md(shuffled), encoding="utf-8")
    return document


def _bucket_accuracy(items: Sequence[dict], labels: Mapping[str, Sequence[str]]) -> dict:
    matched = 0
    union = 0
    details: list[dict] = []
    for item in items:
        expected = set(item["characters"])
        got_raw = labels.get(item["item_id"], [])
        got = {str(name) for name in got_raw}
        unknown = got - set(CAST_NAMES)
        if unknown:
            raise CharacterCheckError(
                f"unknown label(s) for {item['item_id']}: {sorted(unknown)}"
            )
        matched += len(expected & got)
        union += len(expected | got)
        details.append(
            {
                "item_id": item["item_id"],
                "shot_id": item["shot_id"],
                "expected": sorted(expected),
                "got": sorted(got),
                "correct": expected == got,
            }
        )
    accuracy = (matched / union) if union else 1.0
    return {"accuracy": round(accuracy, 4), "appearances": union, "items": details}


def score_deck(deck: Mapping[str, Any], labels: Mapping[str, Sequence[str]]) -> dict:
    """Score a completed labelling sheet against the deck's ground truth.

    ``labels`` maps item id to the character names the labeller ticked. Returns
    panel and frame accuracy plus a per-item breakdown.
    """
    items = deck.get("items")
    if not isinstance(items, list) or not items:
        raise CharacterCheckError("deck must contain an items array")
    targets = deck.get("targets") or {"panel": PANEL_TARGET, "frame": FRAME_TARGET}
    panels = [item for item in items if item.get("kind") == "panel"]
    panel = _bucket_accuracy(panels, labels)
    frame = _bucket_accuracy(items, labels)
    return {
        "panel": panel,
        "frame": frame,
        "targets": {
            "panel": targets.get("panel", PANEL_TARGET),
            "frame": targets.get("frame", FRAME_TARGET),
        },
        "panel_pass": panel["accuracy"] >= targets.get("panel", PANEL_TARGET),
        "frame_pass": frame["accuracy"] >= targets.get("frame", FRAME_TARGET),
    }


def run(
    storyboard: Mapping[str, Any],
    *,
    workspace_root: Path,
    run_id: str,
    seed: int | None = None,
) -> dict:
    """Build the SC-2 deck under ``runs/<run-id>/character-check/``."""
    root = workspace_root.resolve()
    run_dir = root / "runs" / run_id
    output_dir = require_allowed_write_path(
        run_dir / "character-check" / "deck.json", workspace_root=root
    ).parent
    return build_deck(
        storyboard,
        run_dir / "keyframes",
        output_dir=output_dir,
        run_id=run_id,
        seed=seed,
    )
