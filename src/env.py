"""Load the git-ignored ``.env`` into the process environment without echoing it.

API keys live in the ignored ``.env`` (never committed). The file may be saved
as UTF-8 or as UTF-16 (Windows Notepad's default when the file contains
non-ASCII text); this loader decodes either. Values already present in the real
process environment always win, so an exported shell key is never shadowed.
"""

from __future__ import annotations

import os
from pathlib import Path


def _decode(raw: bytes) -> str:
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig")
    return raw.decode("utf-8")


def load_env(path: Path) -> None:
    """Set ``os.environ`` from ``KEY=VALUE`` lines in ``path`` when not already set."""

    if not path.is_file():
        return
    text = _decode(path.read_bytes())
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)
