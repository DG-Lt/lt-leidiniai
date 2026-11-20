"""What happens after a leaflet is downloaded: parse → crops → store, plus storage clean-up.

Runs inside the low-priority job process. A parse error never triggers a new download: the issue
becomes 'parse_failed' and the next check of the chain parses the stored files again (3 tries).
"""
from __future__ import annotations

import json
import shutil
import time
import traceback
from datetime import date, timedelta
from pathlib import Path

from . import db, store
from .parsers import parse_issue

MAX_PARSE_ATTEMPTS = 3


def after_download(conn, settings, issue_id, info, summary, log) -> None:
    if info.parser == "vision":
        from . import vision
        if not vision.ready(settings):
            with conn:
                conn.execute("UPDATE issues SET status='waiting_parser' WHERE id=?", (issue_id,))
            log.info("%s %s: image-only leaflet, waits for the picture reader (option picture_reader: %s, %s)",
                     info.chain, info.key, settings.picture_reader,
                     vision.read_status(settings).get("message") or "not ready")
            return
    parse_stored(conn, settings, issue_id, info.parser, summary, log)


def parser_of(chain: str) -> str:
    return {"maxima": "maxima", "rimi": "rimi", "silas": "vision", "vynoteka": "vynoteka"}.get(chain, "pdf")


def parse_stored(conn, settings, issue_id: int, parser: str | None, summary: dict, log) -> bool:
    """Parse an issue from its stored files. Returns True when offers were saved."""
    issue = conn.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()
    chain = issue["chain"]
    files = json.loads(issue["files"] or "[]")
    meta = json.loads(issue["meta"] or "{}")
    parser = parser or meta.get("parser") or parser_of(chain)
    ref = date.fromisoformat(issue["valid_from"]) if issue["valid_from"] else date.today()
    t0 = time.monotonic()
    with conn:
        conn.execute("UPDATE issues SET parse_attempts=parse_attempts+1 WHERE id=?", (issue_id,))
    try:
        missing = [f["name"] for f in files if not Path(f["path"]).exists()]
        if missing:
            raise FileNotFoundError(f"stored file(s) missing: {', '.join(missing)}")
        images = {}
        if parser == "vision":
            from . import vision
            if not vision.ready(settings):
                with conn:
                    conn.execute("UPDATE issues SET status='waiting_parser', parse_attempts=parse_attempts-1"
                                 " WHERE id=?", (issue_id,))
                log.info("%s %s: image-only leaflet, the picture reader is not ready", chain, issue["key"])
                return False
            try:
                offers, images = vision.parse_issue(settings, issue, files, log)
            except vision.NoPictures as e:
                with conn:
                    conn.execute("UPDATE issues SET status='waiting_parser', parse_attempts=parse_attempts-1"
                                 " WHERE id=?", (issue_id,))
                log.info("%s %s: %s – still waiting", chain, issue["key"], e)
                return False
        else:
            offers = parse_issue(chain, parser, files, meta, ref, log)
        t_parse = time.monotonic() - t0
        if parser in ("pdf", "catalogue_pdf", "vynoteka"):
            images = render_issue_crops(settings, issue, files, offers, log)
        counts = store.save_offers(conn, issue, offers, images)
        with conn:
            conn.execute("UPDATE issues SET status='parsed', offers=?, parsed_at=?, error=NULL WHERE id=?",
                         (len(offers), db.now_iso(), issue_id))
        entry = {"key": issue["key"], **counts, "images": len(images),
                 "parse_s": round(t_parse, 1), "seconds": round(time.monotonic() - t0, 1)}
        summary.setdefault("parsed", []).append(entry)
        log.info("%s %s: %d offer(s) (%d named, %d priced, %d image(s)) in %.0f s; flags %s",
                 chain, issue["key"], counts["offers"], counts["named"], counts["priced"], len(images),
                 entry["seconds"], counts["flags"] or "–")
        if not offers and parser in ("pdf", "catalogue_pdf", "vynoteka") and not _has_prices(files):
            # award / assortment catalogues without a single price (Lithuania bans alcohol advertising): not a fault
            log.info("%s %s: no prices printed in this leaflet (catalogue) – nothing to list", chain, issue["key"])
        elif not offers:
            summary["warnings"].append(f"{issue['key']}: no offers found (layout changed?)")
            log.warning("%s %s: the parser found no offers", chain, issue["key"])
        elif counts["named"] < 0.8 * counts["offers"]:
            summary["warnings"].append(f"{issue['key']}: only {counts['named']}/{counts['offers']} offers have a name")
        return bool(offers)
    except Exception as e:
        with conn:
            conn.execute("UPDATE issues SET status='parse_failed', error=? WHERE id=?", (f"parse: {e}"[:500], issue_id))
        summary["errors"].append(f"{issue['key']}: parse failed: {e}")
        log.error("%s %s: parse failed: %s", chain, issue["key"], e)
        log.debug(traceback.format_exc())
        return False


