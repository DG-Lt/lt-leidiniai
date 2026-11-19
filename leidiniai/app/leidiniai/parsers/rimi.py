"""Rimi: iPaper hotspots (enrichments.json) looked up in the e-shop search (eshop.json), both saved by the fetcher.

A hotspot URL carries one or more product codes (`?query=101029 101030`); the e-shop answer lists
products with a GTM JSON (id, name, category 'SH-11-…', regular price) and the card text. Card text forms:

  '3 49 € 23,27 €/kg Saldainiai … 4.49 € už vnt. …'      leading price = Mano Rimi card price, 4.49 = shelf
  'Lietiniai … 2.87 € už vnt. … Įprasta kaina: 3,59 €'   general discount: 2.87 now, 3.59 regular
  'Ledjūrio menkės … Šiuo metu prekės nėra'              not available in the e-shop

The e-shop price may differ from the paper leaflet (docs/findings.md). Products are kept when their id
is one of the hotspot's codes; when none match, the first result is kept and flagged 'fuzzy'.
"""
from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urlparse

from . import Offer, cents, finish

LEAD = re.compile(r"^(\d{1,4}) (\d\d) €\s+(\d+,\d\d) €/(\w+)")
SHELF = re.compile(r"(\d{1,4}\.\d\d) € už (\w+)")
REGULAR = re.compile(r"Įprasta kaina:\s*(\d+,\d\d)\s*€")
UNIT = re.compile(r"Kaina už vienetą:\s*(\d+,\d\d)\s*€/(\w+)")


def offer_from(p: dict, page: int | None, group: int) -> Offer:
    g = p.get("gtm") or {}
    text = p.get("text") or ""
    o = Offer(chain="rimi", name=g.get("name") or "", kind="hotspot", page=page,
              ext_id=str(g.get("id")) if g.get("id") else None, ext_category=g.get("category"),
              image_url=p.get("img"))
    shelf = SHELF.search(text)
    shelf_c = cents(shelf.group(1)) if shelf else (round(g["price"] * 100) if g.get("price") else None)
    lead = LEAD.match(text)
    reg = REGULAR.search(text)
    unit = UNIT.search(text)
    if lead:
        o.price = int(lead.group(1)) * 100 + int(lead.group(2))
        o.old_price = cents(reg.group(1)) if reg else shelf_c
        o.unit, o.unit_price = lead.group(4).lower(), cents(lead.group(3))
        o.card, o.card_text = True, "Mano Rimi kaina"
    else:
        o.price = shelf_c
        o.old_price = cents(reg.group(1)) if reg else None
        if unit:
            o.unit, o.unit_price = unit.group(2).lower(), cents(unit.group(1))
        if not reg:
            o.flags.append("no_discount_in_eshop")
    if "Šiuo metu prekės nėra" in text:
        o.flags.append("unavailable")
    if group > 1:
        o.extra["group"] = group
    return finish(o)


def parse(enrichments_path, eshop_path) -> list[Offer]:
    enr = json.load(open(enrichments_path, encoding="utf-8"))
    shop = json.load(open(eshop_path, encoding="utf-8"))
    out: list[Offer] = []
    seen: set[str] = set()
    for e in enr.get("enrichments", []):
        q = parse_qs(urlparse(e.get("url") or "").query).get("query", [None])[0]
        prods = shop.get(q) if q else None
        if not isinstance(prods, list) or not prods:
            continue
        codes = set(q.split())
        mine = [p for p in prods if str((p.get("gtm") or {}).get("id")) in codes]
        fuzzy = not mine
        if fuzzy:
            mine = prods[:1]
        page = (e["p"] + 1) if isinstance(e.get("p"), int) else None
        for p in mine:
            pid = str((p.get("gtm") or {}).get("id"))
            if pid in seen:
                continue
            seen.add(pid)
            o = offer_from(p, page, len(mine))
            o.bbox = {k: e.get(k) for k in ("x", "y", "w", "h")}  # page fractions
            if fuzzy:
                o.flags.append("fuzzy")
            out.append(o)
    return out
