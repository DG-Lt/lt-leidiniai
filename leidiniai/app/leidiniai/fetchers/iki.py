"""IKI: https://iki.lt/leidiniai/ links the PDFs directly (wp-content/uploads/YYYY/MM/DD/B47-bazinis_www.pdf).

The page is behind Cloudflare; a plain request may be challenged → headless browser fallback.
Dates: week code B<NN> = ISO week, Monday–Sunday. Other PDFs (no week code) are undated.
"""
from __future__ import annotations

import re
from pathlib import PurePosixPath
from urllib.parse import unquote, urlparse

from ..textutil import iso_week_range, parse_range
from .base import Fetcher, FileRef, IssueInfo

PDF_RX = r"https?://(?:www\.)?iki\.lt/wp-content/uploads/[^\"'\s<>]+?\.pdf"


class Iki(Fetcher):
    chain = "iki"
    listing_url = "https://iki.lt/leidiniai/"

    def discover(self):
        html = self.http.text(self.listing_url, need=r"\.pdf")
        out = []
        for url, text in self.links(html, PDF_RX):
            stem = PurePosixPath(unquote(urlparse(url).path)).stem
            m = re.match(r"^[A-Za-z]{0,3}(\d{1,2})[-_](.+)$", stem)
            up = re.search(r"/uploads/(20\d\d)/(\d\d)/", url)
            vf = vt = None
            number = None
            series = re.sub(r"[_-]?www$", "", stem.lower())
            if m and up:
                week, series = int(m.group(1)), re.sub(r"[_-]?www$", "", m.group(2).lower())
                year, month = int(up.group(1)), int(up.group(2))
                if month == 12 and week <= 5:
                    year += 1
                try:
                    vf, vt = iso_week_range(year, week, 0)
                    number = str(week)
                except ValueError:
                    pass
            if vf is None and text:
                vf, vt = parse_range(text, self.today)
            out.append(IssueInfo(
                chain=self.chain, key=stem, series=series, title=text or stem, number=number,
                valid_from=vf, valid_to=vt, source_url=self.listing_url,
                files=[FileRef(url, PurePosixPath(urlparse(url).path).name)], parser="pdf",
            ))
        return out
