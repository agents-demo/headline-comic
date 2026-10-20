"""Tests for the MiniMax-H3 (vLLM-Omni) adapter (T043) with no live network or GPU calls."""

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError

from src.skills.video_recovery import classify_failure
from src.providers.minimax_h3 import (
    MiniMaxH3CloudProvider,
    MiniMaxH3Error,
    MiniMaxH3TimeoutError,
    MiniMaxH3VideoProvider,
    _basic_auth,
    _split_auth,
    _stable_seed,
    build_request_fields,
    compile_prompt,
    encode_multipart,
    extra_params,
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

KEYFRAME_BYTES = b"KEYFRAME-PNG-BYTES-12345"


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


def _parse_multipart(body: bytes, content_type: str) -> tuple[dict[str, str], dict[str, bytes]]:
    """Split a multipart body back into (fields, files) by name."""
    boundary = content_type.split("boundary=", 1)[1].encode("ascii")
    fields: dict[str, str] = {}
    files: dict[str, bytes] = {}
    for part in body.split(b"--" + boundary):
        part = part.strip(b"\r\n")
        if not part or part == b"--":
            continue
        headers_blob, _, content = part.partition(b"\r\n\r\n")
        name = None
        filename = None
        for line in headers_blob.decode("utf-8", "replace").split("\r\n"):
            if line.startswith("Content-Disposition:"):
                for token in line.split(";"):
                    token = token.strip()
                    if token.startswith("name="):
                        name = token.split("=", 1)[1].strip('"')
                    elif token.startswith("filename="):
                        filename = token.split("=", 1)[1].strip('"')
        if filename is not None:
            files[name] = content
        else:
            fields[name] = content.decode("utf-8")
    return fields, files


class MiniMaxH3Tests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch("src.providers.minimax_h3.load_env")
        patcher.start()
        self.addCleanup(patcher.stop)
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name).resolve()
        self.keyframes = self.root / "runs" / "r001" / "keyframes"
        self.keyframes.mkdir(parents=True)
        (self.keyframes / "shot-01.png").write_bytes(KEYFRAME_BYTES)

    def tearDown(self) -> None:
        self._temp.cleanup()

    def _provider(self, urlopen, **kwargs) -> MiniMaxH3VideoProvider:
        return MiniMaxH3VideoProvider(
            base_url="http://127.0.0.1:8000",
            urlopen=urlopen,
            probe=lambda path: (5.0, 1280, 720),
            run=_fake_run,
            **kwargs,
        )

    def _happy_urlopen(self, content: bytes = b"mp4"):
        requests = []

        def urlopen(req, timeout=None):
            requests.append(req)
            return _BytesResponse(content)

        return urlopen, requests

    def test_render_posts_sync_multipart_and_returns_clip(self) -> None:
        urlopen, requests = self._happy_urlopen()
        provider = self._provider(urlopen)
        render = provider.renderer({"shots": [SHOT]}, self.keyframes)
        result = render(SHOT)

        self.assertEqual(result.path, self.keyframes.parent / "shots" / "shot-01.mp4")
        self.assertEqual(result.duration_s, 5.0)
        self.assertEqual((result.width, result.height), (1280, 720))

        self.assertEqual(len(requests), 1)
        req = requests[0]
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(req.full_url, "http://127.0.0.1:8000/v1/videos/sync")

        content_type = req.headers["Content-type"]
        self.assertTrue(content_type.startswith("multipart/form-data; boundary="))
        fields, files = _parse_multipart(req.data, content_type)

        self.assertEqual(fields["prompt"], compile_prompt(SHOT))
        self.assertEqual(fields["width"], "1024")
        self.assertEqual(fields["height"], "576")
        self.assertEqual(fields["aspect_ratio"], "16:9")
        self.assertEqual(fields["fps"], "24.0")
        self.assertEqual(fields["num_inference_steps"], "50")
        self.assertEqual(fields["flow_shift"], "12.0")
        self.assertEqual(fields["seed"], str(_stable_seed("shot-01")))

        extra = json.loads(fields["extra_params"])
        self.assertEqual(extra["task"], "fl2va")
        self.assertEqual(extra["duration"], 5.0)
        self.assertEqual(extra["audio_flow_shift"], 3.0)

        self.assertEqual(files["input_reference"], KEYFRAME_BYTES)

        # The prompt is compiled deterministically from the storyboard fields.
        for needle in ("Miniature tilt-shift", SHOT["scene_setting"], SHOT["gag"], SHOT["audio_cue"]):
            self.assertIn(needle, fields["prompt"])

    def test_submit_writes_raw_then_normalizes(self) -> None:
        urlopen, requests = self._happy_urlopen(content=b"raw-mp4-bytes")
        provider = self._provider(urlopen)
        render = provider.renderer({"shots": [SHOT]}, self.keyframes)
        result = render(SHOT)
        self.assertTrue((self.keyframes.parent / "shots" / "shot-01-raw.mp4").is_file())
        self.assertTrue(result.path.is_file())

    def test_timeout_is_classified_as_timeout(self) -> None:
        def urlopen(req, timeout=None):
            raise TimeoutError("slow")

        provider = self._provider(urlopen, timeout=1.0)
        render = provider.renderer({"shots": [SHOT]}, self.keyframes)
        with self.assertRaises(MiniMaxH3TimeoutError) as ctx:
            render(SHOT)
        self.assertEqual(classify_failure(error=ctx.exception, expected_duration_s=5.0), "timeout")

    def test_http_error_is_classified_as_api_error(self) -> None:
        def urlopen(req, timeout=None):
            raise HTTPError(
                req.full_url, 500, "Internal Server Error", {},
                io.BytesIO(b'{"detail": "server exploded"}'),
            )

        provider = self._provider(urlopen)
        render = provider.renderer({"shots": [SHOT]}, self.keyframes)
        with self.assertRaises(MiniMaxH3Error) as ctx:
            render(SHOT)
        self.assertIn("server exploded", str(ctx.exception))
        self.assertEqual(classify_failure(error=ctx.exception, expected_duration_s=5.0), "api_error")

    def test_empty_response_is_an_api_error(self) -> None:
        provider = self._provider(self._happy_urlopen(content=b"")[0])
        render = provider.renderer({"shots": [SHOT]}, self.keyframes)
        with self.assertRaises(MiniMaxH3Error):
            render(SHOT)

    def test_missing_keyframe_raises(self) -> None:
        (self.keyframes / "shot-01.png").unlink()
        provider = self._provider(self._happy_urlopen()[0])
        render = provider.renderer({"shots": [SHOT]}, self.keyframes)
        with self.assertRaises(MiniMaxH3Error):
            render(SHOT)

    def test_unknown_variant_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self._provider(self._happy_urlopen()[0], variant="nope")

    def test_userinfo_in_base_url_adds_basic_auth_header(self) -> None:
        urlopen, requests = self._happy_urlopen()
        provider = MiniMaxH3VideoProvider(
            base_url="http://batya:sekret@10.10.12.102:8000",
            urlopen=urlopen,
            probe=lambda path: (5.0, 1280, 720),
            run=_fake_run,
        )
        render = provider.renderer({"shots": [SHOT]}, self.keyframes)
        render(SHOT)
        req = requests[0]
        self.assertEqual(req.full_url, "http://10.10.12.102:8000/v1/videos/sync")
        self.assertEqual(req.headers["Authorization"], _basic_auth("batya", "sekret"))

    def test_no_auth_header_without_credentials(self) -> None:
        urlopen, requests = self._happy_urlopen()
        provider = self._provider(urlopen)
        render = provider.renderer({"shots": [SHOT]}, self.keyframes)
        render(SHOT)
        self.assertNotIn("Authorization", requests[0].headers)


