"""One chain check, run as a low-priority child process: `python -m leidiniai.job <chain> [--trigger X]`.

discover → store/refresh issues → download new ones → parse (pipeline.py) → clean-up. Logs go to stdout; the parent
process relays them into its log. A summary is stored in `runs`.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import traceback
from datetime import date

from . import config, db, fetchers, pipeline
from .http import Http
from .logs import setup_logging, write_run_summary

log = logging.getLogger("leidiniai.job")


LEARNT_META = ("parser",)  # learnt while downloading (Rimi catalogue → catalogue_pdf): the listing does not know it


def merge_meta(stored: str | None, listed: dict) -> dict:
    """The listing's meta replaces the stored one, except keys the download learnt."""
    try:
        old = json.loads(stored or "{}")
    except ValueError:
        old = {}
    out = dict(listed)
    for k in LEARNT_META:
        if k in old and k not in out:
            out[k] = old[k]
    return out


def upsert(conn, info, now) -> tuple[int, bool]:
    r = conn.execute("SELECT id, status, meta FROM issues WHERE chain=? AND key=?", (info.chain, info.key)).fetchone()
    vf = info.valid_from.isoformat() if info.valid_from else None
    vt = info.valid_to.isoformat() if info.valid_to else None
    with conn:
        if r:
            if info.meta.get("listed_only"):
                conn.execute("UPDATE issues SET last_seen=? WHERE id=?", (now, r["id"]))
            else:
                conn.execute("UPDATE issues SET last_seen=?, title=?, series=?, number=COALESCE(?,number),"
                             " valid_from=COALESCE(?,valid_from), valid_to=COALESCE(?,valid_to), meta=? WHERE id=?",
                             (now, info.title, info.series, info.number, vf, vt,
                              json.dumps(merge_meta(r["meta"], info.meta), ensure_ascii=False), r["id"]))
                if vf or vt:  # dates learnt later (IKI 0.4.0 → 0.4.1): offers without own dates follow the leaflet
                    conn.execute("UPDATE offers SET valid_from=COALESCE(valid_from, ?), valid_to=COALESCE(valid_to, ?)"
                                 " WHERE issue_id=?", (vf, vt, r["id"]))
            return r["id"], False
        cur = conn.execute(
            "INSERT INTO issues(chain,key,series,title,number,valid_from,valid_to,source_url,meta,status,first_seen,last_seen)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (info.chain, info.key, info.series, info.title, info.number, vf, vt, info.source_url,
             json.dumps(info.meta, ensure_ascii=False), "new", now, now))
        return cur.lastrowid, True


