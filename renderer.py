"""Render a Kanban ticket card as a PIL Image for e-paper display.

Color palette (index-based) for B/W/R/Y tags:
  0 = white
  1 = black
  2 = red
  3 = yellow
"""

from __future__ import annotations

import hashlib
import math
import random
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


def _sym_ready_flower(draw: ImageDraw.ImageDraw, bx: int, by: int, size: int, petal_fill: int = 3) -> None:
    """Flower with black-outlined petals, stem, and leaf for Ready status."""
    cx = bx + size // 2
    cy = by + size // 3       # flower head in upper third, leaving room for stem

    petal_r  = max(2, size // 7)
    petal_d  = max(3, size // 5)
    center_r = max(1, size // 9)
    stem_lw  = max(1, size // 12)

    stem_top = cy + petal_d + petal_r - 1
    stem_bot = by + size - 1

    # Stem (drawn first so petals sit on top)
    draw.line([(cx, stem_top), (cx, stem_bot)], fill=1, width=stem_lw)

    # Leaf: small filled ellipse branching right from mid-stem
    leaf_y = stem_top + (stem_bot - stem_top) // 2
    lw = max(3, size // 5)
    lh = max(2, size // 9)
    draw.ellipse([cx + 1, leaf_y - lh, cx + lw, leaf_y + lh], fill=1)

    # Petals: black shadow ellipse first, then colored on top → visible outline
    for i in range(6):
        angle = math.radians(i * 60)
        px = cx + int(petal_d * math.cos(angle))
        py = cy + int(petal_d * math.sin(angle))
        draw.ellipse([px - petal_r - 1, py - petal_r - 1,
                      px + petal_r + 1, py + petal_r + 1], fill=1)
        draw.ellipse([px - petal_r, py - petal_r,
                      px + petal_r, py + petal_r], fill=petal_fill)

    # Black center dot
    draw.ellipse([cx - center_r, cy - center_r,
                  cx + center_r, cy + center_r], fill=1)


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
    issue_number: int = 0,
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
    elif s == "ready":
        petal_fill = random.Random(issue_number).choice([2, 3])  # stable per issue
        _sym_ready_flower(draw, bx, by, size, petal_fill)
    else:
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

    size_header = max(8, height // 10)
    size_medium = max(10, height // 9)
    size_small = max(8, height // 11)

    font_header = _load_font(font_bold_path, size_header)
    font_medium = _load_font(font_path, size_medium)
    font_small = _load_font(font_path, size_small)

    # White background
    draw.rectangle([0, 0, width - 1, height - 1], fill=0)

    # Header: black bar with white repo name (left) and [#issue] (right)
    issue_label = f"[#{issue_number}]"
    bbox = draw.textbbox((0, 0), issue_label, font=font_header)
    iw, ih = bbox[2] - bbox[0], bbox[3] - bbox[1]
    header_h = ih + 8

    # Status symbol: 1/3 of the white space below the header bar
    sym_size = (height - header_h) // 3
    sym_x = width - sym_size
    sym_y = height - sym_size

    draw.rectangle([0, 0, width - 1, header_h - 1], fill=1)
    draw.text((width - iw - 4, 4), issue_label, fill=0, font=font_header)

    if repo_name:
        avail_w = width - iw - 16  # 4px left pad + 8px gap before issue number + 4px right pad
        text = repo_name
        if draw.textlength(text, font=font_header) > avail_w:
            while text and draw.textlength(text + "…", font=font_header) > avail_w:
                text = text[:-1]
            text = text + "…"
        draw.text((4, 4), text, fill=0, font=font_header)

    # Body: title text, stopping above the symbol row
    body_top = header_h + 4
    body_bottom = sym_y - 4

    avail_w = width - 8  # 4px padding each side
    words = title.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = (current + " " + word).strip()
        if draw.textlength(candidate, font=font_medium) <= avail_w:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    if not lines:
        lines = [title]

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
    _draw_status_symbol(draw, img, sym_x, sym_y, sym_size, status, issue_number)

    return img.convert("RGB")


# ---------------------------------------------------------------------------
# Train car rendering — used for the "unused tag" pool
# ---------------------------------------------------------------------------

# 0 = steam engine (always last pulled from unused pool)
# 1-6 = rolling stock car types
_NUM_CAR_TYPES = 7


def _car_type_for_mac(mac: str) -> int:
    """Deterministic car type 1-6 for a MAC address (0 = steam engine, assigned separately)."""
    h = int(hashlib.md5(mac.encode()).hexdigest()[:8], 16)
    return 1 + h % (_NUM_CAR_TYPES - 1)


def _train_geo(H: int) -> tuple[int, int, int]:
    """Returns (rail_y, wheel_r, axle_y) for canvas height H."""
    rail_y = H - 9
    wheel_r = max(7, H // 11)
    axle_y = rail_y - wheel_r
    return rail_y, wheel_r, axle_y


def _draw_rails(draw: ImageDraw.ImageDraw, W: int, H: int) -> None:
    rail_y = H - 9
    tie_w = max(8, W // 28)
    for tx in range(0, W, tie_w + 7):
        draw.rectangle([tx, rail_y - 2, tx + tie_w, rail_y + 6], fill=1)
    draw.line([(0, rail_y), (W - 1, rail_y)], fill=1, width=2)
    draw.line([(0, rail_y + 4), (W - 1, rail_y + 4)], fill=1, width=2)


def _wheel(draw: ImageDraw.ImageDraw, cx: int, cy: int, r: int) -> None:
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=1)
    ir = max(2, r - 3)
    draw.ellipse([cx - ir, cy - ir, cx + ir, cy + ir], fill=0)
    draw.ellipse([cx - 2, cy - 2, cx + 2, cy + 2], fill=1)


def _coupler(draw: ImageDraw.ImageDraw, x: int, y: int, right: bool = False) -> None:
    d = 1 if right else -1
    draw.rectangle([x, y - 2, x + d * 7, y + 2], fill=1)
    draw.rectangle([x + d * 7, y - 4, x + d * 10, y + 4], fill=1)


# --- Car type 0: Steam locomotive -------------------------------------------

def _car_steam(draw: ImageDraw.ImageDraw, img: Image.Image, W: int, H: int) -> None:
    _, wr, ay = _train_geo(H)
    lx = W // 9
    rx = W - W // 9
    span = rx - lx
    cab_x = lx + span * 68 // 100
    boiler_top = ay - H * 33 // 100
    cab_top    = ay - H * 48 // 100

    # Cowcatcher (angled wedge at front/left)
    draw.polygon([(lx, boiler_top), (lx, ay), (lx - W // 22, ay + 4)], fill=1)

    # Boiler body
    draw.rectangle([lx, boiler_top, cab_x, ay], fill=1)

    # Boiler bands (white lines)
    for frac in (0.25, 0.50, 0.72):
        bx = lx + int((cab_x - lx) * frac)
        draw.line([(bx, boiler_top + 2), (bx, ay - 2)], fill=0, width=1)

    # Sand dome
    dome_cx = lx + (cab_x - lx) * 55 // 100
    dome_r = max(5, W // 26)
    draw.ellipse([dome_cx - dome_r, boiler_top - dome_r // 2,
                  dome_cx + dome_r, boiler_top + dome_r], fill=1)

    # Smokestack
    stk_cx = lx + (cab_x - lx) // 6
    stk_w  = max(5, W // 32)
    stk_h  = max(10, H // 6)
    stk_top = boiler_top - stk_h
    draw.rectangle([stk_cx - stk_w // 2, stk_top + 4,
                    stk_cx + stk_w // 2, boiler_top], fill=1)
    draw.rectangle([stk_cx - stk_w // 2 - 3, stk_top,
                    stk_cx + stk_w // 2 + 3, stk_top + 5], fill=1)

    # Smoke puffs (filled circle + smaller white hollow inside)
    for dx, dy, r in [(0, -8, 7), (6, -16, 6), (-4, -23, 5), (5, -30, 4)]:
        px, py = stk_cx + dx, stk_top + dy
        if py - r >= 2:
            draw.ellipse([px - r, py - r, px + r, py + r], fill=1)
            ir = r - 2
            if ir > 1:
                draw.ellipse([px - ir, py - ir, px + ir, py + ir], fill=0)

    # Headlight (yellow circle on front face)
    hl_r = max(3, W // 55)
    hl_y = boiler_top + (ay - boiler_top) // 2
    draw.ellipse([lx + 2, hl_y - hl_r, lx + 2 + hl_r * 2, hl_y + hl_r], fill=3)

    # Cab body
    draw.rectangle([cab_x, cab_top, rx, ay], fill=1)

    # Cab windows (two white panes)
    cw = max(5, (rx - cab_x) // 3 - 2)
    ch = (ay - cab_top) // 3
    for i in range(2):
        wx = cab_x + 3 + i * (cw + 3)
        if wx + cw < rx - 2:
            draw.rectangle([wx, cab_top + 4, wx + cw, cab_top + 4 + ch], fill=0)

    # Drive wheels (2 large)
    dw1 = lx + (cab_x - lx) * 32 // 100
    dw2 = lx + (cab_x - lx) * 62 // 100
    _wheel(draw, dw1, ay, wr)
    _wheel(draw, dw2, ay, wr)
    # Connecting rod
    draw.line([(dw1, ay - wr // 3), (dw2, ay - wr // 3)], fill=1, width=max(2, H // 28))

    # Small pilot wheel (front)
    swr = max(5, wr * 2 // 3)
    _wheel(draw, lx + swr + 2, ay, swr)

    # Small trailing wheel (under cab)
    _wheel(draw, cab_x + (rx - cab_x) // 2, ay, swr)


# --- Car type 1: Coal tender ------------------------------------------------

def _car_tender(draw: ImageDraw.ImageDraw, img: Image.Image, W: int, H: int) -> None:
    _, wr, ay = _train_geo(H)
    lx, rx = W // 8, W - W // 8
    car_top = ay - H * 38 // 100
    coal_top = car_top - max(4, H // 12)

    # Car body
    draw.rectangle([lx, car_top, rx, ay], fill=1)

    # Coal mound (slightly uneven filled shape on top)
    mid = (lx + rx) // 2
    draw.polygon([
        (lx + 4, car_top),
        (lx + 4, coal_top + 4),
        (lx + (rx - lx) // 5, coal_top),
        (mid - 5, coal_top - 5),
        (mid + 8, coal_top - 3),
        (rx - (rx - lx) // 5, coal_top + 2),
        (rx - 4, car_top),
    ], fill=1)

    # Highlight lumps on coal (white dashes suggest texture)
    for cx in range(lx + 12, rx - 10, 18):
        draw.arc([cx, coal_top - 2, cx + 10, coal_top + 6], 200, 340, fill=0, width=1)

    # Frame stripe
    draw.line([(lx, ay - 3), (rx, ay - 3)], fill=0, width=1)

    # Wheels (2)
    span = rx - lx
    for wx in [lx + span // 4, rx - span // 4]:
        _wheel(draw, wx, ay, wr)

    _coupler(draw, lx, ay - wr // 2, right=False)
    _coupler(draw, rx, ay - wr // 2, right=True)


# --- Car type 2: Passenger car ----------------------------------------------

def _car_passenger(draw: ImageDraw.ImageDraw, img: Image.Image, W: int, H: int) -> None:
    _, wr, ay = _train_geo(H)
    lx, rx = W // 10, W - W // 10
    car_top = ay - H * 44 // 100
    roof_h  = max(5, H // 14)
    roof_top = car_top - roof_h

    # Roof (slightly rounded via polygon)
    roof_mid = (lx + rx) // 2
    draw.polygon([
        (lx + 6, car_top), (rx - 6, car_top),
        (rx - 2, roof_top + roof_h // 2),
        (roof_mid, roof_top),
        (lx + 2, roof_top + roof_h // 2),
    ], fill=1)

    # Car body
    draw.rectangle([lx, car_top, rx, ay], fill=1)

    # Windows (row of white rectangles)
    win_w = max(8, (rx - lx) // 8)
    win_h = max(8, (ay - car_top) // 3)
    win_y  = car_top + (ay - car_top) // 5
    gap    = max(4, (rx - lx - 4) // 7 - win_w)
    x = lx + 6
    while x + win_w <= rx - 6:
        draw.rectangle([x, win_y, x + win_w, win_y + win_h], fill=0)
        x += win_w + gap

    # Door line (center)
    door_cx = (lx + rx) // 2
    draw.line([(door_cx, car_top + 2), (door_cx, ay - 2)], fill=0, width=1)

    # Bottom stripe
    draw.line([(lx, ay - 4), (rx, ay - 4)], fill=0, width=2)

    # Wheels (3 axles for a long car)
    span = rx - lx
    for wx in [lx + span // 5, (lx + rx) // 2, rx - span // 5]:
        _wheel(draw, wx, ay, wr)

    _coupler(draw, lx, ay - wr // 2, right=False)
    _coupler(draw, rx, ay - wr // 2, right=True)


# --- Car type 3: Box car ----------------------------------------------------

def _car_boxcar(draw: ImageDraw.ImageDraw, img: Image.Image, W: int, H: int) -> None:
    _, wr, ay = _train_geo(H)
    lx, rx = W // 9, W - W // 9
    car_top = ay - H * 46 // 100

    # Body
    draw.rectangle([lx, car_top, rx, ay], fill=1)

    # Roof cap (slightly raised)
    draw.rectangle([lx - 2, car_top - 3, rx + 2, car_top + 2], fill=1)

    # Sliding door (two panels with gap)
    door_w = (rx - lx) * 28 // 100
    door_cx = (lx + rx) // 2
    door_h = (ay - car_top) * 7 // 10
    # Left panel
    draw.rectangle([door_cx - door_w, car_top + 4,
                    door_cx - 2, car_top + 4 + door_h], fill=0)
    draw.rectangle([door_cx - door_w, car_top + 4,
                    door_cx - 2, car_top + 4 + door_h], outline=1)
    # Right panel
    draw.rectangle([door_cx + 2, car_top + 4,
                    door_cx + door_w, car_top + 4 + door_h], fill=0)
    draw.rectangle([door_cx + 2, car_top + 4,
                    door_cx + door_w, car_top + 4 + door_h], outline=1)

    # Door track rail
    draw.line([(lx + 4, car_top + 3), (rx - 4, car_top + 3)], fill=0, width=1)

    # Side bracing lines
    for frac in (0.18, 0.82):
        bx = lx + int((rx - lx) * frac)
        draw.line([(bx, car_top + 2), (bx, ay - 2)], fill=0, width=1)

    # Wheels (2)
    span = rx - lx
    for wx in [lx + span // 4, rx - span // 4]:
        _wheel(draw, wx, ay, wr)

    _coupler(draw, lx, ay - wr // 2, right=False)
    _coupler(draw, rx, ay - wr // 2, right=True)


# --- Car type 4: Tank car ---------------------------------------------------

def _car_tanker(draw: ImageDraw.ImageDraw, img: Image.Image, W: int, H: int) -> None:
    _, wr, ay = _train_geo(H)
    lx, rx = W // 9, W - W // 9
    tank_r_v = H * 20 // 100          # vertical radius of tank
    tank_cy  = ay - tank_r_v - H // 12  # vertical center of tank

    # Underframe (thin rectangle below tank)
    frame_y = ay - H // 8
    draw.rectangle([lx, frame_y, rx, ay], fill=1)

    # Tank body (fat ellipse / stadium shape)
    tank_r_h = (rx - lx) // 2 - 4
    draw.ellipse([lx + 4, tank_cy - tank_r_v, rx - 4, tank_cy + tank_r_v], fill=1)

    # Tank bands (white arcs)
    mid = (lx + rx) // 2
    for bx in [mid - (rx - lx) // 4, mid, mid + (rx - lx) // 4]:
        draw.line([(bx, tank_cy - tank_r_v + 2), (bx, tank_cy + tank_r_v - 2)], fill=0, width=1)

    # Dome valve on top
    dome_r = max(4, W // 28)
    draw.ellipse([(lx + rx) // 2 - dome_r, tank_cy - tank_r_v - dome_r * 2,
                  (lx + rx) // 2 + dome_r, tank_cy - tank_r_v + 2], fill=1)

    # Safety valve nub on dome
    dv_x = (lx + rx) // 2
    draw.rectangle([dv_x - 2, tank_cy - tank_r_v - dome_r * 2 - 4,
                    dv_x + 2, tank_cy - tank_r_v - dome_r * 2], fill=1)

    # Support legs from tank to frame
    for leg_x in [lx + (rx - lx) // 4, rx - (rx - lx) // 4]:
        draw.line([(leg_x, tank_cy + tank_r_v), (leg_x, frame_y)], fill=1, width=2)

    # Wheels (2)
    span = rx - lx
    for wx in [lx + span // 4, rx - span // 4]:
        _wheel(draw, wx, ay, wr)

    _coupler(draw, lx, ay - wr // 2, right=False)
    _coupler(draw, rx, ay - wr // 2, right=True)


# --- Car type 5: Flat car with log load -------------------------------------

def _car_flatcar(draw: ImageDraw.ImageDraw, img: Image.Image, W: int, H: int) -> None:
    _, wr, ay = _train_geo(H)
    lx, rx = W // 9, W - W // 9
    deck_y = ay - H * 18 // 100   # top of deck
    deck_h = max(4, H // 18)

    # Deck (thin flat platform)
    draw.rectangle([lx, deck_y, rx, deck_y + deck_h], fill=1)

    # Stake pockets (small vertical rectangles at edges)
    for sx in [lx + 8, lx + (rx - lx) // 3, rx - (rx - lx) // 3, rx - 8]:
        draw.rectangle([sx - 2, deck_y - 6, sx + 2, deck_y], fill=1)

    # Log stack: rows of overlapping circles
    log_r = max(5, H // 15)
    cols = max(3, (rx - lx) // (log_r * 2 + 2))
    rows = 2
    total_w = cols * (log_r * 2 + 1)
    log_start_x = (lx + rx - total_w) // 2 + log_r
    for row in range(rows):
        offset = log_r * row // 2  # stagger upper row
        base_y = deck_y - log_r - row * (log_r * 2 - 2)
        for col in range(cols - row):
            lc_x = log_start_x + col * (log_r * 2 + 1) + offset
            # Log end-on: filled circle with ring
            draw.ellipse([lc_x - log_r, base_y - log_r,
                          lc_x + log_r, base_y + log_r], fill=1)
            ir = max(2, log_r - 3)
            draw.ellipse([lc_x - ir, base_y - ir, lc_x + ir, base_y + ir], fill=0)
            draw.ellipse([lc_x - 2, base_y - 2, lc_x + 2, base_y + 2], fill=1)

    # Wheels (2)
    span = rx - lx
    for wx in [lx + span // 4, rx - span // 4]:
        _wheel(draw, wx, ay, wr)

    _coupler(draw, lx, ay - wr // 2, right=False)
    _coupler(draw, rx, ay - wr // 2, right=True)


# --- Car type 6: Caboose (red) ----------------------------------------------

def _car_caboose(draw: ImageDraw.ImageDraw, img: Image.Image, W: int, H: int) -> None:
    _, wr, ay = _train_geo(H)
    lx, rx = W // 9, W - W // 9
    car_top  = ay - H * 42 // 100
    cup_w    = (rx - lx) * 40 // 100
    cup_x    = (lx + rx - cup_w) // 2
    cup_top  = car_top - H * 20 // 100

    # Main body (red)
    draw.rectangle([lx, car_top, rx, ay], fill=2)

    # Roof (black)
    draw.rectangle([lx - 2, car_top - 3, rx + 2, car_top + 2], fill=1)

    # Cupola sides and roof (black outline, red fill)
    draw.rectangle([cup_x, cup_top, cup_x + cup_w, car_top], fill=2)
    draw.rectangle([cup_x - 2, cup_top - 3, cup_x + cup_w + 2, cup_top + 2], fill=1)

    # Cupola windows
    cwin_w = max(5, cup_w // 4)
    cwin_h = max(4, (car_top - cup_top) // 2)
    for i in range(2):
        wx = cup_x + 4 + i * (cup_w - cwin_w * 2 - 4)
        draw.rectangle([wx, cup_top + 3, wx + cwin_w, cup_top + 3 + cwin_h], fill=0)

    # Body windows
    win_w = max(8, (rx - lx) // 6)
    win_h = max(7, (ay - car_top) // 3)
    win_y  = car_top + (ay - car_top) // 5
    for wx in [lx + 6, rx - 6 - win_w]:
        draw.rectangle([wx, win_y, wx + win_w, win_y + win_h], fill=0)

    # Bottom trim stripe (black)
    draw.line([(lx, ay - 4), (rx, ay - 4)], fill=1, width=2)

    # Wheels (2)
    span = rx - lx
    for wx in [lx + span // 4, rx - span // 4]:
        _wheel(draw, wx, ay, wr)

    _coupler(draw, lx, ay - wr // 2, right=False)
    _coupler(draw, rx, ay - wr // 2, right=True)


_CAR_DRAWERS = [
    _car_steam, _car_tender, _car_passenger, _car_boxcar,
    _car_tanker, _car_flatcar, _car_caboose,
]


def render_train_car(
    width: int,
    height: int,
    car_type: int,
    font_path: str = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    font_bold_path: str = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
) -> Image.Image:
    """Render a train car of the given type (0=steam engine, 1-6=rolling stock)."""
    img = Image.new("P", (width, height))
    img.putpalette(_PALETTE_RGB)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, width - 1, height - 1], fill=0)
    _draw_rails(draw, width, height)
    car_type = max(0, min(car_type, _NUM_CAR_TYPES - 1))
    _CAR_DRAWERS[car_type](draw, img, width, height)
    return img.convert("RGB")


def render_unused(
    width: int,
    height: int,
    font_path: str = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    font_bold_path: str = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
) -> Image.Image:
    """Render a simple 'unused' placeholder for tags with no current sprint item."""
    img = Image.new("P", (width, height))
    img.putpalette(_PALETTE_RGB)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, width - 1, height - 1], fill=0)

    font = _load_font(font_bold_path, max(12, height // 7))
    text = "unused"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((width - tw) // 2, (height - th) // 2), text, fill=1, font=font)

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
