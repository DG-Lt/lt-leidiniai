"""Leaflet parsers: turn a downloaded issue (PDF, offers page, Rimi hotspots) into a list of Offer.

Every parser is pure: files in, offers out. Storage (products, offers, categories) is in `store.py`;
crop rendering for PDFs is in `pdf_text.render_crops`. Prices are integer cents everywhere.

`python -m leidiniai.parsers <chain> <file> [file2]` prints the offers as JSON (for tuning).
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date


@dataclass
class Offer:
    chain: str
    name: str                          # as printed (may be empty when the parser found none)
    kind: str = "price"                # price | badge (discount without price) | offer (Maxima) | hotspot (Rimi)
    page: int | None = None            # 1-based leaflet page
    price: int | None = None           # cents
    old_price: int | None = None       # cents
    discount_pct: int | None = None
    discount_text: str | None = None   # as printed: '-29%', '1+1', '3 vnt. už', '-40 %'
    unit_price: int | None = None      # cents per unit
    unit: str | None = None            # kg | l | vnt | …
    quantity: str | None = None        # '500 g', '1 vnt.'
    card: bool = False                 # loyalty card / app price
    card_text: str | None = None
    valid_from: date | None = None     # per offer, when the shop prints it (Maxima 'Iki 11.16')
    valid_to: date | None = None
    ext_id: str | None = None          # shop product/offer id (Lidl 7-digit code, Rimi product id, Maxima offer id)
    ext_category: str | None = None    # shop category (Maxima section, Rimi SH code)
    image_url: str | None = None       # remote image (Maxima, Rimi)
    bbox: dict | None = None           # PDF points {x0, top, x1, bottom}
    crop: dict | None = None           # PDF points, region rendered as the offer image
    flags: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        d = asdict(self)
        for k in ("valid_from", "valid_to"):
            if d[k]:
                d[k] = d[k].isoformat()
        return d


_MONEY = re.compile(r"(\d{1,4})\s*[,.]\s*(\d{2})")


def cents(text: str | None) -> int | None:
    """'1,99' / '1.99' / '2,49 €' → 199 … ; None when there is no price in the text."""
    if not text:
        return None
    m = _MONEY.search(text)
    if not m:
        m2 = re.fullmatch(r"\s*(\d{1,4})\s*€?\s*", text)
        return int(m2.group(1)) * 100 if m2 else None
    return int(m.group(1)) * 100 + int(m.group(2))


def pct_from(price: int | None, old: int | None) -> int | None:
    if price and old and old > price:
        return round((1 - price / old) * 100)
    return None


NAME_QTY = re.compile(r"(?:,|\s)\s*((?:\d+\s*[x×]\s*)?\d+(?:[,.]\d+)?\s*(?:kg|g|ml|l|vnt|rit|lap|pak)\.?)\s*[*,.]*\s*$", re.I)


# words that only say how much / how many: a "name" made of these and numbers is no name ('cm', '2 vnt./rink. ml')
SIZE_WORDS = r"rūšių|rūšys|įvairių|spalvų|spalvos|dydžių|vnt|rink|kompl|kg|g|mg|ml|cl|l|cm|mm|m|pak|rit|lap|sl|x"
_SIZE_ONLY = re.compile(rf"(?i)\b(?:{SIZE_WORDS})\b")
# a unit left alone at the end after a word (a size circle next to the name): 'Puodelių rinkinys ml'
_STRAY_UNIT = re.compile(r"(?<=[^\W\d_])\s+(?:ml|cl|l|cm|mm|g|kg)\.?$", re.I)
# abbreviations whose full stop does not end the name ('rieb.', 'vnt.', 'a.r.', 'pr.')
_ABBR = {"vnt", "rieb", "sl", "pak", "g", "kg", "ml", "l", "cl", "cm", "mm", "m", "a", "r", "pr", "d", "kt", "nr",
         "rūš", "įv", "gab", "rit", "lap", "šald", "gryn", "sk", "maž", "did", "pvz", "t", "y", "tūkst", "proc",
         "st", "ž", "ats", "kiek", "mėn", "val", "min", "sav", "max", "apie", "kompl", "pc", "vol"}
SHORT_MIN_REST = 15  # a description shorter than this stays in the name


def short_name(name: str) -> tuple[str, str]:
    """Name up to the first full stop that ends a sentence (next word starts with a capital letter) → (short, rest).
    'Plaukų … peiliukai. Nerūdijančio plieno ašmenys. …' → ('Plaukų … peiliukai', 'Nerūdijančio plieno ašmenys. …')."""
    for m in re.finditer(r"([^\W\d_]+|\d)\.\s+(?=[A-ZĄČĘĖĮŠŲŪŽ0-9])", name):
        w = m.group(1)
        if w.lower() in _ABBR or w.isdigit() or (w.isupper() and len(w) <= 3):  # 'DR. OETKER', 'ST. NICOLAS'
            continue
        short, rest = name[:m.start(1) + len(m.group(1))].strip(), name[m.end():].strip()
        if len(short) >= 3 and len(rest) >= SHORT_MIN_REST:
            return short, rest
        break
    return name, ""


def finish(o: Offer) -> Offer:
    """Common clean-up and derived fields."""
    o.name = re.sub(r"\s+", " ", o.name or "")
    o.name = re.sub(r"[\s,;.*]+$", "", o.name).strip(" ,;")
    o.name = _STRAY_UNIT.sub("", o.name).strip(" ,;")
    if o.quantity is None:
        q = NAME_QTY.search(o.name.replace("*", ""))
        if q:
            o.quantity = q.group(1)
    if not o.extra.get("desc"):
        o.name, desc = short_name(o.name)
        if desc:
            o.extra["desc"] = desc
    if o.discount_pct is None and o.discount_text:
        m = re.search(r"(\d{1,2})\s*%", o.discount_text)
        if m:
            o.discount_pct = int(m.group(1))
    if o.discount_pct is None:
        o.discount_pct = pct_from(o.price, o.old_price)
    if o.old_price is not None and o.price is not None and o.old_price <= o.price:
        o.flags.append("old_not_higher")
        o.old_price = None
    if not o.name:
        o.flags.append("no_name")
    elif not re.search(r"[^\W\d_]{3,}", _SIZE_ONLY.sub("", o.name)):
        o.flags.append("weak_name")  # only a size / quantity ('cm', '2 vnt./rink. ml', '3 rūšių'): no real name
    if o.price is None and o.kind != "badge":
        o.flags.append("no_price")
    return o


def parse_issue(chain: str, parser: str, files: list[dict], meta: dict, ref: date, log) -> list[Offer]:
    """Dispatch on the fetcher's parser name. `files` are the stored file dicts (path, name …)."""
    if parser == "maxima":
        from . import maxima
        f = next(f for f in files if f["name"].endswith(".html"))
        return maxima.parse(open(f["path"], encoding="utf-8").read(), ref)
    if parser == "rimi":
        from . import rimi
        by = {f["name"]: f["path"] for f in files}
        return rimi.parse(by["enrichments.json"], by["eshop.json"])
    if parser == "norfa_promos":
        from . import norfa_promos
        htmls = [open(f["path"], encoding="utf-8").read() for f in sorted(files, key=lambda f: f["name"])
                 if f["name"].endswith(".html")]
        return norfa_promos.parse_pages(htmls, ref)
    if parser == "catalogue_pdf":
        from . import catalogue_pdf
        out = []
        for f in files:
            if f["name"].lower().endswith(".pdf"):
                for o in catalogue_pdf.parse(f["path"], log=log):
                    o.extra["file"] = f["name"]
                    out.append(o)
        return out
    if parser == "vynoteka":
        from . import vynoteka
        out = []
        for f in files:
            if f["name"].lower().endswith(".pdf"):
                for o in vynoteka.parse(f["path"], chain, log=log):
                    o.extra["file"] = f["name"]
                    out.append(o)
        return out
    if parser == "pdf":
        from . import pdf_text
        out: list[Offer] = []
        skip = pdf_text.skip_pages(chain, meta)
        for f in files:
            if f["name"].lower().endswith(".pdf"):
                out += pdf_text.parse(f["path"], chain, skip_pages=skip, log=log)
        return out
    raise ValueError(f"no parser '{parser}'")
