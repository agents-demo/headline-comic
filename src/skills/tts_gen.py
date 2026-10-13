"""S14 tts_gen: narration audio per storyboard shot (T028).

Mirrors ``image_gen`` and ``video_gen`` for the audio half of the video: a
**deterministic mapping** from the Director's storyboard to one narration clip per
shot with non-empty ``narration``, then an **orchestrator** that synthesizes those
clips through the provider-neutral ``TTSProvider`` with retry, caching the results in
``runs/<run-id>/audio/`` and recording the TTS cost through the T007 budget guard.

Fish Audio is the free-plan provider (``src/providers/fishaudio.py``); it is billed at
$0 per 1,000 characters, so the happy path needs no approval record. When a shot's clip
cannot be produced after retries, that shot degrades to subtitles-only (``spoken=False``,
FR-017) rather than failing the run. The hold-last-frame rule (FR-010) is computed here
as the extra seconds a shot's frame must linger when its narration runs longer than the
shot's storyboard duration; the T029 assembler consumes it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.permissions.approval_guard import ApprovalRequired, require_approval
from src.permissions.media_guard import (
    CostRecordError,
    MissingUnitPrice,
    UnitPrice,
    prepare_storyboard_quote,
    record_actual_cost,
    require_allowed_write_path,
)
from src.providers.contracts import TTSRequest, TTSResult

DAILY_CHAR_BUDGET = 5000  # conservative daily narration warning threshold, not a hard guard


class TTSGenError(RuntimeError):
    """Raised when the storyboard cannot be turned into narration clips."""


@dataclass(frozen=True)
class NarrationClip:
    """One shot's narration audio (or its subtitles-only fallback)."""

    shot_id: str
    text: str
    audio_path: Path
    duration_s: float
    spoken: bool
    error: str | None = None


