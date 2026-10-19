"""Tests for the Director skill (T014)."""

import json
import tempfile
import unittest
from pathlib import Path

import jsonschema

from src.providers.llm import ChatResult
from src.skills.storyboard import (
    GAG_DEVICES,
    MAX_SHOTS,
    MIN_SHOTS,
    StoryboardError,
    _coerce_duration,
    _normalize_characters,
    build_storyboard,
    gag_device,
    run,
    save_storyboard,
    validate_storyboard,
)


def _story() -> dict:
    return {
        "schema_version": "1.0",
        "title": "The Little Town's Lantern Walk",
        "fiction_label": "Fiction inspired by today's news",
        "characters": ["courier", "mayor", "pigeon"],
        "beats": [
            {"beat_index": i, "source_ref": i, "text": f"Beat {i} text."}
            for i in range(6)
        ],
    }


def _gag(device: str, beat: int) -> str:
    return f"{device}: the visual joke for beat {beat}."


def _raw_shots() -> dict:
    shots = []
    for beat in range(6):
        shots.append({
            "beat": beat,
            "characters": ["courier"],
            "camera": "wide view",
            "action": f"Action for beat {beat}.",
            "narration": f"Narration for beat {beat}.",
            "comic_caption": f"Caption {beat}",
            "duration_s": 5,
            "comic_panel": True,
            "gag": _gag(GAG_DEVICES[beat % len(GAG_DEVICES)], beat),
            "scene_setting": f"Miniature scene for beat {beat}.",
            "audio_cue": f"Soundscape for beat {beat}.",
        })
    shots.append({
        "beat": 1,
        "characters": ["pigeon"],
        "camera": "tracking",
        "action": "Extra transition.",
        "narration": "Extra one.",
        "duration_s": 5,
        "comic_panel": False,
        "gag": "Scale Contrast: an extra transition gag.",
        "scene_setting": "A tracking miniature street.",
        "audio_cue": "Soft footsteps.",
    })
    shots.append({
        "beat": 4,
        "characters": ["mayor"],
        "camera": "close-up",
        "action": "Another transition.",
        "narration": "Extra two.",
        "duration_s": 5,
        "comic_panel": False,
        "gag": "Relatable Exaggeration: an overblown reaction.",
        "scene_setting": "A close-up toy street corner.",
        "audio_cue": "A cheerful sigh.",
    })
    return {"shots": shots}


def _chat_from_message(messages):
    return ChatResult(
        content=json.dumps(_raw_shots()),
        model="deepseek-chat",
        prompt_tokens=1,
        completion_tokens=1,
    )


class DurationTests(unittest.TestCase):
    def test_clamps_below_and_above(self) -> None:
        self.assertEqual(_coerce_duration(1), 4.0)
        self.assertEqual(_coerce_duration(99), 8.0)

    def test_rounds_one_decimal(self) -> None:
        self.assertEqual(_coerce_duration(5.36), 5.4)

    def test_invalid_defaults_to_five(self) -> None:
        self.assertEqual(_coerce_duration("nope"), 5.0)


class CharactersTests(unittest.TestCase):
    def test_filters_non_cast_and_dedupes(self) -> None:
        self.assertEqual(
            _normalize_characters(["courier", "courier", "stranger", "pigeon"], ["courier", "mayor", "pigeon"]),
            ["courier", "pigeon"],
        )

    def test_caps_at_two(self) -> None:
        self.assertEqual(
            _normalize_characters(["courier", "mayor", "pigeon"], ["courier", "mayor", "pigeon"]),
            ["courier", "mayor"],
        )

    def test_defaults_to_first_cast_member(self) -> None:
        self.assertEqual(_normalize_characters([], ["courier", "mayor", "pigeon"]), ["courier"])


class GagDeviceTests(unittest.TestCase):
    def test_recognises_each_device_prefix(self) -> None:
        for device in GAG_DEVICES:
            self.assertEqual(gag_device(f"{device}: a joke"), device)

    def test_rejects_unprefixed_or_unknown(self) -> None:
        self.assertIsNone(gag_device("A joke without a device."))
        self.assertIsNone(gag_device(""))
        self.assertIsNone(gag_device("Slapstick: a different device"))


