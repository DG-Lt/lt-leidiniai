"""Maxima: the leaflets are image-only iPaper, so offers come from https://www.maxima.lt/pasiulymai
(offer cards with price, old price, discount, unit price, 'Iki 11.23'). The page is a live list, not an
issue: each check stores a snapshot keyed by the set of offer ids; a changed set = new "issue"."""
from __future__ import annotations

import hashlib
import re

from ..textutil import parse_range
from .base import Fetcher, IssueInfo


class Maxima(Fetcher):
    chain = "maxima"
    listing_url = "https://www.maxima.lt/pasiulymai"

    def discover(self):
        html = self.http.text(self.listing_url, need=r'data-controller="offerCard"',
                              wait_for='[data-controller="offerCard"]')
        # raw HTML writes data-offerCard-offer-id (mixed case; BeautifulSoup lower-cases it); numbers until 2026-11, now UUIDs
        ids = sorted(set(re.findall(r'data-offercard-offer-id\s*=\s*["\']([^"\']+)', html, re.I)))
        if not ids:
            n = html.count('data-controller="offerCard"')
            self.log.warning("Maxima: no offer cards found (%d offerCard elements without an offer id; %d bytes)",
                             n, len(html))
            return []
        ends = []
        for t in re.findall(r"offer-price-tag__meta-date[^>]*>([^<]+)<", html):
            _, vt = parse_range(t, self.today)
            if vt:
                ends.append(vt)
        key = hashlib.sha1(",".join(ids).encode()).hexdigest()[:10]
        vt = max(ends) if ends else None
        return [IssueInfo(
            chain=self.chain, key=key, series="pasiulymai",
            title=f"Pasiūlymai ({len(ids)})" + (f" iki {vt.isoformat()}" if vt else ""),
            valid_from=self.today, valid_to=vt, source_url=self.listing_url,
            meta={"offers": len(ids), "min_to": min(ends).isoformat() if ends else None},
            prefetched={"pasiulymai.html": html.encode("utf-8")}, parser="maxima",
        )]
