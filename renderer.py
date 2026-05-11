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

# Status → (accent_fill, text_on_accent)
# accent_fill: palette index for the status bar background
# text_on_accent: palette index for text drawn on top of it
_STATUS_THEME: dict[str, tuple[int, int]] = {
    "needs triage": (3, 1),  # yellow bar, black text — attention needed
    "todo":         (3, 1),  # yellow bar, black text
    "ready":        (3, 1),  # yellow bar, black text — queued up
    "in progress":  (2, 0),  # red bar, white text — active
    "in review":    (2, 0),  # red bar, white text — active review
    "blocked":      (2, 0),  # red bar, white text — urgent
    "done":         (1, 0),  # black bar, white text — completed
    "aborted":      (1, 0),  # black bar, white text — terminal
    "backlog":      (1, 0),  # black bar, white text
}


def _load_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    p = Path(path)
    if p.exists():
        return ImageFont.truetype(str(p), size)
    # Fallback to Pillow's built-in bitmap font
    return ImageFont.load_default()


def render_card(
    width: int,
    height: int,
    issue_number: int,
    title: str,
    status: str,
    assignee: str,
    font_path: str = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    font_bold_path: str = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
) -> Image.Image:
    img = Image.new("P", (width, height))
    img.putpalette(_PALETTE_RGB)
    draw = ImageDraw.Draw(img)

    accent_fill, accent_text = _STATUS_THEME.get(status.lower(), (1, 0))

    # Scale font sizes proportionally to tag height
    size_large = max(12, height // 7)
    size_medium = max(10, height // 9)
    size_small = max(8, height // 11)

    font_large = _load_font(font_bold_path, size_large)
    font_medium = _load_font(font_path, size_medium)
    font_small = _load_font(font_path, size_small)

    header_h = size_large + 8
    footer_h = size_small + 10

    # White background
    draw.rectangle([0, 0, width - 1, height - 1], fill=0)

    # Header: black bar with issue number in yellow
    draw.rectangle([0, 0, width - 1, header_h - 1], fill=1)
    issue_label = f"#{issue_number}"
    bbox = draw.textbbox((0, 0), issue_label, font=font_large)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(
        ((width - tw) // 2, (header_h - th) // 2),
        issue_label,
        fill=3,  # yellow issue number on black header
        font=font_large,
    )

    # Body: title text on white
    body_top = header_h + 4
    body_bottom = height - footer_h - 4

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

    # Footer: status-colored bar (yellow/red/black) with status label + assignee
    draw.rectangle([0, height - footer_h, width - 1, height - 1], fill=accent_fill)

    status_text = status.upper()
    draw.text((4, height - footer_h + 3), status_text, fill=accent_text, font=font_small)

    if assignee:
        assignee_text = f"@{assignee}"
        bbox = draw.textbbox((0, 0), assignee_text, font=font_small)
        aw = bbox[2] - bbox[0]
        draw.text(
            (width - aw - 4, height - footer_h + 3),
            assignee_text,
            fill=accent_text,
            font=font_small,
        )

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