class BuildStoryboardTests(unittest.TestCase):
    def test_injects_ids_and_source_refs(self) -> None:
        storyboard = build_storyboard(_raw_shots())
        self.assertEqual(storyboard["schema_version"], "1.0")
        self.assertEqual(len(storyboard["shots"]), 8)
        for index, shot in enumerate(storyboard["shots"]):
            self.assertEqual(shot["shot_id"], f"shot-{index + 1:02d}")
            self.assertEqual(shot["source_ref"], shot["beat"])

    def test_one_panel_per_beat(self) -> None:
        storyboard = build_storyboard(_raw_shots())
        for beat in range(6):
            panels = [s for s in storyboard["shots"] if s["beat"] == beat and s["comic_panel"]]
            self.assertEqual(len(panels), 1, f"beat {beat} should have exactly one panel")

    def test_non_panel_shots_drop_caption(self) -> None:
        storyboard = build_storyboard(_raw_shots())
        for shot in storyboard["shots"]:
            if not shot["comic_panel"]:
                self.assertNotIn("comic_caption", shot)
            else:
                self.assertIn("comic_caption", shot)

    def test_panel_gets_caption_from_narration_when_missing(self) -> None:
        raw = {"shots": []}
        for beat in range(6):
            raw["shots"].append({
                "beat": beat,
                "camera": "wide",
                "action": "a",
                "narration": f"n {beat}",
                "duration_s": 5,
                "comic_panel": True,
                "gag": _gag(GAG_DEVICES[beat % len(GAG_DEVICES)], beat),
                "scene_setting": "a miniature scene",
                "audio_cue": "a soundscape",
            })
        raw["shots"].append({"beat": 1, "camera": "track", "action": "x", "narration": "e1", "duration_s": 5, "comic_panel": False, "gag": "Scale Contrast: a gag", "scene_setting": "s", "audio_cue": "a"})
        raw["shots"].append({"beat": 4, "camera": "close", "action": "y", "narration": "e2", "duration_s": 5, "comic_panel": False, "gag": "Absurd Literalization: a gag", "scene_setting": "s", "audio_cue": "a"})
        storyboard = build_storyboard(raw)
        for shot in storyboard["shots"]:
            if shot["comic_panel"]:
                self.assertTrue(shot["comic_caption"])

    def test_too_few_shots_raises(self) -> None:
        with self.assertRaises(StoryboardError):
            build_storyboard({"shots": [{"beat": 0, "camera": "w", "action": "a"}]})

    def test_too_many_shots_raises(self) -> None:
        raw = {"shots": []}
        for _ in range(MAX_SHOTS + 1):
            raw["shots"].append({"beat": 0, "camera": "w", "action": "a"})
        with self.assertRaises(StoryboardError):
            build_storyboard(raw)

    def test_invalid_beat_raises(self) -> None:
        raw = _raw_shots()
        raw["shots"][0]["beat"] = 7
        with self.assertRaises(StoryboardError):
            build_storyboard(raw)

    def test_missing_camera_raises(self) -> None:
        raw = _raw_shots()
        del raw["shots"][0]["camera"]
        with self.assertRaises(StoryboardError):
            build_storyboard(raw)

    def test_missing_gag_raises(self) -> None:
        raw = _raw_shots()
        del raw["shots"][0]["gag"]
        with self.assertRaises(StoryboardError):
            build_storyboard(raw)

    def test_unlabelled_gag_raises(self) -> None:
        raw = _raw_shots()
        raw["shots"][0]["gag"] = "a joke with no device prefix"
        with self.assertRaises(StoryboardError):
            build_storyboard(raw)

    def test_missing_scene_setting_raises(self) -> None:
        raw = _raw_shots()
        del raw["shots"][0]["scene_setting"]
        with self.assertRaises(StoryboardError):
            build_storyboard(raw)

    def test_uncovered_beat_raises(self) -> None:
        # 8 shots across beats 0-4 only, leaving beat 5 uncovered.
        shots = []
        for i in range(MIN_SHOTS):
            shots.append({
                "beat": i % 5,
                "camera": "w",
                "action": "a",
                "narration": "n",
                "duration_s": 5,
                "gag": _gag(GAG_DEVICES[i % len(GAG_DEVICES)], i),
                "scene_setting": "s",
                "audio_cue": "a",
            })
        with self.assertRaises(StoryboardError):
            build_storyboard({"shots": shots})


class ValidateStoryboardTests(unittest.TestCase):
    def test_valid_storyboard_passes(self) -> None:
        self.assertEqual(validate_storyboard(build_storyboard(_raw_shots())), [])

    def test_invalid_storyboard_reports_errors(self) -> None:
        storyboard = build_storyboard(_raw_shots())
        storyboard["shots"][0]["characters"] = ["courier", "mayor", "pigeon"]
        self.assertTrue(validate_storyboard(storyboard))

    def test_fixture_storyboard_is_valid(self) -> None:
        fixture = json.loads(
            (Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "t006-sample" / "storyboard.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(validate_storyboard(fixture), [])


class SaveStoryboardTests(unittest.TestCase):
    def test_save_and_refuse_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            storyboard = build_storyboard(_raw_shots())
            path = save_storyboard(storyboard, workspace_root=root, run_id="r1")
            self.assertTrue(path.exists())
            with self.assertRaises(FileExistsError):
                save_storyboard(storyboard, workspace_root=root, run_id="r1")


class RunTests(unittest.TestCase):
    def test_run_end_to_end_schema_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = run(_story(), workspace_root=root, run_id="r1", chat=_chat_from_message)
            self.assertEqual(result["errors"], [])

            schema = json.loads(
                (Path(__file__).resolve().parents[2] / "schemas" / "storyboard.schema.json").read_text(
                    encoding="utf-8"
                )
            )
            jsonschema.Draft202012Validator(schema).validate(result["document"])

            self.assertTrue((root / "runs" / "r1" / "storyboard.json").exists())


if __name__ == "__main__":
    unittest.main()
