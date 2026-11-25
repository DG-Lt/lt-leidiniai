"""Offer pages: Pasiūlymai (current offers), product history, Stebimi (watch list), offer images."""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, send_from_directory, url_for

from .. import CHAIN_NAMES, db, store, watchmatch
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


def watch_terms(conn, include_muted: bool = False) -> list:
    """Watched words; muted ones (Nutildyti) only when asked for (the Stebimi page lists them)."""
    terms = conn.execute("SELECT * FROM watch ORDER BY term").fetchall()
    return terms if include_muted else watchmatch.active(terms)


def watched(name_key: str, chain: str, terms) -> bool:
    return bool(watchmatch.matching_terms(terms, name_key, chain))


def ending_days() -> int:
    return settings().ending_soon_days


def ending_soon(valid_to) -> bool:
    """End date within `ending_soon_days` (today included): highlighted wherever an offer's end date is shown."""
    from ..ha_state import ending_soon as _es
    return ending_days() > 0 and _es(valid_to, date.today(), ending_days())


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
            "top": "1" if args.get("top") == "1" else "", "exact": "1" if args.get("exact") == "1" else "",
            "ending": "1" if args.get("ending") == "1" else "", "stock": "1" if args.get("stock") == "1" else ""}


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
    if f["stock"]:  # "Atsargoms": long-life (or frozen) at a really good price (stock.py)
        from .. import stock
        with db.session(settings()) as c2:
            cond, sa = stock.sql(stock.rules(c2))
        where += " AND " + cond
        a += sa
    if f["ending"]:  # "Besibaigiantys": ends within ending_soon_days (today included)
        where += " AND o.valid_to IS NOT NULL AND o.valid_to >= ? AND o.valid_to <= ?"
        a += [today.isoformat(), (today + timedelta(days=ending_days())).isoformat()]
    return where, a


def watched_sql(terms) -> tuple[str, list]:
    """SQL expression: 1 when the offer matches a watch-list term (same rule as `watched`), else 0."""
    if not terms:
        return "0", []
    parts, a = [], []
    for t in terms:
        p, pa = watchmatch.sql(t)
        parts.append(p)
        a += pa
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
    rows = conn.execute(f"SELECT o.*, i.title AS issue_title, i.source_url, i.files AS issue_files {base} ORDER BY {order}"
                        f" LIMIT {PAGE_SIZE} OFFSET {(page - 1) * PAGE_SIZE}", a + oa).fetchall()
    g_stock(conn, rows)
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
    p = logos.find(settings(), chain)
    # the file's time in the address: a new upload is shown at once instead of the browser's cached copy
    return url_for("offers.logo", chain=chain, v=int(p.stat().st_mtime)) if p else None


def offer_original(o) -> str | None:
    """Offer row (with issue_files) → link to its leaflet page."""
    try:
        return original_link({"id": o["issue_id"], "files": o["issue_files"]}, o["page"])
    except (KeyError, IndexError):
        return None


def g_stock(conn, rows) -> None:
    """Atsargoms badges for these rows (stock.annotate), read by the cards through `stock_badge`."""
    from flask import g

    from .. import stock
    have = getattr(g, "stock_badges", {})
    have.update(stock.annotate(conn, rows))
    g.stock_badges = have


def stock_badge(o) -> str | None:
    from flask import g
    try:
        return getattr(g, "stock_badges", {}).get(o["id"])
    except (KeyError, IndexError, TypeError):
        return None


def ctx():
    return {"CATEGORIES": CATEGORIES, "image_url": image_url, "logo_url": logo_url, "SORT_LT": SORT_LT, "WHEN_LT": WHEN_LT, "flags_of": flags_of, "extra_of": extra_of,
            "offer_original": offer_original, "today_iso": date.today().isoformat(), "ending_soon": ending_soon, "stock_badge": stock_badge,
            "ending_days": ending_days()}


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


