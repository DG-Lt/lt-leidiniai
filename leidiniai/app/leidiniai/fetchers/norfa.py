"""Norfa: https://www.norfa.lt/leidiniai/ shows "NORFA Nr. 23 (523)" + "2026.11.12 - 2026.11.25";
the PDF comes from /leidiniai/download/<n> (button "Atsisiųsti leidinį").

Also the short promotions on https://www.norfa.lt/akciju-puslapiai/akcijos/ (4 per page, ?start=0,4,8 …),
kept like Maxima's offers page: a snapshot "issue" keyed by the set of priced promotions."""
from __future__ import annotations

import hashlib
import re
from datetime import date

from ..textutil import parse_range
from .base import Fetcher, FileRef, IssueInfo


class Norfa(Fetcher):
    chain = "norfa"
    listing_url = "https://www.norfa.lt/leidiniai/"

    def discover(self):
        html = self.http.text(self.listing_url, need=r"Nr\.\s*\d+")
        text = self.soup(html).get_text("\n", strip=True)
        downloads = [u for u, _ in self.links(html, r"https?://www\.norfa\.lt/leidiniai/download/\d+")]
        downloads += [f"https://www.norfa.lt/leidiniai/download/{n}"
                      for n in re.findall(r"leidiniai/download/(\d+)", html)]
        downloads = list(dict.fromkeys(downloads)) or ["https://www.norfa.lt/leidiniai/download/1"]
        out = []
        for i, m in enumerate(re.finditer(r"NORFA\s+Nr\.\s*(\d+)\s*(?:\((\d+)\))?", text)):
            short, total = m.group(1), m.group(2)
            vf, vt = parse_range(text[m.end():m.end() + 80], self.today)
            key = total or f"{self.today.year}-{short}"
            url = downloads[min(i, len(downloads) - 1)]
            out.append(IssueInfo(
                chain=self.chain, key=key, series="leidinys", title=m.group(0).strip(),
                number=f"{short} ({total})" if total else short, valid_from=vf, valid_to=vt,
                source_url=self.listing_url, files=[FileRef(url, f"Norfa{key}.pdf")], parser="pdf",
            ))
        try:
            promos = self.promotions()
        except Exception as e:  # the leaflet must not be lost because of the extra page
            self.log.warning("norfa: promotions page not read: %s", e)
            promos = None
        if promos:
            out.append(promos)
        return out

    PROMOS_URL = "https://www.norfa.lt/akciju-puslapiai/akcijos?start={n}"
    MAX_PROMO_PAGES = 10

    def promotions(self) -> IssueInfo | None:
        from ..parsers import norfa_promos
        pages = []
        for p in range(self.MAX_PROMO_PAGES):
            html = self.http.text(self.PROMOS_URL.format(n=p * 4), browser_ok=False)
            if "c-discount-item" not in html:
                break
            pages.append(html)
        offers = norfa_promos.parse_pages(pages, self.today)
        if not offers:
            self.log.info("norfa: promotions page – %d page(s), no priced promotion", len(pages))
            return None
        ids = sorted(o.ext_id or o.name for o in offers)
        ends = [o.valid_to for o in offers if o.valid_to]
        starts = [o.valid_from for o in offers if o.valid_from]
        self.log.info("norfa: promotions page – %d page(s), %d priced promotion(s)", len(pages), len(offers))
        return IssueInfo(
            chain=self.chain, key="akcijos-" + hashlib.sha1("|".join(ids).encode()).hexdigest()[:10],
            series="akcijos", title=f"Akcijos svetainėje ({len(offers)})",
            valid_from=min(starts) if starts else self.today, valid_to=max(ends) if ends else None,
            source_url="https://www.norfa.lt/akciju-puslapiai/akcijos/",
            meta={"offers": len(offers), "min_to": min(ends).isoformat() if ends else None, "snapshot": True,
                  "parser": "norfa_promos"},
            prefetched={f"akcijos-{i}.html": h.encode("utf-8") for i, h in enumerate(pages)},
            parser="norfa_promos",
        )
