"""IKI: https://iki.lt/leidiniai/ (checked 2026-11-20).

The listing shows the current price leaflet in a `.page-content.publications` block: `h2` title
("IKI Kainų leidinys Nr. 47"), `.date-block` ("Pasiūlymai galioja 2026 11 16 - 2026 11 22") and an
"ATSIŲSTI LEIDINĮ" button linking the PDF (wp-content/uploads/YYYY/MM/DD/<name>.pdf). "Kiti IKI leidiniai"
links sub-pages (/leidiniai/<slug>/) with the same block (store offers, catalogues; some undated).
Only PDFs inside these blocks are leaflets – the footer links policy PDFs, which are skipped.

The page is behind Cloudflare; a plain request may be challenged → headless browser fallback.
Older file names carried the ISO week (B47-bazinis_www.pdf = week 47, Monday–Sunday): used when a block has no dates.
"""
from __future__ import annotations

import re
from pathlib import PurePosixPath
from urllib.parse import unquote, urljoin, urlparse

from ..textutil import fold, iso_week_range, parse_range
from .base import Fetcher, FileRef, IssueInfo

SUBPAGE_RX = re.compile(r"^https?://(?:www\.)?iki\.lt/leidiniai/[^/?#]+/?$")
MAX_SUBPAGES = 10


def series_of(title: str, stem: str) -> str:
    """Leaflet line: the weekly price leaflet is one series whatever the file is called; others by file name
    without week codes, dates and edition words ('A4-Dienos-pasiulymu-palaikymas-W47-Stotis' → '…-stotis')."""
    if re.search(r"kain\w* leidinys", fold(title)):
        return "kainu-leidinys"
    s = stem.lower()
    s = re.sub(r"20\d\d[-_]\d\d[-_]\d\d([-_]\d\d[-_]\d\d)?([-_]d)?", "", s)
    s = re.sub(r"(?<![a-z])(nr[_-]?\d+|w\d{1,2}|b\d{1,2}|kw\d{1,2})(?![a-z])", "", s)
    s = re.sub(r"(?<![a-z])(koreguotas|www|bazinis|web|final)(?![a-z])", "", s)
    s = re.sub(r"[-_]+", "-", s).strip("-")
    return s or stem.lower()


class Iki(Fetcher):
    chain = "iki"
    listing_url = "https://iki.lt/leidiniai/"

    def discover(self):
        html = self.http.text(self.listing_url, need=r"publications|\.pdf")
        out = self.blocks(html, self.listing_url)
        subpages = []
        for a in self.soup(html).find_all("a", href=True):
            if a.find_parent(["footer", "header", "nav"]):
                continue
            u = urljoin(self.listing_url, a["href"]).split("#")[0]
            if SUBPAGE_RX.match(u) and u.rstrip("/") != self.listing_url.rstrip("/") and u not in subpages:
                subpages.append(u)
        for u in subpages[:MAX_SUBPAGES]:
            try:
                out += self.blocks(self.http.text(u, need=r"publications|\.pdf"), u)
            except Exception as e:  # one sub-page failing must not lose the main leaflet
                self.log.warning("iki: sub-page %s: %s", u, e)
        seen, uniq = set(), []
        for i in out:
            if i.key not in seen:
                seen.add(i.key)
                uniq.append(i)
        return uniq

    def blocks(self, html: str, page_url: str) -> list[IssueInfo]:
        s = self.soup(html)
        out = []
        for blk in s.select(".page-content.publications"):
            h = blk.select_one("h2.title") or blk.find(["h1", "h2"])
            title = h.get_text(" ", strip=True) if h else ""
            db = blk.select_one(".date-block")
            dates_text = db.get_text(" ", strip=True) if db else ""
            for a in blk.find_all("a", href=True):
                url = urljoin(page_url, a["href"])
                if not re.search(r"\.pdf(\?|$)", url, re.I) or a.find_parent("footer"):
                    continue
                out.append(self.issue(url, title, dates_text, page_url))
        return out

    def issue(self, url: str, title: str, dates_text: str, page_url: str) -> IssueInfo:
        stem = PurePosixPath(unquote(urlparse(url).path)).stem
        vf, vt = parse_range(dates_text, self.today) if dates_text else (None, None)
        number = None
        m = re.search(r"Nr\.?\s*(\d{1,3})", title) or re.search(r"(?i)(?:^|[-_])(?:nr[_-]?|b|w)(\d{1,2})(?=[-_]|$)", stem)
        if m:
            number = m.group(1)
        if vf is None and number:
            up = re.search(r"/uploads/(20\d\d)/(\d\d)/", url)
            if up:
                year, month, week = int(up.group(1)), int(up.group(2)), int(number)
                if month == 12 and week <= 5:
                    year += 1
                try:
                    vf, vt = iso_week_range(year, week, 0)
                except ValueError:
                    pass
        return IssueInfo(
            chain=self.chain, key=stem, series=series_of(title, stem), title=title or stem, number=number,
            valid_from=vf, valid_to=vt, source_url=page_url,
            files=[FileRef(url, PurePosixPath(urlparse(url).path).name, referer=page_url)], parser="pdf",
        )