def narration_shots(storyboard: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Return ``(shot_id, narration)`` for every shot with non-empty narration, in order."""
    shots = storyboard.get("shots")
    if not isinstance(shots, list) or not shots:
        raise TTSGenError("storyboard must contain a non-empty shots array")
    result: list[tuple[str, str]] = []
    for shot in shots:
        if not isinstance(shot, Mapping):
            raise TTSGenError("storyboard shot must be an object")
        shot_id = str(shot.get("shot_id") or "").strip()
        text = str(shot.get("narration") or "").strip()
        if not shot_id:
            raise TTSGenError("storyboard shot is missing its shot_id")
        if text:
            result.append((shot_id, text))
    return result


def total_narration_chars(storyboard: Mapping[str, Any]) -> int:
    """Sum narration characters across the storyboard (the TTS billing quantity)."""
    return sum(len(text) for _, text in narration_shots(storyboard))


def build_tts_requests(
    storyboard: Mapping[str, Any],
    audio_dir: Path,
    voice: str | None = None,
) -> list[TTSRequest]:
    """One request per narration shot, output to ``audio_dir/<shot_id>.mp3``."""
    return [
        TTSRequest(text=text, output_path=audio_dir / f"{shot_id}.mp3", voice=voice)
        for shot_id, text in narration_shots(storyboard)
    ]


def hold_last_frame_s(
    storyboard: Mapping[str, Any],
    clips_by_shot: Mapping[str, NarrationClip],
) -> dict[str, float]:
    """Extra seconds to hold a shot's last frame when narration outruns its video (FR-010)."""
    holds: dict[str, float] = {}
    for shot in storyboard.get("shots") or []:
        if not isinstance(shot, Mapping):
            continue
        shot_id = str(shot.get("shot_id") or "")
        clip = clips_by_shot.get(shot_id)
        if clip is None or not clip.spoken:
            continue
        duration = float(shot.get("duration_s") or 0)
        hold = clip.duration_s - duration
        if hold > 0:
            holds[shot_id] = round(hold, 3)
    return holds


def _retry(fn: Any, max_attempts: int) -> Any:
    last: Exception | None = None
    for _ in range(max_attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - a provider failure is retried, then surfaced
            last = exc
    assert last is not None
    raise last


def _manifest_path(audio_dir: Path) -> Path:
    return audio_dir / "narration.json"


def _load_manifest(audio_dir: Path) -> list[dict[str, Any]] | None:
    path = _manifest_path(audio_dir)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(data, dict) and isinstance(data.get("clips"), list):
        return [clip for clip in data["clips"] if isinstance(clip, dict)]
    return None


def _matches_manifest(manifest: list[dict[str, Any]], shots: list[tuple[str, str]]) -> bool:
    """True when the cached manifest covers exactly the current narration shots."""
    expected = [(shot_id, text) for shot_id, text in shots]
    cached = [
        (str(clip.get("shot_id") or ""), str(clip.get("text") or ""))
        for clip in manifest
        if str(clip.get("shot_id") or "")
    ]
    return cached == expected


def _write_manifest(audio_dir: Path, clips: Sequence[NarrationClip]) -> Path:
    path = _manifest_path(audio_dir)
    records = [
        {
            "shot_id": clip.shot_id,
            "text": clip.text,
            "audio_path": str(clip.audio_path),
            "duration_s": clip.duration_s,
            "spoken": clip.spoken,
            "error": clip.error,
        }
        for clip in clips
    ]
    path.write_text(
        json.dumps({"schema_version": "1.0", "clips": records}, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def synthesize_narration(
    storyboard: Mapping[str, Any],
    provider: Any,
    audio_dir: Path,
    *,
    voice: str | None = None,
    max_attempts: int = 2,
) -> list[NarrationClip]:
    """Synthesize (or reload) one narration clip per shot, degrading failures to subtitles."""
    shots = narration_shots(storyboard)
    manifest = _load_manifest(audio_dir)
    if manifest is not None and _matches_manifest(manifest, shots):
        return [
            NarrationClip(
                shot_id=str(clip.get("shot_id") or ""),
                text=str(clip.get("text") or ""),
                audio_path=Path(str(clip.get("audio_path") or "")),
                duration_s=float(clip.get("duration_s") or 0),
                spoken=bool(clip.get("spoken")),
                error=str(clip.get("error")) if clip.get("error") else None,
            )
            for clip in manifest
        ]

    clips: list[NarrationClip] = []
    for shot_id, text in shots:
        out_path = audio_dir / f"{shot_id}.mp3"
        request = TTSRequest(text=text, output_path=out_path, voice=voice)
        try:
            result: TTSResult = _retry(lambda: provider.synthesize(request), max_attempts)
            clips.append(NarrationClip(shot_id, text, result.audio_path, result.duration_s, True))
        except Exception as exc:  # noqa: BLE001 - FR-017: degrade this shot to subtitles-only
            clips.append(NarrationClip(shot_id, text, out_path, 0.0, False, str(exc)))

    _write_manifest(audio_dir, clips)
    return clips


def run(
    storyboard: Mapping[str, Any],
    *,
    provider: Any,
    workspace_root: Path,
    run_id: str,
    unit_prices: Mapping[str, UnitPrice],
    audio_dir: Path | None = None,
    voice: str | None = None,
    max_attempts: int = 2,
    approval_path: Path | None = None,
) -> list[NarrationClip]:
    """Synthesize the run's narration, budgeted and guarded.

    The TTS unit price is recorded explicitly (``unit_prices["tts"]``, per 1,000
    characters). A non-zero price additionally requires an approval record for the
    run; the free Fish Audio path is $0 and skips that paid-only requirement. When the
    storyboard carries no narration there is nothing to bill, and the run is left
    untouched.
    """
    if not narration_shots(storyboard):
        return []

    root = workspace_root.resolve()
    audio_dir = (audio_dir or root / "runs" / run_id / "audio").resolve()
    require_allowed_write_path(audio_dir / "narration.mp3", workspace_root=root)

    tts_price = unit_prices.get("tts")
    if tts_price is None:
        raise MissingUnitPrice("No recorded unit price for TTS calls")

    cost_path = root / "runs" / run_id / "cost.json"
    if cost_path.exists():
        record = json.loads(cost_path.read_text(encoding="utf-8"))
        items = record.get("items") if isinstance(record, dict) else None
        if not isinstance(items, list) or not any(
            isinstance(item, dict) and item.get("category") == "tts" for item in items
        ):
            raise CostRecordError(
                "run cost record lacks a tts line; reserve the image, video and tts quote together"
            )
    else:
        prepare_storyboard_quote(
            storyboard,
            unit_prices,
            workspace_root=root,
            run_id=run_id,
            planned_categories=["tts"],
        )

    if tts_price.usd_per_unit > 0:
        if approval_path is None:
            raise ApprovalRequired("Paid TTS generation requires an approval record")
        require_approval(action="tts", approval_path=approval_path, run_id=run_id)

    audio_dir.mkdir(parents=True, exist_ok=True)
    clips = synthesize_narration(
        storyboard, provider, audio_dir, voice=voice, max_attempts=max_attempts
    )

    actual = tts_price.usd_per_unit * (Decimal(total_narration_chars(storyboard)) / Decimal(1000))
    record_actual_cost(workspace_root=root, run_id=run_id, category="tts", actual_usd=actual)
    return clips
