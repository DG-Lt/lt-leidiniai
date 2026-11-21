"""PDF leaflets with a text layer (IKI, Lidl, Norfa).

Per page: words with font size (pdfplumber) → price anchors (big "1,99" or euros + superscript cents),
discount badges ("-29%", "29"+"%", "1+1"), old prices (mid-size price tokens), unit prices
("1 kg = 5,98 €", "9,45 Eur/kg") and small text lines grouped into blocks. Each text block goes to the
anchor with the lowest direction-aware cost: in all three chains the product text sits to the LEFT of
or ABOVE its own price, so anchors that are wholly left of / above the block cost `left_penalty` /
`above_penalty` times more. Far vertical links (IKI: name above the photo, price below it) need the block and the
anchor to share a column.

Font sizes per chain were measured on the 2026-11 issues (docs/findings.md, Prototype 1).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

from . import Offer, cents, finish


@dataclass(frozen=True)
class ChainCfg:
    price_min: float               # anchor price font size ≥
    old_min: float                 # old price font size range
    old_max: float
    disc_min: float                # discount badge font size ≥
    text_max: float                # product text font size ≤
    maxd: float = 90               # max cost text block → anchor (points)
    near: float = 45               # beyond this vertical gap the block must share a column with the anchor
    left_penalty: float = 3.0      # cost factor for anchors wholly left of the block
    above_penalty: float = 3.0     # cost factor for anchors wholly above the block
    old_maxd: float = 70           # old price / discount badge → anchor
    badge_free: float = 70         # a badge with no price this close becomes its own anchor (category offer)
    card_words: tuple[str, ...] = ()
    code_rx: str | None = None     # product code line (ends a text block; stored as ext_id)
    noise: tuple[str, ...] = ()    # extra line patterns that are not part of a name
    pct_optional: bool = False     # discount badge printed as "-30" with the "%" drawn as a picture (Vynoteka)


CFG: dict[str, ChainCfg] = {
    "lidl": ChainCfg(price_min=40, old_min=9, old_max=11, disc_min=15, text_max=12.6, maxd=110,
                     card_words=("Lidl Plus",), code_rx=r"^\d{5,7}$",
                     noise=(r"^Antram su Lidl Plus$", r"^PERKANT", r"^Brandinta \d+h$", r"^Naujiena!?$",
                            r"su Lidl Plus", r"^Su Lidl Plus$")),
    "norfa": ChainCfg(price_min=20, old_min=8, old_max=12, disc_min=11, text_max=8.5, maxd=100, above_penalty=2.0,
                      card_words=("kortel",),
                      noise=(r"^Nuolaida$", r"^Kaina lentynoje", r"^nuolaida$", r"^Sveriamos produkcijos",
                             r"Nuolaida taikoma kasoje")),
    "iki": ChainCfg(price_min=25, old_min=9, old_max=16, disc_min=40, text_max=13.5, maxd=280, near=60, above_penalty=10.0,
                    card_words=("kortel",),
                    noise=(r"^Ir IKI EXPRESS$", r"^IKI EXPRESS$", r"^PIRKITE", r"^PIRKTI$", r"lastmile\.lt",
                           r"^Įprasta kaina$", r"^Supakuota$", r"^SUTAUPOTE$",
                           r"^Pasiūlymas galioja", r"^Nuolaida suteikiama tik", r"^pažymėtoms prekėms\.?$",
                           r"^prekėms\.?$", r"^SUPERKAINA$")),
    # Vynoteka food leaflet (Nr. 23, 2026-11): badge "-30" 32 pt (no "%" glyph), euros 43 + cents 26 pt,
    # old price 13–14 pt right under the cents, name 9 pt BELOW the price, "TIK" 30 pt, tags ("ITALIŠKAS") 14 pt
    "vynoteka": ChainCfg(price_min=36, old_min=11, old_max=16, disc_min=26, text_max=10.5, maxd=90, near=45,
                         above_penalty=1.0, left_penalty=3.0, pct_optional=True,
                         noise=(r"Kainos galioja", r"^Nr\.\s*\d+", r"^20\d\d \d\d \d\d", r"^NAUJIENA!?$")),
}

COMMON_NOISE = (
    r"^www\.", r"^\d{1,2}/20\d\d$", r"^\*", r"Prekių kiekis ribotas", r"^(TIK|Tik)$", r"^€$", r"^%$",
    r"^[-–]$", r"^\d{1,3}$", r"^iki\.lt$", r"^[=≤]\s*\d+,\d\d\s*€$",
)

BEHIND_OFFSET = 25.0
# leaflet-wide terms printed inside an offer box – never part of the product name
PROMO_RX = re.compile(
    r"Pasiūlymas\s+galioja(?:\s+(?:nuo|iki)\s+(?:20\d\d[\s.\-]+\d{1,2}[\s.\-]+\d{1,2}|\d{1,2}[\s.\-]+\d{1,2}))+\s*\.?"
    r"|Nuolaida\s+suteikiama\s+tik\s+pažymėtoms\s+prekėms\s*\.?"
    r"|\b(?:SUPERKAINA|ANIAKREPUS)\b", re.I)
# Lidl: promotion terms, shelf hints and product codes printed inside the name block
LIDL_RX = re.compile(
    r"Akcijos\s+limitas\s+vieno\s+pirkimo\s+metu(?:\s*[–:-]?\s*\d+\s*(?:vnt|pak|kg|l)?\.?)?"
    r"|Nuolaidos\s+nesumuojamos\.?"
    r"|Pasiūlymas\s+galioja\s+tik\s+nurodytos\s+akcijos\s+metu[^.]{0,120}\.?"
    r"|Pasiūlymas\s+galioja\s+tik\s+(?:su\s+)?Lidl\s+Plus[^.]{0,80}\.?"
    r"|Atsiprašome,?\s+šios\s+prekės\s+laikinai\s+neturime\.?"
    r"|Ieškoti\s+šaldytuve"
    r"|Nevartoti\s+su\s+alkoholiniais\s+gėrimais\.?"
    r"|(?<![\d,.])\b\d{6,7}(?:\s*[-,]\s*\d{5,7})*\b(?![,.]\d)", re.I)
# ≥4 single letters in a row: a vertical badge ('SUPERKAINA' stacked or rotated) read letter by letter
_UP = "A-ZĄČĘĖĮŠŲŪŽ"
LETTER_RUN = re.compile(rf"(?:(?<=\s)|^)(?:[{_UP}]\s+){{3,}}[{_UP}](?=\s|$)")
SPACED = re.compile(r"(?:(?<=\s)|^)(?:[^\W\d_]\s+){2,}[^\W\d_](?=\s|$)")
PRICE_TOKEN = re.compile(r"^\d{1,3}(,\d\d)?$")
UNIT_AFTER = re.compile(r"^(€|Eur)?\s*/\s*(kg|l|vnt|m|kompl|pak|rit)\.?\*?$|^(€|Eur)/(kg|l|vnt|m|pak|rit)\.?\*?$", re.I)
UNIT_RE = re.compile(
    r"(?:\b1\s*(kg|l|vnt|m)\.?\s*[=≤–-]\s*(\d+,\d\d)\s*€)"
    r"|(?:(\d+,\d\d)\s*(?:€|Eur)\s*/\s*(kg|l|vnt|m|pak|rit)\b)", re.I)
QTY_RE = re.compile(
    r"(?<![/\d,])(\d+(?:[,.]\d+)?(?:\s*[x×]\s*\d+(?:[,.]\d+)?)?\s*(?:kg|g|ml|l|vnt|cl|m|pak|rit)\.?)(?![\w=])(?!\s*=)",
    re.I)


# --------------------------------------------------------------------------- geometry

def box(items) -> dict:
    return {"x0": min(i["x0"] for i in items), "x1": max(i["x1"] for i in items),
            "top": min(i["top"] for i in items), "bottom": max(i["bottom"] for i in items)}


def gaps(a, b) -> tuple[float, float]:
    dx = max(0.0, max(a["x0"], b["x0"]) - min(a["x1"], b["x1"]))
    dy = max(0.0, max(a["top"], b["top"]) - min(a["bottom"], b["bottom"]))
    return dx, dy


def dist(a, b) -> float:
    dx, dy = gaps(a, b)
    return math.hypot(dx, dy * 1.3)


def x_overlap(a, b) -> float:
    """Overlap of the x ranges as a share of the narrower one."""
    ov = min(a["x1"], b["x1"]) - max(a["x0"], b["x0"])
    w = max(1.0, min(a["x1"] - a["x0"], b["x1"] - b["x0"]))
    return max(0.0, ov) / w


def block_cost(anchor, block, cfg: ChainCfg) -> float | None:
    dx, dy = gaps(anchor, block)
    d = math.hypot(dx, dy * 1.3)
    # "behind" links pay a fixed offset too, so a tiny gap to the wrong side still loses
    if anchor["bottom"] <= block["top"] + 2:
        d = (d + BEHIND_OFFSET) * cfg.above_penalty
    elif anchor["x1"] <= block["x0"] + 2:
        d = (d + BEHIND_OFFSET) * cfg.left_penalty
    if dy > cfg.near and x_overlap(anchor, block) < 0.3:
        return None
    return d if d <= cfg.maxd else None


# --------------------------------------------------------------------------- tokens

def page_words(page) -> list[dict]:
    # rotated text (side labels, vertical stamps) comes out letter by letter: drop non-upright characters
    page = page.filter(lambda o: o.get("object_type") != "char" or o.get("upright", True))
    ws = page.extract_words(extra_attrs=["size"], keep_blank_chars=False, use_text_flow=False)
    out: list[dict] = []
    for w in ws:
        w = {k: w[k] for k in ("text", "x0", "x1", "top", "bottom", "size")}
        w["size"] = round(w["size"], 1)
        # Lidl draws headlines 2–3× with tiny offsets (shadow): keep one
        if any(o["text"] == w["text"] and abs(o["x0"] - w["x0"]) < 3 and abs(o["top"] - w["top"]) < 3 for o in out[-40:]):
            continue
        # IKI sets badge numbers digit by digit ("4" "8" "%"): join touching digits of the same size
        if out and w["text"].isdigit() and out[-1]["text"].isdigit() and out[-1]["size"] == w["size"] \
                and abs(out[-1]["top"] - w["top"]) < 3 and -6 <= w["x0"] - out[-1]["x1"] <= 1.5:
            out[-1]["text"] += w["text"]
            out[-1]["x1"] = w["x1"]
            continue
        out.append(w)
    for i, w in enumerate(out):
        w["i"] = i
    return out


def same_line(a, b, tol=2.5) -> bool:
    return abs(a["top"] - b["top"]) < tol or abs(a["bottom"] - b["bottom"]) < tol


def unit_token_ids(ws) -> set[int]:
    """Price-looking words that are unit prices: '= 5,98 €' or '9,45 Eur/kg'."""
    out = set()
    for w in ws:
        if not re.fullmatch(r"\d+,\d\d", w["text"]):
            continue
        for o in ws:
            if o is w or not same_line(o, w):
                continue
            if 0 <= o["x0"] - w["x1"] < 8 and (UNIT_AFTER.match(o["text"]) or o["text"].lower().startswith(("eur/", "€/"))):
                out.add(w["i"])
            elif 0 <= w["x0"] - o["x1"] < 10 and o["text"] in ("=", "≤", "–"):
                out.add(w["i"])
    return out


def money_tokens(ws, smin, smax, skip: set[int]) -> tuple[list[dict], set[int]]:
    """Prices within a font-size range: 'x,yy' tokens or euros + smaller top-aligned cents token."""
    out, used = [], set()
    cand = [w for w in ws if w["i"] not in skip and smin <= w["size"] <= smax and PRICE_TOKEN.match(w["text"])]
    for w in cand:
        if w["i"] in used:
            continue
        if "," in w["text"]:
            used.add(w["i"])
            out.append({**box([w]), "value": cents(w["text"]), "size": w["size"], "words": [w["i"]]})
            continue
        cs = [c for c in ws if c["i"] not in skip and c is not w and c["i"] not in used and re.fullmatch(r"\d\d", c["text"])
              and w["size"] * 0.45 <= c["size"] < w["size"] * 0.95
              and w["x1"] - 15 <= c["x0"] <= w["x1"] + 20 and abs(c["top"] - w["top"]) < w["size"] * 0.5]
        if cs:
            c = min(cs, key=lambda c: abs(c["x0"] - w["x1"]))
            used |= {w["i"], c["i"]}
            out.append({**box([w, c]), "value": int(w["text"]) * 100 + int(c["text"]), "size": w["size"],
                        "words": [w["i"], c["i"]]})
    return out, used


def discount_tokens(ws, smin, pct_optional: bool = False) -> tuple[list[dict], set[int]]:
    out, used = [], set()
    for w in ws:
        if w["size"] < smin or w["i"] in used:
            continue
        t = w["text"]
        if pct_optional and re.fullmatch(r"[-–]\d{1,2}", t):
            used.add(w["i"])
            out.append({**box([w]), "text": t.replace("–", "-") + "%"})
            continue
        if re.fullmatch(r"[-–]\d{1,2}\s?%", t) or re.fullmatch(r"\d\+\d", t):
            used.add(w["i"])
            out.append({**box([w]), "text": t.replace("–", "-").replace(" ", "")})
            continue
        if re.fullmatch(r"\d{1,2}%", t):
            used.add(w["i"])
            out.append({**box([w]), "text": "-" + t})
    # IKI "1+1" / "2+1": two big single digits side by side, the "+" is a drawing
    for a in ws:
        if a["i"] in used or a["size"] < smin or not re.fullmatch(r"\d", a["text"]):
            continue
        for b in ws:
            if b is a or b["i"] in used or b["size"] != a["size"] or not re.fullmatch(r"\d", b["text"]):
                continue
            if abs(a["top"] - b["top"]) < 4 and 8 <= b["x0"] - a["x1"] <= 25:
                used |= {a["i"], b["i"]}
                out.append({**box([a, b]), "text": f"{a['text']}+{b['text']}"})
                break
    # separate "%": pair each with the nearest top-aligned number just left of it (one number per %)
    for p in ws:
        if p["text"] not in ("%", "%*") or p["i"] in used:
            continue
        cand = [w for w in ws if w["i"] not in used and w["size"] >= smin and re.fullmatch(r"\d{1,2}", w["text"])
                and -6 <= p["x0"] - w["x1"] <= 12 and p["size"] <= w["size"]
                and abs(p["top"] - w["top"]) < w["size"] * 0.35]
        if not cand:
            continue
        w = min(cand, key=lambda w: abs(p["x0"] - w["x1"]))
        parts = [w, p]
        mn = [m for m in ws if m["text"] in ("-", "–") and m["i"] not in used and m["x1"] <= w["x0"] + 3
              and w["x0"] - m["x1"] < 30 and abs((m["top"] + m["bottom"]) / 2 - (w["top"] + w["bottom"]) / 2) < w["size"] * 0.6]
        parts += mn[:1]
        used |= {q["i"] for q in parts}
        out.append({**box(parts), "text": "-" + w["text"] + "%"})
    return out, used


def lines_of(ws) -> list[dict]:
    ws = sorted(ws, key=lambda w: (round(w["top"]), w["x0"]))
    L: list[dict] = []
    for w in ws:
        for ln in L:
            if same_line(ln, w, 2) and 0 <= w["x0"] - ln["x1"] < max(8, w["size"]) and abs(ln["size"] - w["size"]) < 1.5:
                ln["text"] += " " + w["text"]
                ln["x1"] = w["x1"]
                ln["bottom"] = max(ln["bottom"], w["bottom"])
                break
        else:
            L.append({"text": w["text"], "x0": w["x0"], "x1": w["x1"], "top": w["top"], "bottom": w["bottom"], "size": w["size"]})
    return L


def blocks_of(lines, cfg: ChainCfg, gap=6.5, xtol=6) -> list[dict]:
    """Stack lines that are left-, right- or centre-aligned and close vertically. A product code line ends a block."""
    code = re.compile(cfg.code_rx) if cfg.code_rx else None
    B: list[dict] = []
    for ln in sorted(lines, key=lambda l: (l["top"], l["x0"])):
        for b in B:
            if b.get("closed"):
                continue
            last = b["lines"][-1]
            aligned = (abs(last["x0"] - ln["x0"]) < xtol or abs(last["x1"] - ln["x1"]) < xtol
                       or abs((last["x0"] + last["x1"]) / 2 - (ln["x0"] + ln["x1"]) / 2) < xtol)
            if aligned and -1 <= ln["top"] - last["bottom"] < gap:
                b["lines"].append(ln)
                b.update(box([b, ln]))
                break
        else:
            b = {"lines": [ln], **box([ln])}
            B.append(b)
        if code and code.match(ln["text"]):
            b["closed"] = True
    return B


def page_images(page) -> list[dict]:
    W, H = page.width, page.height
    out = []
    for im in page.images:
        x0, x1, top, bottom = max(0, im["x0"]), min(W, im["x1"]), max(0, im["top"]), min(H, im["bottom"])
        if x1 - x0 < 15 or bottom - top < 15 or (x1 - x0) * (bottom - top) > 0.35 * W * H:
            continue
        out.append({"x0": x0, "x1": x1, "top": top, "bottom": bottom})
    return out


# --------------------------------------------------------------------------- page → offers

def _noise(cfg: ChainCfg):
    return re.compile("|".join(f"(?:{p})" for p in COMMON_NOISE + cfg.noise))


def parse_page(page, pno: int, chain: str, cfg: ChainCfg) -> list[Offer]:
    return parse_words(page_words(page), page_images(page), pno, chain, cfg)


def parse_words(ws: list[dict], imgs: list[dict], pno: int, chain: str, cfg: ChainCfg) -> list[Offer]:
    """Words {text, x0, x1, top, bottom, size, i} (PDF text layer or OCR, in points) → offers."""
    unit_ids = unit_token_ids(ws)
    disc, du = discount_tokens(ws, cfg.disc_min, cfg.pct_optional)
    prices, pu = money_tokens(ws, cfg.price_min, 400, du | unit_ids)
    olds, ou = money_tokens(ws, cfg.old_min, cfg.old_max, du | pu | unit_ids)
    used = du | pu | ou
    rest = [w for w in ws if w["i"] not in used and w["size"] <= cfg.text_max]
    blocks = blocks_of(lines_of(rest), cfg)

    anchors = [{**p, "kind": "price"} for p in prices]
    free_badges = []
    for d in disc:
        if not any(dist(d, a) < cfg.badge_free for a in anchors):
            free_badges.append(d)
    anchors += [{**d, "kind": "badge", "value": None} for d in free_badges]
    if not anchors:
        return []

    # old prices and badges → nearest price anchor
    att = {i: {"old": [], "disc": []} for i in range(len(anchors))}
    for kind, things in (("old", olds), ("disc", [d for d in disc if d not in free_badges])):
        for t in things:
            best = min(((dist(a, t), i) for i, a in enumerate(anchors) if a["kind"] == "price"), default=None)
            if best and best[0] <= cfg.old_maxd:
                att[best[1]][kind].append(t)

    # text blocks → anchor with the lowest direction-aware cost
    texts = {i: [] for i in range(len(anchors))}
    for b in blocks:
        best = None
        for i, a in enumerate(anchors):
            c = block_cost(a, b, cfg)
            if c is not None and (best is None or c < best[0]):
                best = (c, i)
        if best:
            texts[best[1]].append(b)

    noise = _noise(cfg)
    code_rx = re.compile(cfg.code_rx) if cfg.code_rx else None
    centres = [((a["x0"] + a["x1"]) / 2, (a["top"] + a["bottom"]) / 2) for a in anchors]
    out = []
    for i, a in enumerate(anchors):
        bl = sorted(texts[i], key=lambda b: (b["top"], b["x0"]))
        all_lines = [ln["text"] for b in bl for ln in b["lines"]]
        joined = " ".join(all_lines)
        ext_id = None
        name_lines = []
        for t in all_lines:
            if code_rx and code_rx.match(t):
                ext_id = ext_id or t
                continue
            t2 = UNIT_RE.sub("", t).strip(" ,/")
            t2 = re.sub(r"\s*[=≤]\s*\d+,\d\d\s*€$", "", t2)
            t2 = re.sub(r"^Supakuota\s+", "", t2)
            if not t2 or noise.search(t2):
                continue
            t2 = SPACED.sub(" ", t2).strip()  # 'A K I E P R U S' (tracked/rotated lettering)
            if not t2:
                continue
            toks = t2.split()
            if len(toks) >= 4 and sum(len(x) == 1 for x in toks) >= 0.6 * len(toks):
                continue  # letters spread out (rotated or tracked text)
            if re.fullmatch(r"[^\W\d_]", t2):
                continue  # a lone letter: one line of vertical lettering
            name_lines.append(t2)
        name = clean_name(" ".join(name_lines), chain)
        o = Offer(chain=chain, name=name, kind=a["kind"], page=pno)
        if a["kind"] == "price":
            o.price = a["value"]
            if att[i]["old"]:
                o.old_price = min(att[i]["old"], key=lambda t: dist(a, t))["value"]
            if att[i]["disc"]:
                o.discount_text = att[i]["disc"][0]["text"]
        else:
            o.discount_text = a["text"]
        m = UNIT_RE.search(joined)
        if m:
            if m.group(1):
                o.unit, o.unit_price = m.group(1).lower(), cents(m.group(2))
            else:
                o.unit, o.unit_price = m.group(4).lower(), cents(m.group(3))
        q = QTY_RE.search(re.sub(r"^Supakuota\s+", "", joined))
        if q:
            o.quantity = q.group(1)
        hit = next((c for c in cfg.card_words if c.lower() in joined.lower()), None)
        if hit:
            o.card, o.card_text = True, next((t for t in all_lines if hit.lower() in t.lower()), hit)
        o.ext_id = ext_id
        parts = [a] + att[i]["old"] + att[i]["disc"] + bl
        bb = box(parts)
        o.bbox = {k: round(v, 1) for k, v in bb.items()}
        # crop: the offer box plus the nearest photo, unless that photo also covers another price
        crop = dict(bb)
        near = sorted(((dist(bb, im), im) for im in imgs), key=lambda t: t[0])
        for dd, im in near[:1]:
            if dd > 25:
                break
            cand = box([crop, im])
            others = [c for j, c in enumerate(centres) if j != i
                      and cand["x0"] < c[0] < cand["x1"] and cand["top"] < c[1] < cand["bottom"]]
            if not others:
                crop = cand
        o.crop = {k: round(v, 1) for k, v in crop.items()}
        if len(bl) > 2:
            o.flags.append("many_blocks")
        o.extra["lines"] = all_lines
        out.append(finish(o))
    return merge_single_prices(out)


def clean_name(name: str, chain: str = "") -> str:
    """Joined name lines → name: drop promo sentences and runs of single letters that come from several lines
    of vertical lettering ('… 500 ml A K I E P R U S'). Lidl: promotion terms and product codes too."""
    name = PROMO_RX.sub(" ", name)
    if chain == "lidl":
        name = LIDL_RX.sub(" ", name)
    name = LETTER_RUN.sub(" ", name)
    return re.sub(r"\s+", " ", name).strip(" ,;.")


def merge_single_prices(offers: list[Offer]) -> list[Offer]:
    """Lidl 'PERKANT 1 VNT. 1,39' + 'Antram su Lidl Plus -68% 0,45': the nameless single-unit price
    belongs to the deal next to it (kept as extra.single_price, not as an offer of its own)."""
    keep = []
    for o in offers:
        if o.name or not any(l.upper().startswith("PERKANT") for l in o.extra.get("lines", [])):
            keep.append(o)
            continue
        target = min((t for t in offers if t is not o and t.name and t.bbox),
                     key=lambda t: dist(t.bbox, o.bbox), default=None)
        if target is not None and dist(target.bbox, o.bbox) < 120:
            target.extra["single_price"] = o.price
            target.extra["single_text"] = next(l for l in o.extra["lines"] if l.upper().startswith("PERKANT"))
            if target.crop and o.crop:
                target.crop = box([target.crop, o.crop])
        else:
            keep.append(o)
    return keep


def skip_pages(chain: str, meta: dict) -> set[int]:
    """Lidl: pages typed PROMOTION in the leaflet API are comparison ads without products (1-based)."""
    if chain != "lidl":
        return set()
    out = set()
    for n, p in enumerate(meta.get("pages") or [], start=1):
        if (p.get("type") or "").upper() == "PROMOTION":
            out.add(int(p.get("number") or n))
    return out


def parse(path: str | Path, chain: str, skip_pages: set[int] | None = None, pages: set[int] | None = None,
          log=None) -> list[Offer]:
    import pdfplumber
    cfg = CFG[chain]
    out: list[Offer] = []
    with pdfplumber.open(str(path)) as pdf:
        for n, page in enumerate(pdf.pages, start=1):
            if (pages and n not in pages) or (skip_pages and n in skip_pages):
                continue
            try:
                offers = parse_page(page, n, chain, cfg)
            except Exception as e:  # one bad page must not lose the leaflet
                if log:
                    log.warning("%s %s p.%d: parse error %s", chain, Path(path).name, n, e)
                offers = []
            out += offers
            for o in offers:
                o.extra["file"] = Path(path).name
            try:
                page.close()
            except Exception:
                pass
    return out


def render_crops(path: str | Path, offers: list[Offer], out_dir: Path, scale: float = 2.0,
                 max_side: int = 640, pad: float = 4) -> dict[int, str]:
    """Render each page once and save the offers' crops as JPEG. Returns {index in offers: file name}."""
    import pypdfium2 as pdfium
    out_dir.mkdir(parents=True, exist_ok=True)
    by_page: dict[int, list[int]] = {}
    for i, o in enumerate(offers):
        if o.crop and o.page:
            by_page.setdefault(o.page, []).append(i)
    names: dict[int, str] = {}
    doc = pdfium.PdfDocument(str(path))
    try:
        for p, idx in sorted(by_page.items()):
            page = doc[p - 1]
            img = page.render(scale=scale).to_pil().convert("RGB")
            for i in idx:
                c = offers[i].crop
                bx = (max(0, int((c["x0"] - pad) * scale)), max(0, int((c["top"] - pad) * scale)),
                      min(img.width, int((c["x1"] + pad) * scale)), min(img.height, int((c["bottom"] + pad) * scale)))
                if bx[2] - bx[0] < 12 or bx[3] - bx[1] < 12:
                    continue
                im = img.crop(bx)
                im.thumbnail((max_side, max_side))
                fn = f"p{p:02d}_{i:04d}.jpg"
                im.save(out_dir / fn, quality=80, optimize=True)
                names[i] = fn
            del img
            page.close()
    finally:
        doc.close()
    return names
