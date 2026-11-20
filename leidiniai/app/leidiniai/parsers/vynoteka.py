"""Vynoteka PDFs (checked 2026-11-20).

- Food leaflet ("Maisto leidinys", Adobe Illustrator, text layer): the generic price/name grouping
  (`pdf_text`, ChainCfg "vynoteka").
- Gift set catalogue ("Kalėdinių rinkinių katalogas", Canva): one set per page – title in 52 pt capitals
  ("ALUS IR" / "UŽKANDŽIAI"), "RINKINYS NR. 2" (often letter-spaced), the price "13,99 €" 48 pt, and the
  contents as numbered 13 pt items ("01" … 23 pt). The next page repeats number and price (back side) – skipped.
  Regular prices: kind "catalogue".
"""
from __future__ import annotations

import re
from pathlib import Path

from . import Offer, cents, finish

SET_RX = re.compile(r"RINKINYS\s*NR\.?\s*(\d+)", re.I)
PRICE_RX = re.compile(r"^(\d{1,4},\d\d)\s*€?$")
TITLE_MIN = 36
PRICE_MIN = 30
ITEM_SIZE = (10, 16)


def is_set_catalogue(path) -> bool:
    import pdfplumber
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages[:6]:
            if any(SET_RX.search(line.replace(" ", "")) for line in (page.extract_text() or "").splitlines()):
                return True
    return False


def parse(path, chain: str = "vynoteka", log=None) -> list[Offer]:
    if is_set_catalogue(path):
        return parse_sets(path, chain)
    from . import pdf_text
    return pdf_text.parse(path, chain, log=log)


def _lines(words):
    from .pdf_text import lines_of
    return lines_of([{**w, "size": round(w["size"], 1)} for w in words])


def parse_sets(path, chain: str = "vynoteka") -> list[Offer]:
    import pdfplumber
    out: list[Offer] = []
    seen: set[str] = set()
    with pdfplumber.open(str(path)) as pdf:
        for pno, page in enumerate(pdf.pages, 1):
            words = page.extract_words(extra_attrs=["size"], keep_blank_chars=False)
            lines = _lines(words)
            m = next((SET_RX.search(ln["text"].replace(" ", "")) for ln in lines
                      if SET_RX.search(ln["text"].replace(" ", ""))), None)  # often letter-spaced
            prices = []
            for ln in lines:
                pm = PRICE_RX.match(ln["text"].strip())
                if pm and ln["size"] >= PRICE_MIN:
                    prices.append((ln, cents(pm.group(1))))
            titles = [ln for ln in lines if ln["size"] >= TITLE_MIN and not PRICE_RX.match(ln["text"].strip())
                      and not SET_RX.search(ln["text"].replace(" ", ""))]
            if not prices or not titles:
                continue  # cover, back side of a set, contact page
            number = m.group(1) if m else None
            if number and number in seen:
                continue
            seen.add(number or f"p{pno}")
            title = " ".join(ln["text"] for ln in sorted(titles, key=lambda l: (l["top"], l["x0"])))
            items = [ln for ln in lines if ITEM_SIZE[0] <= ln["size"] <= ITEM_SIZE[1]
                     and not SET_RX.search(ln["text"].replace(" ", ""))]
            contents = _contents(items)
            name = title.capitalize() if title.isupper() else title
            name = f"Rinkinys Nr. {number}: {name}" if number else name
            o = Offer(chain=chain, name=name, kind="catalogue", page=pno, price=prices[0][1],
                      ext_category="Kalėdiniai rinkiniai", ext_id=f"rinkinys-{number}" if number else None)
            o.extra["contents"] = contents
            o.crop = {"x0": 0, "top": 0, "x1": float(page.width), "bottom": float(page.height)}
            o.extra["file"] = Path(path).name
            out.append(finish(o))
    return out


def _contents(items) -> list[str]:
    """Item text lines → one string per item: lines in the same column that follow each other closely."""
    cols: list[list[dict]] = []
    for ln in sorted(items, key=lambda l: (round(l["x0"] / 40), l["top"])):
        for c in cols:
            last = c[-1]
            if abs(last["x0"] - ln["x0"]) < 8 and 0 <= ln["top"] - last["bottom"] < 9:
                c.append(ln)
                break
        else:
            cols.append([ln])
    cols.sort(key=lambda c: (round(c[0]["top"] / 20), c[0]["x0"]))
    return [re.sub(r"\s+", " ", " ".join(l["text"] for l in c)).strip() for c in cols]
