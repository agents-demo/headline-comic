"""S10 image_gen: one clean 16:9 keyframe per storyboard shot (FR-009, T023).

Two halves. First, a **deterministic mapping** from the Director's free-text
storyboard fields (``camera``, ``action``, ``characters``) to a bounded scene
spec — the camera/action -> preset vocabulary fixed in ``docs/style-bible.md``.
This is pure code: no model writes pixels, and every unmapped phrase falls back
to a documented default so the mapping can never drift. Second, an
**orchestrator** that turns those specs into provider requests (at most three
references per call: the shot's cast sheets plus the town), dispatches them with
retries and parallelism, and records the image cost through the T007 budget
guard.

The AniDoodle provider (``src/providers/anidoodle_image.py``) consumes the
scene-spec JSON carried in each ``ImageRequest.prompt`` and renders the keyframes
locally at $0; a paid image provider can replace it behind the same
``ImageProvider`` interface and the same budget hook.
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.permissions.approval_guard import ApprovalRequired, require_approval
from src.permissions.media_guard import (
    MissingUnitPrice,
    UnitPrice,
    prepare_storyboard_quote,
    record_actual_cost,
    require_allowed_write_path,
)
from src.providers.contracts import ImageRequest, ImageResult

# --- bounded vocabulary (docs/style-bible.md section 5.2) ---------------------

_CAMERA_PRESETS = ("wide", "medium", "close", "overhead")
_ACTION_PRESETS = ("stand", "point", "walk", "flutter", "wave", "work", "gather")

# Keyword priority is significant: check the most specific reads first.
_OVERHEAD_WORDS = ("overhead", "top-down", "top down", "map")
_CLOSE_WORDS = ("close", "detail", "seed", "packet", "packets")
_WIDE_WORDS = ("wide", "establishing", "closing", "establish")
_FLUTTER_WORDS = ("flutter", "flutters", "hop", "hops", "fly", "flies")
_POINT_WORDS = ("point", "points", "invitation", "invites")
_WAVE_WORDS = ("wave", "waves", "welcome", "welcomes", "greet", "greets")
_WORK_WORDS = ("trace", "traces", "tie", "ties", "mark", "marks", "seed", "seeds", "map", "maps")
_WALK_WORDS = ("walk", "walks", "follow", "follows", "lead", "leads", "stroll", "strolls")
_GATHER_WORDS = ("gather", "gathers", "finish", "finishes")

# One prop per story beat, keyed off the deterministic beat index.
_BEAT_PROPS: dict[int, list[str]] = {
    0: [],
    1: ["lamp"],
    2: [],  # beat 2 is the overhead map shot, drawn by the overhead scene
    3: ["canopy"],
    4: ["fence"],
    5: ["clock"],
}

W = 1280
H = 720


def _contains_word(text: str, word: str) -> bool:
    """Whole-word match so e.g. ``hop`` never matches inside ``workshop``."""
    return re.search(rf"\b{re.escape(word)}\b", text) is not None


def normalize_camera(text: str) -> str:
    """Map a free-text camera to one bounded preset (overhead > close > wide > medium)."""
    t = text.lower()
    if any(_contains_word(t, word) for word in _OVERHEAD_WORDS):
        return "overhead"
    if any(_contains_word(t, word) for word in _CLOSE_WORDS):
        return "close"
    if any(_contains_word(t, word) for word in _WIDE_WORDS):
        return "wide"
    return "medium"


def normalize_action(text: str) -> str:
    """Map a free-text action to one bounded pose preset, defaulting to ``stand``."""
    t = text.lower()
    if any(_contains_word(t, word) for word in _FLUTTER_WORDS):
        return "flutter"
    if any(_contains_word(t, word) for word in _POINT_WORDS):
        return "point"
    if any(_contains_word(t, word) for word in _WAVE_WORDS):
        return "wave"
    if any(_contains_word(t, word) for word in _WORK_WORDS):
        return "work"
    if any(_contains_word(t, word) for word in _WALK_WORDS):
        return "walk"
    if any(_contains_word(t, word) for word in _GATHER_WORDS):
        return "gather"
    return "stand"


def view_for(character: str, action: str) -> str:
    """Pick the recognisable cast view for a character doing an action.

    Never the back view: front/three-quarter keep the distinguishing marks
    (yellow beak, blue cap, red sash) visible for the SC-2 character check.
    """
    if character == "pigeon":
        if action == "flutter":
            return "front"
        if action == "walk":
            return "side"
        return "threeQuarter"
    if action == "walk":
        return "side"
    if action == "wave":
        return "front"
    return "threeQuarter"


def _ground_y(camera: str) -> float:
    return {"wide": 470.0, "medium": 480.0, "close": 470.0}.get(camera, 470.0)


def _char_layout(characters: Sequence[tuple[str, str]], camera: str) -> list[dict[str, Any]]:
    """Place one or two characters in world space for a camera preset."""
    layout: list[dict[str, Any]] = []
    if len(characters) == 1:
        points = [(W * 0.5, _ground_y(camera))]
    else:
        points = [(W * 0.38, _ground_y(camera) + 10.0), (W * 0.62, _ground_y(camera))]
    for (name, action), (x, y) in zip(characters, points):
        scale = 2.2 if name == "pigeon" else 2.6
        if name == "pigeon" and action == "flutter":
            y -= 150.0
            scale = 2.0
        layout.append(
            {
                "name": name,
                "view": view_for(name, action),
                "x": round(x, 1),
                "y": round(y, 1),
                "scale": scale,
                "action": action,
            }
        )
    return layout


def _camera_spec(camera: str, layout: Sequence[dict[str, Any]]) -> dict[str, Any]:
    if camera == "overhead":
        return {"mode": "overhead"}
    if camera == "wide":
        return {"mode": "zoom", "scale": 1.0, "fx": W / 2, "fy": H / 2}
    fx = sum(c["x"] for c in layout) / len(layout)
    fy = sum(c["y"] for c in layout) / len(layout)
    scale = {"medium": 1.7, "close": 3.0}[camera]
    return {"mode": "zoom", "scale": scale, "fx": round(fx, 1), "fy": round(fy, 1)}


def scene_spec(shot: Mapping[str, Any]) -> dict[str, Any]:
    """Deterministically turn one storyboard shot into a bounded scene spec."""
    camera = normalize_camera(str(shot.get("camera", "")))
    action = normalize_action(str(shot.get("action", "")))
    characters = [str(c) for c in shot.get("characters", [])][:2]
    layout = _char_layout([(c, action) for c in characters], camera)
    return {
        "shot_id": str(shot.get("shot_id", "")),
        "camera": _camera_spec(camera, layout),
        "characters": layout,
        "props": list(_BEAT_PROPS.get(int(shot.get("beat", 0)), [])),
    }


def build_image_requests(
    storyboard: Mapping[str, Any],
    cast_dir: Path,
    output_dir: Path,
) -> list[ImageRequest]:
    """One request per shot; prompt carries the scene spec, references are <= 3."""
    requests: list[ImageRequest] = []
    for shot in storyboard.get("shots", []):
        spec = scene_spec(shot)
        names = [c["name"] for c in spec["characters"]]
        references: tuple[Path, ...] = tuple(cast_dir / f"{name}.png" for name in names) + (
            cast_dir / "town.png",
        )
        references = tuple(dict.fromkeys(references))[:3]
        prompt = json.dumps(spec, separators=(",", ":"))
        requests.append(
            ImageRequest(
                prompt=prompt,
                output_path=output_dir / f"{spec['shot_id']}.png",
                reference_images=references,
            )
        )
    return requests


def _retry(fn: Any, max_attempts: int) -> Any:
    last: Exception | None = None
    for _ in range(max_attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - a provider failure is retried, then surfaced
            last = exc
    assert last is not None
    raise last


def _dispatch(provider: Any, requests: Sequence[ImageRequest], max_attempts: int) -> list[ImageResult]:
    """Render all requests, using a provider batch method when it offers one."""
    batch = getattr(provider, "generate_batch", None)
    if callable(batch):
        return _retry(lambda: list(batch(requests)), max_attempts)
    # Fallback: per-request generation in a bounded thread pool (future paid providers).
    def one(request: ImageRequest) -> ImageResult:
        return _retry(lambda: provider.generate(request), max_attempts)

    workers = min(8, max(1, len(requests)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(one, requests))


def generate_keyframes(
    storyboard: Mapping[str, Any],
    *,
    provider: Any,
    workspace_root: Path,
    run_id: str,
    unit_prices: Mapping[str, UnitPrice],
    cast_dir: Path | None = None,
    output_dir: Path | None = None,
    max_attempts: int = 2,
    approval_path: Path | None = None,
    planned_categories: Sequence[str] = ("image",),
) -> list[ImageResult]:
    """Generate one keyframe per shot, budgeted and guarded.

    The image unit price is recorded explicitly (``unit_prices["image"]``) and
    reserved through the T007 cost ledger before any call. A non-zero price
    additionally requires an approval record for the run; the local AniDoodle
    path is $0 and skips that paid-only requirement. Outputs stay under
    ``runs/<run-id>/``.

    ``planned_categories`` names every media category this run will call, so a
    single cost reservation covers them all (pass ``("image", "video")`` when the
    video stage follows). Settlement is left to the end of the media phase, so a
    later video/TTS stage can still record against the same run quote.
    """
    root = workspace_root.resolve()
    cast_dir = (cast_dir or root / "assets" / "cast").resolve()
    output_dir = (output_dir or root / "runs" / run_id / "keyframes").resolve()
    require_allowed_write_path(output_dir / "keyframe.png", workspace_root=root)

    image_price = unit_prices.get("image")
    if image_price is None:
        raise MissingUnitPrice("No recorded unit price for image calls")

    prepare_storyboard_quote(
        storyboard,
        unit_prices,
        workspace_root=root,
        run_id=run_id,
        planned_categories=planned_categories,
    )
    if image_price.usd_per_unit > 0:
        if approval_path is None:
            raise ApprovalRequired("Paid image generation requires an approval record")
        require_approval(action="image", approval_path=approval_path, run_id=run_id)

    requests = build_image_requests(storyboard, cast_dir, output_dir)
    results = _dispatch(provider, requests, max_attempts)

    actual = image_price.usd_per_unit * len(requests)
    record_actual_cost(workspace_root=root, run_id=run_id, category="image", actual_usd=actual)
    return results
