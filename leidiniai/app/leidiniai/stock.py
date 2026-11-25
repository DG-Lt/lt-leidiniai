""""Atsargoms" (0.8.2): goods that keep long and are at a really good price – worth buying in bulk.

An offer gets the badge when
- its plain-letter name holds a **long-life** word (pasta, rice, UHT milk, canned food, detergent …) – or a
  **frozen** word (then the badge says it needs freezer space) – and no **exclude** word (fresh, chilled …), and
- the price is really good: discount ≥ `min_discount` %, or the price is at most `near_low_pct` % above the
  lowest price of the same product earlier in the app's history.

Word lists and both numbers are edited on Būsena (stored in kv "stock_rules"); words are matched as the start of a
word in the plain-letter name ("makaron" finds "makaronai"). Fully local: no model involved.
"""
from __future__ import annotations

from .textutil import fold

DEFAULTS = {
    "long": [
        "makaron", "spagec", "lazanij", "ryziai", "ryziu", "kruop", "griki", "avizinia dribsn", "manu kruop",
        "miltai", "miltu", "cukrus", "cukraus", "druska", "aliejus", "aliejaus", "konserv", "skardin",
        "uht", "ilgo galiojimo", "ilgai galiojant", "pieno milteliai", "kava", "kavos", "kapsul", "arbata",
        "medus", "uogiene", "dzemas", "pomidoru pasta", "pomidoru padaz", "padazas", "kecupas", "majonezas",
        "sardin", "tunas", "tuno", "sprotai", "pupel", "zirneliai", "kukuruzai", "lesi", "riesut",
        "dziovint", "sausi pusryciai", "dribsniai",
        "sausas pasaras", "sausas ed", "konservuot",
        "skalbikl", "skalbimo", "minkstiklis", "kapsules skalb", "indaplov", "indu ploviklis", "tualetinis popierius",
        "popieriniai rankslu", "servetel", "siuksliu maisai", "sampun", "dantu pasta", "muilas", "dusas", "dezodorant",
        "degtine", "brendis", "viskis", "konjakas", "romas", "dzinas", "likeris", "vynas", "sidras",
    ],
    "frozen": ["saldyt", "uzsaldyt", "ledai", "koldun", "virtiniai", "picos saldyt"],
    "exclude": ["sviez", "atsaldyt", "vesint", "kept", "troskint", "karstai rukyt", "salot", "misrain", "patiekal",
                "sefai", "suris", "surio", "duona", "bagete", "vata", "saldytuve"],
    "min_discount": 30,
    "near_low_pct": 5,
}


def rules(conn) -> dict:
    from . import db
    r = dict(DEFAULTS)
    r.update(db.kv_get(conn, "stock_rules", {}) or {})
    for k in ("long", "frozen", "exclude"):
        r[k] = [w for w in (fold(x).strip() for x in r[k]) if len(w) >= 2]
    return r


def save_rules(conn, form: dict) -> dict:
    from . import db

    def lines(v):
        return sorted({fold(x).strip() for x in (v or "").replace(",", "\n").splitlines() if len(fold(x).strip()) >= 2})

    def num(v, lo, hi, default):
        try:
            return max(lo, min(hi, int(v)))
        except (TypeError, ValueError):
            return default
    r = {"long": lines(form.get("long")), "frozen": lines(form.get("frozen")), "exclude": lines(form.get("exclude")),
         "min_discount": num(form.get("min_discount"), 5, 90, DEFAULTS["min_discount"]),
         "near_low_pct": num(form.get("near_low_pct"), 0, 50, DEFAULTS["near_low_pct"])}
    db.kv_set(conn, "stock_rules", r)
    return r


def _has(words, name_key: str) -> bool:
    padded = " " + (name_key or "")
    return any((" " + w) in padded for w in words)


def kind(name_key: str, r: dict) -> str | None:
    """'frozen', 'long' or None."""
    if _has(r["exclude"], name_key):
        return None
    if _has(r["frozen"], name_key):
        return "frozen"
    if _has(r["long"], name_key):
        return "long"
    return None


def good_price(row, hist_low: int | None, r: dict) -> bool:
    if row["discount_pct"] and row["discount_pct"] >= r["min_discount"]:
        return True
    return bool(row["price"] and hist_low and row["price"] <= hist_low * (1 + r["near_low_pct"] / 100))


def annotate(conn, rows) -> dict[int, str]:
    """Offer id → 'long' / 'frozen' for the rows that earn the badge."""
    r = rules(conn)
    cand = [x for x in rows if kind(x["name_key"], r)]
    if not cand:
        return {}
    pids = sorted({x["product_id"] for x in cand if x["product_id"]})
    low = {}
    if pids:
        q = ",".join("?" * len(pids))
        for pid, oid, price in conn.execute(f"SELECT product_id, id, price FROM offers WHERE product_id IN ({q})"
                                            " AND price IS NOT NULL", pids):
            low.setdefault(pid, []).append((oid, price))
    out = {}
    for x in cand:
        earlier = [p for oid, p in low.get(x["product_id"], []) if oid != x["id"]]
        if good_price(x, min(earlier) if earlier else None, r):
            out[x["id"]] = kind(x["name_key"], r)
    return out


def sql(r: dict) -> tuple[str, list]:
    """SQL condition (offers aliased `o`) for the "Atsargoms" filter: same rule as `annotate`."""
    def any_word(words):
        if not words:
            return "0", []
        return "(" + " OR ".join("instr(' ' || o.name_key, ?) > 0" for _ in words) + ")", [" " + w for w in words]
    lw, la = any_word(r["long"] + r["frozen"])
    ex, ea = any_word(r["exclude"])
    cond = (f"({lw} AND NOT {ex} AND (COALESCE(o.discount_pct,0) >= ? OR (o.price IS NOT NULL AND o.price <= "
            "(1 + ? / 100.0) * (SELECT MIN(o2.price) FROM offers o2 WHERE o2.product_id=o.product_id AND o2.id<>o.id"
            " AND o2.price IS NOT NULL))))")
    return cond, la + ea + [r["min_discount"], r["near_low_pct"]]
