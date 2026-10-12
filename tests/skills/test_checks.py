"""Tests for the deterministic checks skill (T015)."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

import jsonschema

from src.skills.checks import (
    Check,
    _contains_any_name,
    build_checks_document,
    check_beats,
    check_citations,
    check_storyboard_characters,
    check_storyboard_duration,
    check_storyboard_narration,
    check_storyboard_panels,
    ledger_names,
    run,
    run_checks,
    save_checks,
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
    summaries = [
        {
            "story_id": story_id,
            "sentences": [
                {"text": f"{story_id} first sentence.", "ledger_fact_ids": [ids[0]]},
                {"text": f"{story_id} second sentence.", "ledger_fact_ids": [ids[-1]]},
            ],
        }
        for story_id, ids in facts.items()
    ]
    return {"schema_version": "1.0", "summaries": summaries}


class NameMatchTests(unittest.TestCase):
    def test_full_name_and_surname(self) -> None:
        names = {"John Smith"}
        self.assertEqual(_contains_any_name("John Smith visited town.", names), ["John Smith"])
        self.assertEqual(_contains_any_name("Smith waved at the crowd.", names), ["John Smith"])

    def test_whole_word_only(self) -> None:
        names = {"John Smith"}
        self.assertEqual(_contains_any_name("The Smithsonian opened.", names), [])
        self.assertEqual(_contains_any_name("No names here.", names), [])

    def test_ledger_names_extraction(self) -> None:
        self.assertEqual(ledger_names(_ledger()), set())


class RunChecksTests(unittest.TestCase):
    def test_all_checks_pass_on_fixture(self) -> None:
        checks = run_checks(_ledger(), _summaries(), _story(), _storyboard())
        self.assertEqual(len(checks), 12)
        self.assertTrue(all(check.passed for check in checks), [c.message for c in checks if not c.passed])
        self.assertTrue(build_checks_document(checks)["passed"])

    def test_name_in_story_fails(self) -> None:
        ledger = _ledger()
        ledger["stories"][0]["people"] = ["John Smith"]
        story = copy.deepcopy(_story())
        story["title"] = "John Smith's Big Walk"
        checks = run_checks(ledger, _summaries(), story, _storyboard())
        names = next(c for c in checks if c.check_id == "names-story")
        self.assertFalse(names.passed)
        self.assertEqual(names.owner, "story")

    def test_name_in_storyboard_fails(self) -> None:
        ledger = _ledger()
        ledger["stories"][0]["people"] = ["John Smith"]
        storyboard = copy.deepcopy(_storyboard())
        storyboard["shots"][0]["narration"] = "John Smith waved at the crowd."
        checks = run_checks(ledger, _summaries(), _story(), storyboard)
        names = next(c for c in checks if c.check_id == "names-storyboard")
        self.assertFalse(names.passed)
        self.assertEqual(names.owner, "storyboard")


class BeatCheckTests(unittest.TestCase):
    def test_valid_beats_pass(self) -> None:
        self.assertTrue(check_beats(_story()).passed)

    def test_missing_ending_fails(self) -> None:
        story = copy.deepcopy(_story())
        del story["beats"][-1]["ending"]
        self.assertFalse(check_beats(story).passed)

    def test_wrong_mapping_fails(self) -> None:
        story = copy.deepcopy(_story())
        story["beats"][2]["source_ref"] = 4
        self.assertFalse(check_beats(story).passed)


class StoryboardCheckTests(unittest.TestCase):
    def test_panels_pass(self) -> None:
        self.assertTrue(check_storyboard_panels(_storyboard()).passed)

    def test_two_panels_on_one_beat_fail(self) -> None:
        storyboard = copy.deepcopy(_storyboard())
        storyboard["shots"][2]["comic_panel"] = True  # beat 1 already has a panel
        self.assertFalse(check_storyboard_panels(storyboard).passed)

    def test_characters_pass(self) -> None:
        self.assertTrue(check_storyboard_characters(_storyboard()).passed)

    def test_three_characters_fail(self) -> None:
        storyboard = copy.deepcopy(_storyboard())
        storyboard["shots"][0]["characters"] = ["courier", "mayor", "pigeon"]
        self.assertFalse(check_storyboard_characters(storyboard).passed)

    def test_narration_rate_pass(self) -> None:
        self.assertTrue(check_storyboard_narration(_storyboard()).passed)

    def test_narration_rate_fail(self) -> None:
        storyboard = copy.deepcopy(_storyboard())
        storyboard["shots"][0]["narration"] = " ".join(["word"] * 15)
        storyboard["shots"][0]["duration_s"] = 5
        self.assertFalse(check_storyboard_narration(storyboard).passed)

    def test_duration_sum_pass(self) -> None:
        self.assertTrue(check_storyboard_duration(_storyboard()).passed)

    def test_duration_sum_fail(self) -> None:
        storyboard = copy.deepcopy(_storyboard())
        for shot in storyboard["shots"]:
            shot["duration_s"] = 4
        self.assertFalse(check_storyboard_duration(storyboard).passed)


class CitationCheckTests(unittest.TestCase):
    def test_valid_citations_pass(self) -> None:
        self.assertTrue(check_citations(_ledger(), _summaries()).passed)

    def test_uncited_sentence_fails(self) -> None:
        summaries = _summaries()
        summaries["summaries"][0]["sentences"][0]["ledger_fact_ids"] = []
        self.assertFalse(check_citations(_ledger(), summaries).passed)

    def test_unknown_id_fails(self) -> None:
        summaries = _summaries()
        summaries["summaries"][0]["sentences"][0]["ledger_fact_ids"] = ["f9-9"]
        self.assertFalse(check_citations(_ledger(), summaries).passed)

    def test_wrong_sentence_count_fails(self) -> None:
        summaries = _summaries()
        summaries["summaries"][0]["sentences"] = summaries["summaries"][0]["sentences"][:1]
        self.assertFalse(check_citations(_ledger(), summaries).passed)


class SaveAndRunTests(unittest.TestCase):
    def test_run_writes_schema_valid_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = run(
                _ledger(), _summaries(), _story(), _storyboard(),
                workspace_root=root, run_id="r1",
            )
            self.assertTrue(result["passed"])
            self.assertTrue(result["document"]["passed"])

            schema = json.loads(
                (Path(__file__).resolve().parents[2] / "schemas" / "checks.schema.json").read_text(encoding="utf-8")
            )
            jsonschema.Draft202012Validator(schema).validate(result["document"])

            written = json.loads((root / "runs" / "r1" / "checks.json").read_text(encoding="utf-8"))
            self.assertEqual(len(written["checks"]), 12)

    def test_save_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            document = build_checks_document(run_checks(_ledger(), _summaries(), _story(), _storyboard()))
            save_checks(document, workspace_root=root, run_id="r1")
            with self.assertRaises(FileExistsError):
                save_checks(document, workspace_root=root, run_id="r1")


class CheckDataclassTests(unittest.TestCase):
    def test_as_dict_shape(self) -> None:
        check = Check("x", True, "ok", "story", "story.json")
        self.assertEqual(
            check.as_dict(),
            {"check_id": "x", "passed": True, "blocking": True, "message": "ok", "path": "story.json", "owner": "story"},
        )

    def test_failing_check_flips_overall_pass(self) -> None:
        document = build_checks_document([Check("a", True, "ok", "system"), Check("b", False, "bad", "system")])
        self.assertFalse(document["passed"])


if __name__ == "__main__":
    unittest.main()
