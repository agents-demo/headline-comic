"""Tests for the Writer skill (T013)."""

import json
import tempfile
import unittest
from pathlib import Path

import jsonschema

from src.providers.llm import ChatResult
from src.skills.story import (
    BEAT_COUNT,
    DEFAULT_CAST,
    FICTION_LABEL,
    StoryError,
    _parse_reply,
    build_story,
    run,
    save_story,
    validate_story,
)


def _summaries(count: int = 5) -> list[dict]:
    return [
        {
            "story_id": f"story-{i}",
            "sentences": [
                {"text": f"Summary {i} sentence one.", "ledger_fact_ids": [f"f{i}-1"]},
                {"text": f"Summary {i} sentence two.", "ledger_fact_ids": [f"f{i}-2"]},
            ],
        }
        for i in range(1, count + 1)
    ]


def _raw(title: str = "The Little Town's Lantern Walk", beats: list[str] | None = None) -> dict:
    beats = beats or [f"Beat {i} text." for i in range(BEAT_COUNT)]
    return {"title": title, "beats": [{"text": text} for text in beats]}


def _chat_from_message(messages):
    return ChatResult(
        content=json.dumps(_raw()),
        model="deepseek-chat",
        prompt_tokens=1,
        completion_tokens=1,
    )


class ParseReplyTests(unittest.TestCase):
    def test_plain_json(self) -> None:
        self.assertEqual(_parse_reply('{"title": "t"}')["title"], "t")

    def test_fenced_json(self) -> None:
        self.assertEqual(_parse_reply('```json\n{"title": "t"}\n```')["title"], "t")

    def test_invalid_returns_empty(self) -> None:
        self.assertEqual(_parse_reply("not json"), {})


class BuildStoryTests(unittest.TestCase):
    def test_injects_structure(self) -> None:
        story = build_story(_raw())
        self.assertEqual(story["schema_version"], "1.0")
        self.assertEqual(story["title"], "The Little Town's Lantern Walk")
        self.assertEqual(story["fiction_label"], FICTION_LABEL)
        self.assertEqual(story["characters"], list(DEFAULT_CAST))
        self.assertEqual(len(story["beats"]), BEAT_COUNT)
        for index, beat in enumerate(story["beats"]):
            self.assertEqual(beat["beat_index"], index)
            self.assertEqual(beat["source_ref"], index)
        self.assertTrue(story["beats"][-1]["ending"])
        self.assertNotIn("ending", story["beats"][0])

    def test_custom_cast(self) -> None:
        story = build_story(_raw(), characters=("courier", "pigeon"))
        self.assertEqual(story["characters"], ["courier", "pigeon"])

    def test_missing_title_raises(self) -> None:
        with self.assertRaises(StoryError):
            build_story({"title": "", "beats": [{"text": "x"}] * BEAT_COUNT})

    def test_wrong_beat_count_raises(self) -> None:
        with self.assertRaises(StoryError):
            build_story({"title": "t", "beats": [{"text": "x"}] * 3})

    def test_empty_beat_raises(self) -> None:
        beats = [f"Beat {i} text." for i in range(BEAT_COUNT)]
        beats[2] = "   "
        with self.assertRaises(StoryError):
            build_story({"title": "t", "beats": [{"text": b} for b in beats]})


class ValidateStoryTests(unittest.TestCase):
    def test_valid_story_passes(self) -> None:
        self.assertEqual(validate_story(build_story(_raw())), [])

    def test_invalid_story_reports_errors(self) -> None:
        story = build_story(_raw())
        del story["title"]
        self.assertTrue(validate_story(story))

    def test_fixture_story_is_valid(self) -> None:
        fixture = json.loads(
            (Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "t006-sample" / "story.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(validate_story(fixture), [])


class SaveStoryTests(unittest.TestCase):
    def test_save_and_refuse_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            story = build_story(_raw())
            path = save_story(story, workspace_root=root, run_id="r1")
            self.assertTrue(path.exists())
            self.assertTrue((root / "runs" / "r1" / "story.json").exists())
            with self.assertRaises(FileExistsError):
                save_story(story, workspace_root=root, run_id="r1")


class RunTests(unittest.TestCase):
    def test_run_end_to_end_schema_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = run(_summaries(), workspace_root=root, run_id="r1", chat=_chat_from_message)
            self.assertEqual(result["errors"], [])

            schema = json.loads(
                (Path(__file__).resolve().parents[2] / "schemas" / "story.schema.json").read_text(encoding="utf-8")
            )
            jsonschema.Draft202012Validator(schema).validate(result["document"])

            written = json.loads((root / "runs" / "r1" / "story.json").read_text(encoding="utf-8"))
            self.assertEqual(written["title"], "The Little Town's Lantern Walk")
            self.assertEqual(len(written["beats"]), BEAT_COUNT)


if __name__ == "__main__":
    unittest.main()
