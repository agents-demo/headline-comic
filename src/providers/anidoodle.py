"""Adapter for the project's deterministic, silent AniDoodle video path (T027).

Renders one silent MP4 per run from the bounded scene data staged by
``src/skills/video_gen.py`` (``runs/<run-id>/video_scenes.ts``). The committed
renderer (``scripts/anidoodle/scenes/video.ts``) and cast library are copied into
the scaffolded film project; the renderer animates each scene over its storyboard
duration with a camera push-in (zoom shots) or a pan (the overhead map). No text,
captions or audio are added here — those are T028/T029 work on top of this silent
render. Outputs stay under ``runs/<run-id>/`` and are validated to be under one
minute and silent before the result is returned.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from .contracts import VideoRequest, VideoResult

_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class AniDoodleVideoProvider:
    """Run the local AniDoodle script and validate its silent MP4 artifact."""

    def __init__(self, repo_root: Path | None = None, anidoodle_home: Path | None = None) -> None:
        self.repo_root = (repo_root or Path(__file__).resolve().parents[2]).resolve()
        self.renderer_script = self.repo_root / "scripts" / "anidoodle" / "render_video.mjs"
        if not self.renderer_script.is_file():
            raise FileNotFoundError(f"AniDoodle renderer not found: {self.renderer_script}")
        self.anidoodle_home = self._resolve_home(anidoodle_home)

    def _resolve_home(self, explicit: Path | None) -> Path:
        candidate = explicit or (Path(os.environ["ANIDOODLE_HOME"]) if os.environ.get("ANIDOODLE_HOME") else None)
        if candidate is not None and (Path(candidate) / "skills" / "anidoodle" / "engine" / "tools" / "render.mjs").is_file():
            return Path(candidate)
        fallback = self.repo_root / "anidoodle"
        if (fallback / "skills" / "anidoodle" / "engine" / "tools" / "render.mjs").is_file():
            return fallback
        raise RuntimeError("Set ANIDOODLE_HOME to an AniDoodle checkout")

    def _ffmpeg_bin_dir(self) -> Path | None:
        """Return the vendored ffmpeg bin dir (if any) under runs/_tools/ffmpeg."""
        tools_root = self.repo_root / "runs" / "_tools" / "ffmpeg"
        if not tools_root.is_dir():
            return None
        ffmpeg_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
        for bin_dir in sorted(tools_root.glob("*/bin")):
            if (bin_dir / ffmpeg_name).is_file():
                return bin_dir
        return None

    def render(self, request: VideoRequest) -> VideoResult:
        if not _RUN_ID.fullmatch(request.run_id):
            raise ValueError("run_id may contain only letters, digits, _ and - (max 64 characters)")
        if not 0 < request.max_duration_s < 60:
            raise ValueError("max_duration_s must be greater than 0 and below 60")

        runs_root = (self.repo_root / "runs").resolve()
        run_dir = (runs_root / request.run_id).resolve()
        if run_dir == runs_root or runs_root not in run_dir.parents:
            raise ValueError("render output must stay inside runs/<run-id>")

        env = os.environ.copy()
        env["ANIDOODLE_HOME"] = str(self.anidoodle_home)
        ffmpeg_bin = self._ffmpeg_bin_dir()
        if ffmpeg_bin is not None:
            env["PATH"] = str(ffmpeg_bin) + os.pathsep + env.get("PATH", "")
        subprocess.run(
            ["node", str(self.renderer_script), request.run_id],
            cwd=self.repo_root,
            env=env,
            check=True,
        )

        video_path = run_dir / "video.mp4"
        manifest_path = run_dir / "manifest.json"
        if not video_path.is_file() or not manifest_path.is_file():
            raise RuntimeError("AniDoodle completed without the expected MP4 and manifest")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        duration = float(manifest["durationSeconds"])
        if not 0 < duration <= request.max_duration_s:
            raise RuntimeError(
                f"AniDoodle duration {duration:g}s exceeds the {request.max_duration_s:g}s limit"
            )
        if manifest.get("audio") != "none":
            raise RuntimeError("AniDoodle video output must remain silent")

        return VideoResult(
            video_path=video_path,
            manifest_path=manifest_path,
            duration_s=duration,
            has_audio=False,
        )