class CloudGateTests(unittest.TestCase):
    def test_cloud_renderer_raises_until_wired(self) -> None:
        with mock.patch("src.providers.minimax_h3.load_env"):
            provider = MiniMaxH3CloudProvider()
        with self.assertRaises(MiniMaxH3Error) as ctx:
            provider.renderer({"shots": []}, Path("."))
        self.assertIn("not implemented", str(ctx.exception))


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
    def test_extra_params_json(self) -> None:
        self.assertEqual(
            json.loads(extra_params(task="fl2va", duration=6.0, audio_flow_shift=3.0)),
            {"task": "fl2va", "duration": 6.0, "audio_flow_shift": 3.0},
        )

    def test_build_request_fields_shape(self) -> None:
        fields, files = build_request_fields(
            prompt="p",
            seconds=6.0,
            keyframe_bytes=b"png",
            seed=2101,
        )
        self.assertEqual(fields["seed"], "2101")
        self.assertEqual(fields["width"], "1024")
        self.assertEqual(fields["height"], "576")
        extra = json.loads(fields["extra_params"])
        self.assertEqual(extra, {"task": "fl2va", "duration": 6.0, "audio_flow_shift": 3.0})
        self.assertEqual(files["input_reference"], ("keyframe.png", b"png", "image/png"))

    def test_encode_multipart_round_trips(self) -> None:
        body, content_type = encode_multipart(
            {"prompt": "hello", "seed": "7"},
            {"input_reference": ("keyframe.png", b"\x00\x01PNG", "image/png")},
        )
        fields, files = _parse_multipart(body, content_type)
        self.assertEqual(fields, {"prompt": "hello", "seed": "7"})
        self.assertEqual(files["input_reference"], b"\x00\x01PNG")

    def test_seed_is_deterministic_per_shot(self) -> None:
        from src.providers.minimax_h3 import _stable_seed

        self.assertEqual(_stable_seed("shot-01"), _stable_seed("shot-01"))
        self.assertNotEqual(_stable_seed("shot-01"), _stable_seed("shot-02"))


class AuthTests(unittest.TestCase):
    def test_no_userinfo(self) -> None:
        clean, user, passwd = _split_auth("http://10.10.12.102:8000/")
        self.assertEqual(clean, "http://10.10.12.102:8000")
        self.assertIsNone(user)
        self.assertIsNone(passwd)

    def test_extracts_user_and_password(self) -> None:
        clean, user, passwd = _split_auth("http://batya:sekret@10.10.12.102:8000")
        self.assertEqual(clean, "http://10.10.12.102:8000")
        self.assertEqual(user, "batya")
        self.assertEqual(passwd, "sekret")

    def test_decodes_percent_encoding(self) -> None:
        clean, user, passwd = _split_auth("http://batya:p%40ss@10.10.12.102:8000")
        self.assertEqual(user, "batya")
        self.assertEqual(passwd, "p@ss")

    def test_password_may_contain_at_sign(self) -> None:
        clean, user, passwd = _split_auth("http://batya:pa@ss@10.10.12.102:8000")
        self.assertEqual(clean, "http://10.10.12.102:8000")
        self.assertEqual(user, "batya")
        self.assertEqual(passwd, "pa@ss")

    def test_basic_auth_header_value(self) -> None:
        import base64

        expected = "Basic " + base64.b64encode(b"batya:sekret").decode("ascii")
        self.assertEqual(_basic_auth("batya", "sekret"), expected)


if __name__ == "__main__":
    unittest.main()
