"""Deterministic comic-page composition tests (T024)."""

import json
import os
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from src.skills.compose import (
    AI_GENERATED_MARK,
    COLS,
    FOOTER_H,
    GUTTER,
    HEADER_H,
    MARGIN,
    PAGE_W,
    ROWS,
    ComposeError,
    compose_comic,
    page_size,
    panel_shots,
    run,
)

FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "t006-sample" / "storyboard.json"
FIXTURE_STORY = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "t006-sample" / "story.json"


def _write_keyframes(directory: Path, shot_ids) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for index, shot_id in enumerate(shot_ids):
        color = (60 + index * 25, 120 + index * 12, 180 + index * 8)
        Image.new("RGB", (64, 36), color).save(directory / f"{shot_id}.png")


def _storyboard(shots) -> dict:
    return {"schema_version": "1.0", "shots": shots}


class PanelShotsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_selects_six_panels_one_per_beat_in_order(self) -> None:
        panels = panel_shots(self.fixture)
        self.assertEqual([p["beat"] for p in panels], [0, 1, 2, 3, 4, 5])
        self.assertTrue(all(p["comic_panel"] is True for p in panels))

    def test_missing_beat_panel_raises(self) -> None:
        shots = [
            {"shot_id": "s0", "beat": 0, "comic_panel": True},
            {"shot_id": "s1", "beat": 1, "comic_panel": False},
        ]
        with self.assertRaises(ComposeError):
            panel_shots(_storyboard(shots))

    def test_duplicate_beat_panel_raises(self) -> None:
        shots = [{"shot_id": f"s{b}", "beat": b, "comic_panel": True} for b in range(6)]
        shots.append({"shot_id": "s6", "beat": 3, "comic_panel": True})
        with self.assertRaises(ComposeError):
            panel_shots(_storyboard(shots))


class PageSizeTests(unittest.TestCase):
    def test_deterministic_page_size(self) -> None:
        panel_w = (PAGE_W - 2 * MARGIN - (COLS - 1) * GUTTER) // COLS
        panel_h = int(panel_w * 9 / 16)
        expected_h = MARGIN + HEADER_H + ROWS * panel_h + (ROWS - 1) * GUTTER + FOOTER_H + MARGIN
        self.assertEqual(page_size(), (PAGE_W, expected_h))
        # HEADER_H is the 112px page header; the facts-strip header is a separate
        # constant (STRIP_HEADER_H) and must not shadow it. Pin the real value.
        self.assertEqual(page_size(), (1280, 1298))


class ComposeComicTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.storyboard = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.story = json.loads(FIXTURE_STORY.read_text(encoding="utf-8"))
        self.keyframes = self.root / "keyframes"
        _write_keyframes(self.keyframes, [s["shot_id"] for s in self.storyboard["shots"]])

    def tearDown(self) -> None:
        self._temp.cleanup()

    def _keyframe_bytes(self) -> dict:
        return {
            p.name: p.read_bytes()
            for p in self.keyframes.glob("*.png")
        }

    def test_writes_page_and_panel_copies_without_touching_clean_keyframes(self) -> None:
        before = self._keyframe_bytes()
        output = self.root / "comic.png"
        panels_dir = self.root / "panels"
        result = compose_comic(
            self.storyboard,
            self.keyframes,
            title=self.story["title"],
            fiction_label=self.story["fiction_label"],
            output_path=output,
            panels_dir=panels_dir,
        )
        self.assertEqual(result, output)
        self.assertTrue(output.is_file())
        with Image.open(output) as image:
            self.assertEqual(image.size, page_size())
        self.assertEqual(sorted(p.name for p in panels_dir.glob("*.png")), [p["shot_id"] + ".png" for p in panel_shots(self.storyboard)])
        # clean keyframes are read-only
        self.assertEqual(before, self._keyframe_bytes())

    def test_page_contains_ink_text(self) -> None:
        output = self.root / "comic.png"
        compose_comic(
            self.storyboard,
            self.keyframes,
            title=self.story["title"],
            fiction_label=self.story["fiction_label"],
            output_path=output,
        )
        with Image.open(output) as image:
            data = image.convert("RGB").tobytes()
            dark = sum(1 for i in range(0, len(data), 3) if data[i] < 100 and data[i + 1] < 100 and data[i + 2] < 100)
        self.assertGreater(dark, 500)  # captions, bubbles, markers, title, footer all draw ink

    def test_missing_keyframe_raises(self) -> None:
        (self.keyframes / "shot-08.png").unlink()
        with self.assertRaises(ComposeError):
            compose_comic(
                self.storyboard,
                self.keyframes,
                title="T",
                fiction_label="F",
                output_path=self.root / "comic.png",
            )


class SourceMarkerTests(unittest.TestCase):
    def _panel_region_min_brightness(self, page: Image.Image, beat: int) -> int:
        panel_w = (PAGE_W - 2 * MARGIN - (COLS - 1) * GUTTER) // COLS
        panel_h = int(panel_w * 9 / 16)
        col = beat % COLS
        row = beat // COLS
        x0 = MARGIN + col * (panel_w + GUTTER) + panel_w - 48
        y0 = MARGIN + HEADER_H + row * (panel_h + GUTTER) + 8
        region = page.crop((x0, y0, x0 + 40, y0 + 24)).convert("L")
        return min(region.tobytes())

    def test_marker_only_on_source_panels(self) -> None:
        shots = []
        for beat in range(6):
            shots.append(
                {
                    "shot_id": f"shot-{beat:02d}",
                    "beat": beat,
                    "source_ref": beat,
                    "comic_panel": True,
                    "comic_caption": "Caption.",
                }
            )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            keyframes = root / "keyframes"
            keyframes.mkdir(parents=True, exist_ok=True)
            for shot in shots:
                # white keyframes isolate the ink marker chip from the art itself
                Image.new("RGB", (64, 36), (255, 255, 255)).save(keyframes / f"{shot['shot_id']}.png")
            output = root / "comic.png"
            compose_comic(
                _storyboard(shots),
                keyframes,
                title="T",
                fiction_label="F",
                output_path=output,
            )
            page = Image.open(output).convert("RGB")
            # beat 0 (source_ref 0) has no marker chip; beats 1-5 do (dark ink).
            self.assertGreater(self._panel_region_min_brightness(page, 0), 200)
            for beat in (1, 5):
                self.assertLess(self._panel_region_min_brightness(page, beat), 100)


class RunTests(unittest.TestCase):
    def test_run_writes_comic_and_panels_under_run_dir(self) -> None:
        storyboard = json.loads(FIXTURE.read_text(encoding="utf-8"))
        story = json.loads(FIXTURE_STORY.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run_dir = root / "runs" / "demo"
            keyframes = run_dir / "keyframes"
            _write_keyframes(keyframes, [s["shot_id"] for s in storyboard["shots"]])
            result = run(story, storyboard, workspace_root=root, run_id="demo")
            self.assertTrue(result.is_file())
            self.assertTrue(os.path.samefile(result, run_dir / "comic.png"))
            self.assertEqual(len(list((run_dir / "panels").glob("*.png"))), 6)


if __name__ == "__main__":
    unittest.main()
