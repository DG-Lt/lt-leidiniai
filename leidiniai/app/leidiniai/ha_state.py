"""What the Home Assistant entities show, computed from the database (no MQTT here, so it is easy to test).

Prices go out in euros (float, 2 decimals); dates as ISO strings; text as printed (UTF-8).
"""
from __future__ import annotations

import json
from datetime import date, timedelta

from . import CHAIN_NAMES, db

LIVE = ("parsed", "waiting_parser", "downloaded", "parse_failed")  # leaflets the user can look at
MAX_WATCH_ITEMS = 40   # keep attributes small (HA recorder limit 16 KB)
MAX_STATE_LEN = 255


def eur(cents):
    return None if cents is None else round(cents / 100, 2)


def _current(i, today: str) -> bool:
    return (not i["valid_from"] or i["valid_from"] <= today) and (not i["valid_to"] or i["valid_to"] >= today)


SHORT_SERIES = {"maisto-prekiu-pasiulymai": "Maisto prekės", "ne-maisto-prekiu-pasiulymai": "Ne maisto prekės",
                "pasiulymai": "Pasiūlymai", "akcijos": "Akcijos svetainėje", "gerimu-leidinys": "Gėrimai",
                "maisto-leidinys": "Maisto leidinys"}
SHORT_MAX = 28


def short_title(i) -> str:
    """Leaflet name short enough for a dashboard table: 'MAISTO PREKIŲ PASIŪLYMAI – Nuo lapkričio 23 d.' → 'Maisto
    prekės', 'Pasiūlymai (160) iki 2026-12-07' → 'Pasiūlymai', 'Leidinys Nr. 23. Kainos galioja …' → 'Leidinys Nr. 23'."""
    import re
    if i["series"] in SHORT_SERIES:
        t = SHORT_SERIES[i["series"]]
    else:
        t = re.split(r"\s+[–—-]\s+|\.\s+(?=[A-ZĄČĘĖĮŠŲŪŽ][a-ząčęėįšųūž])|\s+\(", i["title"] or "", maxsplit=1)[0].strip(" .")
        if t.isupper():
            t = t[:1] + t[1:].lower()
    if i["number"] and i["series"] in SHORT_SERIES and i["chain"] != "lidl":
        t = f"{t} Nr. {i['number']}"
    return t if len(t) <= SHORT_MAX else t[:SHORT_MAX - 1].rstrip() + "…"


def _leaflet(i) -> dict:
    return {"title": i["title"], "short_title": short_title(i), "series": i["series"], "number": i["number"],
            "valid_from": i["valid_from"], "valid_to": i["valid_to"], "offers": i["offers"], "status": i["status"],
            "url": i["source_url"]}


def chain_leaflet(conn, chain: str, today: date) -> tuple[str, dict]:
    """State = title of the main leaflet valid today (newest start, then most offers); attributes list all
    current and upcoming leaflets."""
    t = today.isoformat()
    rows = conn.execute(f"SELECT * FROM issues WHERE chain=? AND status IN ({','.join('?' * len(LIVE))})"
                        " AND (valid_to IS NULL OR valid_to >= ?)", (chain, *LIVE, t)).fetchall()
    rows = [r for r in rows if not json.loads(r["meta"] or "{}").get("listed_only")]
    cur = sorted((r for r in rows if _current(r, t)),
                 key=lambda r: (r["valid_from"] or "", r["offers"] or 0, r["id"]), reverse=True)
    nxt = sorted((r for r in rows if r["valid_from"] and r["valid_from"] > t), key=lambda r: (r["valid_from"], -r["id"]))
    st = conn.execute("SELECT * FROM chain_state WHERE chain=?", (chain,)).fetchone()
    main = cur[0] if cur else None
    attrs = {
        "chain": CHAIN_NAMES[chain],
        "short_title": short_title(main) if main else None,
        "valid_from": main["valid_from"] if main else None,
        "valid_to": main["valid_to"] if main else None,
        "offers": main["offers"] if main else None,
        "url": main["source_url"] if main else None,
        "current": [_leaflet(r) for r in cur],
        "upcoming": [_leaflet(r) for r in nxt],
        "current_offers": sum(r["offers"] or 0 for r in cur),
        "last_check": st["last_check"] if st else None,
        "last_error": st["last_error"] if st else None,
    }
    state = (main["title"] if main else "nėra")[:MAX_STATE_LEN]
    return state, attrs


