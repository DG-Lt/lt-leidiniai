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
        # picture leaflets are never read inside a chain check (hours with Ollama): they wait for the picture
        # reading after the night's checks, or for "Skaityti paveikslėlius dabar"
        from . import vision
        with conn:
            conn.execute("UPDATE issues SET status='waiting_parser' WHERE id=?", (issue_id,))
        log.info("%s %s: image-only leaflet, waits for the picture reading (%s)", info.chain, info.key,
                 "at night" if vision.ready(settings) else
                 f"picture_reader: {settings.picture_reader}, {vision.read_status(settings).get('message') or 'not ready'}")
        return
    parse_stored(conn, settings, issue_id, info.parser, summary, log)


def issue_parser(row) -> str:
    try:
        meta = json.loads(row["meta"] or "{}")
    except ValueError:
        meta = {}
    return meta.get("parser") or parser_of(row["chain"])


def picture_issues(conn, issue_id: int | None = None) -> list:
    """Image-only leaflets waiting for the picture reader (or whose reading failed, up to 3 tries), oldest first."""
    rows = conn.execute("SELECT * FROM issues WHERE (status IN ('waiting_parser','parse_failed')"
                        "   OR (status='parsed' AND (json_extract(meta, '$.reread') OR json_extract(meta, '$.failed_pages') IS NOT NULL)))"
                        " AND parse_attempts < ? AND (valid_to IS NULL OR valid_to >= ?) ORDER BY id",
                        (MAX_PARSE_ATTEMPTS, date.today().isoformat())).fetchall()
    rows = [r for r in rows if issue_parser(r) == "vision"]
    return [r for r in rows if issue_id is None or r["id"] == issue_id]


def request_reread(conn, issue_id: int) -> bool:
    """"Skaityti iš naujo": forget the saved page results of a picture leaflet and read it at the next picture
    reading. Its offers stay visible until the new reading is saved."""
    r = conn.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()
    if not r or issue_parser(r) != "vision" or r["status"] not in ("parsed", "parse_failed", "waiting_parser"):
        return False
    meta = json.loads(r["meta"] or "{}")
    if r["status"] == "parsed":
        meta["reread"] = True
    with conn:
        conn.execute("DELETE FROM vision_pages WHERE issue_id=?", (issue_id,))
        conn.execute("UPDATE issues SET parse_attempts=0, meta=?, status=CASE WHEN status='parse_failed'"
                     " THEN 'waiting_parser' ELSE status END WHERE id=?", (json.dumps(meta, ensure_ascii=False), issue_id))
    return True


def parser_of(chain: str) -> str:
    return {"maxima": "maxima", "rimi": "rimi", "silas": "vision", "vynoteka": "vynoteka"}.get(chain, "pdf")


def parse_stored(conn, settings, issue_id: int, parser: str | None, summary: dict, log,
                 progress=lambda page, pages: None) -> bool:
    """Parse an issue from its stored files. Returns True when offers were saved. `progress(page, pages)`: picture
    leaflets report each page."""
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
                failed_pages: list[int] = []
                offers, images = vision.parse_issue(settings, issue, files, log, conn=conn, progress=progress,
                                                    failed_pages=failed_pages)
                meta.pop("failed_pages", None)
                if failed_pages:
                    meta["failed_pages"] = failed_pages
                    summary["warnings"].append(f"{issue['key']}: page(s) {', '.join(map(str, failed_pages))} not read")
            except vision.NoPictures as e:
                with conn:
                    conn.execute("UPDATE issues SET status='waiting_parser', parse_attempts=parse_attempts-1"
                                 " WHERE id=?", (issue_id,))
                log.info("%s %s: %s – still waiting", chain, issue["key"], e)
                return False
        else:
            offers = parse_issue(chain, parser, files, meta, ref, log)
            from .vision import offer_dates
            offer_dates(offers, issue)  # an offer's own printed dates (Lidl "11 21–11 22 …"), inside the leaflet's
        t_parse = time.monotonic() - t0
        if parser in ("pdf", "catalogue_pdf", "vynoteka"):
            images = render_issue_crops(settings, issue, files, offers, log)
        counts = store.save_offers(conn, issue, offers, images)
        meta.pop("reread", None)
        meta.pop("reread_error", None)
        with conn:
            conn.execute("UPDATE issues SET status='parsed', offers=?, parsed_at=?, error=NULL, meta=? WHERE id=?",
                         (len(offers), db.now_iso(), json.dumps(meta, ensure_ascii=False), issue_id))
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
        # a failed re-reading keeps the earlier offers on show
        st = "parsed" if meta.get("reread") and issue["status"] == "parsed" else "parse_failed"
        if st == "parsed":
            meta["reread_error"] = str(e)[:300]  # shown on the Leidiniai row and in the problem sensor
        with conn:
            conn.execute("UPDATE issues SET status=?, error=?, meta=? WHERE id=?",
                         (st, f"parse: {e}"[:500], json.dumps(meta, ensure_ascii=False), issue_id))
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
    """Issues downloaded but not parsed (crash, parser bug fixed by an update): parse from the stored files.
    Picture leaflets are left to the picture reading (job.run_pictures)."""
    rows = conn.execute("SELECT * FROM issues WHERE chain=? AND status IN ('downloaded','parse_failed')"
                        " AND parse_attempts < ?", (chain, MAX_PARSE_ATTEMPTS)).fetchall()
    for r in rows:
        if r["valid_to"] and r["valid_to"] < date.today().isoformat():
            continue
        if issue_parser(r) == "vision":
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
