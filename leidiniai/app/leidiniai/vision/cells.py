"""Product cells of a leaflet page picture, used to tidy the boxes a vision model gives.

Šilas (and most picture leaflets) print offers on white cards laid out in a grid over a grey or coloured
background. The model's own boxes are rough (shifted, too small, half of a neighbour), so a box is snapped to the
card it sits in.

Pillow only (no numpy in the app image). The page is shrunk to ~300 px wide and each pixel marked "card white"
(R, G, B all ≥ WHITE; the Šilas wood background stays ≤ 241). Gaps between cards hold (almost) no card white –
photos that overflow a card are not white either – so the page is cut into rows where a whole pixel row is nearly
free of white, and each row into cells the same way along the columns. Cells that are mostly not white (pictures
without cards, e.g. a free collage page) are dropped; such pages keep the model's boxes.
"""
from __future__ import annotations

WORK_W = 300          # width of the shrunk page used for finding cells
WHITE = 248           # card white: R, G and B at least this
GAP = 0.004           # a pixel row / column belongs to a gap when (almost) none of it is card white …
BG = 0.5              # … and at least this share of it is plain background (light, grey: not a photo)
MIN_GAP = 2           # … for at least this many pixels (of the shrunk page) in a row
MIN_SIDE = 0.10       # a cell is at least this share of the page width and height
MAX_AREA = 0.5        # … and at most this share of the page area
MIN_FILL = 0.15       # … and at least this share of it is card white (cards hold big photos)


def _white_map(img):
    W, H = img.size
    s = WORK_W / W
    w, h = WORK_W, max(1, round(H * s))
    raw = img.convert("RGB").resize((w, h)).tobytes()  # R, G, B bytes (works on every Pillow 10–12)
    white, bg = [], []
    for k in range(0, len(raw), 3):
        r, g, b = raw[k], raw[k + 1], raw[k + 2]
        lo, hi = min(r, g, b), max(r, g, b)
        white.append(1 if lo >= WHITE else 0)
        bg.append(1 if lo < WHITE and lo >= 185 and hi - lo <= 16 else 0)
    return white, bg, w, h, s


def _gap_profile(white, bg, w, xs, ys, along_x: bool) -> list[float]:
    """Per column (along_x) or per row: 1.0 = card, 0.0 = gap (no card white and mostly plain background)."""
    out = []
    for a in (xs if along_x else ys):
        n = wt = bt = 0
        for b in (ys if along_x else xs):
            i = (b * w + a) if along_x else (a * w + b)
            n += 1
            wt += white[i]
            bt += bg[i]
        out.append(0.0 if (wt / n < GAP and bt / n >= BG) else 1.0)
    return out


def _runs(profile: list[float], lo: int, hi: int) -> list[tuple[int, int]]:
    """Stretches [a, b) of `profile[lo:hi]` that are not gaps (gap: value 0 for ≥ MIN_GAP in a row)."""
    out, start, gap = [], None, 0
    for i in range(lo, hi):
        if profile[i - lo] == 0:
            gap += 1
            if gap >= MIN_GAP and start is not None:
                out.append((start, i - gap + 1))
                start = None
        else:
            if start is None:
                start = i
            gap = 0
    if start is not None:
        out.append((start, hi))
    return out


def find_cells(img) -> list[tuple[int, int, int, int]]:
    """Card boxes (x0, y0, x1, y1) in pixels of `img` (a PIL image), top-to-bottom, left-to-right."""
    W, H = img.size
    if W < 50 or H < 50:
        return []
    white, bg, w, h, s = _white_map(img)
    rows = _gap_profile(white, bg, w, range(w), range(h), along_x=False)
    cells = []
    for y0, y1 in _runs(rows, 0, h):
        if y1 - y0 < MIN_SIDE * h:
            continue
        cols = _gap_profile(white, bg, w, range(w), range(y0, y1), along_x=True)
        for x0, x1 in _runs(cols, 0, w):
            if x1 - x0 < MIN_SIDE * w:
                continue
            # tighten the top and bottom to this column range (cards in a row may differ in height)
            sub = _gap_profile(white, bg, w, range(x0, x1), range(y0, y1), along_x=False)
            for a, b in _runs(sub, y0, y1):
                if b - a < MIN_SIDE * h:
                    continue
                area = (x1 - x0) * (b - a)
                if area > MAX_AREA * w * h:
                    continue
                fill = sum(sum(white[y * w + x0:y * w + x1]) for y in range(a, b)) / area
                if fill < MIN_FILL:
                    continue
                cells.append((round(x0 / s), round(a / s), min(W, round(x1 / s)), min(H, round(b / s))))
    cells.sort(key=lambda c: (round(c[1] / (H * 0.05)), c[0]))
    return cells


def _overlap(a, b) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return w * h if w > 0 and h > 0 else 0


def snap(box, cells) -> tuple[int, int, int, int] | None:
    """The cell `box` belongs to: the one holding its centre, else the one it overlaps most (≥ 30 % of the box)."""
    if not cells or not box:
        return None
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    inside = [c for c in cells if c[0] <= cx <= c[2] and c[1] <= cy <= c[3]]
    if inside:
        return min(inside, key=lambda c: (c[2] - c[0]) * (c[3] - c[1]))
    area = max(1, (x1 - x0) * (y1 - y0))
    best = max(cells, key=lambda c: _overlap(box, c))
    return best if _overlap(box, best) >= 0.3 * area else None