def ending_soon(valid_to: str | None, today: date, days: int) -> bool:
    """The offer ends within `days` days (today included): highlighted, "Besibaigiantys" filter (0.8.1)."""
    return bool(valid_to) and today.isoformat() <= valid_to <= (today + timedelta(days=days)).isoformat()


def watched_on_sale(conn, today: date, mark_hits: bool = False, ending_days: int = 3) -> tuple[int, dict]:
    """Offers valid today whose name matches a watch term (watchmatch: every word, any order; Tikslus žodis)."""
    from . import watchmatch
    t = today.isoformat()
    terms = conn.execute("SELECT * FROM watch ORDER BY term").fetchall()
    if not terms:
        return 0, {"terms": 0, "items": []}
    rows = conn.execute(
        "SELECT o.*, i.title AS issue_title FROM offers o JOIN issues i ON i.id=o.issue_id"
        " WHERE i.status='parsed' AND (o.valid_to IS NULL OR o.valid_to >= ?) AND (o.valid_from IS NULL OR o.valid_from <= ?)"
        " ORDER BY COALESCE(o.discount_pct,0) DESC, o.price IS NULL, o.price", (t, t)).fetchall()
    items, hit_terms = [], set()
    for r in rows:
        ts = watchmatch.matching_terms(terms, r["name_key"], r["chain"])
        if not ts:
            continue
        hit_terms.update(w["id"] for w in ts)
        items.append({"term": ts[0]["term"], "terms": [w["term"] for w in ts], "chain": CHAIN_NAMES[r["chain"]],
                      "name": r["name"], "price": eur(r["price"]), "old_price": eur(r["old_price"]),
                      "discount_pct": r["discount_pct"], "discount": r["discount_text"],
                      "card": bool(r["card"]), "valid_to": r["valid_to"],
                      "ending_soon": ending_soon(r["valid_to"], today, ending_days), "product_id": r["product_id"]})
    if mark_hits and hit_terms:
        with conn:
            conn.executemany("UPDATE watch SET last_hit=? WHERE id=?", [(db.now_iso(), i) for i in hit_terms])
    by_term = {w["term"]: sum(1 for x in items if w["term"] in x["terms"]) for w in terms}
    by_chain: dict[str, int] = {}
    for x in items:
        by_chain[x["chain"]] = by_chain.get(x["chain"], 0) + 1
    by_chain = dict(sorted(by_chain.items(), key=lambda kv: -kv[1]))
    return len(items), {"terms": len(terms), "by_term": by_term, "by_chain": by_chain,
                        "ending_soon": sum(1 for x in items if x["ending_soon"]),
                        "items": items[:MAX_WATCH_ITEMS], "truncated": len(items) > MAX_WATCH_ITEMS}


def problems(conn, chains, today: date) -> list[str]:
    """Reasons for the 'problem' binary sensor: failed last check, leaflets that failed to download/parse."""
    t = today.isoformat()
    out = []
    for c in chains:
        st = conn.execute("SELECT last_error FROM chain_state WHERE chain=?", (c,)).fetchone()
        if st and st["last_error"]:
            out.append(f"{CHAIN_NAMES[c]}: {st['last_error'][:200]}")
    q = ",".join("?" * len(chains)) or "''"
    for r in conn.execute(f"SELECT chain, title, status, error FROM issues WHERE chain IN ({q})"
                          " AND status IN ('failed','parse_failed') AND (valid_to IS NULL OR valid_to >= ?)", (*chains, t)):
        what = "neatsisiųstas" if r["status"] == "failed" else "neperskaitytas"
        out.append(f"{CHAIN_NAMES[r['chain']]} „{r['title']}“ {what}: {(r['error'] or '')[:200]}")
    return out


