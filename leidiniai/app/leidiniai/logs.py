"""Logging: stdout (HA "Log" tab) + rotating files in /data/logs, per-run summaries, and the download zip.

- `leidiniai.log` (+ .1 … .10): 5 MB each. The job child process logs to stdout only; the parent relays its lines
  into this log, so one file holds everything in order.
- `runs/<run_id>-<chain>.json`: one summary per chain check (the same JSON as in the `runs` table). The newest
  RUN_FILES_KEEP are kept.
- `build_zip()`: logs + the last ZIP_RUNS summaries + env.json (version, options, schema, counts, disk use).
  Nothing secret is written: options come from Settings.public() and MQTT credentials are never logged.
"""
from __future__ import annotations

import io
import json
import logging
import logging.handlers
import os
import platform
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path

FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
DATEFMT = "%Y-%m-%d %H:%M:%S"
LOG_FILE = "leidiniai.log"
MAX_BYTES = 5 * 1024 * 1024
BACKUPS = 10
RUN_FILES_KEEP = 200
ZIP_RUNS = 20

# Safety net: values that look like credentials are masked in the zip (logs should not contain any).
_SECRET_RE = re.compile(r"(?i)\b(password|passwd|token|secret|authorization)(\"?\s*[:=]\s*\"?)([^\s\",]+)")


def setup_logging(settings, stdout_only: bool = False) -> None:
    root = logging.getLogger()
    root.setLevel(getattr(logging, str(settings.log_level).upper(), logging.INFO))
    for h in list(root.handlers):
        root.removeHandler(h)
        h.close()
    fmt = logging.Formatter(FORMAT, DATEFMT)
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(fmt)
    root.addHandler(h)
    if not stdout_only:
        settings.log_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(settings.log_dir / LOG_FILE, maxBytes=MAX_BYTES,
                                                  backupCount=BACKUPS, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    logging.getLogger("waitress").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


# -- run summaries ------------------------------------------------------------
def runs_dir(settings) -> Path:
    return settings.log_dir / "runs"


def write_run_summary(settings, summary: dict) -> Path:
    d = runs_dir(settings)
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{int(summary['run_id']):06d}-{summary['chain']}.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)
    prune_run_summaries(settings)
    return p


def run_summary_files(settings) -> list[Path]:
    """Newest first (file names start with the zero-padded run id)."""
    d = runs_dir(settings)
    return sorted(d.glob("*.json"), reverse=True) if d.exists() else []


def prune_run_summaries(settings, keep: int = RUN_FILES_KEEP) -> int:
    old = run_summary_files(settings)[keep:]
    for p in old:
        p.unlink(missing_ok=True)
    return len(old)


def tail(settings, lines: int = 200) -> list[str]:
    """Last lines of the current log file (for the Būsena page)."""
    p = settings.log_dir / LOG_FILE
    if not p.exists():
        return []
    with p.open("rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - 256 * 1024))
        data = f.read().decode("utf-8", errors="replace")
    return data.splitlines()[-lines:]


# -- zip ----------------------------------------------------------------------
def mask(text: str) -> str:
    return _SECRET_RE.sub(lambda m: m.group(1) + m.group(2) + "***", text)


def _dir_size(p: Path) -> int:
    n = 0
    if p.exists():
        for root, _, files in os.walk(p):
            for f in files:
                try:
                    n += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
    return n


def environment(settings) -> dict:
    from . import __version__, db
    env = {
        "version": __version__,
        "created": datetime.now().astimezone().isoformat(timespec="seconds"),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "timezone": os.environ.get("TZ") or datetime.now().astimezone().tzname(),
        "options": settings.public(),
        "disk_bytes": {d: _dir_size(settings.data_dir / d) for d in ("pdf", "img", "logs", "cache", "tmp")},
    }
    if settings.db_path.exists():
        env["disk_bytes"]["db"] = settings.db_path.stat().st_size
        try:
            with db.session(settings) as conn:
                env["schema"] = conn.execute("PRAGMA user_version").fetchone()[0]
                env["rows"] = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                               for t in ("issues", "runs", "products", "offers", "watch", "category_keywords")}
                env["issue_status"] = {r[0]: r[1] for r in conn.execute(
                    "SELECT chain || ':' || status, COUNT(*) FROM issues GROUP BY chain, status")}
                env["chain_state"] = [dict(r) for r in conn.execute("SELECT * FROM chain_state ORDER BY chain")]
                env["issues_recent"] = [dict(r) for r in conn.execute(
                    "SELECT id, chain, key, series, title, valid_from, valid_to, status, attempts, parse_attempts,"
                    " offers, error, first_seen, last_seen FROM issues ORDER BY id DESC LIMIT 60")]
        except Exception as e:  # the zip must work even when the database is broken
            env["db_error"] = str(e)
    try:
        import importlib.metadata as md
        env["packages"] = {p: md.version(p) for p in ("flask", "waitress", "requests", "pdfplumber", "pypdfium2",
                                                      "playwright", "paho-mqtt", "Pillow", "beautifulsoup4")
                           if _has_dist(md, p)}
    except Exception:
        pass
    return env


def _has_dist(md, name) -> bool:
    try:
        md.version(name)
        return True
    except md.PackageNotFoundError:
        return False


def build_zip(settings, runs: int = ZIP_RUNS) -> tuple[bytes, str]:
    """(zip bytes, file name). Logs are masked as a safety net; summaries come from files, else from the DB."""
    buf = io.BytesIO()
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        logs = sorted(settings.log_dir.glob(LOG_FILE + "*")) if settings.log_dir.exists() else []
        for p in logs:
            try:
                z.writestr(f"logs/{p.name}", mask(p.read_text(encoding="utf-8", errors="replace")))
            except OSError as e:
                z.writestr(f"logs/{p.name}.error.txt", str(e))
        files = run_summary_files(settings)[:runs]
        for p in files:
            z.write(p, f"runs/{p.name}")
        if not files and settings.db_path.exists():
            _runs_from_db(settings, z, runs)
        z.writestr("env.json", json.dumps(environment(settings), ensure_ascii=False, indent=1, default=str))
    return buf.getvalue(), f"leidiniai-logs-{stamp}.zip"


def _runs_from_db(settings, z, runs):
    from . import db
    try:
        with db.session(settings) as conn:
            for r in conn.execute("SELECT id, chain, summary FROM runs ORDER BY id DESC LIMIT ?", (runs,)):
                z.writestr(f"runs/{r['id']:06d}-{r['chain']}.json", r["summary"] or "{}")
    except Exception as e:
        z.writestr("runs/error.txt", str(e))
