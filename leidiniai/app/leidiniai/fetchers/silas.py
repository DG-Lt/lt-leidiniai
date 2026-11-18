"""Šilas: https://www.silas.lt/akcijos/ – heading "Leidinys Nr. 23. Kainos galioja 2026 m. lapkričio 18 d. – gruodžio 1 d."
with one JPEG per page and a PDF that holds the same images (image-only → vision model, later step)."""
from __future__ import annotations

import re
from pathlib import PurePosixPath
from urllib.parse import urlparse

from ..textutil import parse_range
from .base import Fetcher, FileRef, IssueInfo


class Silas(Fetcher):
    chain = "silas"
    listing_url = "https://www.silas.lt/akcijos/"

    def discover(self):
        html = self.http.text(self.listing_url, need=r"Leidinys\s+Nr")
        text = self.soup(html).get_text("\n", strip=True)
        m = re.search(r"Leidinys\s+Nr\.\s*(\d+)\.?\s*([^\n]*)", text)
        if not m:
            self.log.warning("Šilas: leaflet heading not found")
            return []
        number = m.group(1)
        vf, vt = parse_range(m.group(2), self.today)
        pdfs = [u for u, _ in self.links(html, r"https?://www\.silas\.lt/wp-content/uploads/[^\"'\s<>]+?\.pdf")]
        pages = [u for u, _ in self.links(html, r"https?://www\.silas\.lt/wp-content/uploads/[^\"'\s<>]+?\.jpe?g")]
        year = (vf or self.today).year
        files = [FileRef(pdfs[0], PurePosixPath(urlparse(pdfs[0]).path).name)] if pdfs else \
            [FileRef(u, PurePosixPath(urlparse(u).path).name) for u in pages]
        return [IssueInfo(
            chain=self.chain, key=f"{year}-{number}", series="leidinys", title=m.group(0).strip(),
            number=number, valid_from=vf, valid_to=vt, source_url=self.listing_url, files=files,
            meta={"page_images": pages}, parser="vision",
        )]
