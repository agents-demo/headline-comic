"""S2/S9 human-in-the-loop gates (FR-007, US1, US3).

Deterministic state machine for the two human gates:

* **Pick five** — the presenter must pick exactly five distinct candidate ids
  before the pipeline continues.
* **Approve / edit / reject** — the presenter sees the script, storyboard, check
  results and cost estimate, then approves, asks to edit, or rejects. An edit
  re-runs the code checks and the Verifier (the retry loop itself is T018); this
  module only models the gate and what an approval is allowed to do.

The rules encoded here:

* every blocking code check (from ``checks.json``) must pass — a code-check
  failure blocks approval and can never be overridden (US3);
* a Verifier failure (from ``verifier.json``) can only be overridden explicitly,
  one check id at a time, and each override is written to ``run.log`` (FR-007);
* an approval record listing the approved actions is what unlocks paid media
  calls (FR-014); it is read back by the T007 approval guard.

Code checks and Verifier checks are told apart by their source document, not by
their ``owner`` field: the Verifier reports ``owner`` as the stage it would route
the failure back to (``summary`` or ``story``), the same values code checks use.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Mapping, Sequence

from src.flow.runlog import append_entry, log_entry
from src.permissions.media_guard import require_allowed_write_path

REQUIRED_PICKS = 5
DECISIONS = ("approve", "edit", "reject")
APPROVAL_FILENAME = "approval.json"


class PickError(ValueError):
    """Raised when the presenter has not picked exactly five distinct stories."""


class ApprovalError(ValueError):
    """Raised when an approval request is malformed (bad decision or override)."""


class Decision(str, Enum):
    APPROVE = "approve"
    EDIT = "edit"
    REJECT = "reject"


@dataclass(frozen=True)
class ApprovalOutcome:
    """The result of evaluating one approval decision against checks + Verifier."""

    decision: str
    allowed: bool
    code_failures: tuple[str, ...]
    verifier_failures: tuple[str, ...]
    overridden: tuple[str, ...]
    message: str


def pick_stories(candidate_ids: Sequence[str]) -> list[str]:
    """Validate the presenter's pick and return the ids in selection order."""

    ids = [str(cid).strip() for cid in candidate_ids]
    if len(ids) != REQUIRED_PICKS:
        raise PickError(f"Pick exactly {REQUIRED_PICKS} stories; got {len(ids)}")
    if any(not cid for cid in ids):
        raise PickError("Story ids must not be empty")
    if len(set(ids)) != REQUIRED_PICKS:
        raise PickError("Picked stories must be distinct")
    return ids


def checks_from(document: Mapping[str, object]) -> list[dict]:
    """Extract the ``checks`` list from a checks-envelope document (T015/T016)."""

    if not isinstance(document, Mapping):
        return []
    checks = document.get("checks")
    if not isinstance(checks, list):
        return []
    return [dict(check) for check in checks if isinstance(check, Mapping)]


def combined_checks(
    checks_document: Mapping[str, object],
    verifier_document: Mapping[str, object],
) -> list[dict]:
    """Merge the T015 code checks and T016 Verifier checks into one sequence."""

    return checks_from(checks_document) + checks_from(verifier_document)


def _blocking_failures(checks: Sequence[Mapping[str, object]]) -> dict[str, dict]:
    """Return failed blocking checks keyed by id; missing ``blocking`` is blocking."""

    failures: dict[str, dict] = {}
    for check in checks:
        if check.get("passed"):
            continue
        if check.get("blocking", True) is False:
            continue
        check_id = check.get("check_id")
        if check_id is None:
            continue
        failures[str(check_id)] = dict(check)
    return failures


def evaluate_approval(
    checks_document: Mapping[str, object],
    verifier_document: Mapping[str, object],
    *,
    decision: str,
    overrides: Sequence[str] = (),
) -> ApprovalOutcome:
    """Decide whether an approval is allowed and which failures remain.

    ``decision`` is one of ``approve``, ``edit``, ``reject``. ``overrides`` may
    name only failing Verifier checks (checks from ``verifier_document``); naming
    a code check, a passing check, or an unknown id raises ``ApprovalError``.
    Only ``approve`` can ever be ``allowed``.
    """

    if decision not in DECISIONS:
        raise ApprovalError(f"decision must be one of {DECISIONS}; got {decision!r}")

    override_ids = [str(item).strip() for item in overrides]
    if any(not item for item in override_ids):
        raise ApprovalError("override ids must not be empty")
    if len(set(override_ids)) != len(override_ids):
        raise ApprovalError("overrides must be distinct")

    code_failures = sorted(_blocking_failures(checks_from(checks_document)))
    verifier_failures = sorted(_blocking_failures(checks_from(verifier_document)))

    invalid_overrides = [cid for cid in override_ids if cid not in set(verifier_failures)]
    if invalid_overrides:
        raise ApprovalError(
            "Only failing Verifier checks may be overridden; invalid override: "
            + ", ".join(invalid_overrides)
        )

    remaining = sorted(cid for cid in verifier_failures if cid not in set(override_ids))

    if decision == Decision.APPROVE:
        if code_failures:
            allowed, message = False, "Blocked by code checks: " + ", ".join(code_failures)
        elif remaining:
            allowed, message = False, "Verifier failures remain: " + ", ".join(remaining)
        else:
            allowed, message = True, "Approved"
    elif decision == Decision.EDIT:
        allowed, message = False, "Edit requested; code checks and Verifier will run again"
    else:
        allowed, message = False, "Rejected"

    return ApprovalOutcome(
        decision=decision,
        allowed=allowed,
        code_failures=tuple(code_failures),
        verifier_failures=tuple(remaining),
        overridden=tuple(sorted(set(override_ids))),
        message=message,
    )


def build_approval_record(
    run_id: str,
    approved_actions: Sequence[str],
    *,
    decision: str = Decision.APPROVE,
    overrides: Sequence[str] = (),
    generated_at: datetime | None = None,
) -> dict:
    """Build the approval record that unlocks paid media calls (FR-014)."""

    return {
        "schema_version": "1.0",
        "run_id": str(run_id),
        "decision": decision,
        "approved_actions": [str(action) for action in approved_actions],
        "overridden_checks": [str(cid) for cid in overrides],
        "generated_at": (generated_at or datetime.now(timezone.utc)).isoformat(),
    }


def save_approval(
    record: Mapping[str, object],
    *,
    workspace_root: Path,
    run_id: str,
) -> Path:
    """Write the approval record into the run folder; refuse to overwrite."""

    path = require_allowed_write_path(
        workspace_root / "runs" / run_id / APPROVAL_FILENAME, workspace_root=workspace_root
    )
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite existing approval record: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(record), indent=2) + "\n", encoding="utf-8")
    return path


def log_approval(
    workspace_root: Path,
    run_id: str,
    outcome: ApprovalOutcome,
    *,
    approved_actions: Sequence[str] = (),
) -> Path:
    """Write the approval decision and any overrides to run.log (FR-007)."""

    append_entry(
        workspace_root,
        run_id,
        log_entry(
            "approval",
            decision=outcome.decision,
            allowed=outcome.allowed,
            message=outcome.message,
            approved_actions=list(approved_actions),
        ),
    )
    for check_id in outcome.overridden:
        append_entry(
            workspace_root,
            run_id,
            log_entry("override", check_id=check_id),
        )
    return require_allowed_write_path(
        workspace_root / "runs" / run_id / "run.log", workspace_root=workspace_root
    )