def render_issue_crops(settings, issue, files, offers, log) -> dict[int, str]:
    """Crops for PDF offers, rendered page by page per file. Returns {offer index: path relative to img_dir}."""
    from .parsers import pdf_text
    rel = Path(issue["chain"]) / str(issue["id"])
    out_dir = settings.img_dir / rel
    if out_dir.exists():
        shutil.rmtree(out_dir)
    images: dict[int, str] = {}
    for f in files:
        if not f["name"].lower().endswith(".pdf"):
            continue
        idx = [i for i, o in enumerate(offers) if o.extra.get("file") == f["name"]]
        if not idx:
            continue
        sub = [offers[i] for i in idx]
        try:
            names = pdf_text.render_crops(f["path"], sub, out_dir)
        except Exception as e:  # pictures are nice to have; the offers still count
            log.warning("%s %s: crops failed for %s: %s", issue["chain"], issue["key"], f["name"], e)
            continue
        for j, fn in names.items():
            images[idx[j]] = str(rel / fn)
    return images


def retry_parses(conn, settings, chain: str, summary: dict, log) -> None:
    """Issues downloaded but not parsed (crash, parser bug fixed by an update, picture reader now ready):
    parse from the stored files."""
    from . import vision
    states = ("downloaded", "parse_failed", "waiting_parser") if vision.ready(settings) else ("downloaded", "parse_failed")
    rows = conn.execute(f"SELECT id, key, valid_to FROM issues WHERE chain=? AND status IN ({','.join('?' * len(states))})"
                        " AND parse_attempts < ?", (chain, *states, MAX_PARSE_ATTEMPTS)).fetchall()
    for r in rows:
        if r["valid_to"] and r["valid_to"] < date.today().isoformat():
            continue
        log.info("%s %s: parsing the stored files again", chain, r["key"])
        parse_stored(conn, settings, r["id"], None, summary, log)


def housekeep(conn, settings, log, today: date | None = None) -> dict:
    """Delete leaflet files after keep_pdf_weeks and crops after keep_images_weeks (counted from valid_to)."""
    today = today or date.today()
    out = {"pdf_dirs": 0, "img_dirs": 0}
    pdf_before = (today - timedelta(weeks=settings.keep_pdf_weeks)).isoformat()
    img_before = (today - timedelta(weeks=settings.keep_images_weeks)).isoformat()
    for r in conn.execute("SELECT id, chain, key, files, valid_to, last_seen FROM issues").fetchall():
        end = r["valid_to"] or r["last_seen"][:10]
        if end < pdf_before:
            d = settings.pdf_dir / r["chain"] / r["key"].replace("/", "_")
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)
                out["pdf_dirs"] += 1
        if end < img_before:
            d = settings.img_dir / r["chain"] / str(r["id"])
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)
                out["img_dirs"] += 1
                with conn:
                    conn.execute("UPDATE offers SET image=NULL WHERE issue_id=? AND image NOT LIKE 'http%'", (r["id"],))
    if out["pdf_dirs"] or out["img_dirs"]:
        log.info("clean-up: removed %d leaflet folder(s), %d crop folder(s)", out["pdf_dirs"], out["img_dirs"])
    return out


def _has_prices(files: list[dict]) -> bool:
    """Does any stored PDF mention prices (€, Eur, kaina)? The text layer only. The two wine award catalogues of
    2026-11 (IKI, Rimi) have none – names and tasting notes only."""
    import re
    import pdfplumber
    rx = re.compile(r"€|\bEur\b|\bEUR\b|\bkaina\b", re.I)  # a leaflet with prices says so somewhere
    for f in files:
        if not f.get("name", "").lower().endswith(".pdf"):
            continue
        try:
            with pdfplumber.open(f["path"]) as pdf:
                for page in pdf.pages:
                    if rx.search(page.extract_text() or ""):
                        return True
        except Exception:
            return True  # can't tell: keep the warning
    return False
