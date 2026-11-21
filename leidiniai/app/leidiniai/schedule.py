"""When to check each chain, and the background runner.

Rule (docs/findings.md): a chain is checked at the nightly check time when
- it has no leaflet yet, or
- the newest leaflet of a series still on the listing ends within WINDOW days (Maxima: 1 day), or
- it was not checked for 7 days (undated catalogues), the last check failed, or a leaflet waits to be downloaded.
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

from . import db, vision

log = logging.getLogger("leidiniai.schedule")
WINDOW = {"maxima": 1}
DEFAULT_WINDOW = 2
MAX_GAP_DAYS = 7
NIGHT_HOURS = 4  # a missed check time is made up only within this many hours


def due(conn, chain: str, today: date, reader_ready: bool = False) -> tuple[bool, str, date]:
    """(due now?, reason, date of the next due night). `reader_ready` is no longer used: picture leaflets are read
    by the picture lane (Runner.request_pictures), not by a chain check."""
    st = conn.execute("SELECT * FROM chain_state WHERE chain=?", (chain,)).fetchone()
    issues = conn.execute("SELECT * FROM issues WHERE chain=? AND status NOT IN ('superseded')", (chain,)).fetchall()
    if not issues or not st or not st["last_check"]:
        return True, "no leaflet yet", today
    last = datetime.fromisoformat(st["last_check"]).date()
    if st["last_error"]:
        return True, "last check failed", today
    if any(i["status"] == "new" and (not i["valid_to"] or i["valid_to"] >= today.isoformat()) for i in issues):
        return True, "a leaflet waits to be downloaded", today
    if any(i["status"] == "downloaded" and i["parse_attempts"] < 3
           and (not i["valid_to"] or i["valid_to"] >= today.isoformat()) for i in issues):
        return True, "a leaflet waits to be read again", today
    listed_at = max(i["last_seen"] for i in issues)[:10]
    ends = []
    for series in {i["series"] for i in issues}:
        rows = [i for i in issues if i["series"] == series and i["last_seen"][:10] == listed_at]
        if not rows:
            continue  # series no longer listed
        newest = max(rows, key=lambda i: (i["valid_to"] or "", i["first_seen"]))
        end = newest["valid_to"]
        end = json.loads(newest["meta"] or "{}").get("min_to") or end  # offers pages: when the first one ends
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
    """Two lanes, each one job at a time as a nice'd child process:
    - checks: chain checks (nightly + manual queue), as before;
    - pictures: reading image-only leaflets with the picture reader (hours on a CPU). It starts only when the checks
      lane is idle (after the night's checks, which may download new picture leaflets) and never blocks a check.
    """

    def __init__(self, settings, on_done=None, on_start=None):
        self.settings = settings
        self.on_done = on_done or (lambda chain, run_id: None)
        self.on_start = on_start or (lambda chain: None)
        self.q: queue.Queue = queue.Queue()
        self.pq: queue.Queue = queue.Queue()
        self.current: str | None = None
        self.pictures: dict | None = None      # {chain, issue_id, title, page, pages} while reading pictures
        self.pictures_waiting = False          # picture reading queued, waits for the checks to finish
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._loop, name="scheduler", daemon=True)
        self._pt = threading.Thread(target=self._picture_loop, name="pictures", daemon=True)

    def start(self):
        self._t.start()
        self._pt.start()
        try:
            self._resume_pictures()
        except Exception:
            log.exception("Could not check for an unfinished picture reading")

    def stop(self):
        self._stop.set()

    def request(self, chain: str, trigger: str = "manual"):
        chains = self.settings.chains if chain == "all" else [chain]
        for c in chains:
            self.q.put((c, trigger))
        log.info("Check requested (%s): %s", trigger, ", ".join(chains))

    def request_pictures(self, trigger: str = "manual", issue_id: int | None = None):
        self.pq.put((trigger, issue_id))
        self.pictures_waiting = True
        log.info("Picture reading requested (%s)%s", trigger, f": leaflet {issue_id}" if issue_id else "")

    def activity(self) -> dict:
        """What runs now, for the HA activity sensor and the Leidiniai page."""
        from . import CHAIN_NAMES
        parts = []
        if self.current:
            parts.append(f"tikrinamas {CHAIN_NAMES.get(self.current, self.current)}")
        p = self.pictures
        if p:
            name = CHAIN_NAMES.get(p.get("chain"), p.get("chain") or "")
            parts.append(f"{name}: puslapis {p['page']}/{p['pages']}" if p.get("page") else f"{name}: paveikslėliai")
        elif self.pictures_waiting:
            parts.append("paveikslėliai laukia eilėje")
        return {"state": "; ".join(parts) or "laukia",
                "checking": CHAIN_NAMES.get(self.current) if self.current else None,
                "queued_checks": self.q.qsize(),
                "pictures": dict(p) if p else None,
                "pictures_queued": bool(self.pictures_waiting and not p)}

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
    def _night_slot(self, now: datetime) -> datetime | None:
        """Tonight's check time, if `now` is within NIGHT_HOURS after it."""
        hh, mm = map(int, self.settings.check_time.split(":"))
        slot = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if now < slot:
            slot -= timedelta(days=1)
        return slot if now - slot <= timedelta(hours=NIGHT_HOURS) else None

    def _nightly(self):
        now = datetime.now()
        slot = self._night_slot(now)
        if not slot:
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
        if vision.ready(self.settings):  # after the checks: leaflets that wait (also the ones downloaded tonight)
            self.request_pictures("night")

    def _resume_pictures(self):
        """A picture reading cut short by a restart or an update continues at once if it is still night;
        otherwise at the next night (pages already read are kept either way)."""
        if not vision.ready(self.settings) or not self._night_slot(datetime.now()):
            return
        from .pipeline import picture_issues
        with db.session(self.settings) as conn:
            todo = picture_issues(conn)
            started = [r for r in todo if conn.execute("SELECT 1 FROM vision_pages WHERE issue_id=? LIMIT 1",
                                                       (r["id"],)).fetchone()]
        if started:
            log.info("Picture reading was cut short (%s): continuing", ", ".join(r["key"] for r in started))
            self.request_pictures("resume")

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

    def _picture_loop(self):
        while not self._stop.is_set():
            try:
                trigger, issue_id = self.pq.get(timeout=30)
            except queue.Empty:
                continue
            while not self._stop.is_set() and (self.current or not self.q.empty()):
                time.sleep(5)  # the checks first: they are short and may download picture leaflets
            more = []  # requests queued meanwhile: one reading covers all waiting leaflets
            while True:
                try:
                    more.append(self.pq.get_nowait())
                except queue.Empty:
                    break
            if more:
                issue_id = None if issue_id is None or any(i is None or i != issue_id for _, i in more) else issue_id
            self._run_pictures(trigger, issue_id)
            self.pictures_waiting = not self.pq.empty()

    def _spawn(self, args, jl, on_line=None):
        """Run `python -m leidiniai.job <args>` nice'd; relay its log. Returns (exit code, run_id)."""
        cmd = [sys.executable, "-m", "leidiniai.job", *args]
        if shutil.which("ionice"):
            cmd = ["ionice", "-c", "3"] + cmd
        run_id = None
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                             env=child_env(self.settings), preexec_fn=lambda: os.nice(15),
                             cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        for line in p.stdout:
            line = line.rstrip()
            if line.startswith("SUMMARY "):
                run_id = json.loads(line[8:]).get("run_id")
            elif line.startswith("PROGRESS "):
                if on_line:
                    try:
                        on_line(json.loads(line[9:]))
                    except ValueError:
                        pass
            elif line:
                relay(jl, line)
        return p.wait(), run_id

    def _run_pictures(self, trigger, issue_id):
        self.pictures = {"chain": None, "page": None, "pages": None}
        jl = logging.getLogger("leidiniai.job.pictures")
        t0 = time.monotonic()
        args = ["--pictures", "--trigger", trigger] + (["--issue", str(issue_id)] if issue_id else [])

        def on_progress(d):
            self.pictures = d
            try:
                self.on_start(d.get("chain"))  # publish the activity at once
            except Exception:
                log.exception("progress hook failed")

        run_id = None
        try:
            rc, run_id = self._spawn(args, jl, on_progress)
            log.info("picture reading finished (exit %s) in %.0f s", rc, time.monotonic() - t0)
        except Exception:
            log.exception("Could not run the picture reading")
        finally:
            chain = (self.pictures or {}).get("chain")
            self.pictures = None
        try:
            self.on_done(chain, run_id)
        except Exception:
            log.exception("after-run hook failed")

    def _run(self, chain, trigger):
        self.current = chain
        try:
            self.on_start(chain)
        except Exception:
            log.exception("before-run hook failed")
        jl = logging.getLogger(f"leidiniai.job.{chain}")
        t0 = time.monotonic()
        run_id = None
        try:
            rc, run_id = self._spawn([chain, "--trigger", trigger], jl)
            log.info("%s check finished (exit %s) in %.0f s", chain, rc, time.monotonic() - t0)
        except Exception:
            log.exception("Could not run the %s check", chain)
        finally:
            self.current = None
        try:
            self.on_done(chain, run_id)
        except Exception:
            log.exception("after-run hook failed")
