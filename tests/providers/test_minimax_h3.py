"""Tests for the MiniMax-H3 adapter (T043) with no live network or GPU calls."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.skills.video_recovery import classify_failure
from src.providers.minimax_h3 import (
    MiniMaxH3Error,
    MiniMaxH3TimeoutError,
    MiniMaxH3VideoProvider,
    build_request_body,
    compile_prompt,
    keyframe_condition,
    keyframe_uri,
)

SHOT = {
    "shot_id": "shot-01",
    "duration_s": 5.0,
    "camera": "wide establishing view",
    "action": "The courier points toward a winding town path.",
    "gag": "Scale Contrast: the invitation unfurls into a giant banner.",
    "scene_setting": "Miniature town square at dusk with paper lanterns.",
    "audio_cue": "Soft evening ambience and a distant clock chime.",
}


class _BytesResponse:
    def __init__(self, payload: bytes) -> None:
        self._bytes = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self) -> bytes:
        return self._bytes


class _Proc:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _fake_run(args, **kwargs):
    out = Path(args[-1])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(b"mp4")
    return _Proc(0)


class MiniMaxH3Tests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch("src.providers.minimax_h3.load_env")
        patcher.start()
        self.addCleanup(patcher.stop)
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name).resolve()
        self.keyframes = self.root / "runs" / "r001" / "keyframes"
        self.keyframes.mkdir(parents=True)
        (self.keyframes / "shot-01.png").write_bytes(b"png")

    def tearDown(self) -> None:
        self._temp.cleanup()

    def _provider(self, urlopen, **kwargs) -> MiniMaxH3VideoProvider:
        return MiniMaxH3VideoProvider(
            base_url="http://127.0.0.1:30010",
            media_base_uri="file:///data/minimax-h3",
            urlopen=urlopen,
            probe=lambda path: (5.0, 1280, 720),
            run=_fake_run,
            sleep=lambda s: None,
            **kwargs,
        )

    def _happy_urlopen(self, content: bytes = b"mp4"):
        requests = []

        def urlopen(req, timeout=None):
            requests.append(req)
            url = req.full_url
            if req.get_method() == "POST":
                return _BytesResponse(b'{"id": "job-1"}')
            if url.endswith("/content"):
                return _BytesResponse(content)
            return _BytesResponse(b'{"status": "completed"}')

        return urlopen, requests

    def test_render_submits_fl2va_request_and_returns_clip(self) -> None:
        urlopen, requests = self._happy_urlopen()
        provider = self._provider(urlopen)
        render = provider.renderer({"shots": [SHOT]}, self.keyframes)
        result = render(SHOT)

        self.assertEqual(result.path, self.keyframes.parent / "shots" / "shot-01.mp4")
        self.assertEqual(result.duration_s, 5.0)
        self.assertEqual((result.width, result.height), (1280, 720))

        posts = [r for r in requests if r.get_method() == "POST"]
        self.assertEqual(len(posts), 1)
        body = json.loads(posts[0].data)
        self.assertEqual(body["model"], "MiniMaxAI/MiniMax-H3")
        self.assertEqual(body["task"], "fl2va")
        self.assertEqual(body["seconds"], 5.0)
        self.assertEqual(body["target"]["short_edge"], 768)
        self.assertEqual(body["target"]["aspect_ratio"], "16:9")
        self.assertEqual(body["conditions"], [
            keyframe_condition("file:///data/minimax-h3/r001/keyframes/shot-01.png", 0)
        ])
        # The prompt is compiled deterministically from the storyboard fields.
        for needle in ("Miniature tilt-shift", SHOT["scene_setting"], SHOT["gag"], SHOT["audio_cue"]):
            self.assertIn(needle, body["prompt"])

    def test_poll_and_download_called_once_each(self) -> None:
        urlopen, requests = self._happy_urlopen()
        provider = self._provider(urlopen)
        render = provider.renderer({"shots": [SHOT]}, self.keyframes)
        render(SHOT)

        urls = [r.full_url for r in requests]
        self.assertEqual(urls.count("http://127.0.0.1:30010/v1/videos/job-1"), 1)
        self.assertEqual(urls.count("http://127.0.0.1:30010/v1/videos/job-1/content"), 1)

    def test_pending_until_deadline_is_a_timeout(self) -> None:
        def urlopen(req, timeout=None):
            if req.get_method() == "POST":
                return _BytesResponse(b'{"id": "job-1"}')
            return _BytesResponse(b'{"status": "pending"}')

        provider = self._provider(urlopen, timeout=0.0, poll_interval=0.001)
        render = provider.renderer({"shots": [SHOT]}, self.keyframes)
        with self.assertRaises(MiniMaxH3TimeoutError) as ctx:
            render(SHOT)
        # The recovery classifies this as a timeout, not an API error.
        self.assertEqual(classify_failure(error=ctx.exception, expected_duration_s=5.0), "timeout")

    def test_failed_status_is_an_api_error(self) -> None:
        def urlopen(req, timeout=None):
            if req.get_method() == "POST":
                return _BytesResponse(b'{"id": "job-1"}')
            return _BytesResponse(b'{"status": "failed"}')

        provider = self._provider(urlopen)
        render = provider.renderer({"shots": [SHOT]}, self.keyframes)
        with self.assertRaises(MiniMaxH3Error) as ctx:
            render(SHOT)
        self.assertEqual(classify_failure(error=ctx.exception, expected_duration_s=5.0), "api_error")

    def test_missing_keyframe_raises(self) -> None:
        (self.keyframes / "shot-01.png").unlink()
        provider = self._provider(self._happy_urlopen()[0])
        render = provider.renderer({"shots": [SHOT]}, self.keyframes)
        with self.assertRaises(MiniMaxH3Error):
            render(SHOT)

    def test_unknown_variant_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self._provider(self._happy_urlopen()[0], variant="nope")


class CompilePromptTests(unittest.TestCase):
    def test_includes_every_storyboard_field(self) -> None:
        prompt = compile_prompt(SHOT)
        for needle in (SHOT["scene_setting"], SHOT["action"], SHOT["gag"], SHOT["camera"], SHOT["audio_cue"]):
            self.assertIn(needle, prompt)

    def test_omits_empty_fields(self) -> None:
        prompt = compile_prompt({"shot_id": "s", "gag": "Scale Contrast: a gag."})
        self.assertIn("Visual gag", prompt)
        self.assertNotIn("Scene:", prompt)
        self.assertNotIn("Audio:", prompt)


class RequestShapeTests(unittest.TestCase):
    def test_keyframe_uri_joins_run_and_shot(self) -> None:
        self.assertEqual(
            keyframe_uri("file:///data/minimax-h3", "r001", "shot-02"),
            "file:///data/minimax-h3/r001/keyframes/shot-02.png",
        )

    def test_build_request_body_shape(self) -> None:
        body = build_request_body(
            model="MiniMaxAI/MiniMax-H3",
            prompt="p",
            seconds=6.0,
            keyframe_uri="file:///data/minimax-h3/r001/keyframes/shot-01.png",
            seed=2101,
        )
        self.assertEqual(body["conditions"][0]["frame_index"], 0)
        self.assertEqual(body["quality"], "exact")
        self.assertEqual(body["num_outputs_per_prompt"], 1)
        self.assertEqual(body["seed"], 2101)
        self.assertEqual(body["target"]["duration_seconds"], 6.0)

    def test_seed_is_deterministic_per_shot(self) -> None:
        from src.providers.minimax_h3 import _stable_seed

        self.assertEqual(_stable_seed("shot-01"), _stable_seed("shot-01"))
        self.assertNotEqual(_stable_seed("shot-01"), _stable_seed("shot-02"))


if __name__ == "__main__":
    unittest.main()
