"""Panel pages."""
from __future__ import annotations

from flask import Blueprint, current_app, render_template

bp = Blueprint("ui", __name__)


def settings():
    return current_app.config["SETTINGS"]


@bp.get("/busena")
def status():
    return render_template("status.html", options=settings().public())


STATUS_LT = {"new": "naujas", "downloaded": "atsisiųstas", "parsed": "apdorotas", "parse_failed": "skaitymo klaida",
             "waiting_parser": "laukia skaitytuvo",
             "failed": "klaida", "expired": "pasibaigęs", "superseded": "pakeistas naujesniu"}


@bp.get("/leidiniai")
def leaflets():
    from datetime import date
    from .. import db
    from ..schedule import due
    s = settings()
    runner = current_app.config.get("RUNNER")
    with db.session(s) as conn:
        chains = []
        nxt = runner.next_checks() if runner else {}
        for c in s.chains:
            st = conn.execute("SELECT * FROM chain_state WHERE chain=?", (c,)).fetchone()
            is_due, reason, _ = due(conn, c, date.today())
            chains.append({"chain": c, "state": st, "due": is_due, "reason": reason, "next": nxt.get(c)})
        issues = conn.execute("SELECT * FROM issues ORDER BY COALESCE(valid_to,'9999') DESC, id DESC LIMIT 200").fetchall()
        runs = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 30").fetchall()
    return render_template("leaflets.html", chains=chains, issues=issues, runs=runs, status_lt=STATUS_LT,
                           running=runner.current if runner else None)


@bp.post("/tikrinti")
def check_now():
    from flask import flash, redirect, request, url_for
    runner = current_app.config.get("RUNNER")
    chain = request.form.get("chain", "all")
    if runner and (chain == "all" or chain in settings().chains):
        runner.request(chain, "manual")
        flash("Tikrinimas įtrauktas į eilę.", "ok")
    return redirect(url_for("ui.leaflets"))
