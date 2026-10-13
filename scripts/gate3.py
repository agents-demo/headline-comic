"""Gate 3 validation: generated video and fallback video from the same run.

Gate 3 (tasks.md): "generated video and fallback video from the same run." This
driver takes the hand-written t006 fixture through the visual stages S12-S14 in
one run directory and produces both finished videos:

* **generated video** — the silent AniDoodle ``shots.mp4`` (S13) assembled into
  ``runs/<run-id>/video.mp4`` (S14) with title/closing cards, crossfades,
  subtitles, the music bed and the persistent "AI-generated fiction" mark;
* **fallback video** — the pan/zoom-over-keyframes ``fallback.mp4`` (S12),
  assembled through the exact same S14 assembly so the two videos share their
  holds, crossfades, subtitles, music and cards (FR-017, D6).

The verification is deterministic ffprobe code: both files exist, are 1280x720,
carry an audio stream, sit under 60 seconds, and carry the ``title``/``comment``
metadata. Narration is the subtitles-only path (no TTS clips are passed), which
is the offline FR-017 degradation — the gate does not need the Fish Audio key or
a network, and the music bed still plays.

Usage::

    PYTHONPATH=. .venv/Scripts/python.exe -m scripts.gate3 [--run-id gate3] \
        [--skip-keyframes] [--skip-video] [--skip-music] [--verify-only] [--force]

``--skip-video`` reuses an existing ``shots.mp4`` (the AniDoodle whole-run render
is the slow step); ``--skip-music`` reuses an existing ``audio/bed.wav`` (which
needs the scaffolded AniDoodle music engine); ``--skip-keyframes`` reuses the
keyframes (the AniDoodle still render). ``--verify-only`` checks an
already-assembled run. ``--force`` clears the run dir first (the skills refuse
to overwrite their own outputs).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from src.permissions.media_guard import UnitPrice
from src.providers.anidoodle import AniDoodleVideoProvider
from src.providers.anidoodle_image import AniDoodleImageProvider
from src.skills import (
    generate_keyframes,
    run_assembler,
    run_fallback,
    run_music_gen,
    run_video_gen,
)
from src.skills.assemble import _find_tool

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "t006-sample"

VIDEO_OUT = "video.mp4"
FALLBACK_OUT = "fallback.mp4"
BED_NAME = "bed.wav"


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURE / name).read_text(encoding="utf-8"))


def _run_dir(run_id: str) -> Path:
    return ROOT / "runs" / run_id


def render_keyframes(storyboard: dict, run_id: str) -> None:
    keyframes_dir = _run_dir(run_id) / "keyframes"
    shot_ids = [str(shot["shot_id"]) for shot in storyboard["shots"]]
    if all((keyframes_dir / f"{shot_id}.png").is_file() for shot_id in shot_ids):
        print(f"  keyframes: already present ({len(shot_ids)} shots)")
        return
    print(f"  keyframes: rendering {len(shot_ids)} shots via AniDoodle stills ...")
    provider = AniDoodleImageProvider(ROOT)
    generate_keyframes(
        storyboard,
        provider=provider,
        workspace_root=ROOT,
        run_id=run_id,
        unit_prices={"image": UnitPrice.create("anidoodle", "keyframe", "0")},
    )


def render_shots(storyboard: dict, run_id: str) -> None:
    shots = _run_dir(run_id) / "shots.mp4"
    if shots.is_file():
        print("  shots:      already present (shots.mp4)")
        return
    print("  shots:      rendering silent AniDoodle video (slow) ...")
    run_video_gen(
        storyboard,
        provider=AniDoodleVideoProvider(ROOT),
        workspace_root=ROOT,
        run_id=run_id,
        unit_prices={"video": UnitPrice.create("anidoodle", "video", "0")},
    )


def render_bed(storyboard: dict, run_id: str) -> None:
    bed = _run_dir(run_id) / "audio" / BED_NAME
    if bed.is_file():
        print("  music:      already present (audio/bed.wav)")
        return
    print("  music:      rendering the music-box bed ...")
    run_music_gen(storyboard, workspace_root=ROOT, run_id=run_id)


def assemble_generated(story: dict, storyboard: dict, candidates: dict, summaries: dict, ledger: dict, run_id: str) -> None:
    out = _run_dir(run_id) / VIDEO_OUT
    if out.is_file():
        print(f"  generated:  already present ({VIDEO_OUT})")
        return
    print(f"  generated:  assembling {VIDEO_OUT} from shots.mp4 ...")
    run_assembler(
        story,
        storyboard,
        candidates,
        summaries,
        workspace_root=ROOT,
        run_id=run_id,
        ledger=ledger,
        video_path=_run_dir(run_id) / "shots.mp4",
        bed_path=_run_dir(run_id) / "audio" / BED_NAME,
        output_name=VIDEO_OUT,
    )


def assemble_fallback(story: dict, storyboard: dict, candidates: dict, summaries: dict, ledger: dict, run_id: str) -> None:
    out = _run_dir(run_id) / FALLBACK_OUT
    if out.is_file():
        print(f"  fallback:   already present ({FALLBACK_OUT})")
        return
    print(f"  fallback:   rendering {FALLBACK_OUT} from keyframes ...")
    run_fallback(
        story,
        storyboard,
        candidates,
        summaries,
        workspace_root=ROOT,
        run_id=run_id,
        ledger=ledger,
        bed_path=_run_dir(run_id) / "audio" / BED_NAME,
    )


def _probe(path: Path) -> dict[str, Any]:
    ffprobe = _find_tool(ROOT, "ffprobe")
    proc = subprocess.run(
        [
            ffprobe, "-v", "error",
            "-show_entries", "format=duration:format_tags=comment,title:stream=codec_type,width,height",
            "-of", "json", str(path),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe could not read {path}: {proc.stderr.strip()[:200]}")
    return json.loads(proc.stdout)


def _check_video(name: str, path: Path, title: str, checks: list[dict[str, Any]]) -> None:
    def record(key: str, ok: bool, detail: str) -> None:
        checks.append({"name": f"{name} {key}", "ok": ok, "detail": detail})

    if not path.is_file():
        record("present", False, f"missing {path}")
        return
    record("present", True, f"{path.name} exists")

    info = _probe(path)
    fmt = info.get("format") if isinstance(info, dict) else None
    streams = info.get("streams") if isinstance(info, dict) else None
    tags = fmt.get("tags") if isinstance(fmt, dict) else None

    duration = float((fmt or {}).get("duration") or 0)
    record("duration under 60s", 0 < duration < 60.0, f"{duration:g}s")

    if isinstance(streams, list):
        video = [s for s in streams if s.get("codec_type") == "video"]
        audio = [s for s in streams if s.get("codec_type") == "audio"]
        size = (video[0].get("width"), video[0].get("height")) if video else None
        record("resolution 1280x720", size == (1280, 720), f"{size[0]}x{size[1]}" if size else "no video stream")
        record("audio stream", bool(audio), "audio present" if audio else "no audio stream")
    else:
        record("streams", False, "no streams in probe")

    comment = (tags or {}).get("comment")
    record("fiction metadata", comment == "AI-generated fiction", f"comment={comment!r}")
    record("title metadata", (tags or {}).get("title") == title, f"title={(tags or {}).get('title')!r}")


def verify_run(run_id: str, story: dict) -> dict[str, Any]:
    """Deterministic ffprobe checks backing Gate 3. Returns a report."""
    run_dir = _run_dir(run_id)
    title = str(story.get("title") or "")
    checks: list[dict[str, Any]] = []
    _check_video("generated", run_dir / VIDEO_OUT, title, checks)
    _check_video("fallback", run_dir / FALLBACK_OUT, title, checks)
    passed = sum(1 for check in checks if check["ok"])
    return {"checks": checks, "passed": passed, "total": len(checks)}


def _print_report(report: dict[str, Any]) -> None:
    print()
    print(f"Gate 3 report — {report['passed']}/{report['total']} checks pass")
    for check in report["checks"]:
        mark = "PASS" if check["ok"] else "FAIL"
        print(f"  [{mark}] {check['name']}: {check['detail']}")
    if report["passed"] != report["total"]:
        print()
        print("Gate 3 NOT closed: fix the failing checks above and re-run.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gate 3 validation: generated + fallback video from one run")
    parser.add_argument("--run-id", default="gate3", help="run directory name under runs/ (default %(default)s)")
    parser.add_argument("--skip-keyframes", action="store_true", help="reuse existing keyframes instead of rendering")
    parser.add_argument("--skip-video", action="store_true", help="reuse existing shots.mp4 instead of the AniDoodle render")
    parser.add_argument("--skip-music", action="store_true", help="reuse existing audio/bed.wav instead of rendering")
    parser.add_argument("--verify-only", action="store_true", help="only verify an already-assembled run")
    parser.add_argument("--force", action="store_true", help="clear runs/<run-id> before rendering")
    args = parser.parse_args(argv)

    story = _load("story.json")
    storyboard = _load("storyboard.json")
    summaries = _load("summaries.json")
    candidates = _load("candidates.json")
    ledger = _load("ledger.json")

    run_dir = _run_dir(args.run_id)
    if args.force and run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    if not args.verify_only:
        if args.skip_keyframes:
            print("keyframes: skipped (reusing existing)")
        else:
            render_keyframes(storyboard, args.run_id)
        if args.skip_video:
            print("shots:     skipped (reusing existing shots.mp4)")
        else:
            render_shots(storyboard, args.run_id)
        if args.skip_music:
            print("music:     skipped (reusing existing bed.wav)")
        else:
            render_bed(storyboard, args.run_id)
        assemble_generated(story, storyboard, candidates, summaries, ledger, args.run_id)
        assemble_fallback(story, storyboard, candidates, summaries, ledger, args.run_id)

    report = verify_run(args.run_id, story)
    _print_report(report)
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    sys.exit(main())
