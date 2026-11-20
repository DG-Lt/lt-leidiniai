"""Offer pages: Pasiūlymai (current offers), product history, Stebimi (watch list), offer images."""
from __future__ import annotations

import json
from datetime import date

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, send_from_directory, url_for

from .. import CHAIN_NAMES, db, store
from ..categories import CATEGORIES
from ..textutil import fold

bp = Blueprint("offers", __name__)
PAGE_SIZE = 60

SORTS = {
    "disc": "COALESCE(o.discount_pct,0) DESC, o.price IS NULL, o.price",
    "price": "o.price IS NULL, o.price",
    "unit": "o.unit_price IS NULL, o.unit, o.unit_price",
    "name": "o.name_key",
    "new": "i.first_seen DESC, o.seq",
    "leaflet": "o.chain, o.issue_id, o.seq",
}
SORT_LT = {"disc": "Didžiausia nuolaida", "price": "Pigiausi", "unit": "Vieneto kaina", "name": "Pavadinimas",
           "new": "Naujausi", "leaflet": "Kaip leidinyje"}
WHEN_LT = {"now": "Galioja dabar", "soon": "Netrukus", "all": "Visi"}


def settings():
    return current_app.config["SETTINGS"]


def mqtt_refresh():
    """Watch list changed: update the HA 'watched on sale' sensor."""
    m = current_app.config.get("MQTT")
    if m:
        m.refresh()


def watch_terms(conn) -> list:
    return conn.execute("SELECT * FROM watch ORDER BY term").fetchall()


def watched(name_key: str, chain: str, terms) -> bool:
    return any(t["term_key"] in name_key and (not t["chain"] or t["chain"] == chain) for t in terms)


def current_where(today: date, when: str) -> tuple[str, list]:
    """Offers of parsed, still valid leaflets. 'now' = valid today, 'soon' = starts later."""
    t = today.isoformat()
    w = ["i.status='parsed'", "(o.valid_to IS NULL OR o.valid_to >= ?)"]
    a: list = [t]
    if when == "now":
        w.append("(o.valid_from IS NULL OR o.valid_from <= ?)")
        a.append(t)
    elif when == "soon":
        w.append("o.valid_from > ?")
        a.append(t)
    return " AND ".join(w), a


def _filters(args):
    q = (args.get("q") or "").strip()
    return {"q": q, "chain": args.get("chain") if args.get("chain") in CHAIN_NAMES else "",
            "cat": args.get("cat") if args.get("cat") in CATEGORIES else "",
            "when": args.get("when") if args.get("when") in WHEN_LT else "now",
            "sort": args.get("sort") if args.get("sort") in SORTS else "disc",
            "disc": "1" if args.get("disc") == "1" else "", "nocard": "1" if args.get("nocard") == "1" else "",
            "top": "1" if args.get("top") == "1" else "", "exact": "1" if args.get("exact") == "1" else ""}


def _where(f, today: date, with_chain: bool = True) -> tuple[str, list]:
    where, a = current_where(today, f["when"])
    for word in fold(f["q"]).split():  # every word must be there, in any order
        if f["exact"]:  # "Tikslus žodis": whole words only ("alus" no longer finds "natūralus")
            where += " AND (' ' || o.name_key || ' ') LIKE ?"
            a.append(f"% {word} %")
        else:
            where += " AND o.name_key LIKE ?"
            a.append(f"%{word}%")
    if with_chain and f["chain"]:
        where += " AND o.chain=?"
        a.append(f["chain"])
    if f["cat"]:
        where += " AND o.category=?"
        a.append(f["cat"])
    if f["disc"]:
        where += " AND (o.discount_pct > 0 OR o.discount_text IS NOT NULL)"
    if f["nocard"]:
        where += " AND o.card=0"
    return where, a


