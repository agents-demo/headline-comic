"""Tests for the Verifier skill (T016)."""

import json
import tempfile
import unittest
from pathlib import Path

import jsonschema

from src.providers.llm import ChatResult
from src.skills.verifier import (
    VERIFIER_MODEL,
    _coerce_bool,
    _parse_reply,
    _verdicts_from,
    build_verifier_document,
    run,
    save_verifier,
)

_FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "t006-sample"


def _load(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def _ledger() -> dict:
    return _load("ledger.json")


def _story() -> dict:
    return _load("story.json")


def _storyboard() -> dict:
    return _load("storyboard.json")


def _summaries() -> dict:
    facts = {
        "story-1": ["f1-1", "f1-2"],
        "story-2": ["f2-1"],
        "story-3": ["f3-1"],
        "story-4": ["f4-1"],
        "story-5": ["f5-1"],
    }
    return {
        "schema_version": "1.0",
        "summaries": [
            {
                "story_id": story_id,
                "sentences": [
                    {"text": f"{story_id} first sentence.", "ledger_fact_ids": [ids[0]]},
                    {"text": f"{story_id} second sentence.", "ledger_fact_ids": [ids[-1]]},
                ],
            }
            for story_id, ids in facts.items()
        ],
    }


def _verdicts_raw(passed: bool = True) -> dict:
    ids = ["verify-summaries", "verify-causation", "verify-real-people", "verify-graphic", "verify-satire"]
    return {"items": [{"check_id": cid, "passed": passed, "reason": f"ok {cid}"} for cid in ids]}


def _chat_from_message(passed: bool = True):
    def chat(messages):
        return ChatResult(content=json.dumps(_verdicts_raw(passed)), model="deepseek-reasoner", prompt_tokens=1, completion_tokens=1)
    return chat


class ParseReplyTests(unittest.TestCase):
    def test_fenced_json(self) -> None:
        self.assertEqual(_parse_reply('```json\n{"items": []}\n```')["items"], [])

    def test_non_json_returns_empty(self) -> None:
        self.assertEqual(_parse_reply("just prose"), {})


class CoerceBoolTests(unittest.TestCase):
    def test_bool(self) -> None:
        self.assertTrue(_coerce_bool(True))
        self.assertFalse(_coerce_bool(False))

    def test_strings(self) -> None:
        self.assertTrue(_coerce_bool("true"))
        self.assertTrue(_coerce_bool("yes"))
        self.assertFalse(_coerce_bool("false"))
        self.assertFalse(_coerce_bool("no"))


class VerdictsTests(unittest.TestCase):
    def test_maps_all_five_ids(self) -> None:
        verdicts = _verdicts_from(_verdicts_raw())
        self.assertEqual([v["check_id"] for v in verdicts], [
            "verify-summaries", "verify-causation", "verify-real-people", "verify-graphic", "verify-satire",
        ])
        self.assertTrue(all(v["passed"] for v in verdicts))

    def test_missing_item_fails_closed(self) -> None:
        raw = _verdicts_raw()
        raw["items"] = raw["items"][:-1]  # drop the last item
        verdicts = _verdicts_from(raw)
        self.assertFalse(verdicts[-1]["passed"])
        self.assertIn("did not report", verdicts[-1]["reason"])

    def test_string_false_is_false(self) -> None:
        raw = _verdicts_raw()
        raw["items"][0]["passed"] = "false"
        verdicts = _verdicts_from(raw)
        self.assertFalse(verdicts[0]["passed"])


class DocumentTests(unittest.TestCase):
    def test_document_shape_and_schema(self) -> None:
        document = build_verifier_document(_verdicts_from(_verdicts_raw()))
        self.assertTrue(document["passed"])
        self.assertEqual(len(document["checks"]), 5)
        for check in document["checks"]:
            self.assertEqual(check["owner"], "summary" if check["check_id"] == "verify-summaries" else "story")

        schema = json.loads(
            (Path(__file__).resolve().parents[2] / "schemas" / "checks.schema.json").read_text(encoding="utf-8")
        )
        jsonschema.Draft202012Validator(schema).validate(document)

    def test_failing_verdict_flips_pass(self) -> None:
        raw = _verdicts_raw()
        raw["items"][1]["passed"] = False
        document = build_verifier_document(_verdicts_from(raw))
        self.assertFalse(document["passed"])


class RunTests(unittest.TestCase):
    def test_run_writes_verifier_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = run(
                _ledger(), _summaries(), _story(), _storyboard(),
                workspace_root=root, run_id="r1", chat=_chat_from_message(True),
            )
            self.assertTrue(result["passed"])
            written = json.loads((root / "runs" / "r1" / "verifier.json").read_text(encoding="utf-8"))
            self.assertEqual(len(written["checks"]), 5)
            self.assertTrue(written["passed"])

    def test_run_returns_failure_when_verifier_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = run(
                _ledger(), _summaries(), _story(), _storyboard(),
                workspace_root=root, run_id="r1", chat=_chat_from_message(False),
            )
            self.assertFalse(result["passed"])


class SaveVerifierTests(unittest.TestCase):
    def test_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            document = build_verifier_document(_verdicts_from(_verdicts_raw()))
            save_verifier(document, workspace_root=root, run_id="r1")
            with self.assertRaises(FileExistsError):
                save_verifier(document, workspace_root=root, run_id="r1")


class ModelConfigTests(unittest.TestCase):
    def test_verifier_uses_different_model(self) -> None:
        self.assertEqual(VERIFIER_MODEL, "deepseek-reasoner")


if __name__ == "__main__":
    unittest.main()
