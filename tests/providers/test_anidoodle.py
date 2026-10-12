"""Focused tests for the AniDoodle adapter without launching a renderer."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.providers import AniDoodleVideoProvider, VideoProvider, VideoRequest


class AniDoodleVideoProviderTests(unittest.TestCase):
    def make_provider(self, root: Path) -> AniDoodleVideoProvider:
        script = root / "scripts" / "anidoodle" / "render_gate0.mjs"
        script.parent.mkdir(parents=True)
        script.write_text("// test fixture", encoding="utf-8")
        return AniDoodleVideoProvider(root)

    def make_artifacts(self, root: Path, run_id: str, *, duration: float = 8, audio: str = "none") -> None:
        run_dir = root / "runs" / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "anidoodle-pip.mp4").write_bytes(b"fixture mp4")
        (run_dir / "manifest.json").write_text(
            json.dumps({"durationSeconds": duration, "audio": audio}), encoding="utf-8"
        )

    def test_adapter_implements_provider_contract_and_returns_validated_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            provider = self.make_provider(root)
            self.make_artifacts(root, "demo")

            with patch("src.providers.anidoodle.subprocess.run") as run:
                result = provider.render(VideoRequest("demo", max_duration_s=10))

            self.assertIsInstance(provider, VideoProvider)
            self.assertEqual(result.video_path, root.resolve() / "runs" / "demo" / "anidoodle-pip.mp4")
            self.assertEqual(result.manifest_path, root.resolve() / "runs" / "demo" / "manifest.json")
            self.assertEqual(result.duration_s, 8)
            self.assertFalse(result.has_audio)
            self.assertEqual(run.call_args.args[0][-1], "demo")

    def test_invalid_run_id_is_rejected_before_launch(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            provider = self.make_provider(Path(temp))
            with patch("src.providers.anidoodle.subprocess.run") as run:
                with self.assertRaisesRegex(ValueError, "run_id"):
                    provider.render(VideoRequest("../outside"))
            run.assert_not_called()

    def test_duration_limit_must_be_below_one_minute(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            provider = self.make_provider(Path(temp))
            with patch("src.providers.anidoodle.subprocess.run") as run:
                with self.assertRaisesRegex(ValueError, "max_duration_s"):
                    provider.render(VideoRequest("demo", max_duration_s=60))
            run.assert_not_called()

    def test_rendered_duration_must_fit_request_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            provider = self.make_provider(root)
            self.make_artifacts(root, "demo", duration=11)
            with patch("src.providers.anidoodle.subprocess.run"):
                with self.assertRaisesRegex(RuntimeError, "exceeds"):
                    provider.render(VideoRequest("demo", max_duration_s=10))

    def test_audio_output_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            provider = self.make_provider(root)
            self.make_artifacts(root, "demo", audio="present")
            with patch("src.providers.anidoodle.subprocess.run"):
                with self.assertRaisesRegex(RuntimeError, "remain silent"):
                    provider.render(VideoRequest("demo"))

    def test_missing_render_artifact_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            provider = self.make_provider(root)
            (root / "runs" / "demo").mkdir(parents=True)
            with patch("src.providers.anidoodle.subprocess.run"):
                with self.assertRaisesRegex(RuntimeError, "expected MP4 and manifest"):
                    provider.render(VideoRequest("demo"))


if __name__ == "__main__":
    unittest.main()