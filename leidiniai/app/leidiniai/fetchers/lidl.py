"""Lidl: listing page links /l/lt/leidinys/<slug>/ar/0; the Schwarz leaflet API gives dates, pages and the PDF.

API: https://endpoints.leaflets.schwarz/v4/flyer?flyer_identifier=<slug>&region_id=0
Only new slugs are looked up (one request each).
"""
from __future__ import annotations

import re

from ..textutil import parse_range
from .base import Fetcher, FileRef, IssueInfo
from datetime import date

API = "https://endpoints.leaflets.schwarz/v4/flyer?flyer_identifier={slug}&region_id=0"
SLUG_RX = r"https?://www\.lidl\.lt/l/lt/leidinys/([a-z0-9-]+)/ar/\d+"


def series_of(slug: str) -> str:
    s = re.sub(r"-(20\d{6})", "", slug)          # date 20261116
    s = re.sub(r"-kw\d{1,2}", "", s)              # kw47
    s = re.sub(r"-20\d\d(kw\d+)?", "", s)         # 2026, 2025kw18
    s = re.sub(r"-(pr|lapkritis|spalis|gruodis|sausis|vasaris|kovas|balandis|geguze|birzelis|liepa|rugpjutis|rugsejis)$", "", s)
    return s.strip("-") or slug


class Lidl(Fetcher):
    chain = "lidl"
    listing_url = "https://www.lidl.lt/c/kainu-leidiniai/s10020254"

    def __init__(self, *a, known_keys: set[str] | None = None, **kw):
        super().__init__(*a, **kw)
        self.known = known_keys or set()

    def discover(self):
        html = self.http.text(self.listing_url, need=r"/l/lt/leidinys/")
        out = []
        for url, text in self.links(html, SLUG_RX):
            slug = re.search(SLUG_RX, url).group(1)
            if slug in self.known:
                # already looked up: report it as still listed without another API request
                out.append(IssueInfo(chain=self.chain, key=slug, series=series_of(slug), title=text or slug,
                                     source_url=url, meta={"listed_only": True}))
                continue
            j = self.http.json(API.format(slug=slug))
            fl = (j or {}).get("flyer") or {}
            if not fl.get("pdfUrl"):
                self.log.warning("Lidl %s: no PDF in the leaflet API answer", slug)
                continue
            def d(k):
                v = fl.get(k)
                return date.fromisoformat(v[:10]) if v else None
            vf, vt = d("offerStartDate") or d("startDate"), d("offerEndDate") or d("endDate")
            if not vf and text:
                vf, vt = parse_range(text, self.today)
            pages = [{"number": p.get("number"), "type": p.get("type"), "keyWords": p.get("keyWords"),
                      "width": p.get("width"), "height": p.get("height")} for p in fl.get("pages") or []]
            title = " – ".join(x for x in (fl.get("name"), fl.get("title")) if x) or text or slug
            out.append(IssueInfo(
                chain=self.chain, key=slug, series=series_of(slug), title=title,
                number=(re.search(r"kw(\d+)", slug) or [None, None])[1],
                valid_from=vf, valid_to=vt, source_url=url,
                files=[FileRef(fl.get("hiResPdfUrl") or fl["pdfUrl"], f"{slug}.pdf", referer=url)],
                meta={"flyer_id": fl.get("id"), "category": fl.get("subcategory") or fl.get("category"),
                      "pages": pages, "publish_start": fl.get("startDate")},
                parser="pdf",
            ))
        return out