def original_link(issue_row, page: int | None) -> str | None:
    """Link to the stored leaflet file at a page (PDF '#page=N', or the page picture) while it is kept
    (keep_pdf_weeks); None when the files are gone."""
    try:
        files = json.loads(issue_row["files"] or "[]")
    except (ValueError, KeyError, IndexError):
        return None
    files = [f for f in files if f.get("path") and Path(f["path"]).exists()]
    if not files:
        return None
    if any(f["name"].lower().endswith(".pdf") for f in files):
        return url_for("offers.original", iid=issue_row["id"]) + (f"#page={page}" if page else "")
    return url_for("offers.original", iid=issue_row["id"], p=page or 1)


@bp.get("/leidinys/<int:iid>/originalas")
def original(iid):
    """The stored leaflet file: the PDF (the browser opens it at '#page=N'), or page picture `p` of a leaflet made
    of pictures (Vynoteka drinks)."""
    from flask import send_file
    with db.session(settings()) as conn:
        r = conn.execute("SELECT files FROM issues WHERE id=?", (iid,)).fetchone()
    if not r:
        abort(404)
    root = settings().pdf_dir.resolve()
    files = [f for f in json.loads(r["files"] or "[]") if f.get("path")]
    files = [f for f in files if Path(f["path"]).resolve().is_relative_to(root) and Path(f["path"]).exists()]
    pdf = next((f for f in files if f["name"].lower().endswith(".pdf")), None)
    if pdf:
        return send_file(pdf["path"], mimetype="application/pdf", download_name=pdf["name"], max_age=3600)
    pics = sorted((f for f in files if f["name"].lower().endswith((".jpg", ".jpeg", ".png", ".webp"))),
                  key=lambda f: f["name"])
    try:
        n = int(request.args.get("p") or 1)
    except ValueError:
        n = 1
    if not pics or not 1 <= n <= len(pics):
        abort(404)
    return send_file(pics[n - 1]["path"], max_age=3600)


@bp.get("/produktas/<int:pid>")
def product(pid):
    with db.session(settings()) as conn:
        p = conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
        if not p:
            abort(404)
        hist = conn.execute("SELECT o.*, i.title AS issue_title, i.number, i.source_url, i.files AS issue_files"
                            " FROM offers o JOIN issues i ON i.id=o.issue_id"
                            " WHERE o.product_id=? ORDER BY COALESCE(o.valid_from, i.first_seen) DESC, o.id DESC", (pid,)).fetchall()
        originals = {h["id"]: original_link({"id": h["issue_id"], "files": h["issue_files"]}, h["page"]) for h in hist}
        g_stock(conn, hist)
        same = []
        if p["name_key"] and not p["ident"].startswith("~"):
            same = conn.execute("SELECT p.*, (SELECT MIN(o.price) FROM offers o WHERE o.product_id=p.id AND (o.valid_to IS NULL OR o.valid_to>=?))"
                                " AS now_price FROM products p WHERE p.name_key=? AND p.id<>? ORDER BY p.chain",
                                (date.today().isoformat(), p["name_key"], pid)).fetchall()
        terms = watch_terms(conn)
    prices = [h["price"] for h in hist if h["price"] is not None]
    stats = {"min": min(prices) if prices else None, "max": max(prices) if prices else None, "n": len(hist)}
    key_hint = (p["name_key"] or "").split()[0] if p["name_key"] else ""
    desc = next((extra_of(h).get("desc") for h in hist if extra_of(h).get("desc")), None)
    return render_template("product.html", p=p, hist=hist, same=same, stats=stats, key_hint=key_hint, desc=desc,
                           originals=originals, is_watched=watched(p["name_key"], p["chain"], terms), **ctx())


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


VIEWS = {"zodis": "Pagal žodį", "tinklas": "Pagal tinklą"}