def watched_sql(terms) -> tuple[str, list]:
    """SQL expression: 1 when the offer matches a watch-list term (same rule as `watched`), else 0."""
    if not terms:
        return "0", []
    parts, a = [], []
    for t in terms:
        if t["chain"]:
            parts.append("(instr(o.name_key, ?) > 0 AND o.chain=?)")
            a += [t["term_key"], t["chain"]]
        else:
            parts.append("instr(o.name_key, ?) > 0")
            a.append(t["term_key"])
    return "(CASE WHEN " + " OR ".join(parts) + " THEN 1 ELSE 0 END)", a


def query_offers(conn, args, today: date):
    f = _filters(args)
    try:
        page = max(1, int(args.get("p") or 1))
    except ValueError:
        page = 1
    where, a = _where(f, today)
    base = f"FROM offers o JOIN issues i ON i.id=o.issue_id WHERE {where}"
    total = conn.execute(f"SELECT COUNT(*) {base}", a).fetchone()[0]
    order, oa = SORTS[f["sort"]], []
    if f["top"]:  # "Stebimi viršuje": watched offers first, each group in the chosen order; filters unchanged
        expr, oa = watched_sql(watch_terms(conn))
        order = f"{expr} DESC, {order}"
    rows = conn.execute(f"SELECT o.*, i.title AS issue_title, i.source_url {base} ORDER BY {order}"
                        f" LIMIT {PAGE_SIZE} OFFSET {(page - 1) * PAGE_SIZE}", a + oa).fetchall()
    w2, a2 = _where(f, today, with_chain=False)
    counts = {r[0]: r[1] for r in conn.execute(
        f"SELECT o.chain, COUNT(*) FROM offers o JOIN issues i ON i.id=o.issue_id WHERE {w2} GROUP BY o.chain", a2)}
    return rows, total, page, f, counts


def image_url(img: str | None) -> str | None:
    if not img:
        return None
    if img.startswith(("http://", "https://")):
        return img
    return url_for("offers.image", path=img)


def flags_of(row) -> list[str]:
    try:
        return json.loads(row["flags"] or "[]")
    except ValueError:
        return []


def extra_of(row) -> dict:
    try:
        return json.loads(row["extra"] or "{}")
    except (ValueError, KeyError, IndexError):
        return {}


def logo_url(chain: str) -> str | None:
    from .. import logos
    return url_for("offers.logo", chain=chain) if logos.find(settings(), chain) else None


def ctx():
    return {"CATEGORIES": CATEGORIES, "image_url": image_url, "logo_url": logo_url, "SORT_LT": SORT_LT, "WHEN_LT": WHEN_LT, "flags_of": flags_of, "extra_of": extra_of,
            "today_iso": date.today().isoformat()}


@bp.get("/")
def offers():
    today = date.today()
    with db.session(settings()) as conn:
        rows, total, page, f, counts = query_offers(conn, request.args, today)
        terms = watch_terms(conn)
        leaflets = conn.execute("SELECT COUNT(*) FROM issues WHERE status='parsed' AND (valid_to IS NULL OR valid_to >= ?)",
                                (today.isoformat(),)).fetchone()[0]
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    marks = {r["id"]: watched(r["name_key"], r["chain"], terms) for r in rows}
    return render_template("offers.html", offers=rows, total=total, page=page, pages=pages, f=f, counts=counts,
                           marks=marks, leaflets=leaflets, **ctx())


@bp.get("/logo/<chain>")
def logo(chain):
    from .. import logos
    p = logos.find(settings(), chain) if chain in CHAIN_NAMES else None
    if not p:
        abort(404)
    r = send_from_directory(p.parent, p.name, mimetype=logos.MIME[p.suffix], max_age=3600)
    r.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; img-src data:"
    r.headers["X-Content-Type-Options"] = "nosniff"
    return r


@bp.get("/img/<path:path>")
def image(path):
    d = settings().img_dir
    if ".." in path.split("/"):
        abort(404)
    return send_from_directory(d, path, max_age=7 * 24 * 3600)


