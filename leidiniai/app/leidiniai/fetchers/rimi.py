"""Rimi: https://www.rimi.lt/asortimentas/rimi-savaitinis-leidinys lists the iPaper leaflets
(https://leidiniai.rimi.lt/<year>/<type>/<slug>/). Products come from the iPaper hotspots
(Enrichments JSON, loaded with a token → headless browser) looked up in the e-shop search.
Weekly 'Nr. NN (YYYY)' runs Tuesday–Monday of ISO week NN."""
from __future__ import annotations

import json
import re
import time
from urllib.parse import parse_qs, quote, urlparse

from ..textutil import iso_week_range
from .base import Fetcher, IssueInfo

LEAF_RX = r"https?://leidiniai\.rimi\.lt/(20\d\d)/([a-z]+)/([a-z0-9-]+)/?"
ESHOP = "https://www.rimi.lt/e-parduotuve/lt/paieska?query={q}"


class Rimi(Fetcher):
    chain = "rimi"
    listing_url = "https://www.rimi.lt/asortimentas/rimi-savaitinis-leidinys"

    def discover(self):
        html = self.http.text(self.listing_url, need=r"leidiniai\.rimi\.lt/20")
        out = []
        for url, text in self.links(html, LEAF_RX):
            m = re.search(LEAF_RX, url)
            year, typ, slug = m.group(1), m.group(2), m.group(3)
            vf = vt = number = None
            nm = re.search(r"nr-(\d+)$", slug)
            if typ == "weekly" and nm:
                number = nm.group(1)
                try:
                    vf, vt = iso_week_range(int(year), int(number), 1)
                except ValueError:
                    pass
            series = "weekly" if typ == "weekly" else re.sub(r"-?nr-\d+$|-?20\d\d", "", slug) or slug
            out.append(IssueInfo(
                chain=self.chain, key=f"{year}/{typ}/{slug}", series=series, title=text or slug,
                number=number, valid_from=vf, valid_to=vt, source_url=url.rstrip("/") + "/",
                meta={"type": typ}, parser="rimi",
            ))
        return out

    def download(self, issue, folder):
        page = self.http.browser.render(issue.source_url, capture=r"/Enrichments/", settle_ms=4000)
        self.http.browser_pages += 1
        enr = []
        for c in page.captured:
            try:
                enr += json.loads(c["body"]).get("enrichments", [])
            except Exception as e:
                self.log.warning("Rimi enrichments not JSON (%s): %s", e, c["url"])
        if not enr:
            raise RuntimeError("Rimi: no iPaper hotspots captured (page layout changed?)")
        spots = [{"p": e.get("pageIndex"), "x": e.get("x"), "y": e.get("y"), "w": e.get("width"),
                  "h": e.get("height"), "url": e.get("url"), "type": e.get("type")} for e in enr]
        queries = []
        for s in spots:
            q = parse_qs(urlparse(s["url"] or "").query).get("query", [None])[0]
            if q and q not in queries:
                queries.append(q)
        self.log.info("Rimi %s: %d hotspots, %d e-shop lookups", issue.key, len(spots), len(queries))
        from bs4 import BeautifulSoup
        shop = {}
        t0 = time.monotonic()
        for q in queries:
            try:
                h = self.http.text(ESHOP.format(q=quote(q)), browser_ok=False)
            except Exception as e:
                shop[q] = {"error": str(e)}
                continue
            d = BeautifulSoup(h, "lxml")
            res = []
            for c in d.select("[data-gtm-eec-product]"):
                try:
                    g = json.loads(c["data-gtm-eec-product"])
                except Exception:
                    g = {}
                card = c.find_parent(class_="card") or c
                img = card.find("img")
                res.append({"gtm": g, "text": re.sub(r"\s+", " ", card.get_text(" ")).strip()[:300],
                            "img": (img.get("src") or img.get("data-src")) if img else None})
            shop[q] = res
        self.log.info("Rimi %s: e-shop lookups took %.0f s", issue.key, time.monotonic() - t0)
        issue.prefetched = {
            "enrichments.json": json.dumps({"source": issue.source_url, "enrichments": spots}, ensure_ascii=False).encode(),
            "eshop.json": json.dumps(shop, ensure_ascii=False).encode(),
        }
        issue.files = []
        return super().download(issue, folder)
