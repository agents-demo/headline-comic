"""Deterministic text renderers for the human gates (T017 skeleton).

Pure functions that turn the run artifacts (story, storyboard, checks,
verifier, cost estimate) into the lines the presenter sees at the pick-5 and
approval gates. No model is involved; these renderers are reused by the full
demo UI in T034. Every function returns a list of strings so tests can assert
exact output and the caller can join or indent as it likes.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from src.flow.hitl import checks_from

FICTION_LABEL = "Fiction inspired by today's news"


def render_candidate_list(
    candidates: Sequence[Mapping[str, object]],
    *,
    hidden_count: int = 0,
) -> list[str]:
    """Render the ranked candidate list with a hidden-count line (US1)."""

    lines = [f"{len(candidates)} stories to choose from (hidden: {hidden_count})"]
    for index, candidate in enumerate(candidates, start=1):
        lines.append(
            f"  [{index}] {candidate.get('title', '')} — "
            f"{candidate.get('publisher', '')} ({candidate.get('published_at', '')})"
        )
    return lines


def render_pick_summary(selected_ids: Sequence[str]) -> list[str]:
    """Render the presenter's five selections."""

    return [f"Picked {len(selected_ids)}: {', '.join(selected_ids)}"]


def render_story(story: Mapping[str, object]) -> list[str]:
    """Render the storyline (title + six beats) for the approval screen."""

    lines = [
        f"Title: {story.get('title', '')}",
        f"Label: {story.get('fiction_label', FICTION_LABEL)}",
        f"Cast: {', '.join(story.get('characters', []) or [])}",
    ]
    for beat in story.get("beats") or []:
        marker = ""
        if beat.get("source_ref"):
            marker = f" [source {beat['source_ref']}]"
        if beat.get("ending"):
            marker += " (closing)"
        lines.append(f"  beat {beat.get('beat_index')}: {beat.get('text', '')}{marker}")
    return lines


def render_storyboard(storyboard: Mapping[str, object]) -> list[str]:
    """Render the shot list (FR-016) for the approval screen."""

    lines: list[str] = []
    for shot in storyboard.get("shots") or []:
        panel = " panel" if shot.get("comic_panel") else ""
        caption = shot.get("comic_caption")
        lines.append(
            f"  {shot.get('shot_id')}: beat {shot.get('beat')} "
            f"[{', '.join(shot.get('characters', []) or [])}] "
            f"{shot.get('duration_s')}s {shot.get('camera', '')}{panel}"
        )
        lines.append(f"      action: {shot.get('action', '')}")
        lines.append(f"      narration: {shot.get('narration', '')}")
        if caption:
            lines.append(f"      caption: {caption}")
    return lines


def render_checks(
    checks_document: Mapping[str, object],
    verifier_document: Mapping[str, object],
) -> list[str]:
    """Render the combined code + Verifier check results, failures first."""

    labeled = [("code", check) for check in checks_from(checks_document)]
    labeled += [("verifier", check) for check in checks_from(verifier_document)]

    failures = [(kind, check) for kind, check in labeled if not check.get("passed")]
    passing = [(kind, check) for kind, check in labeled if check.get("passed")]

    lines = [f"Checks: {len(passing)} passed, {len(failures)} failed"]
    for kind, check in failures:
        lines.append(f"  FAIL [{kind}] {check.get('check_id')}: {check.get('message', '')}")
    for _, check in passing:
        lines.append(f"  pass {check.get('check_id')}")
    return lines


def render_cost_estimate(estimate: Mapping[str, object]) -> list[str]:
    """Render the cost estimate (FR-012) for the approval screen."""

    lines = [
        f"Estimated cost: ${estimate.get('run_estimate_usd', 0):.2f} USD "
        f"(budget ${estimate.get('run_budget_usd', 0):.2f})",
    ]
    for item in estimate.get("items") or []:
        lines.append(
            f"  {item.get('category')}: {item.get('quantity')} "
            f"{item.get('unit')} @ ${item.get('unit_price_usd', 0):.6f} "
            f"= ${item.get('estimated_usd', 0):.2f}"
        )
    return lines


def render_approval_screen(
    story: Mapping[str, object],
    storyboard: Mapping[str, object],
    checks_document: Mapping[str, object],
    verifier_document: Mapping[str, object],
    estimate: Mapping[str, object],
) -> str:
    """Render the full approval screen and return it as one string (US3)."""

    sections = [
        render_story(story),
        render_storyboard(storyboard),
        render_checks(checks_document, verifier_document),
        render_cost_estimate(estimate),
    ]
    blocks = ["\n".join(section) for section in sections]
    return "\n\n".join(blocks)
