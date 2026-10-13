"""SC-2 character-check protocol tests (T025)."""

import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from src.skills.character_check import (
    CAST_NAMES,
    SIGNATURE_COLOURS,
    CharacterCheckError,
    build_deck,
    check_cast_sheet,
    check_signature_colours,
    deck_items,
    run,
    score_deck,
)

FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "t006-sample" / "storyboard.json"


def _write_keyframes(directory: Path, shot_ids) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for shot_id in shot_ids:
        Image.new("RGB", (64, 36), (200, 200, 200)).save(directory / f"{shot_id}.png")


class DeckItemsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.storyboard = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.keyframes = self.root / "keyframes"
        _write_keyframes(self.keyframes, [s["shot_id"] for s in self.storyboard["shots"]])

    def tearDown(self) -> None:
        self._temp.cleanup()

    def test_one_item_per_shot_with_ground_truth(self) -> None:
        items = deck_items(self.storyboard, self.keyframes)
        self.assertEqual(len(items), len(self.storyboard["shots"]))
        by_shot = {item["shot_id"]: item for item in items}
        for shot in self.storyboard["shots"]:
            item = by_shot[shot["shot_id"]]
            self.assertEqual(item["characters"], sorted(shot["characters"]))
            self.assertEqual(item["kind"], "panel" if shot["comic_panel"] else "frame")
        panels = [item for item in items if item["kind"] == "panel"]
        self.assertEqual(len(panels), 6)

    def test_missing_keyframe_raises(self) -> None:
        (self.keyframes / "shot-03.png").unlink()
        with self.assertRaises(CharacterCheckError):
            deck_items(self.storyboard, self.keyframes)


class BuildDeckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.storyboard = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.keyframes = self.root / "keyframes"
        _write_keyframes(self.keyframes, [s["shot_id"] for s in self.storyboard["shots"]])

    def tearDown(self) -> None:
        self._temp.cleanup()

    def _build(self, out: Path, seed: int) -> dict:
        return build_deck(self.storyboard, self.keyframes, output_dir=out, run_id="demo", seed=seed)

    def test_writes_deck_answer_key_and_sheet(self) -> None:
        out = self.root / "cc"
        doc = self._build(out, seed=7)
        self.assertEqual(len(doc["items"]), 8)
        self.assertEqual(sorted(p.name for p in (out / "deck").glob("*.png")), [f"item-{i:02d}.png" for i in range(1, 9)])
        answer_key = json.loads((out / "answer-key.json").read_text(encoding="utf-8"))
        for item in doc["items"]:
            self.assertEqual(answer_key[item["item_id"]]["shot_id"], item["shot_id"])
            self.assertEqual(answer_key[item["item_id"]]["characters"], item["characters"])
        sheet = (out / "sheet.md").read_text(encoding="utf-8")
        for item in doc["items"]:
            self.assertIn(item["item_id"], sheet)

    def test_shuffle_is_a_permutation_of_shots(self) -> None:
        doc = self._build(self.root / "cc", seed=7)
        shot_ids = sorted(item["shot_id"] for item in doc["items"])
        self.assertEqual(shot_ids, sorted(s["shot_id"] for s in self.storyboard["shots"]))

    def test_same_seed_reproduces_same_order(self) -> None:
        first = self._build(self.root / "a", seed=7)
        second = self._build(self.root / "b", seed=7)
        self.assertEqual([i["shot_id"] for i in first["items"]], [i["shot_id"] for i in second["items"]])

    def test_different_seed_shuffles_differently(self) -> None:
        first = self._build(self.root / "a", seed=7)
        second = self._build(self.root / "b", seed=8)
        self.assertNotEqual([i["shot_id"] for i in first["items"]], [i["shot_id"] for i in second["items"]])

    def test_refuses_to_overwrite(self) -> None:
        out = self.root / "cc"
        self._build(out, seed=7)
        with self.assertRaises(FileExistsError):
            self._build(out, seed=7)


class ScoreDeckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.storyboard = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.keyframes = self.root / "keyframes"
        _write_keyframes(self.keyframes, [s["shot_id"] for s in self.storyboard["shots"]])
        self.deck = build_deck(self.storyboard, self.keyframes, output_dir=self.root / "cc", run_id="demo", seed=7)

    def tearDown(self) -> None:
        self._temp.cleanup()

    def _perfect_labels(self) -> dict:
        return {item["item_id"]: item["characters"] for item in self.deck["items"]}

    def test_perfect_labels_score_full(self) -> None:
        result = score_deck(self.deck, self._perfect_labels())
        self.assertEqual(result["panel"]["accuracy"], 1.0)
        self.assertEqual(result["frame"]["accuracy"], 1.0)
        self.assertTrue(result["panel_pass"] and result["frame_pass"])

    def test_missed_character_lowers_accuracy(self) -> None:
        labels = self._perfect_labels()
        # drop every character from a two-character panel item
        panel_item = next(i for i in self.deck["items"] if i["kind"] == "panel" and len(i["characters"]) == 2)
        labels[panel_item["item_id"]] = panel_item["characters"][:1]
        result = score_deck(self.deck, labels)
        self.assertLess(result["panel"]["accuracy"], 1.0)

    def test_unknown_label_fails_closed(self) -> None:
        labels = self._perfect_labels()
        first = self.deck["items"][0]["item_id"]
        labels[first] = ["superhero"]
        with self.assertRaises(CharacterCheckError):
            score_deck(self.deck, labels)


class SignatureColourTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)

    def tearDown(self) -> None:
        self._temp.cleanup()

    def _sheet(self, colours, name="sheet.png") -> Path:
        image = Image.new("RGB", (40, 24), (255, 255, 255))
        for index, colour in enumerate(colours):
            for x in range(index * 8, index * 8 + 6):
                for y in range(4, 18):
                    image.putpixel((x, y), colour)
        path = self.root / name
        image.save(path)
        return path

    def test_present_colours_are_detected(self) -> None:
        sheet = self._sheet([(46, 111, 149), (244, 201, 93)])
        self.assertEqual(
            check_signature_colours(sheet, [(46, 111, 149), (244, 201, 93), (192, 57, 43)]),
            [(46, 111, 149), (244, 201, 93)],
        )

    def test_tolerance_matches_antialiased_fill(self) -> None:
        sheet = self._sheet([(49, 115, 152)])  # within tolerance 8 of courier cap #2e6f95
        self.assertIn((46, 111, 149), check_signature_colours(sheet, [(46, 111, 149)]))

    def test_every_cast_member_has_unique_and_shared_marks(self) -> None:
        self.assertEqual(sorted(SIGNATURE_COLOURS), list(CAST_NAMES))
        # a colour unique to each character must be present in its own set
        unique = {"courier": (46, 111, 149), "mayor": (192, 57, 43), "pigeon": (51, 71, 91)}
        for name, colour in unique.items():
            self.assertIn(colour, SIGNATURE_COLOURS[name])

    def test_check_cast_sheet_ok_and_missing(self) -> None:
        sheet = self._sheet(SIGNATURE_COLOURS["mayor"], name="mayor.png")
        result = check_cast_sheet(sheet, "mayor")
        self.assertTrue(result["ok"])
        self.assertEqual(result["missing"], [])

        bare = self._sheet([(46, 111, 149)], name="bare.png")
        missing = check_cast_sheet(bare, "mayor")
        self.assertFalse(missing["ok"])
        self.assertIn((192, 57, 43), missing["missing"])

    def test_unknown_character_fails_closed(self) -> None:
        with self.assertRaises(CharacterCheckError):
            check_cast_sheet(self.root / "x.png", "superhero")


class RunTests(unittest.TestCase):
    def test_run_writes_deck_under_run_dir(self) -> None:
        storyboard = json.loads(FIXTURE.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run_dir = root / "runs" / "demo"
            _write_keyframes(run_dir / "keyframes", [s["shot_id"] for s in storyboard["shots"]])
            doc = run(storyboard, workspace_root=root, run_id="demo", seed=11)
            self.assertEqual(doc["run_id"], "demo")
            self.assertTrue((run_dir / "character-check" / "deck.json").is_file())
            self.assertEqual(len(list((run_dir / "character-check" / "deck").glob("*.png"))), 8)
            # second call refuses to overwrite the deck
            with self.assertRaises(FileExistsError):
                run(storyboard, workspace_root=root, run_id="demo", seed=11)


if __name__ == "__main__":
    unittest.main()
