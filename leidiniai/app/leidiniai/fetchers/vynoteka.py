"""Vynoteka: the LEIDINIAI menu on https://vynoteka.lt/ links each publication page (checked 2026-11-20):

- "Gėrimų leidinys" /gerimu-leidinys-2026-23 – a page viewer `<Flyer pages='["325_slide_1.jpg", …]'
  front-cover=… back-cover=…>`: JPEG pages (2480×3508) only, no PDF ("Leidinys PDF" is ?pdf=1, the same viewer)
  → picture reader.
- "Maisto leidinys" /nr-23-kainos-galioja-2026-11-09-2026-11-22 and "Kalėdinių rinkinių katalogas 2026" –
  `<div class="flip-book-container1" src="/upload/media/<hash>.pdf">`: PDF with a text layer.
- "Žiemos katalogas 2026" – a video only (`<publication-video>`): skipped.

Every page prints "Kainos galioja 2026 11 16 - 2026 11 29". Biweekly drinks/food leaflets (Nr. in the slug).
The age gate on the site is client-side; plain requests get the page."""
from __future__ import annotations

import html as htmllib
import json
import re
from urllib.parse import urljoin, urlparse

from ..textutil import fold, parse_range
from .base import Fetcher, FileRef, IssueInfo

BASE = "https://vynoteka.lt/"
PUB_TEXT = re.compile(r"(?i)leidinys|katalogas")


class Vynoteka(Fetcher):
    chain = "vynoteka"
    listing_url = BASE

    def publications(self, html: str) -> list[tuple[str, str]]:
        """(page url, menu text) of the publications linked on the home page; '?pdf=1' (same viewer) dropped."""
        out: dict[str, str] = {}
        for a in self.soup(html).find_all("a", href=True):
            text = a.get_text(" ", strip=True)
            p = urlparse(urljoin(BASE, a["href"]))
            if p.netloc not in ("vynoteka.lt", "www.vynoteka.lt") or p.query or p.path.count("/") != 1 or p.path == "/":
                continue
            if not (PUB_TEXT.search(text) or PUB_TEXT.search(p.path.replace("-", " ")) or "kainos-galioja" in p.path):
                continue
            u = f"https://vynoteka.lt{p.path}"
            good = PUB_TEXT.search(text) and text not in ("Leidinys online", "Leidinys PDF")
            if u not in out or (good and not out[u]):
                out[u] = text if good else ""
        return list(out.items())

    def discover(self):
        home = self.http.text(BASE, need=r"(?i)leidin")
        out = []
        for url, menu_text in self.publications(home):
            try:
                page = self.http.text(url, browser_ok=False)
            except Exception as e:
                self.log.warning("vynoteka: %s not read: %s", url, e)
                continue
            info = self.issue_from_page(url, menu_text, page)
            if info:
                out.append(info)
        return out

    def issue_from_page(self, url: str, menu_text: str, page: str) -> IssueInfo | None:
        slug = urlparse(url).path.strip("/")
        m = re.search(r"<title>\s*([^<]+?)\s*</title>", page)
        title = htmllib.unescape(m.group(1)).split("|")[0].strip() if m else ""
        if not title or title.lower().startswith(("vynoteka", "nr")):
            title = menu_text or slug
        mk = re.search(r"Kainos galioja\s*([0-9][0-9 .\-–]{8,30})", page)
        vf, vt = parse_range(mk.group(1), self.today) if mk else (None, None)
        nm = re.search(r"(?:^|-)nr-(\d+)(?:-|$)", slug) or re.search(r"-20\d\d-(\d+)$", slug)
        number = nm.group(1) if nm else None
        series = re.sub(r"[^a-z0-9]+", "-", fold(title)).strip("-") or slug
        year = (vf or self.today).year
        key = f"{slug}" if re.search(r"20\d\d|nr-\d+", slug) else f"{slug}-{vf or year}"
        base = dict(chain=self.chain, key=key, series=series, title=title, number=number,
                    valid_from=vf, valid_to=vt, source_url=url)
        pdf = re.search(r'flip-book-container1"\s+src="([^"]+\.pdf)"', page) or \
            re.search(r'src="(/upload/media/[^"]+\.pdf)"', page)
        if pdf:
            return IssueInfo(**base, files=[FileRef(urljoin(BASE, pdf.group(1)), f"{slug[:60]}.pdf", referer=url)],
                             meta={"kind": "pdf", "parser": "vynoteka"}, parser="vynoteka")
        fl = re.search(r"<Flyer\b([^>]*)>", page, re.S)
        if fl:
            attrs = dict(re.findall(r'([\w-]+)="([^"]*)"', fl.group(1)))
            try:
                pages = json.loads(htmllib.unescape(attrs.get("pages", "[]")))
            except ValueError:
                pages = []
            urls = []
            if attrs.get("front-cover"):
                urls.append(htmllib.unescape(attrs["front-cover"]))
            urls += [urljoin(BASE, "/upload/pdf/" + p.lstrip("/")) if "/" not in p else urljoin(BASE, p) for p in pages]
            if attrs.get("back-cover"):
                urls.append(htmllib.unescape(attrs["back-cover"]))
            if not urls:
                self.log.warning("vynoteka: %s – page viewer without pages", url)
                return None
            files = [FileRef(u, f"p{i:02d}.jpg", referer=url) for i, u in enumerate(urls, 1)]
            return IssueInfo(**base, files=files, meta={"kind": "pages", "pages": len(files), "parser": "vision"},
                             parser="vision")
        if "<publication-video" in page:
            self.log.info("vynoteka: %s is a video only – nothing to read", title)
            return None
        self.log.warning("vynoteka: %s – no PDF, page viewer or video found (layout changed?)", url)
        return None
