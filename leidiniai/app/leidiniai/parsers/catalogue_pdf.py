"""Price-list catalogues in PDF (Rimi "Alkoholinių gėrimų asortimento katalogas", checked on Nr. 23, 2026-11).

No discounts: these are regular prices (alcohol advertising and price promotions are banned in Lithuania since
2018), so every item is kind "catalogue" without an old price. Layout per cell, top to bottom: big euros (54 pt)
with superscript cents (18 pt) and "EUR", the volume ("0,75 l"), a description (7 pt), the name (8 pt: type
line, BRAND line, "(2 rūšys)"), the unit price ("1 l - 13,32 EUR", 6.5 pt). Country names are printed as single
rotated letters – ignored. The validity ("2026 11 17-2026 11 30") is on the cover.
"""
from __future__ import annotations

import re
from datetime import date

from ..textutil import parse_range
from . import Offer, cents, finish

EUROS_MIN = 30        # pt
CENTS = (12, 30)
NAME_SIZE = (7.6, 9.2)
VOLUME = re.compile(r"(?<![\d,])(\d+(?:,\d+)?\s*(?:l|ml|cl|g|kg))(?![\w])", re.I)
COVER_RANGE = re.compile(r"(20\d\d)[ .](\d\d)[ .](\d\d)\s*[-–]\s*(20\d\d)[ .](\d\d)[ .](\d\d)")
UNIT = re.compile(r"1\s*(l|kg)\s*[-–]\s*(\d+,\d\d)\s*EUR", re.I)


def _lines(words):
    rows: dict[int, list] = {}
    for w in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
        rows.setdefault(round(w["top"] / 3), []).append(w)
    return [sorted(ws, key=lambda w: w["x0"]) for _, ws in sorted(rows.items())]


def parse(path, log=None) -> list[Offer]:
    import pdfplumber
    out: list[Offer] = []
    vf = vt = None
    with pdfplumber.open(str(path)) as pdf:
        first = (pdf.pages[0].extract_text() or "") if pdf.pages else ""
        ext = "Alkoholio katalogas" if re.search(r"(?i)alkohol", first) else None
        m = COVER_RANGE.search(first)  # "2026 11 17-2026 11 30" (the cover also says "nuo lapkričio 19 d.")
        if m:
            y1, m1, d1, y2, m2, d2 = map(int, m.groups())
            vf, vt = date(y1, m1, d1), date(y2, m2, d2)
        else:
            vf, vt = parse_range(first, date.today())
        for pno, page in enumerate(pdf.pages, 1):
            words = page.extract_words(extra_attrs=["size", "fontname"], keep_blank_chars=False)
            euros = [w for w in words if w["size"] >= EUROS_MIN and w["text"].isdigit()]
            cents_w = [w for w in words if CENTS[0] <= w["size"] <= CENTS[1] and re.fullmatch(r"\d\d", w["text"])]
            anchors = []
            for e in euros:
                c = min((c for c in cents_w if -5 <= c["x0"] - e["x1"] <= 40 and abs(c["top"] - e["top"]) <= 30),
                        key=lambda c: abs(c["x0"] - e["x1"]), default=None)
                anchors.append((e, c))
            for e, c in anchors:
                right = min((a["x0"] for a, _ in anchors if a["x0"] > e["x0"] + 60 and abs(a["top"] - e["top"]) < 60),
                            default=page.width)
                below = min((a["top"] for a, _ in anchors if a["top"] > e["top"] + 60 and abs(a["x0"] - e["x0"]) < 120),
                            default=page.height - 30)
                x0, x1 = e["x0"] - 25, min(right - 5, e["x0"] + 200)
                region = [w for w in words if x0 <= w["x0"] < x1 and e["top"] - 5 < w["top"] < below - 5]
                name_lines, unit, vol = [], None, None
                for ln in _lines(region):
                    text = " ".join(w["text"] for w in ln)
                    size = ln[0]["size"]
                    m = UNIT.search(text)
                    if m and unit is None:
                        unit = m
                        continue
                    if vol is None and ln[0]["top"] < e["top"] + 80 and not (NAME_SIZE[0] <= size <= NAME_SIZE[1]):
                        mv = VOLUME.search(text)
                        if mv:
                            vol = mv.group(1)
                            continue
                    if NAME_SIZE[0] <= size <= NAME_SIZE[1] and len(text) > 2:
                        name_lines.append(text)
                o = Offer(chain="rimi", name=" ".join(name_lines), kind="catalogue", page=pno, ext_category=ext,
                          price=int(e["text"]) * 100 + (int(c["text"]) if c else 0),
                          valid_from=vf, valid_to=vt, quantity=vol)
                if unit:
                    o.unit, o.unit_price = unit.group(1).lower(), cents(unit.group(2))
                o.crop = {"x0": e["x0"] - 10, "top": e["top"] - 10, "x1": min(right - 5, page.width),
                          "bottom": below - 5}  # the whole cell: price, bottle, name
                if not o.name:  # a decoration price (page 4 of Nr. 23 is a poster): not a product
                    continue
                if vol and vol not in o.name:
                    o.name = f"{o.name}, {vol}"
                out.append(finish(o))
    return out
