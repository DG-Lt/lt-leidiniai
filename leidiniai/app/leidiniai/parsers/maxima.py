"""Maxima: offer cards on https://www.maxima.lt/pasiulymai (saved HTML snapshot).

Card: h4 name, image, price-integer/fraction, old-price, bottom-discount ('-40%') or discount-value
(category offers, no price), benefit ('2 vnt. už', '1+1'), meta-comparison ('1 kg – 2,36 €',
'1 kg ≤ 9,92 €'), meta-date ('Iki 11.16'), meta-label ('nuo', 'Perkant 2 ar daugiau'),
icon alt ('Tik su AČIŪ kortele'). The section h2 before a card is Maxima's category.
"""
from __future__ import annotations

import json
import re
from datetime import date

from bs4 import BeautifulSoup

from ..textutil import parse_range
from . import Offer, cents, finish

# h2 headings on the page that are categories (the rest are menus/footers)
NOT_CATEGORIES = {"Kas esame", "Karjera", "Mums rūpi", "Kitos akcijos", "Parduotuvės", "Verslui", "Pasirinkite kategorijas"}
UNIT_RE = re.compile(r"1\s*([^\s–≤-]+?)\.?\s*[–≤-]\s*(\d+,\d\d)\s*€")


def _t(el, cls):
    x = el.select_one("." + cls)
    return x.get_text(" ", strip=True) if x else None


def parse(html: str, ref: date) -> list[Offer]:
    s = BeautifulSoup(html, "lxml")
    out: list[Offer] = []
    seen: set[str] = set()
    cat = None
    for el in s.select('h2, [data-controller="offerCard"]'):
        if el.name == "h2":
            t = el.get_text(" ", strip=True)
            if t and t not in NOT_CATEGORIES:
                cat = t
            continue
        oid = el.get("data-offercard-offer-id")
        if not oid or oid in seen:
            continue
        seen.add(oid)
        h4 = el.select_one("h4")
        o = Offer(chain="maxima", name=h4.get_text(" ", strip=True) if h4 else "", kind="offer",
                  ext_id=oid, ext_category=cat)
        i, f = _t(el, "offer-price-tag__price-integer"), _t(el, "offer-price-tag__price-fraction")
        if i and f and i.isdigit() and f.isdigit():
            o.price = int(i) * 100 + int(f)
        o.old_price = cents(_t(el, "offer-price-tag__old-price"))
        bd = _t(el, "offer-price-tag__bottom-discount")
        dv = _t(el, "offer-price-tag__discount-value")
        ben = _t(el, "offer-price-tag__benefit")
        o.discount_text = bd or (dv.replace(" ", "") + "%" if dv else None) or ben
        if o.price is None and dv:
            o.kind = "badge"
        if ben and bd:
            o.extra["benefit"] = ben
        cmp_ = _t(el, "offer-price-tag__meta-comparison")
        if cmp_:
            m = UNIT_RE.search(cmp_)
            if m:
                o.unit, o.unit_price = m.group(1).rstrip(".").lower(), cents(m.group(2))
            o.extra["unit_text"] = cmp_
        d = _t(el, "offer-price-tag__meta-date")
        if d:
            vf, vt = parse_range(d, ref)
            o.valid_from, o.valid_to = vf, vt
        label = _t(el, "offer-price-tag__meta-label")
        if label:
            o.extra["label"] = label
        icon = el.select_one(".offer-price-tag__icon img")
        if icon and icon.get("alt"):
            o.card_text = icon["alt"]
            o.card = "kortel" in icon["alt"].lower()
        img = el.select_one(".offer-image img") or el.select_one("img")
        if img:
            o.image_url = img.get("src") or img.get("data-src")
        try:
            o.extra["sg"] = json.loads(el.get("data-categories-multiple") or "[]")
        except ValueError:
            pass
        out.append(finish(o))
    return out
