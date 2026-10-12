"""Tests for the run.log writer (T017, FR-011)."""

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.flow.runlog import (
    append_entry,
    log_entry,
    read_entries,
    run_log_path,
    validate_run_id,
)


class ValidateRunIdTests(unittest.TestCase):
    def test_accepts_plain_ids(self) -> None:
        self.assertEqual(validate_run_id("r1"), "r1")
        self.assertEqual(validate_run_id("2026-10-12_08-00"), "2026-10-12_08-00")

    def test_rejects_escape_attempts(self) -> None:
        for bad in ("../x", "", "a/b", "a b", ".hidden"):
            with self.assertRaises(ValueError, msg=bad):
                validate_run_id(bad)


class LogEntryTests(unittest.TestCase):
    def test_entry_has_timestamp_and_event(self) -> None:
        entry = log_entry("approval", decision="approve")
        self.assertEqual(entry["event"], "approval")
        self.assertEqual(entry["decision"], "approve")
        self.assertIn("ts", entry)

    def test_entry_accepts_explicit_timestamp(self) -> None:
        ts = datetime(2026, 10, 12, 8, 0, tzinfo=timezone.utc)
        entry = log_entry("stage", ts=ts, stage="S1")
        self.assertEqual(entry["ts"], ts.isoformat())
        self.assertEqual(entry["stage"], "S1")


class AppendAndReadTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            append_entry(root, "r1", log_entry("stage", stage="S1", seconds=1.5))
            append_entry(root, "r1", log_entry("approval", decision="approve"))
            entries = read_entries(root, "r1")
            self.assertEqual([e["event"] for e in entries], ["stage", "approval"])
            self.assertEqual(entries[0]["seconds"], 1.5)

    def test_missing_log_reads_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(read_entries(Path(tmp), "nope"), [])

    def test_run_log_lives_under_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = run_log_path(root, "r1")
            self.assertEqual(path.resolve(), (root / "runs" / "r1" / "run.log").resolve())


if __name__ == "__main__":
    unittest.main()