def last_run(conn) -> tuple[str | None, dict]:
    r = conn.execute("SELECT * FROM runs WHERE finished IS NOT NULL ORDER BY id DESC LIMIT 1").fetchone()
    if not r:
        return None, {}
    s = json.loads(r["summary"] or "{}")
    return r["finished"], {"chain": CHAIN_NAMES.get(r["chain"], r["chain"]), "status": r["status"], "trigger": r["trigger"],
                           "run_id": r["id"], "new_leaflets": len(s.get("new_issues", [])),
                           "warnings": len(s.get("warnings", [])), "errors": len(s.get("errors", [])),
                           "seconds": s.get("timings", {}).get("total_s")}


def leaflets_to_announce(conn, today: date, announced: set[int]) -> list[dict]:
    """Leaflets ready to look at (parsed, or waiting for the vision parser) and not yet announced."""
    t = today.isoformat()
    out = []
    for r in conn.execute("SELECT * FROM issues WHERE status IN ('parsed','waiting_parser')"
                          " AND (valid_to IS NULL OR valid_to >= ?) ORDER BY id", (t,)):
        if r["id"] in announced or json.loads(r["meta"] or "{}").get("listed_only"):
            continue
        out.append({"issue_id": r["id"], "chain": r["chain"], "chain_name": CHAIN_NAMES[r["chain"]], **_leaflet(r)})
    return out


def watch_hit_key(r) -> str:
    """Stable across re-reading and name fixes (0.8.1; 0.8.0 used the name and re-announced 11 offers after the
    re-parse): leaflet, page, prices."""
    return f"{r['issue_id']}:{r['page']}:{r['price']}:{r['old_price']}"


def watch_hits(conn, today: date) -> list[dict]:
    """Watched offers valid today or later from leaflets **first seen** after the watch term was added (re-reading
    a leaflet does not make its offers new). Each: one event.leidiniai_watch_hit (mqtt.Bridge.announce_watch_hits)."""
    from . import watchmatch
    t = today.isoformat()
    terms = conn.execute("SELECT * FROM watch ORDER BY created").fetchall()
    if not terms:
        return []
    rows = conn.execute("SELECT o.*, i.title AS issue_title, i.first_seen FROM offers o JOIN issues i ON i.id=o.issue_id"
                        " WHERE i.status='parsed' AND (o.valid_to IS NULL OR o.valid_to >= ?) ORDER BY i.id, o.seq",
                        (t,)).fetchall()
    out, seen = [], set()
    for r in rows:
        ts = [w for w in watchmatch.matching_terms(terms, r["name_key"], r["chain"])
              if (r["first_seen"] or "") >= (w["created"] or "")]
        k = watch_hit_key(r)
        if not ts or k in seen:
            continue
        seen.add(k)
        out.append({"key": k, "term": ts[0]["term"], "chain": r["chain"], "chain_name": CHAIN_NAMES[r["chain"]],
                    "name": r["name"], "price": eur(r["price"]), "old_price": eur(r["old_price"]),
                    "discount": r["discount_text"] or (f"-{r['discount_pct']}%" if r["discount_pct"] else None),
                    "card": bool(r["card"]), "valid_from": r["valid_from"], "valid_to": r["valid_to"],
                    "leaflet": r["issue_title"], "product_id": r["product_id"], "path": f"/produktas/{r['product_id']}"})
    return out


def picture_reader(settings) -> tuple[str, dict]:
    """sensor.leidiniai_picture_reader: state in Lithuanian, the reader's own message as attribute
    ('atsisiunčiamas modelis qwen2.5vl:7b 40%')."""
    from . import vision
    st = vision.read_status(settings)
    if settings.picture_reader == "none":
        return "išjungtas", {"reader": "none", "message": "išjungtas (parinktis picture_reader)"}
    state = {"ready": "paruoštas", "preparing": "ruošiamas", "error": "klaida", "off": "išjungtas"}.get(
        st.get("state"), "nežinomas")
    if state == "paruoštas" and st.get("signature") != vision._signature(settings):
        state = "ruošiamas"
    return state, {"reader": settings.picture_reader, "model": settings.ollama_model
                   if settings.picture_reader == "ollama" else None,
                   "external": bool(settings.ollama_url), "message": st.get("message"), "updated": st.get("updated")}
