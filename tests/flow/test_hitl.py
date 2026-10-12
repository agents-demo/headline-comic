"""Tests for the human-in-the-loop gates (T017)."""

import json
import tempfile
import unittest
from pathlib import Path

from src.flow.hitl import (
    ApprovalError,
    Decision,
    PickError,
    build_approval_record,
    checks_from,
    combined_checks,
    evaluate_approval,
    log_approval,
    pick_stories,
    save_approval,
)
from src.flow.runlog import read_entries


def _check(check_id: str, passed: bool, *, owner: str = "story") -> dict:
    return {"check_id": check_id, "passed": passed, "blocking": True, "message": check_id, "owner": owner}


def _checks(*items: dict) -> dict:
    return {
        "schema_version": "1.0",
        "passed": all(item["passed"] for item in items),
        "checks": list(items),
    }


def _all_pass() -> tuple[dict, dict]:
    code = _checks(
        _check("schema-ledger", True, owner="ledger"),
        _check("names-story", True, owner="story"),
    )
    verifier = _checks(
        _check("verify-summaries", True, owner="summary"),
        _check("verify-causation", True, owner="story"),
    )
    return code, verifier


class PickStoriesTests(unittest.TestCase):
    def test_accepts_exactly_five_distinct(self) -> None:
        self.assertEqual(pick_stories(["a", "b", "c", "d", "e"]), ["a", "b", "c", "d", "e"])

    def test_rejects_too_few(self) -> None:
        with self.assertRaises(PickError):
            pick_stories(["a", "b", "c", "d"])

    def test_rejects_too_many(self) -> None:
        with self.assertRaises(PickError):
            pick_stories(["a", "b", "c", "d", "e", "f"])

    def test_rejects_duplicates(self) -> None:
        with self.assertRaises(PickError):
            pick_stories(["a", "a", "c", "d", "e"])

    def test_rejects_empty_id(self) -> None:
        with self.assertRaises(PickError):
            pick_stories(["a", "b", "c", "d", " "])

    def test_strips_whitespace(self) -> None:
        self.assertEqual(pick_stories([" a ", "b", "c", "d", "e"]), ["a", "b", "c", "d", "e"])


class ChecksFromTests(unittest.TestCase):
    def test_extracts_checks(self) -> None:
        document = _checks(_check("x", True), _check("y", False))
        self.assertEqual([c["check_id"] for c in checks_from(document)], ["x", "y"])

    def test_missing_or_malformed_document_is_empty(self) -> None:
        self.assertEqual(checks_from({}), [])
        self.assertEqual(checks_from({"checks": "nope"}), [])

    def test_combined_merges_both_sources(self) -> None:
        code, verifier = _all_pass()
        merged = combined_checks(code, verifier)
        self.assertEqual(len(merged), 4)


class EvaluateApprovalTests(unittest.TestCase):
    def test_approve_when_all_pass(self) -> None:
        code, verifier = _all_pass()
        outcome = evaluate_approval(code, verifier, decision=Decision.APPROVE)
        self.assertTrue(outcome.allowed)
        self.assertEqual(outcome.message, "Approved")

    def test_code_failure_blocks_and_cannot_be_overridden(self) -> None:
        code = _checks(_check("names-story", False, owner="story"))
        verifier = _checks(_check("verify-causation", True))
        outcome = evaluate_approval(code, verifier, decision=Decision.APPROVE)
        self.assertFalse(outcome.allowed)
        self.assertEqual(outcome.code_failures, ("names-story",))

        with self.assertRaises(ApprovalError):
            evaluate_approval(code, verifier, decision=Decision.APPROVE, overrides=["names-story"])

    def test_verifier_failure_blocks_until_overridden(self) -> None:
        code = _checks(_check("names-story", True, owner="story"))
        verifier = _checks(_check("verify-causation", False, owner="story"))
        outcome = evaluate_approval(code, verifier, decision=Decision.APPROVE)
        self.assertFalse(outcome.allowed)
        self.assertEqual(outcome.verifier_failures, ("verify-causation",))

        outcome = evaluate_approval(code, verifier, decision=Decision.APPROVE, overrides=["verify-causation"])
        self.assertTrue(outcome.allowed)
        self.assertEqual(outcome.overridden, ("verify-causation",))
        self.assertEqual(outcome.verifier_failures, ())

    def test_override_of_passing_or_unknown_check_is_an_error(self) -> None:
        code, verifier = _all_pass()
        with self.assertRaises(ApprovalError):
            evaluate_approval(code, verifier, decision=Decision.APPROVE, overrides=["verify-causation"])
        with self.assertRaises(ApprovalError):
            evaluate_approval(code, verifier, decision=Decision.APPROVE, overrides=["no-such-check"])

    def test_duplicate_overrides_are_an_error(self) -> None:
        code = _checks(_check("names-story", True))
        verifier = _checks(_check("verify-causation", False))
        with self.assertRaises(ApprovalError):
            evaluate_approval(
                code, verifier, decision=Decision.APPROVE,
                overrides=["verify-causation", "verify-causation"],
            )

    def test_edit_and_reject_are_never_allowed(self) -> None:
        code, verifier = _all_pass()
        edit = evaluate_approval(code, verifier, decision=Decision.EDIT)
        self.assertFalse(edit.allowed)
        self.assertIn("run again", edit.message)

        reject = evaluate_approval(code, verifier, decision=Decision.REJECT)
        self.assertFalse(reject.allowed)
        self.assertEqual(reject.message, "Rejected")

    def test_unknown_decision_is_an_error(self) -> None:
        code, verifier = _all_pass()
        with self.assertRaises(ApprovalError):
            evaluate_approval(code, verifier, decision="maybe")


class ApprovalRecordTests(unittest.TestCase):
    def test_record_shape(self) -> None:
        record = build_approval_record("r1", ["generate_keyframes"], overrides=["verify-causation"])
        self.assertEqual(record["run_id"], "r1")
        self.assertEqual(record["decision"], "approve")
        self.assertEqual(record["approved_actions"], ["generate_keyframes"])
        self.assertEqual(record["overridden_checks"], ["verify-causation"])

    def test_save_approval_writes_and_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = build_approval_record("r1", ["generate_video"])
            path = save_approval(record, workspace_root=root, run_id="r1")
            self.assertTrue(path.exists())
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["run_id"], "r1")
            with self.assertRaises(FileExistsError):
                save_approval(record, workspace_root=root, run_id="r1")


class LogApprovalTests(unittest.TestCase):
    def test_logs_approval_and_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code = _checks(_check("names-story", True))
            verifier = _checks(_check("verify-causation", False))
            outcome = evaluate_approval(code, verifier, decision=Decision.APPROVE, overrides=["verify-causation"])
            log_approval(root, "r1", outcome, approved_actions=["generate_video"])

            entries = read_entries(root, "r1")
            events = [(e["event"], e.get("check_id")) for e in entries]
            self.assertIn(("approval", None), events)
            self.assertIn(("override", "verify-causation"), events)

            approval = next(e for e in entries if e["event"] == "approval")
            self.assertTrue(approval["allowed"])
            self.assertEqual(approval["decision"], "approve")
            self.assertEqual(approval["approved_actions"], ["generate_video"])


if __name__ == "__main__":
    unittest.main()
