"""FR-011 run.log writer.

Appends JSON Lines entries recording stage timings, cost, approvals and
overrides. Deterministic code: the pipeline writes one line per event and later
views read the file back as a sequence. The file lives at
``runs/<run_id>/run.log`` and is opened in append mode, so entries survive the
retry/edit loop; the full artifact set remains inspectable afterwards.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from src.permissions.media_guard import require_allowed_write_path

RUN_LOG_NAME = "run.log"

_RUN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")


def validate_run_id(run_id: str) -> str:
    """Reject run ids that could escape the runs/ folder or confuse readers."""

    run_id = str(run_id)
    if not _RUN_ID_RE.fullmatch(run_id):
        raise ValueError("invalid run id")
    return run_id


def run_log_path(workspace_root: Path, run_id: str) -> Path:
    """Return the allowed run.log path for a run, without creating it."""

    return require_allowed_write_path(
        workspace_root / "runs" / validate_run_id(run_id) / RUN_LOG_NAME,
        workspace_root=workspace_root,
    )


def log_entry(event: str, *, ts: datetime | None = None, **fields: Any) -> dict:
    """Build one run.log line: a timestamp, an event name, and extra fields."""

    entry: dict[str, Any] = {
        "ts": (ts or datetime.now(timezone.utc)).isoformat(),
        "event": event,
    }
    entry.update(fields)
    return entry


def append_entry(workspace_root: Path, run_id: str, entry: Mapping[str, Any]) -> Path:
    """Append one JSON line to the run's run.log and return the path."""

    path = run_log_path(workspace_root, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(entry), ensure_ascii=False) + "\n")
    return path


def read_entries(workspace_root: Path, run_id: str) -> list[dict]:
    """Read run.log back as a list of entry dicts; a missing log yields [].

    A malformed line stops the reader with an error rather than silently
    dropping data, so nothing is ever mis-reported to the presenter.
    """

    path = run_log_path(workspace_root, run_id)
    if not path.exists():
        return []
    entries: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parsed = json.loads(line)
        if not isinstance(parsed, dict):
            raise ValueError(f"run.log line is not an object: {line!r}")
        entries.append(parsed)
    return entries
