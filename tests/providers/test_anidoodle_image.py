"""Focused tests for the AniDoodle image adapter without launching a renderer."""

import json
from pathlib import Path
import tempfile
import unittest

from src.providers.anidoodle_image import AniDoodleImageProvider, render_scenes_ts
from src.providers.contracts import ImageRequest


class RenderScenesTsTests(unittest.TestCase):
    def test_serializes_export_const_scenes(self) -> None:
        text = render_scenes_ts([{"shot_id": "shot-01", "camera": {"mode": "overhead"}}])
        self.assertIn("export const scenes =", text)
        self.assertIn('"shot_id": "shot-01"', text)
        self.assertTrue(text.rstrip().endswith(";"))


class AniDoodleImageProviderTests(unittest.TestCase):
    def make_provider(self, root: Path) -> AniDoodleImageProvider:
        script = root / "scripts" / "anidoodle" / "render_keyframes.mjs"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text("// test fixture", encoding="utf-8")
        still = root / "anidoodle" / "skills" / "anidoodle" / "engine" / "tools" / "still.mjs"
        still.parent.mkdir(parents=True, exist_ok=True)
        still.write_text("// test fixture", encoding="utf-8")
        return AniDoodleImageProvider(root, anidoodle_home=root / "anidoodle")

    def _request(self, root: Path, run_id: str, shot_id: str = "shot-01") -> ImageRequest:
        return ImageRequest(
            prompt=json.dumps({"shot_id": shot_id}),
            output_path=root / "runs" / run_id / "keyframes" / f"{shot_id}.png",
        )

    def test_run_id_derived_from_single_run_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            provider = self.make_provider(root)
            requests = [self._request(root, "demo", "shot-01"), self._request(root, "demo", "shot-02")]
            self.assertEqual(provider._run_id_from(requests), "demo")

    def test_run_id_rejects_mixed_run_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            provider = self.make_provider(root)
            requests = [self._request(root, "demo-a"), self._request(root, "demo-b")]
            with self.assertRaises(ValueError):
                provider._run_id_from(requests)

    def test_run_id_rejects_output_outside_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            provider = self.make_provider(root)
            request = ImageRequest(prompt="{}", output_path=root / "elsewhere" / "x.png")
            with self.assertRaises(ValueError):
                provider._run_id_from([request])

    def test_generate_batch_empty_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            provider = self.make_provider(root)
            self.assertEqual(provider.generate_batch([]), [])


if __name__ == "__main__":
    unittest.main()
