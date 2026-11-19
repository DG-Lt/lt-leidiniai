"""Panel pages."""
from __future__ import annotations

from flask import Blueprint, current_app, render_template

bp = Blueprint("ui", __name__)


def settings():
    return current_app.config["SETTINGS"]


@bp.get("/busena")
def status():
    from .. import logs
    s = settings()
    return render_template("status.html", options=s.public(), log_tail=logs.tail(s, 150),
                           run_files=len(logs.run_summary_files(s)))


@bp.get("/zurnalai.zip")
def logs_zip():
    """"Atsisiųsti žurnalus": log files + last run summaries + env.json, for debugging."""
    from flask import Response
    from .. import logs
    data, name = logs.build_zip(settings())
    return Response(data, mimetype="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


@bp.get("/tikrinimas/<int:run_id>")
def run_detail(run_id):
    import json
    from flask import abort
    from .. import db
    with db.session(settings()) as conn:
        r = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    if not r:
        abort(404)
    summary = json.loads(r["summary"] or "{}")
    return render_template("run.html", run=r, summary=summary,
                           pretty=json.dumps(summary, ensure_ascii=False, indent=2))


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
