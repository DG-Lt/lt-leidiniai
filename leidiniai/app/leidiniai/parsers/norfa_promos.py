"""Norfa: short promotions on https://www.norfa.lt/akciju-puslapiai/akcijos/ (not in the leaflet).

Each `.c-discount-item` has a title, a description and a picture. Only items with a date range and a price
("1 kg - tik 6,49 Eur") or a percentage ("- 30% RIVONA …") are offers; the rest of the page is news, games and
sponsorship, which is skipped. Checked 2026-11-20: e.g. "Didžiausiose parduotuvėse NORFA H, XXL, XL 2026 m.
11 18-11 22 d. žuvies ant ledo skyriuose Atšildytas didysis jūrinis ešerys (skrostas), 1 kg - tik 6,49 Eur."
"""
from __future__ import annotations

import re
from datetime import date
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..textutil import fold, month_number
from . import Offer, cents, finish

BASE = "https://www.norfa.lt/"
PRICE = re.compile(r"[-–]\s*tik\s+(\d+[,.]\d\d)\s*(?:Eur|€)", re.I)
PCT = re.compile(r"(?:^|[\s:(])[-–]\s?(\d{1,2})\s?%")
NUM_RANGE = re.compile(r"\b(\d{1,2})[ ,.](\d{1,2})\s*[-–]\s*(\d{1,2})[ ,.](\d{1,2})\b")        # 11 18-11 22
WORD_RANGE = re.compile(r"\b([A-Za-zĄČĘĖĮŠŲŪŽąčęėįšųūž]{4,})\s+(\d{1,2})\s*[-–]\s*(\d{1,2})\s*d\b")  # lapkričio 17-22 d
YEAR = re.compile(r"\b(20\d\d)\s*m\b")
CUT_BEFORE = re.compile(r".*(?:skyriuose|\bd\.|:)\s+", re.S)  # where the shop/date preamble ends


def _year(text: str, ref: date, month: int) -> int:
    m = YEAR.search(text)
    if m:
        return int(m.group(1))
    if ref.month == 12 and month <= 2:
        return ref.year + 1
    if ref.month <= 2 and month >= 11:
        return ref.year - 1
    return ref.year


def dates(text: str, ref: date) -> tuple[date | None, date | None]:
    m = NUM_RANGE.search(text)
    try:
        if m:
            m1, d1, m2, d2 = map(int, m.groups())
            if 1 <= m1 <= 12 and 1 <= m2 <= 12:
                y = _year(text, ref, m1)
                return date(y, m1, d1), date(y + (1 if m2 < m1 else 0), m2, d2)
        m = WORD_RANGE.search(text)
        if m:
            mon = month_number(m.group(1))
            if mon:
                y = _year(text, ref, mon)
                return date(y, mon, int(m.group(2))), date(y, mon, int(m.group(3)))
    except ValueError:
        pass
    return None, None


def _name_before_price(desc: str, end: int) -> str:
    part = desc[:end]
    part = CUT_BEFORE.sub("", part)
    return part.strip(" ,.;-–")


def parse_item(title: str, desc: str, img: str | None, href: str | None, ref: date) -> Offer | None:
    text = f"{title}. {desc}"
    vf, vt = dates(desc, ref)
    if vf is None:
        vf, vt = dates(title, ref)
    if vf is None:
        return None
    o = Offer(chain="norfa", name="", kind="price", valid_from=vf, valid_to=vt, ext_id=href,
              image_url=urljoin(BASE, img) if img else None)
    p = PRICE.search(desc)
    pd = PCT.search(desc)
    pct = pd or PCT.search(title)
    if p:
        o.price = cents(p.group(1))
        o.name = _name_before_price(desc, p.start())
    elif pct:
        o.kind = "badge"
        o.discount_pct = int(pct.group(1))
        o.discount_text = f"-{pct.group(1)}%"
        rest = desc[pd.end():] if pd else ""
        o.name = re.split(r"[*.]", rest, maxsplit=1)[0].strip(" ,:;-–") or re.sub(r"\d.*$", "", title).strip()
    else:
        return None
    if not o.name or len(o.name) > 160:  # the description didn't follow the usual pattern: the title tells it
        o.name = re.sub(r"\s*\d{1,2}[ ,.]\d{1,2}\s*[-–].*$|\s*(?:lapkri|gruod|saus|vasar|kov|bal|geg|birž|liep|rugp|rugs|spal)\w*\s+\d.*$",
                        "", title).strip()
    if "kortel" in fold(text):
        o.card = True
        o.card_text = "su NORFA nuolaidų kortele"
    shops = re.search(r"(Tik\s+)?(didžiausiose parduotuvėse[^0-9]*?)(?=\s20\d\d|\s\d|$)", desc, re.I)
    if shops:
        o.extra["shops"] = shops.group(2).strip(" ,.")
    o.extra["promo_title"] = title
    return finish(o)


def parse_pages(htmls: list[str], ref: date) -> list[Offer]:
    out, seen = [], set()
    for html in htmls:
        s = BeautifulSoup(html, "lxml")
        for it in s.select(".c-discount-item"):
            t = it.select_one(".c-discount-item__title")
            d = it.select_one(".c-discount-item__description")
            if not t or not d:
                continue
            href = t.get("href")
            if href in seen:
                continue
            seen.add(href)
            img = it.select_one("img")
            o = parse_item(t.get_text(" ", strip=True), re.sub(r"\s+", " ", d.get_text(" ", strip=True)),
                           img.get("src") if img else None, href, ref)
            if o:
                out.append(o)
    return out