def run(chain: str, trigger: str, settings) -> dict:
    conn = db.open_db(settings)
    now = db.now_iso()
    today = date.today()
    t0 = time.monotonic()
    with conn:
        run_id = conn.execute("INSERT INTO runs(chain,trigger,started) VALUES(?,?,?)", (chain, trigger, now)).lastrowid
    summary = {"run_id": run_id, "chain": chain, "trigger": trigger, "started": now, "issues_listed": 0,
               "new_issues": [], "downloaded": [], "skipped_expired": [], "warnings": [], "errors": [], "timings": {}}
    http = Http(settings, log)
    status = "ok"
    try:
        known = {r["key"] for r in conn.execute("SELECT key FROM issues WHERE chain=?", (chain,))}
        cls = fetchers.get(chain)
        f = cls(http, log, today, known_keys=known) if chain == "lidl" else cls(http, log, today)
        t = time.monotonic()
        infos = f.discover()
        summary["timings"]["discover_s"] = round(time.monotonic() - t, 1)
        summary["issues_listed"] = len(infos)
        log.info("%s: %d leaflet(s) listed", chain, len(infos))
        if not infos:
            summary["warnings"].append("no leaflet found on the listing page")
            status = "warning"
        for info in infos:
            iid, new = upsert(conn, info, now)
            if new:
                summary["new_issues"].append({"id": iid, "key": info.key, "title": info.title,
                                              "valid_from": str(info.valid_from or ""), "valid_to": str(info.valid_to or "")})
                log.info("%s: new leaflet %s – %s (%s … %s)", chain, info.key, info.title, info.valid_from, info.valid_to)
            row = conn.execute("SELECT * FROM issues WHERE id=?", (iid,)).fetchone()
            if row["status"] not in ("new", "failed") or info.meta.get("listed_only"):
                continue
            if row["status"] == "failed" and row["attempts"] >= 3:
                continue
            if info.valid_to and info.valid_to < today:
                with conn:
                    conn.execute("UPDATE issues SET status='expired' WHERE id=?", (iid,))
                summary["skipped_expired"].append(info.key)
                continue
            t = time.monotonic()
            folder = settings.pdf_dir / chain / info.key.replace("/", "_")
            try:
                files = f.download(info, folder)
                st = "downloaded"
                with conn:
                    conn.execute("UPDATE issues SET files=?, status=?, downloaded_at=?, error=NULL, attempts=attempts+1,"
                                 " meta=? WHERE id=?",  # the fetcher may learn things while downloading (parser)
                                 (json.dumps(files, ensure_ascii=False), st, db.now_iso(),
                                  json.dumps(info.meta, ensure_ascii=False), iid))
                summary["downloaded"].append({"key": info.key, "files": len(files),
                                              "bytes": sum(x["bytes"] for x in files),
                                              "seconds": round(time.monotonic() - t, 1)})
                log.info("%s: downloaded %s (%d file(s), %s bytes)", chain, info.key, len(files),
                         sum(x["bytes"] for x in files))
                pipeline.after_download(conn, settings, iid, info, summary, log)
            except Exception as e:
                status = "error"
                msg = f"{info.key}: {e}"
                summary["errors"].append(msg)
                log.error("%s: download failed for %s: %s", chain, info.key, e)
                log.debug(traceback.format_exc())
                with conn:
                    conn.execute("UPDATE issues SET status='failed', error=?, attempts=attempts+1 WHERE id=?", (str(e)[:500], iid))
        pipeline.retry_parses(conn, settings, chain, summary, log)
        if summary.get("parsed"):  # new shop-categorised products teach the others: sort the unlocked ones again
            from .store import recategorise
            t = time.monotonic()
            moved = recategorise(conn)
            summary["timings"]["recategorise_s"] = round(time.monotonic() - t, 1)
            log.info("%s: categories re-sorted, %d product(s) moved", chain, moved)
        # snapshots of a live offers page (Maxima, Norfa promotions): the newest replaces the older ones
        for info in infos:
            if info.chain == "maxima" or info.meta.get("snapshot"):
                with conn:
                    conn.execute("UPDATE issues SET status='superseded' WHERE chain=? AND series=? AND key<>?"
                                 " AND status NOT IN ('superseded','expired')", (info.chain, info.series, info.key))
    except Exception as e:
        status = "error"
        summary["errors"].append(str(e))
        log.error("%s: check failed: %s", chain, e)
        log.debug(traceback.format_exc())
    finally:
        if status != "error":
            from . import logos
            logos.refresh(settings, chain, http, log)
        http.close()
    try:
        summary["cleanup"] = pipeline.housekeep(conn, settings, log)
    except Exception as e:
        summary["warnings"].append(f"clean-up failed: {e}")
        log.warning("clean-up failed: %s", e)
    if status != "error" and summary["errors"]:  # parse failures are recorded without an exception
        status = "error"
    elif status == "ok" and summary["warnings"]:
        status = "warning"
    summary["http"] = http.stats()
    summary["timings"]["total_s"] = round(time.monotonic() - t0, 1)
    summary["status"] = status
    fin = db.now_iso()
    summary["finished"] = fin
    with conn:
        conn.execute("UPDATE runs SET finished=?, status=?, summary=? WHERE id=?",
                     (fin, status, json.dumps(summary, ensure_ascii=False), run_id))
        conn.execute("INSERT INTO chain_state(chain,last_check,last_ok,last_error,last_run_id) VALUES(?,?,?,?,?)"
                     " ON CONFLICT(chain) DO UPDATE SET last_check=excluded.last_check,"
                     " last_ok=COALESCE(excluded.last_ok, chain_state.last_ok), last_error=excluded.last_error,"
                     " last_run_id=excluded.last_run_id",
                     (chain, fin, fin if status != "error" else None,
                      "; ".join(summary["errors"])[:500] or None, run_id))
    conn.close()
    try:
        write_run_summary(settings, summary)
    except Exception as e:
        log.warning("could not write the run summary file: %s", e)
    log.info("%s: run %d finished – %s (%s s, %d request(s), %d browser page(s))", chain, run_id, status,
             summary["timings"]["total_s"], summary["http"]["requests"], summary["http"]["browser_pages"])
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("chain")
    ap.add_argument("--trigger", default="manual")
    a = ap.parse_args(argv)
    settings = config.load()
    setup_logging(settings, stdout_only=True)
    s = run(a.chain, a.trigger, settings)
    print("SUMMARY " + json.dumps({"run_id": s["run_id"], "status": s["status"]}), flush=True)
    return 0 if s["status"] != "error" else 1


if __name__ == "__main__":
    sys.exit(main())
