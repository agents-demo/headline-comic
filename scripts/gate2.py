"""Gate 2 validation: render the visual half from the fixture run and verify it.

Gate 2 (tasks.md): "comic page and fact cards from the fixture run, characters
recognisable." This driver regenerates the whole visual half deterministically
from the hand-written t006 fixture — the AniDoodle keyframes (one clean 16:9
still per storyboard shot), the 2x3 comic page, the five source-linked fact
cards, and the SC-2 character-labelling deck — then runs the deterministic
verifications that back the gate's three criteria:

* **comic page** — ``runs/<run-id>/comic.png`` at the composed 1280x1298 size
  with title/footer/caption ink present;
* **fact cards** — ``runs/<run-id>/facts.png`` at the 640px strip width with the
  "Based on: N sources" header and card ink present;
* **characters recognisable** — the SC-2 deck is built with its answer key and
  labelling sheet (the human measurement), and each cast sheet in
  ``assets/cast/`` carries every one of its signature colours (the deterministic
  anchor: the comic is drawn from the same ``cast.ts`` as those sheets).

The actual SC-2 2-person labelling measurement is a human step the presenter
performs with the regenerated deck and ``sheet.md``; this driver scores the deck
against its own ground truth (always 1.0/1.0) only to prove the scoring pipeline
works, not as evidence of recognisability.

Usage::

    PYTHONPATH=. .venv/Scripts/python.exe -m scripts.gate2 [--run-id gate2] \
        [--skip-keyframes] [--verify-only] [--force]

``--skip-keyframes`` reuses existing keyframes under ``runs/<run-id>/keyframes``
(the AniDoodle still render is the slow step). ``--verify-only`` checks an
already-rendered run without rendering anything. ``--force`` clears the run dir
first (the skills refuse to overwrite their own outputs).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from PIL import Image

from src.permissions.media_guard import UnitPrice
from src.providers.anidoodle_image import AniDoodleImageProvider
from src.skills import (
    CAST_NAMES,
    check_cast_sheet,
    generate_keyframes,
    page_size,
    run_character_check,
    run_composer,
    run_facts,
    score_deck,
)
from src.skills.compose import STRIP_W

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "t006-sample"
CAST_DIR = ROOT / "assets" / "cast"


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURE / name).read_text(encoding="utf-8"))


def _run_dir(run_id: str) -> Path:
    return ROOT / "runs" / run_id


def _has_ink(png: Path, *, dark_pixels: int = 300, threshold: int = 100) -> bool:
    with Image.open(png) as image:
        data = image.convert("RGB").tobytes()
    dark = sum(
        1
        for i in range(0, len(data), 3)
        if data[i] < threshold and data[i + 1] < threshold and data[i + 2] < threshold
    )
    return dark >= dark_pixels


def render_keyframes(storyboard: dict, run_id: str) -> None:
    """Render one keyframe per shot (skips when already present)."""
    keyframes_dir = _run_dir(run_id) / "keyframes"
    shot_ids = [str(shot["shot_id"]) for shot in storyboard["shots"]]
    if all((keyframes_dir / f"{shot_id}.png").is_file() for shot_id in shot_ids):
        print(f"  keyframes: already present ({len(shot_ids)} shots)")
        return
    print(f"  keyframes: rendering {len(shot_ids)} shots via AniDoodle stills ...")
    provider = AniDoodleImageProvider(ROOT)
    generate_keyframes(
        storyboard,
        provider=provider,
        workspace_root=ROOT,
        run_id=run_id,
        unit_prices={"image": UnitPrice.create("anidoodle", "keyframe", "0")},
    )


def render_comic(story: dict, storyboard: dict, run_id: str) -> None:
    output = _run_dir(run_id) / "comic.png"
    if output.is_file():
        print("  comic:      already present")
        return
    print("  comic:      composing 2x3 page ...")
    run_composer(story, storyboard, workspace_root=ROOT, run_id=run_id)


def render_facts(summaries: dict, candidates: dict, ledger: dict, run_id: str) -> None:
    output = _run_dir(run_id) / "facts.png"
    if output.is_file():
        print("  facts:      already present")
        return
    print("  facts:      drawing 5 source-linked cards ...")
    run_facts(summaries, candidates, workspace_root=ROOT, run_id=run_id, ledger=ledger)


def render_deck(storyboard: dict, run_id: str) -> None:
    output = _run_dir(run_id) / "character-check" / "deck.json"
    if output.is_file():
        print("  deck:       already present")
        return
    print("  deck:       building SC-2 labelling deck ...")
    run_character_check(storyboard, workspace_root=ROOT, run_id=run_id)


def verify_run(run_id: str, storyboard: dict) -> dict[str, Any]:
    """Deterministic checks backing Gate 2's three criteria. Returns a report."""
    run_dir = _run_dir(run_id)
    shots = storyboard["shots"]
    checks: list[dict[str, Any]] = []

    def record(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    # comic page
    comic = run_dir / "comic.png"
    if comic.is_file():
        with Image.open(comic) as image:
            size = image.size
        record(
            "comic page size",
            size == page_size(),
            f"comic.png {size[0]}x{size[1]} (expected {page_size()[0]}x{page_size()[1]})",
        )
        record("comic page ink", _has_ink(comic), "title/captions/footer ink present")
    else:
        record("comic page", False, f"missing {comic}")

    # fact cards
    facts = run_dir / "facts.png"
    if facts.is_file():
        with Image.open(facts) as image:
            width = image.size[0]
        record("facts strip width", width == STRIP_W, f"facts.png {width}px (expected {STRIP_W})")
        record("facts strip ink", _has_ink(facts), "header + card ink present")
    else:
        record("facts strip", False, f"missing {facts}")

    # keyframes: one 1280x720 still per shot
    missing = [s["shot_id"] for s in shots if not (run_dir / "keyframes" / f"{s['shot_id']}.png").is_file()]
    record("keyframes complete", not missing, f"{len(shots) - len(missing)}/{len(shots)} shots" + (f" missing {missing}" if missing else ""))

    # SC-2 deck: built, answer key + sheet, and scoring pipeline self-consistent
    deck_path = run_dir / "character-check" / "deck.json"
    if deck_path.is_file():
        deck = json.loads(deck_path.read_text(encoding="utf-8"))
        items = deck.get("items", [])
        sheet = run_dir / "character-check" / "sheet.md"
        key = run_dir / "character-check" / "answer-key.json"
        record("deck complete", len(items) == len(shots) and sheet.is_file() and key.is_file(), f"{len(items)} items, sheet+answer-key present")
        perfect = {item["item_id"]: item["characters"] for item in items}
        score = score_deck(deck, perfect)
        record(
            "deck scoring self-check",
            score["panel_pass"] and score["frame_pass"],
            f"panel {score['panel']['accuracy']:.2f} (>= {score['targets']['panel']}), "
            f"frame {score['frame']['accuracy']:.2f} (>= {score['targets']['frame']})",
        )
    else:
        record("deck", False, f"missing {deck_path}")

    # characters recognisable: cast sheets carry their signature colours
    for name in CAST_NAMES:
        sheet = CAST_DIR / f"{name}.png"
        if not sheet.is_file():
            record(
                f"cast {name} recognisable",
                False,
                f"missing {sheet} (regenerate with scripts/anidoodle/render_cast.mjs)",
            )
            continue
        result = check_cast_sheet(sheet, name)
        record(
            f"cast {name} recognisable",
            result["ok"],
            "all signature colours present" if result["ok"] else f"missing {result['missing']}",
        )

    passed = sum(1 for check in checks if check["ok"])
    return {"checks": checks, "passed": passed, "total": len(checks)}


def _print_report(report: dict[str, Any]) -> None:
    print()
    print(f"Gate 2 report — {report['passed']}/{report['total']} checks pass")
    for check in report["checks"]:
        mark = "PASS" if check["ok"] else "FAIL"
        print(f"  [{mark}] {check['name']}: {check['detail']}")
    if report["passed"] != report["total"]:
        print()
        print("Gate 2 NOT closed: fix the failing checks above and re-run.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gate 2 validation: render + verify the visual half")
    parser.add_argument("--run-id", default="gate2", help="run directory name under runs/ (default %(default)s)")
    parser.add_argument("--skip-keyframes", action="store_true", help="reuse existing keyframes instead of rendering")
    parser.add_argument("--verify-only", action="store_true", help="only verify an already-rendered run")
    parser.add_argument("--force", action="store_true", help="clear runs/<run-id> before rendering")
    args = parser.parse_args(argv)

    story = _load("story.json")
    storyboard = _load("storyboard.json")
    summaries = _load("summaries.json")
    candidates = _load("candidates.json")
    ledger = _load("ledger.json")

    run_dir = _run_dir(args.run_id)
    if args.force and run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    if not args.verify_only:
        if args.skip_keyframes:
            print("keyframes: skipped (reusing existing)")
        else:
            render_keyframes(storyboard, args.run_id)
        render_comic(story, storyboard, args.run_id)
        render_facts(summaries, candidates, ledger, args.run_id)
        render_deck(storyboard, args.run_id)

    report = verify_run(args.run_id, storyboard)
    _print_report(report)
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    sys.exit(main())
