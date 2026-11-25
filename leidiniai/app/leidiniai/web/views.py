"""Panel pages."""
from __future__ import annotations

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

bp = Blueprint("ui", __name__)


def settings():
    return current_app.config["SETTINGS"]


@bp.get("/busena")
def status():
    from .. import logs
    s = settings()
    m = current_app.config.get("MQTT")
    mqtt = "prisijungta" if m and m.connected else "neprisijungta" if m else "išjungta"
    from .. import CHAIN_NAMES, logos
    logo_rows = [{"chain": c, "name": n, "user": bool(logos.find(s, c, "user")), "auto": bool(logos.find(s, c, "auto")),
                  "url": url_for("offers.logo", chain=c, v=int(logos.find(s, c).stat().st_mtime)) if logos.find(s, c) else None}
                 for c, n in CHAIN_NAMES.items()]
    from .. import vision
    reader = vision.read_status(s)
    if s.picture_reader == "none":
        reader = {"state": "off", "message": "išjungtas (parinktis picture_reader)"}
    from .. import db, stock
    with db.session(s) as conn:
        stock_rules = stock.rules(conn)
    return render_template("status.html", options=s.public(), log_tail=logs.tail(s, 150), mqtt=mqtt,
                           run_files=len(logs.run_summary_files(s)), logo_rows=logo_rows, reader=reader,
                           stock_rules=stock_rules)


@bp.post("/atsargoms")
def stock_rules_save():
    """Būsena → Atsargoms: word lists and the "really good price" numbers."""
    from .. import db, stock
    with db.session(settings()) as conn:
        if request.form.get("reset"):
            db.kv_set(conn, "stock_rules", {})
            flash("Atsargoms taisyklės atstatytos į numatytąsias.", "ok")
        else:
            r = stock.save_rules(conn, request.form)
            flash(f"Atsargoms taisyklės išsaugotos: {len(r['long'])} ilgai laikomų, {len(r['frozen'])} šaldytų, "
                  f"{len(r['exclude'])} išimčių žodžių.", "ok")
    return redirect(url_for("ui.status") + "#atsargoms")


@bp.post("/logotipai/<chain>")
def logo_upload(chain):
    """Būsena → Tinklų logotipai: the user's own logo file for a chain (wins over the downloaded one)."""
    from .. import CHAIN_NAMES, logos
    if chain not in CHAIN_NAMES:
        return "", 404
    if request.form.get("remove"):
        logos.remove_upload(settings(), chain)
        flash(f"{CHAIN_NAMES[chain]}: įkeltas logotipas pašalintas.")
    else:
        f = request.files.get("file")
        data = f.read(logos.MAX_BYTES + 1) if f else b""
        try:
            if not data:
                raise ValueError("nepasirinktas failas")
            logos.save_upload(settings(), chain, data, clear_white=request.form.get("white") == "1")
            flash(f"{CHAIN_NAMES[chain]}: logotipas įkeltas.")
        except ValueError as e:
            flash(f"{CHAIN_NAMES[chain]}: {e}.")
    return redirect(url_for("ui.status") + "#logotipai")


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
    from .. import db, vision
    from ..schedule import due
    s = settings()
    runner = current_app.config.get("RUNNER")
    with db.session(s) as conn:
        chains = []
        nxt = runner.next_checks() if runner else {}
        for c in s.chains:
            st = conn.execute("SELECT * FROM chain_state WHERE chain=?", (c,)).fetchone()
            is_due, reason, _ = due(conn, c, date.today(), vision.ready(s))
            chains.append({"chain": c, "state": st, "due": is_due, "reason": reason, "next": nxt.get(c)})
        issues = conn.execute("SELECT * FROM issues ORDER BY COALESCE(valid_to,'9999') DESC, id DESC LIMIT 200").fetchall()
        runs = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 30").fetchall()
        from ..pipeline import issue_parser, picture_issues
        pictures = {i["id"] for i in issues if issue_parser(i) == "vision"}
        pages_read = {r[0]: r[1] for r in conn.execute("SELECT issue_id, COUNT(*) FROM vision_pages GROUP BY issue_id")}
        waiting_pictures = len(picture_issues(conn))
    rereading = {i["id"] for i in issues if i["status"] == "parsed" and '"reread": true' in (i["meta"] or "")}
    return render_template("leaflets.html", chains=chains, issues=issues, runs=runs, status_lt=STATUS_LT,
                           running=runner.current if runner else None,
                           activity=runner.activity() if runner else None, reader_ready=vision.ready(s),
                           pictures=pictures, pages_read=pages_read, rereading=rereading,
                           waiting_pictures=waiting_pictures)


@bp.post("/tikrinti")
def check_now():
    from flask import flash, redirect, request, url_for
    runner = current_app.config.get("RUNNER")
    chain = request.form.get("chain", "all")
    if runner and (chain == "all" or chain in settings().chains):
        runner.request(chain, "manual")
        flash("Tikrinimas įtrauktas į eilę.", "ok")
    return redirect(url_for("ui.leaflets"))


@bp.post("/paveiksleliai")
def read_pictures():
    """"Skaityti paveikslėlius dabar": read the picture leaflets that wait now instead of at night."""
    from .. import vision
    runner = current_app.config.get("RUNNER")
    if not vision.ready(settings()):
        flash("Paveikslėlių skaitytuvas neparuoštas (parinktis picture_reader, žr. Būsena).", "err")
    elif runner:
        runner.request_pictures("manual")
        flash("Paveikslėlių skaitymas įtrauktas į eilę – prasidės, kai baigsis tikrinimai.", "ok")
    return redirect(url_for("ui.leaflets"))


@bp.post("/leidinys/<int:iid>/skaityti-is-naujo")
def reread(iid):
    """"Skaityti iš naujo": mark a picture leaflet to be read again from the first page (e.g. after a reader
    update). Read at night, or at once with "Skaityti paveikslėlius dabar" (0.8.1: no longer starts by itself).
    Its offers stay until the new reading is saved."""
    from .. import db
    from ..pipeline import request_reread
    with db.session(settings()) as conn:
        ok = request_reread(conn, iid)
    if not ok:
        flash("Šio leidinio iš naujo perskaityti negalima.", "err")
    else:
        flash("Pažymėta skaityti iš naujo – bus perskaitytas naktį arba paspaudus „Skaityti paveikslėlius dabar“."
              " Iki tol rodomi seni pasiūlymai.", "ok")
    return redirect(url_for("ui.leaflets"))
