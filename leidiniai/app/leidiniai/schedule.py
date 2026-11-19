"""When to check each chain, and the background runner.

Rule (docs/findings.md): a chain is checked at the nightly check time when
- it has no leaflet yet, or
- the newest leaflet of a series still on the listing ends within WINDOW days (Maxima: 1 day), or
- it was not checked for 7 days (undated catalogues), or the last check failed.
After a check that finds nothing new the rule stays true, so it is checked again the next night.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import date, datetime, timedelta

from . import db

log = logging.getLogger("leidiniai.schedule")
WINDOW = {"maxima": 1}
DEFAULT_WINDOW = 2
MAX_GAP_DAYS = 7
NIGHT_HOURS = 4  # a missed check time is made up only within this many hours


def due(conn, chain: str, today: date) -> tuple[bool, str, date]:
    """(due now?, reason, date of the next due night)."""
    st = conn.execute("SELECT * FROM chain_state WHERE chain=?", (chain,)).fetchone()
    issues = conn.execute("SELECT * FROM issues WHERE chain=? AND status NOT IN ('superseded')", (chain,)).fetchall()
    if not issues or not st or not st["last_check"]:
        return True, "no leaflet yet", today
    last = datetime.fromisoformat(st["last_check"]).date()
    if st["last_error"]:
        return True, "last check failed", today
    listed_at = max(i["last_seen"] for i in issues)[:10]
    ends = []
    for series in {i["series"] for i in issues}:
        rows = [i for i in issues if i["series"] == series and i["last_seen"][:10] == listed_at]
        if not rows:
            continue  # series no longer listed
        newest = max(rows, key=lambda i: (i["valid_to"] or "", i["first_seen"]))
        end = newest["valid_to"]
        if chain == "maxima":
            end = json.loads(newest["meta"] or "{}").get("min_to") or end
        if end:
            ends.append(date.fromisoformat(end))
    window = WINDOW.get(chain, DEFAULT_WINDOW)
    nxt = last + timedelta(days=MAX_GAP_DAYS)
    if ends:
        nxt = min(nxt, min(ends) - timedelta(days=window))
    nxt = max(nxt, last + timedelta(days=1)) if nxt <= last else nxt
    if today >= nxt:
        return True, ("leaflet ends soon" if ends and today >= min(ends) - timedelta(days=window)
                      else f"not checked for {MAX_GAP_DAYS} days"), today
    return False, "", nxt


_CHILD_LINE = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d (DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+(\S+): (.*)$")


def relay(jl: logging.Logger, line: str) -> None:
    """Log a line of the job process with its own level; the child's timestamp/name prefix is dropped."""
    m = _CHILD_LINE.match(line)
    if m:
        jl.log(getattr(logging, m.group(1)), "%s", m.group(3))
    else:  # tracebacks, library prints
        jl.info("%s", line)


def child_env(settings) -> dict:
    env = dict(os.environ)
    n = str(settings.threads)
    env.update(OMP_NUM_THREADS=n, OPENBLAS_NUM_THREADS=n, MKL_NUM_THREADS=n, PYTHONUNBUFFERED="1")
    return env


class Runner:
    """Runs one chain check at a time as a nice'd child process; nightly scheduling + manual queue."""

    def __init__(self, settings, on_done=None):
        self.settings = settings
        self.on_done = on_done or (lambda chain, run_id: None)
        self.q: queue.Queue = queue.Queue()
        self.current: str | None = None
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._loop, name="scheduler", daemon=True)

    def start(self):
        self._t.start()

    def stop(self):
        self._stop.set()

    def request(self, chain: str, trigger: str = "manual"):
        chains = self.settings.chains if chain == "all" else [chain]
        for c in chains:
            self.q.put((c, trigger))
        log.info("Check requested (%s): %s", trigger, ", ".join(chains))

    def next_checks(self) -> dict[str, str]:
        hh, mm = map(int, self.settings.check_time.split(":"))
        out = {}
        with db.session(self.settings) as conn:
            for c in self.settings.chains:
                is_due, _, d = due(conn, c, date.today())
                if is_due:
                    d = date.today()
                    if datetime.now() >= datetime.combine(d, datetime.min.time()).replace(hour=hh, minute=mm):
                        d += timedelta(days=1)
                out[c] = datetime.combine(d, datetime.min.time()).replace(hour=hh, minute=mm).astimezone().isoformat()
        return out

    # -- internals -----------------------------------------------------------
    def _nightly(self):
        hh, mm = map(int, self.settings.check_time.split(":"))
        now = datetime.now()
        slot = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if now < slot:
            slot -= timedelta(days=1)
        if now - slot > timedelta(hours=NIGHT_HOURS):
            return
        with db.session(self.settings) as conn:
            done = db.kv_get(conn, "last_nightly")
            if done == slot.isoformat():
                return
            db.kv_set(conn, "last_nightly", slot.isoformat())
            todo = []
            for c in self.settings.chains:
                is_due, reason, _ = due(conn, c, now.date())
                if is_due:
                    todo.append(c)
                    log.info("Night check: %s due (%s)", c, reason)
        if not todo:
            log.info("Night check: nothing due")
        for c in todo:
            self.q.put((c, "night"))

    def _loop(self):
        while not self._stop.is_set():
            try:
                self._nightly()
            except Exception:
                log.exception("Scheduler error")
            try:
                chain, trigger = self.q.get(timeout=30)
            except queue.Empty:
                continue
            self._run(chain, trigger)

    def _run(self, chain, trigger):
        self.current = chain
        cmd = [sys.executable, "-m", "leidiniai.job", chain, "--trigger", trigger]
        if shutil.which("ionice"):
            cmd = ["ionice", "-c", "3"] + cmd
        jl = logging.getLogger(f"leidiniai.job.{chain}")
        t0 = time.monotonic()
        run_id = None
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                 env=child_env(self.settings), preexec_fn=lambda: os.nice(15),
                                 cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            for line in p.stdout:
                line = line.rstrip()
                if line.startswith("SUMMARY "):
                    run_id = json.loads(line[8:]).get("run_id")
                elif line:
                    relay(jl, line)
            rc = p.wait()
            log.info("%s check finished (exit %s) in %.0f s", chain, rc, time.monotonic() - t0)
        except Exception:
            log.exception("Could not run the %s check", chain)
        finally:
            self.current = None
        try:
            self.on_done(chain, run_id)
        except Exception:
            log.exception("after-run hook failed")
