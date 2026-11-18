from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup


@dataclass
class FileRef:
    url: str
    name: str                 # file name to store under pdf/<chain>/<key>/
    referer: str | None = None


@dataclass
class IssueInfo:
    chain: str
    key: str                  # unique per chain, stable between checks
    series: str               # leaflet line: next issue of the same series replaces this one
    title: str                # as printed
    number: str | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    source_url: str | None = None
    files: list[FileRef] = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    prefetched: dict[str, bytes] = field(default_factory=dict)  # name → content fetched during discover
    parser: str = "pdf"       # which parser reads the files (step 3); 'none' = waits for a parser


class Fetcher:
    chain: str = ""
    listing_url: str = ""

    def __init__(self, http, log: logging.Logger, today: date):
        self.http = http
        self.log = log
        self.today = today

    def discover(self) -> list[IssueInfo]:
        raise NotImplementedError

    def download(self, issue: IssueInfo, folder: Path) -> list[dict]:
        """Default: write prefetched content, then fetch every FileRef (spaced by Http)."""
        out = []
        for name, data in issue.prefetched.items():
            p = folder / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
            import hashlib
            out.append({"url": issue.source_url, "name": name, "path": str(p),
                        "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
        for f in issue.files:
            out.append(self.http.download(f.url, folder / f.name, referer=f.referer or self.listing_url))
        return out

    # helpers
    @staticmethod
    def soup(html: str) -> BeautifulSoup:
        return BeautifulSoup(html, "lxml")

    def links(self, html: str, pattern: str, base: str | None = None) -> list[tuple[str, str]]:
        """(absolute url, link text) for every <a href> matching pattern, in page order, no duplicates."""
        s = self.soup(html)
        seen, out = set(), []
        rx = re.compile(pattern)
        for a in s.find_all("a", href=True):
            u = urljoin(base or self.listing_url, a["href"])
            if rx.search(u) and u not in seen:
                seen.add(u)
                out.append((u, a.get_text(" ", strip=True)))
        # links only present in scripts/JSON (JS-rendered pages)
        for m in rx.finditer(html.replace("\\/", "/")):
            u = urljoin(base or self.listing_url, m.group(0))
            if u not in seen and u.startswith("http"):
                seen.add(u)
                out.append((u, ""))
        return out
