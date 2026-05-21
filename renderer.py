"""Render a Kanban ticket card as a PIL Image for e-paper display.

Color palette (index-based) for B/W/R/Y tags:
  0 = white
  1 = black
  2 = red
  3 = yellow
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Palette: white, black, red, yellow — matches B/W/R/Y e-paper tags.
_PALETTE_RGB = [
    255, 255, 255,  # 0 white
    0,   0,   0,   # 1 black
    220, 30,  30,  # 2 red
    255, 255, 0,   # 3 yellow
] + [0] * (256 * 3 - 12)


def _load_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    p = Path(path)
    if p.exists():
        return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()


# ---------------------------------------------------------------------------
# Status symbol helpers — each draws into a square at (bx, by) of `size` px
# ---------------------------------------------------------------------------

def _sym_outline(draw: ImageDraw.ImageDraw, bx: int, by: int, size: int) -> None:
    draw.rectangle([bx, by, bx + size - 1, by + size - 1], outline=1, fill=0)


def _sym_stripes(
    draw: ImageDraw.ImageDraw, img: Image.Image, bx: int, by: int, size: int
) -> None:
    """45-degree alternating black/white stripes (In Progress)."""
    stripe_w = max(2, size // 4)
    for row in range(size):
        for col in range(size):
            color = 1 if ((col + row) // stripe_w) % 2 == 0 else 0
            img.putpixel((bx + col, by + row), color)


def _sym_done(draw: ImageDraw.ImageDraw, bx: int, by: int, size: int) -> None:
    """White checkmark on a filled black box."""
    draw.rectangle([bx, by, bx + size - 1, by + size - 1], fill=1)
    m = max(2, size // 6)
    lw = max(2, size // 10)
    cx = bx + m + (size - 2 * m) // 3
    cy = by + size - m
    draw.line([(bx + m, by + size // 2), (cx, cy)], fill=0, width=lw)
    draw.line([(cx, cy), (bx + size - m, by + m)], fill=0, width=lw)


def _sym_aborted(draw: ImageDraw.ImageDraw, bx: int, by: int, size: int) -> None:
    """White X on a filled black box."""
    draw.rectangle([bx, by, bx + size - 1, by + size - 1], fill=1)
    m = max(2, size // 5)
    lw = max(2, size // 10)
    draw.line([(bx + m, by + m), (bx + size - m, by + size - m)], fill=0, width=lw)
    draw.line([(bx + size - m, by + m), (bx + m, by + size - m)], fill=0, width=lw)


def _sym_blocked(draw: ImageDraw.ImageDraw, bx: int, by: int, size: int) -> None:
    """Red octagon inside an empty box outline (Blocked)."""
    _sym_outline(draw, bx, by, size)
    m = max(2, size // 6)
    cut = max(2, (size - 2 * m) // 3)
    l, r = bx + m, bx + size - 1 - m
    t, b = by + m, by + size - 1 - m
    draw.polygon([
        l + cut, t,
        r - cut, t,
        r,       t + cut,
        r,       b - cut,
        r - cut, b,
        l + cut, b,
        l,       b - cut,
        l,       t + cut,
    ], fill=2)  # red


def _sym_in_review(draw: ImageDraw.ImageDraw, bx: int, by: int, size: int) -> None:
    """Speech bubble inside an empty box outline (In Review)."""
    _sym_outline(draw, bx, by, size)
    m = max(2, size // 7)
    bl, br = bx + m, bx + size - 1 - m
    bt, bb = by + m, by + int(size * 0.62)
    draw.rectangle([bl, bt, br, bb], fill=1)
    tw = max(2, size // 4)
    draw.polygon([(bl, bb), (bl + tw, bb), (bl, by + size - 1 - m)], fill=1)


def _draw_drop_arrow(draw: ImageDraw.ImageDraw, x: int, y: int, size: int) -> None:
    """Draw a ↳-style drop arrow fitting in a square of `size` pixels."""
    lw = max(1, size // 7)
    stem_x = x + lw // 2
    turn_y = y + (size * 2) // 3
    tip_x  = x + size - 1
    aw = max(2, size // 4)
    draw.line([(stem_x, y), (stem_x, turn_y)], fill=1, width=lw)
    draw.line([(stem_x, turn_y), (tip_x, turn_y)], fill=1, width=lw)
    draw.line([(tip_x - aw, turn_y - aw), (tip_x, turn_y)], fill=1, width=lw)
    draw.line([(tip_x - aw, turn_y + aw), (tip_x, turn_y)], fill=1, width=lw)


def _draw_status_symbol(
    draw: ImageDraw.ImageDraw,
    img: Image.Image,
    bx: int,
    by: int,
    size: int,
    status: str,
) -> None:
    s = status.lower().strip()
    if s == "in progress":
        _sym_stripes(draw, img, bx, by, size)
    elif s == "done":
        _sym_done(draw, bx, by, size)
    elif s == "aborted":
        _sym_aborted(draw, bx, by, size)
    elif s == "blocked":
        _sym_blocked(draw, bx, by, size)
    elif s == "in review":
        _sym_in_review(draw, bx, by, size)
    else:
        # Ready, Todo, Backlog, Needs Triage — empty outline
        _sym_outline(draw, bx, by, size)


def render_card(
    width: int,
    height: int,
    issue_number: int,
    title: str,
    status: str,
    assignee: str,
    repo_name: str = "",
    sub_issues: tuple[int, ...] = (),
    font_path: str = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    font_bold_path: str = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
) -> Image.Image:
    img = Image.new("P", (width, height))
    img.putpalette(_PALETTE_RGB)
    draw = ImageDraw.Draw(img)

    size_large = max(12, height // 7)
    size_medium = max(10, height // 9)
    size_small = max(8, height // 11)

    font_large = _load_font(font_bold_path, size_large)
    font_medium = _load_font(font_path, size_medium)
    font_small = _load_font(font_path, size_small)

    # Status symbol: square in bottom-right corner, 1/5 of tag height
    sym_size = height // 5
    sym_x = width - sym_size
    sym_y = height - sym_size

    # White background
    draw.rectangle([0, 0, width - 1, height - 1], fill=0)

    # Header: repo name (left) and [#issue] (right), bold on white
    issue_label = f"[#{issue_number}]"
    bbox = draw.textbbox((0, 0), issue_label, font=font_large)
    iw, ih = bbox[2] - bbox[0], bbox[3] - bbox[1]
    header_h = ih + 8

    if repo_name:
        draw.text((4, 4), repo_name, fill=1, font=font_large)
    draw.text((width - iw - 4, 4), issue_label, fill=1, font=font_large)

    # Body: title text, stopping above the symbol row
    body_top = header_h + 4
    body_bottom = sym_y - 4

    avg_char_w = max(1, draw.textlength("M", font=font_medium))
    chars_per_line = max(1, int((width - 8) / avg_char_w))
    lines = textwrap.wrap(title, width=chars_per_line) or [title]

    line_h = size_medium + 3
    y = body_top
    for line in lines:
        if y + line_h > body_bottom:
            break
        draw.text((4, y), line, fill=1, font=font_medium)
        y += line_h

    # Sub-issues row: ↳ [#98] [#87] [#101]
    if sub_issues:
        sub_line_h = size_small + 3
        if y + sub_line_h <= body_bottom:
            arrow_w = size_small + 4
            _draw_drop_arrow(draw, 4, y, size_small)
            sub_text = " ".join(f"[#{n}]" for n in sub_issues)
            draw.text((4 + arrow_w, y), sub_text, fill=1, font=font_small)

    # Assignee: left-aligned, vertically centred in the symbol row
    if assignee:
        assignee_text = f"@{assignee}"
        bbox = draw.textbbox((0, 0), assignee_text, font=font_small)
        ah = bbox[3] - bbox[1]
        draw.text((4, sym_y + (sym_size - ah) // 2), assignee_text, fill=1, font=font_small)

    # Status symbol: bottom-right corner
    _draw_status_symbol(draw, img, sym_x, sym_y, sym_size, status)

    return img.convert("RGB")


def render_waiting_prompt(
    width: int,
    height: int,
    tag_label: str,
    font_path: str = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    font_bold_path: str = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
) -> Image.Image:
    """Render a neutral 'waiting to be registered' screen."""
    img = Image.new("P", (width, height))
    img.putpalette(_PALETTE_RGB)
    draw = ImageDraw.Draw(img)

    size_large  = max(12, height // 7)
    size_medium = max(10, height // 9)

    font_large  = _load_font(font_bold_path, size_large)
    font_medium = _load_font(font_path, size_medium)

    draw.rectangle([0, 0, width - 1, height - 1], fill=0)  # white background

    # Black header with tag label
    header_h = size_large + 8
    draw.rectangle([0, 0, width - 1, header_h - 1], fill=1)
    bbox = draw.textbbox((0, 0), tag_label, font=font_large)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((width - tw) // 2, (header_h - th) // 2), tag_label, fill=0, font=font_large)

    # Centred "WAITING TO REGISTER" text
    for i, text in enumerate(["WAITING TO", "REGISTER"]):
        font = font_large if i == 1 else font_medium
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        y = header_h + (height - header_h) // 2 + (i - 1) * (th + 6)
        draw.text(((width - tw) // 2, y), text, fill=1, font=font)

    return img.convert("RGB")


def render_registered_confirmation(
    width: int,
    height: int,
    tag_label: str,
    font_path: str = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    font_bold_path: str = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
) -> Image.Image:
    """Render a 'Registered' confirmation screen."""
    img = Image.new("P", (width, height))
    img.putpalette(_PALETTE_RGB)
    draw = ImageDraw.Draw(img)

    size_large  = max(12, height // 7)
    size_medium = max(10, height // 9)

    font_large  = _load_font(font_bold_path, size_large)
    font_medium = _load_font(font_path, size_medium)

    draw.rectangle([0, 0, width - 1, height - 1], fill=0)  # white background

    # Black header with tag label
    header_h = size_large + 8
    draw.rectangle([0, 0, width - 1, header_h - 1], fill=1)
    bbox = draw.textbbox((0, 0), tag_label, font=font_large)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((width - tw) // 2, (header_h - th) // 2), tag_label, fill=0, font=font_large)

    # "REGISTERED" centred in the body
    text = "REGISTERED"
    bbox = draw.textbbox((0, 0), text, font=font_large)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((width - tw) // 2, header_h + (height - header_h - th) // 2), text, fill=1, font=font_large)

    return img.convert("RGB")


def render_registration_prompt(
    width: int,
    height: int,
    tag_label: str,
    column: str = "READY",
    font_path: str = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    font_bold_path: str = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
) -> Image.Image:
    """Render a 'tap me to register' screen on an e-paper tag."""
    img = Image.new("P", (width, height))
    img.putpalette(_PALETTE_RGB)
    draw = ImageDraw.Draw(img)

    size_large  = max(12, height // 7)
    size_medium = max(10, height // 9)

    font_large  = _load_font(font_bold_path, size_large)
    font_medium = _load_font(font_path, size_medium)

    draw.rectangle([0, 0, width - 1, height - 1], fill=0)  # white background

    # Yellow header showing the tag's alias/label
    header_h = size_large + 8
    draw.rectangle([0, 0, width - 1, header_h - 1], fill=3)
    bbox = draw.textbbox((0, 0), tag_label, font=font_large)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((width - tw) // 2, (header_h - th) // 2), tag_label, fill=1, font=font_large)

    # Centred instruction block
    lines = [("TAP ME ON", font_medium, 1), (column, font_large, 2), ("TO REGISTER", font_medium, 1)]
    line_heights = []
    for text, font, _ in lines:
        b = draw.textbbox((0, 0), text, font=font)
        line_heights.append(b[3] - b[1] + 6)

    total_h = sum(line_heights)
    y = header_h + (height - header_h - total_h) // 2

    for (text, font, fill), lh in zip(lines, line_heights):
        b = draw.textbbox((0, 0), text, font=font)
        tw = b[2] - b[0]
        draw.text(((width - tw) // 2, y), text, fill=fill, font=font)
        y += lh

    return img.convert("RGB")
