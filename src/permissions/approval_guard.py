"""Small fail-closed guard for paid media provider calls.

Local deterministic renderers such as AniDoodle do not use this paid-call
guard. It protects external providers that can incur per-call charges.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable


class ApprovalRequired(PermissionError):
    """Raised before a paid provider is called without a matching approval."""


def require_approval(
    *,
    action: str,
    approval_path: Path,
    run_id: str,
) -> dict[str, Any]:
    """Return a validated approval record or fail closed.

    Records are per run and explicitly list approved action names. Missing,
    malformed, mismatched, or non-approving records all block the call.
    """

    try:
        record = json.loads(approval_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ApprovalRequired(f"No valid approval record for {action}") from exc

    if not isinstance(record, dict):
        raise ApprovalRequired("Approval record must be a JSON object")
    if record.get("run_id") != run_id:
        raise ApprovalRequired("Approval record belongs to a different run")
    actions = record.get("approved_actions")
    if not isinstance(actions, list) or action not in actions:
        raise ApprovalRequired(f"Action is not approved: {action}")
    return record


def guarded_paid_call(
    provider: Any,
    *,
    action: str,
    approval_path: Path,
    run_id: str,
    method: str = "generate",
    **kwargs: Any,
) -> Any:
    """Gate 0 approval check; pipeline media dispatch must use media_guard.guarded_storyboard_call."""

    require_approval(action=action, approval_path=approval_path, run_id=run_id)
    operation: Callable[..., Any] = getattr(provider, method)
    return operation(**kwargs)
