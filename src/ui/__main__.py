"""Runnable UI skeleton (T017): ``python -m src.ui``.

Prints a read-only approval screen built from the T006 fixture run and walks the
two HITL gates (pick-5 and approve/edit/reject) so the entry point and the gate
logic are provably wired. The interactive "Run today" flow is T034; this module
exists now so the CLI command in CLAUDE.md works and the renderers have a live
consumer.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from src.flow.hitl import (
    Decision,
    evaluate_approval,
    log_approval,
    pick_stories,
)
from src.skills.checks import build_checks_document, run_checks
from src.ui.render import (
    render_approval_screen,
    render_candidate_list,
    render_checks,
    render_cost_estimate,
    render_pick_summary,
)

_FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "t006-sample"


def _load(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def _demo_estimate(storyboard: dict) -> dict:
    shots = storyboard["shots"]
    return {
        "schema_version": "1.0",
        "currency": "USD",
        "run_estimate_usd": 0.0,
        "run_actual_usd": 0.0,
        "settled": False,
        "run_budget_usd": 25.0,
        "project_total_usd": 0.0,
        "project_budget_usd": 300.0,
        "items": [
            {"category": "image", "quantity": len(shots), "unit": "keyframe",
             "unit_price_usd": 0.0, "estimated_usd": 0.0},
            {"category": "video", "quantity": len(shots), "unit": "shot",
             "unit_price_usd": 0.0, "estimated_usd": 0.0},
        ],
        "tavily_credits": 0.0,
    }


def main() -> int:
    ledger = _load("ledger.json")
    story = _load("story.json")
    storyboard = _load("storyboard.json")

    # S7 deterministic checks over the fixture artifacts.
    checks_document = build_checks_document(run_checks(ledger, {}, story, storyboard))
    verifier_document = {"schema_version": "1.0", "passed": True, "checks": []}
    estimate = _demo_estimate(storyboard)

    print("=== S1 candidate list (skeleton) ===")
    print("\n".join(render_candidate_list([
        {"title": story["title"], "publisher": "fixture", "published_at": "2026-10-12T00:00:00Z"},
    ], hidden_count=0)))
    print()

    # S2: pick exactly five (demonstrate both outcomes).
    print("=== S2 pick-5 gate ===")
    print("\n".join(render_pick_summary(pick_stories(["s1", "s2", "s3", "s4", "s5"]))))
    try:
        pick_stories(["s1", "s2"])
    except ValueError as exc:
        print(f"pick rejected: {exc}")
    print()

    # S9: approval gate.
    print("=== S9 approval screen ===")
    print(render_approval_screen(story, storyboard, checks_document, verifier_document, estimate))
    print()

    outcome = evaluate_approval(checks_document, verifier_document, decision=Decision.APPROVE)
    print(f"approve -> allowed={outcome.allowed}: {outcome.message}")
    print()

    # Show how an explicit Verifier override is logged.
    print("=== override logging demo ===")
    print("code check results (fragment):")
    for line in render_checks(checks_document, verifier_document)[:3]:
        print(f"  {line}")
    print("cost estimate:")
    for line in render_cost_estimate(estimate):
        print(f"  {line}")
    print()
    print("To log an approval with overrides, call log_approval(...) with a run folder.")
    _ = log_approval  # silence unused-import lint if run via tooling
    return 0


if __name__ == "__main__":
    sys.exit(main())
