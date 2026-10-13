"""S11 compose: the six comic panels into one labelled 2 x 3 page (FR-009, FR-013).

Deterministic code, no model. ``panel_shots`` selects exactly the six shots the
Director flagged as comic panels (one per beat, ordered 0-5); ``compose_comic``
pastes their clean 16:9 keyframes into a two-column, three-row grid and draws, on
copies only — the panel captions, the optional speech bubbles, the ``source 1-5``
markers, the story title and the ``AI-generated fiction`` footer mark. The clean
keyframes under ``keyframes/`` are never modified; composited panel copies can be
written to ``panels/`` alongside the finished ``comic.png``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence

from PIL import Image, ImageDraw, ImageFont

from src.permissions.media_guard import require_allowed_write_path

AI_GENERATED_MARK = "AI-generated fiction"

# Page geometry (see docs/style-bible.md section 5.3: text composited on copies).
PAGE_W = 1280
MARGIN = 48
GUTTER = 24
HEADER_H = 112
FOOTER_H = 64
COLS = 2
ROWS = 3

_PAPER = "#f6f1e5"
_INK = "#17212b"
_INK_SOFT = "#5a6472"
_WHITE = "#ffffff"

_FONT_PATHS = (
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
)
_BOLD_PATHS = (
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
)

_font_cache: dict[tuple[int, bool], ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}


class ComposeError(RuntimeError):
    """Raised when the storyboard cannot be composed into a comic page."""


def panel_shots(storyboard: Mapping[str, object]) -> list[dict]:
    """Return the six comic-panel shots, one per beat, ordered by beat 0-5."""
    shots = storyboard.get("shots")
    if not isinstance(shots, list) or not shots:
        raise ComposeError("storyboard must contain a non-empty shots array")
    by_beat: dict[int, list[dict]] = {beat: [] for beat in range(6)}
    for shot in shots:
        if not isinstance(shot, Mapping):
            raise ComposeError("storyboard shot must be an object")
        beat = shot.get("beat")
        if not isinstance(beat, int) or beat not in by_beat:
            continue
        if shot.get("comic_panel") is True:
            by_beat[beat].append(dict(shot))
    missing = [beat for beat, panels in by_beat.items() if not panels]
    extra = [beat for beat, panels in by_beat.items() if len(panels) > 1]
    if missing or extra:
        problems = []
        if missing:
            problems.append(f"missing panel for beat(s) {missing}")
        if extra:
            problems.append(f"more than one panel for beat(s) {extra}")
        raise ComposeError("; ".join(problems))
    return [by_beat[beat][0] for beat in range(6)]


def page_size() -> tuple[int, int]:
    """Return the deterministic (width, height) of the composed page."""
    panel_w = (PAGE_W - 2 * MARGIN - (COLS - 1) * GUTTER) // COLS
    panel_h = int(panel_w * 9 / 16)
    height = MARGIN + HEADER_H + ROWS * panel_h + (ROWS - 1) * GUTTER + FOOTER_H + MARGIN
    return PAGE_W, height


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    key = (size, bold)
    if key not in _font_cache:
        for candidate in (_BOLD_PATHS if bold else _FONT_PATHS):
            if Path(candidate).is_file():
                _font_cache[key] = ImageFont.truetype(candidate, size)
                break
        else:
            _font_cache[key] = ImageFont.load_default(size)
    return _font_cache[key]


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if not current or draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _fit(draw: ImageDraw.ImageDraw, text: str, font, max_width: int, max_lines: int) -> list[str]:
    lines = _wrap(draw, text, font, max_width)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while draw.textlength(last + "\u2026", font=font) > max_width and len(last) > 1:
            last = last[:-1]
        lines[-1] = last.rstrip() + "\u2026"
    return lines


def _draw_caption(draw: ImageDraw.ImageDraw, panel_w: int, panel_h: int, caption: str) -> None:
    font = _font(18)
    inset = 10
    pad = 8
    lines = _fit(draw, caption, font, panel_w - 2 * inset, 2)
    if not lines:
        return
    line_h = font.size + 6
    box_h = len(lines) * line_h + 2 * pad
    box_y = panel_h - box_h - 8
    draw.rounded_rectangle([inset, box_y, panel_w - inset, panel_h - 8], radius=10, fill=_WHITE, outline=_INK)
    y = box_y + pad
    for line in lines:
        draw.text((inset + pad, y), line, font=font, fill=_INK)
        y += line_h


def _draw_bubble(draw: ImageDraw.ImageDraw, panel_w: int, dialogue: str) -> None:
    font = _font(18, bold=True)
    pad = 10
    x = 12
    y = 12
    max_w = panel_w - 2 * x - 24
    lines = _fit(draw, dialogue, font, max_w, 3)
    if not lines:
        return
    line_h = font.size + 6
    text_w = max(draw.textlength(line, font=font) for line in lines)
    box_w = int(text_w) + 2 * pad
    box_h = len(lines) * line_h + 2 * pad
    draw.rounded_rectangle([x, y, x + box_w, y + box_h], radius=12, fill=_WHITE, outline=_INK)
    # tail pointing down toward the scene
    draw.polygon([(x + 18, y + box_h), (x + 34, y + box_h), (x + 20, y + box_h + 12)], fill=_WHITE)
    ty = y + pad
    for line in lines:
        draw.text((x + pad, ty), line, font=font, fill=_INK)
        ty += line_h


def _draw_source_marker(draw: ImageDraw.ImageDraw, panel_w: int, source_ref: int) -> None:
    if not 1 <= source_ref <= 5:
        return
    font = _font(15, bold=True)
    label = f"source {source_ref}"
    pad = 8
    text_w = int(draw.textlength(label, font=font))
    chip_w = text_w + 2 * pad
    chip_h = font.size + 8
    x = panel_w - chip_w - 8
    y = 8
    draw.rounded_rectangle([x, y, x + chip_w, y + chip_h], radius=6, fill=_INK)
    draw.text((x + pad, y + 4), label, font=font, fill=_WHITE)


def _render_panel(
    keyframe_path: Path, shot: Mapping[str, object], panel_w: int, panel_h: int
) -> Image.Image:
    """Resize the clean keyframe to panel size, then draw text on the copy only."""
    image = Image.open(keyframe_path).convert("RGB").resize((panel_w, panel_h), Image.LANCZOS)
    draw = ImageDraw.Draw(image)
    caption = str(shot.get("comic_caption") or "").strip()
    dialogue = str(shot.get("dialogue") or "").strip()
    source_ref = shot.get("source_ref")
    if dialogue:
        _draw_bubble(draw, panel_w, dialogue)
    if caption:
        _draw_caption(draw, panel_w, panel_h, caption)
    if isinstance(source_ref, int):
        _draw_source_marker(draw, panel_w, source_ref)
    return image


def compose_comic(
    storyboard: Mapping[str, object],
    keyframes_dir: Path,
    *,
    title: str,
    fiction_label: str,
    output_path: Path,
    panels_dir: Path | None = None,
) -> Path:
    """Build the 2 x 3 comic page from the six comic-panel keyframes.

    Composites captions, bubbles and source markers on copies only (the clean
    keyframes are read, never written), optionally saving each composited panel
    to ``panels_dir``, and writes the finished page to ``output_path``.
    """
    panels = panel_shots(storyboard)
    keyframes_dir = keyframes_dir.resolve()
    page_w, page_h = page_size()
    panel_w = (PAGE_W - 2 * MARGIN - (COLS - 1) * GUTTER) // COLS
    panel_h = int(panel_w * 9 / 16)

    rendered: list[Image.Image] = []
    for shot in panels:
        keyframe = keyframes_dir / f"{shot['shot_id']}.png"
        if not keyframe.is_file():
            raise ComposeError(f"missing keyframe for panel {shot['shot_id']}: {keyframe}")
        panel = _render_panel(keyframe, shot, panel_w, panel_h)
        rendered.append(panel)
        if panels_dir is not None:
            panels_dir.mkdir(parents=True, exist_ok=True)
            panel.save(panels_dir / f"{shot['shot_id']}.png")

    page = Image.new("RGB", (page_w, page_h), _PAPER)
    draw = ImageDraw.Draw(page)

    # header: story title + fiction label
    title_font = _font(38, bold=True)
    subtitle_font = _font(22)
    draw.text(
        (PAGE_W / 2, MARGIN + 8),
        title,
        font=title_font,
        fill=_INK,
        anchor="ma",
    )
    draw.text(
        (PAGE_W / 2, MARGIN + 56),
        fiction_label,
        font=subtitle_font,
        fill=_INK_SOFT,
        anchor="ma",
    )

    # 2 x 3 grid, row-major: beat 0 -> (0,0) ... beat 5 -> (1,2)
    grid_x = MARGIN
    grid_y = MARGIN + HEADER_H
    for index, panel in enumerate(rendered):
        col = index % COLS
        row = index // COLS
        x = grid_x + col * (panel_w + GUTTER)
        y = grid_y + row * (panel_h + GUTTER)
        page.paste(panel, (x, y))

    # footer: persistent AI-generated fiction mark
    draw.text(
        (PAGE_W / 2, page_h - MARGIN - 6),
        AI_GENERATED_MARK,
        font=_font(20, bold=True),
        fill=_INK_SOFT,
        anchor="ms",
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    page.save(output_path)
    return output_path


def run(
    story: Mapping[str, object],
    storyboard: Mapping[str, object],
    *,
    workspace_root: Path,
    run_id: str,
) -> Path:
    """Write ``runs/<run-id>/comic.png`` (and panel copies) from a finished story + storyboard."""
    root = workspace_root.resolve()
    run_dir = root / "runs" / run_id
    output_path = require_allowed_write_path(run_dir / "comic.png", workspace_root=root)
    if output_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing comic: {output_path}")
    title = str(story.get("title") or "").strip()
    if not title:
        raise ComposeError("story must carry a title")
    return compose_comic(
        storyboard,
        run_dir / "keyframes",
        title=title,
        fiction_label=str(story.get("fiction_label") or "Fiction inspired by today's news"),
        output_path=output_path,
        panels_dir=run_dir / "panels",
    )


# --- facts strip (T026): five source-linked factual cards ----------------------

STRIP_W = 640
CARD_PAD_X = 24
CARD_GAP = 18
STRIP_HEADER_H = 76


def facts_cards(
    summaries: Mapping[str, object],
    candidates: Mapping[str, object],
    *,
    ledger: Mapping[str, object] | None = None,
) -> list[dict]:
    """Pair each candidate (in rank order) with its two-sentence summary.

    The cards are numbered ``source 1-5`` in candidate order, matching the
    storyboard's ``source_ref`` markers. Title and link come from the candidate;
    the two-sentence summary comes from the matching summaries entry; the link
    falls back to the ledger story URL when the candidate lacks one.
    """
    summary_by_id = {
        str(summary.get("story_id") or ""): summary
        for summary in (summaries.get("summaries") or [])
        if isinstance(summary, Mapping)
    }
    ledger_by_id = {
        str(story.get("story_id") or ""): story
        for story in (ledger.get("stories") or [])
        if isinstance(story, Mapping)
    } if ledger is not None else {}
    raw_candidates = candidates.get("candidates")
    if not isinstance(raw_candidates, list):
        raise ComposeError("candidates must contain a candidates array")
    cards: list[dict] = []
    for index, candidate in enumerate(raw_candidates, start=1):
        if not isinstance(candidate, Mapping):
            raise ComposeError("candidate must be an object")
        candidate_id = str(candidate.get("candidate_id") or "")
        summary = summary_by_id.get(candidate_id)
        sentences = [str(s.get("text") or "") for s in (summary.get("sentences") or []) if isinstance(s, Mapping)]
        url = str(candidate.get("url") or "") or str(ledger_by_id.get(candidate_id, {}).get("url") or "")
        cards.append(
            {
                "source": index,
                "title": str(candidate.get("title") or "").strip(),
                "summary": " ".join(sentences).strip(),
                "link": url.strip(),
            }
        )
    return cards


def render_facts_strip(cards: Sequence[Mapping[str, object]], *, output_path: Path) -> Path:
    """Render the five fact cards as a vertical strip (title + summary + link)."""
    if not cards:
        raise ComposeError("facts strip needs at least one card")
    measurer = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    title_font = _font(22, bold=True)
    body_font = _font(18)
    link_font = _font(14)
    content_w = STRIP_W - 2 * CARD_PAD_X

    layouts: list[dict] = []
    height = STRIP_HEADER_H
    for card in cards:
        title_lines = _fit(measurer, str(card.get("title") or ""), title_font, content_w, 2)
        body_lines = _wrap(measurer, str(card.get("summary") or ""), body_font, content_w)
        link_lines = _fit(measurer, str(card.get("link") or ""), link_font, content_w, 2)
        title_lh = title_font.size + 4
        body_lh = body_font.size + 4
        link_lh = link_font.size + 2
        card_h = (
            12
            + title_lh * len(title_lines)
            + 6
            + body_lh * len(body_lines)
            + 6
            + link_lh * len(link_lines)
            + 14
        )
        layouts.append(
            {
                "card": card,
                "title_lines": title_lines,
                "body_lines": body_lines,
                "link_lines": link_lines,
                "title_lh": title_lh,
                "body_lh": body_lh,
                "link_lh": link_lh,
                "h": card_h,
            }
        )
        height += card_h + CARD_GAP
    height += 8

    image = Image.new("RGB", (STRIP_W, height), _PAPER)
    draw = ImageDraw.Draw(image)
    draw.text((STRIP_W / 2, 18), f"Based on: {len(cards)} sources", font=_font(24, bold=True), fill=_INK, anchor="ma")
    draw.text((STRIP_W / 2, 52), "Today's news — the five stories behind the comic", font=_font(15), fill=_INK_SOFT, anchor="ma")

    y = STRIP_HEADER_H
    for layout in layouts:
        card = layout["card"]
        source = int(card.get("source") or 0)
        draw.line([(CARD_PAD_X, y - 6), (STRIP_W - CARD_PAD_X, y - 6)], fill=_INK_SOFT, width=1)
        # source chip
        label = f"source {source}" if source else "source"
        pad = 8
        text_w = int(draw.textlength(label, font=link_font))
        chip_w = text_w + 2 * pad
        chip_h = link_font.size + 8
        draw.rounded_rectangle([CARD_PAD_X, y, CARD_PAD_X + chip_w, y + chip_h], radius=5, fill=_INK)
        draw.text((CARD_PAD_X + pad, y + 4), label, font=link_font, fill=_WHITE)
        ty = y + chip_h + 10
        for line in layout["title_lines"]:
            draw.text((CARD_PAD_X, ty), line, font=title_font, fill=_INK)
            ty += layout["title_lh"]
        ty += 4
        for line in layout["body_lines"]:
            draw.text((CARD_PAD_X, ty), line, font=body_font, fill=_INK)
            ty += layout["body_lh"]
        ty += 4
        for line in layout["link_lines"]:
            draw.text((CARD_PAD_X, ty), line, font=link_font, fill=_INK_SOFT)
            ty += layout["link_lh"]
        y += layout["h"] + CARD_GAP

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)
    return output_path


def run_facts(
    summaries: Mapping[str, object],
    candidates: Mapping[str, object],
    *,
    workspace_root: Path,
    run_id: str,
    ledger: Mapping[str, object] | None = None,
) -> Path:
    """Write ``runs/<run-id>/facts.png`` — the five source-linked fact cards."""
    root = workspace_root.resolve()
    output_path = require_allowed_write_path(root / "runs" / run_id / "facts.png", workspace_root=root)
    if output_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing facts strip: {output_path}")
    return render_facts_strip(facts_cards(summaries, candidates, ledger=ledger), output_path=output_path)
