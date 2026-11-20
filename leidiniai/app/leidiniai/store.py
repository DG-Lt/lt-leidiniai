"""Save parsed offers: one product row per (chain, ident), offers per issue (re-parsing replaces them)."""
from __future__ import annotations

import json
from collections import Counter

from .categories import Classifier
from .db import now_iso
from .parsers import Offer
from .textutil import fold

STABLE_IDS = {"lidl", "rimi"}  # chains whose ext_id is a product code (Maxima's is an offer id)


def product_ident(o: Offer, issue_id: int, seq: int) -> str:
    if o.chain in STABLE_IDS and o.ext_id:
        return f"id:{o.ext_id}"
    key = fold(o.name)
    if not key or "weak_name" in o.flags:
        return f"~{issue_id}-{seq}"  # nameless: kept for the picture, not merged with anything
    return key


def upsert_product(conn, o: Offer, ident: str, name_key: str, image: str | None, now: str, clf: Classifier) -> tuple[int, str]:
    r = conn.execute("SELECT id, category, category_locked FROM products WHERE chain=? AND ident=?",
                     (o.chain, ident)).fetchone()
    if r and r["category_locked"]:
        cat, src = r["category"], "user"
    else:
        cat, src = clf.classify(o.chain, o.name, o.ext_category)
    if r:
        conn.execute("UPDATE products SET name=CASE WHEN ?<>'' THEN ? ELSE name END, name_key=CASE WHEN ?<>'' THEN ? ELSE name_key END,"
                     " quantity=COALESCE(?,quantity), category=?, category_source=?, image=COALESCE(?,image), last_seen=? WHERE id=?",
                     (o.name, o.name, name_key, name_key, o.quantity, cat, src, image, now, r["id"]))
        return r["id"], cat
    cur = conn.execute("INSERT INTO products(chain,ident,name,name_key,quantity,category,category_source,image,first_seen,last_seen)"
                       " VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (o.chain, ident, o.name, name_key, o.quantity, cat, src, image, now, now))
    return cur.lastrowid, cat


def save_offers(conn, issue, offers: list[Offer], images: dict[int, str] | None = None) -> dict:
    """Replace the issue's offers. `images`: index in offers → stored image (relative crop path).
    Returns counts for the run summary."""
    images = images or {}
    clf = Classifier(conn)
    now = now_iso()
    flags = Counter()
    cats = Counter()
    with conn:
        conn.execute("DELETE FROM offers WHERE issue_id=?", (issue["id"],))
        for seq, o in enumerate(offers):
            key = fold(o.name)
            ident = product_ident(o, issue["id"], seq)
            image = images.get(seq) or o.image_url
            pid, cat = upsert_product(conn, o, ident, key, image, now, clf)
            vf = o.valid_from.isoformat() if o.valid_from else issue["valid_from"]
            vt = o.valid_to.isoformat() if o.valid_to else issue["valid_to"]
            extra = dict(o.extra)
            if o.bbox:
                extra["bbox"] = o.bbox
            conn.execute(
                "INSERT INTO offers(issue_id,product_id,chain,seq,page,kind,name,name_key,price,old_price,discount_pct,"
                "discount_text,unit_price,unit,quantity,card,card_text,valid_from,valid_to,category,ext_id,ext_category,"
                "image,flags,extra) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (issue["id"], pid, o.chain, seq, o.page, o.kind, o.name, key, o.price, o.old_price, o.discount_pct,
                 o.discount_text, o.unit_price, o.unit, o.quantity, int(o.card), o.card_text, vf, vt, cat,
                 o.ext_id, o.ext_category, image, json.dumps(o.flags), json.dumps(extra, ensure_ascii=False)))
            flags.update(o.flags)
            cats[cat] += 1
    return {"offers": len(offers), "flags": dict(flags), "categories": dict(cats),
            "named": sum(1 for o in offers if o.name), "priced": sum(1 for o in offers if o.price is not None)}


def recategorise(conn, product_id: int | None = None) -> int:
    """Re-run the classifier on unlocked products (after the dictionary changed) and copy to their offers."""
    clf = Classifier(conn)
    q = "SELECT p.id, p.chain, p.name, p.category, (SELECT ext_category FROM offers o WHERE o.product_id=p.id" \
        " ORDER BY o.id DESC LIMIT 1) AS ext FROM products p WHERE p.category_locked=0"
    args: tuple = ()
    if product_id:
        q += " AND p.id=?"
        args = (product_id,)
    n = 0
    with conn:
        for r in conn.execute(q, args).fetchall():
            cat, src = clf.classify(r["chain"], r["name"], r["ext"])
            if cat != r["category"]:
                n += 1
            conn.execute("UPDATE products SET category=?, category_source=? WHERE id=?", (cat, src, r["id"]))
            conn.execute("UPDATE offers SET category=? WHERE product_id=?", (cat, r["id"]))
    return n


def set_category(conn, product_id: int, category: str, keyword: str | None = None) -> None:
    """User correction from the panel. Optionally teach the dictionary a keyword."""
    with conn:
        conn.execute("UPDATE products SET category=?, category_source='user', category_locked=1 WHERE id=?",
                     (category, product_id))
        conn.execute("UPDATE offers SET category=? WHERE product_id=?", (category, product_id))
        k = fold(keyword) if keyword else ""
        if k:
            conn.execute("INSERT INTO category_keywords(keyword_key,category,source,created) VALUES(?,?,'user',?)"
                         " ON CONFLICT(keyword_key) DO UPDATE SET category=excluded.category, source='user'",
                         (k, category, now_iso()))
    # every correction is also an example for similar names (category learning): sort the rest again
    recategorise(conn)


CATEGORIES_VERSION = 2  # bump when the classifier changes: unlocked products are sorted again once at start


def recategorise_if_changed(conn, log) -> None:
    from .db import kv_get, kv_set
    if kv_get(conn, "categories_version", 1) >= CATEGORIES_VERSION:
        return
    n = recategorise(conn)
    kv_set(conn, "categories_version", CATEGORIES_VERSION)
    log.info("Categories: classifier updated, %d product(s) moved to another category", n)