@bp.get("/produktas/<int:pid>")
def product(pid):
    with db.session(settings()) as conn:
        p = conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
        if not p:
            abort(404)
        hist = conn.execute("SELECT o.*, i.title AS issue_title, i.number, i.source_url FROM offers o JOIN issues i ON i.id=o.issue_id"
                            " WHERE o.product_id=? ORDER BY COALESCE(o.valid_from, i.first_seen) DESC, o.id DESC", (pid,)).fetchall()
        same = []
        if p["name_key"] and not p["ident"].startswith("~"):
            same = conn.execute("SELECT p.*, (SELECT MIN(o.price) FROM offers o WHERE o.product_id=p.id AND (o.valid_to IS NULL OR o.valid_to>=?))"
                                " AS now_price FROM products p WHERE p.name_key=? AND p.id<>? ORDER BY p.chain",
                                (date.today().isoformat(), p["name_key"], pid)).fetchall()
        terms = watch_terms(conn)
    prices = [h["price"] for h in hist if h["price"] is not None]
    stats = {"min": min(prices) if prices else None, "max": max(prices) if prices else None, "n": len(hist)}
    key_hint = (p["name_key"] or "").split()[0] if p["name_key"] else ""
    return render_template("product.html", p=p, hist=hist, same=same, stats=stats, key_hint=key_hint,
                           is_watched=watched(p["name_key"], p["chain"], terms), **ctx())


@bp.post("/produktas/<int:pid>/kategorija")
def product_category(pid):
    cat = request.form.get("category")
    if cat not in CATEGORIES:
        abort(400)
    kw = (request.form.get("keyword") or "").strip() if request.form.get("learn") == "1" else None
    with db.session(settings()) as conn:
        if not conn.execute("SELECT 1 FROM products WHERE id=?", (pid,)).fetchone():
            abort(404)
        store.set_category(conn, pid, cat, kw)
    flash("Kategorija pakeista." + (f" Raktažodis „{kw}“ įsimintas." if kw else ""), "ok")
    return redirect(url_for("offers.product", pid=pid))


@bp.get("/stebimi")
def watch():
    today = date.today()
    with db.session(settings()) as conn:
        terms = watch_terms(conn)
        where, a = current_where(today, "all")
        rows = conn.execute(f"SELECT o.*, i.title AS issue_title FROM offers o JOIN issues i ON i.id=o.issue_id WHERE {where}"
                            " ORDER BY o.price IS NULL, o.price", a).fetchall()
    hits = {t["id"]: [r for r in rows if t["term_key"] in r["name_key"] and (not t["chain"] or t["chain"] == r["chain"])]
            for t in terms}
    return render_template("watch.html", terms=terms, hits=hits, **ctx())


@bp.post("/stebimi")
def watch_add():
    term = (request.form.get("term") or "").strip()
    chain = request.form.get("chain") or None
    if chain and chain not in CHAIN_NAMES:
        chain = None
    key = fold(term)
    back = request.form.get("back") or url_for("offers.watch")
    if not back.startswith("/") or back.startswith("//"):
        back = url_for("offers.watch")
    if len(key) < 3:
        flash("Įveskite bent 3 raides.", "err")
        return redirect(back)
    with db.session(settings()) as conn:
        with conn:
            conn.execute("INSERT INTO watch(term,term_key,chain,created) VALUES(?,?,?,?) ON CONFLICT(term_key) DO NOTHING",
                         (term, key, chain, db.now_iso()))
    mqtt_refresh()
    flash(f"Stebima: „{term}“.", "ok")
    safe = back.startswith("/") and not back.startswith("//")
    return redirect(back if safe else url_for("offers.watch"))


@bp.post("/stebimi/<int:wid>/salinti")
def watch_delete(wid):
    with db.session(settings()) as conn:
        with conn:
            conn.execute("DELETE FROM watch WHERE id=?", (wid,))
    mqtt_refresh()
    flash("Pašalinta iš stebimų.", "ok")
    return redirect(url_for("offers.watch"))
