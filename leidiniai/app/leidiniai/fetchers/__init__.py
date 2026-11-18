"""Per-chain fetchers: find the current leaflets (discover) and fetch their files (download)."""
from __future__ import annotations

from .base import FileRef, Fetcher, IssueInfo


def get(chain: str) -> type[Fetcher]:
    from . import iki, lidl, maxima, norfa, rimi, silas
    return {"iki": iki.Iki, "lidl": lidl.Lidl, "maxima": maxima.Maxima, "norfa": norfa.Norfa,
            "rimi": rimi.Rimi, "silas": silas.Silas}[chain]


__all__ = ["FileRef", "Fetcher", "IssueInfo", "get"]
