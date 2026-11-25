"""Watch list (Stebimi) matching – one rule for the panel, Pasiūlymai "Stebimi viršuje", the HA sensor and the HA
event (0.8.1).

A term matches an offer when **every word** of the term is in the offer's plain-letter name (any order):
"Natura aliejus" finds "Saulėgrąžų aliejus NATURA*, 1,5 l". With **Tikslus žodis** (`watch.exact`) each word
must be a whole word: "alus" no longer finds "natūralus". A term limited to one chain matches only there.
"""
from __future__ import annotations


def words(term) -> list[str]:
    return (term["term_key"] or "").split()


def matches(term, name_key: str, chain: str) -> bool:
    if term["chain"] and term["chain"] != chain:
        return False
    ws = words(term)
    if not ws:
        return False
    if _exact(term):
        padded = f" {name_key or ''} "
        return all(f" {w} " in padded for w in ws)
    return all(w in (name_key or "") for w in ws)


def matching_terms(terms, name_key: str, chain: str) -> list:
    return [t for t in terms if matches(t, name_key, chain)]


def sql(term) -> tuple[str, list]:
    """SQL condition (offers aliased `o`) for one term."""
    parts, a = [], []
    for w in words(term):
        if _exact(term):
            parts.append("instr(' ' || o.name_key || ' ', ?) > 0")
            a.append(f" {w} ")
        else:
            parts.append("instr(o.name_key, ?) > 0")
            a.append(w)
    if not parts:
        return "0", []
    if term["chain"]:
        parts.append("o.chain=?")
        a.append(term["chain"])
    return "(" + " AND ".join(parts) + ")", a


def _exact(term) -> bool:
    try:
        return bool(term["exact"])
    except (KeyError, IndexError):
        return False


def muted(term, today=None) -> bool:
    """Nutildyti (0.8.2): muted words do not highlight, count, sort first or send events until `muted_until`."""
    from datetime import date
    try:
        until = term["muted_until"]
    except (KeyError, IndexError):
        return False
    return bool(until) and until >= (today or date.today()).isoformat()


def active(terms, today=None) -> list:
    return [t for t in terms if not muted(t, today)]
