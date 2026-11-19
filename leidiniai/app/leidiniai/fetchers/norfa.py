"""Norfa: https://www.norfa.lt/leidiniai/ shows "NORFA Nr. 23 (523)" + "2026.11.12 - 2026.11.25";
the PDF comes from /leidiniai/download/<n> (button "Atsisiųsti leidinį")."""
from __future__ import annotations

import re

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
        return out
