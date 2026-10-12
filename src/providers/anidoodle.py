"""Adapter for the project's deterministic, silent AniDoodle render path.

T005 wires in and validates the local renderer. T027 will replace its fixed
Gate 0 scene with a bounded mapping from validated storyboard data.
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

    def __init__(self, repo_root: Path | None = None) -> None:
        self.repo_root = (repo_root or Path(__file__).resolve().parents[2]).resolve()
        self.renderer_script = self.repo_root / "scripts" / "anidoodle" / "render_gate0.mjs"
        if not self.renderer_script.is_file():
            raise FileNotFoundError(f"AniDoodle renderer not found: {self.renderer_script}")

    def render(self, request: VideoRequest) -> VideoResult:
        if not _RUN_ID.fullmatch(request.run_id):
            raise ValueError("run_id may contain only letters, digits, _ and - (max 64 characters)")
        if not 0 < request.max_duration_s < 60:
            raise ValueError("max_duration_s must be greater than 0 and below 60")

        runs_root = (self.repo_root / "runs").resolve()
        run_dir = (runs_root / request.run_id).resolve()
        if run_dir == runs_root or runs_root not in run_dir.parents:
            raise ValueError("render output must stay inside runs/<run-id>")

        subprocess.run(
            ["node", str(self.renderer_script), request.run_id],
            cwd=self.repo_root,
            env=os.environ.copy(),
            check=True,
        )

        video_path = run_dir / "anidoodle-pip.mp4"
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
            raise RuntimeError("AniDoodle proof output must remain silent")

        return VideoResult(
            video_path=video_path,
            manifest_path=manifest_path,
            duration_s=duration,
            has_audio=False,
        )