@bp.get("/stebimi")
def watch():
    """Stebimi: grouped by watched word (as typed) or by chain – chains with the most watched offers first, each
    offer once even when several words find it (pick the shop to drive to). The view is remembered (cookie)."""
    from flask import make_response
    view = request.args.get("view") or request.cookies.get("stebimi_view") or "zodis"
    if view not in VIEWS:
        view = "zodis"
    today = date.today()
    with db.session(settings()) as conn:
        all_terms = watch_terms(conn, include_muted=True)
        where, a = current_where(today, "all")
        rows = conn.execute(f"SELECT o.*, i.title AS issue_title, i.files AS issue_files FROM offers o JOIN issues i ON i.id=o.issue_id WHERE {where}"
                            " ORDER BY o.price IS NULL, o.price", a).fetchall()
        rows = [r for r in rows if watchmatch.matching_terms(all_terms, r["name_key"], r["chain"])]
        g_stock(conn, rows)
    active = watchmatch.active(all_terms, today)
    # muted words last on Pagal žodį; they do not count in Pagal tinklą
    terms = active + [t for t in all_terms if t not in active]
    hits = {t["id"]: [r for r in rows if watchmatch.matches(t, r["name_key"], r["chain"])] for t in all_terms}
    found = [(r, watchmatch.matching_terms(active, r["name_key"], r["chain"])) for r in rows]
    found = [(r, ts) for r, ts in found if ts]
    by_chain: dict[str, dict] = {}
    for r, ts in found:
        g = by_chain.setdefault(r["chain"], {"chain": r["chain"], "offers": [], "terms": {}})
        g["offers"].append(r)
        for t in ts:
            g["terms"][t["term"]] = g["terms"].get(t["term"], 0) + 1
    chains = sorted(by_chain.values(), key=lambda g: (-len(g["offers"]), CHAIN_NAMES[g["chain"]]))
    resp = make_response(render_template("watch.html", terms=terms, hits=hits, chains=chains, view=view, views=VIEWS,
                                         muted=lambda t: watchmatch.muted(t, today), **ctx()))
    if request.args.get("view") in VIEWS:
        resp.set_cookie("stebimi_view", view, max_age=365 * 86400, samesite="Lax")
    return resp


@bp.post("/stebimi")
def watch_add():
    term = (request.form.get("term") or "").strip()
    chain = request.form.get("chain") or None
    exact = 1 if request.form.get("exact") == "1" else 0
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
            conn.execute("INSERT INTO watch(term,term_key,chain,created,exact) VALUES(?,?,?,?,?) ON CONFLICT(term_key) DO NOTHING",
                         (term, key, chain, db.now_iso(), exact))
    mqtt_refresh()
    flash(f"Stebima: „{term}“{' (tikslus žodis)' if exact else ''}.", "ok")
    safe = back.startswith("/") and not back.startswith("//")
    return redirect(back if safe else url_for("offers.watch"))


@bp.post("/stebimi/<int:wid>/nutildyti")
def watch_mute(wid):
    """Nutildyti for 1–10 weeks; weeks 0 = Atšaukti."""
    try:
        weeks = max(0, min(10, int(request.form.get("weeks") or 0)))
    except ValueError:
        weeks = 0
    until = (date.today() + timedelta(weeks=weeks)).isoformat() if weeks else None
    with db.session(settings()) as conn:
        with conn:
            conn.execute("UPDATE watch SET muted_until=? WHERE id=?", (until, wid))
    mqtt_refresh()
    flash(f"Nutildyta iki {until}." if until else "Nutildymas atšauktas.", "ok")
    return redirect(url_for("offers.watch"))


@bp.post("/stebimi/<int:wid>/tikslus")
def watch_exact(wid):
    """Toggle "Tikslus žodis" of one watched word."""
    exact = 1 if request.form.get("exact") == "1" else 0
    with db.session(settings()) as conn:
        with conn:
            conn.execute("UPDATE watch SET exact=? WHERE id=?", (exact, wid))
    mqtt_refresh()
    return redirect(url_for("offers.watch"))


@bp.post("/stebimi/<int:wid>/salinti")
def watch_delete(wid):
    with db.session(settings()) as conn:
        with conn:
            conn.execute("DELETE FROM watch WHERE id=?", (wid,))
    mqtt_refresh()
    flash("Pašalinta iš stebimų.", "ok")
    return redirect(url_for("offers.watch"))
