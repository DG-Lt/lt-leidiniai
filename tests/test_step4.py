"""Step 4: rotating log files, per-run summaries, the "Atsisiųsti žurnalus" zip."""
import io
import json
import logging
import zipfile

from leidiniai import db, logs


def _reset_logging():
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
        h.close()


def test_file_log_and_rotation(settings, monkeypatch):
    monkeypatch.setattr(logs, "MAX_BYTES", 2000)
    try:
        logs.setup_logging(settings)
        lg = logging.getLogger("leidiniai.test")
        for i in range(200):
            lg.warning("eilutė %03d – Šilas ąčęėįšųūž", i)
        for h in logging.getLogger().handlers:
            h.flush()
    finally:
        _reset_logging()
    files = sorted(p.name for p in settings.log_dir.glob("leidiniai.log*"))
    assert "leidiniai.log" in files and "leidiniai.log.1" in files
    assert len(files) <= logs.BACKUPS + 1
    tail = logs.tail(settings, 5)
    assert len(tail) == 5 and tail[-1].endswith("eilutė 199 – Šilas ąčęėįšųūž") and " WARNING " in tail[-1]


def test_stdout_only_has_no_file(settings):
    try:
        logs.setup_logging(settings, stdout_only=True)
        logging.getLogger("x").warning("child")
    finally:
        _reset_logging()
    assert not (settings.log_dir / "leidiniai.log").exists()


def test_run_summaries_kept_and_pruned(settings, monkeypatch):
    for i in range(1, 8):
        logs.write_run_summary(settings, {"run_id": i, "chain": "iki", "status": "ok"})
    assert [p.name for p in logs.run_summary_files(settings)][:2] == ["000007-iki.json", "000006-iki.json"]
    assert logs.prune_run_summaries(settings, keep=3) == 4
    assert len(logs.run_summary_files(settings)) == 3


def test_zip_contents_and_masking(settings):
    (settings.log_dir / "leidiniai.log").write_text("2026-11-19 03:30:00 INFO    x: password=hunter2 token: abc Šilas\n",
                                                   encoding="utf-8")
    (settings.log_dir / "leidiniai.log.1").write_text("older\n", encoding="utf-8")
    for i in range(1, 26):
        logs.write_run_summary(settings, {"run_id": i, "chain": "norfa", "status": "ok"})
    with db.session(settings) as conn:
        with conn:
            conn.execute("INSERT INTO chain_state(chain,last_check) VALUES('norfa','2026-11-19T03:30:00+02:00')")
    data, name = logs.build_zip(settings)
    assert name.startswith("leidiniai-logs-") and name.endswith(".zip")
    z = zipfile.ZipFile(io.BytesIO(data))
    names = z.namelist()
    assert "logs/leidiniai.log" in names and "logs/leidiniai.log.1" in names and "env.json" in names
    runs = [n for n in names if n.startswith("runs/")]
    assert len(runs) == logs.ZIP_RUNS and "runs/000025-norfa.json" in runs and "runs/000005-norfa.json" not in runs
    log_text = z.read("logs/leidiniai.log").decode("utf-8")
    assert "hunter2" not in log_text and "abc" not in log_text and "Šilas" in log_text
    env = json.loads(z.read("env.json"))
    assert env["schema"] == len(db.MIGRATIONS) and env["options"]["check_time"] == "03:30"
    assert env["chain_state"][0]["chain"] == "norfa" and "offers" in env["rows"]


def test_zip_falls_back_to_db_runs(settings):
    with db.session(settings) as conn:
        with conn:
            conn.execute("INSERT INTO runs(chain,trigger,started,status,summary) VALUES('iki','manual','x','ok','{\"a\":1}')")
    z = zipfile.ZipFile(io.BytesIO(logs.build_zip(settings)[0]))
    assert z.read("runs/000001-iki.json") == b'{"a":1}'


def test_relay_keeps_child_level(caplog):
    from leidiniai.schedule import relay
    jl = logging.getLogger("leidiniai.job.iki")
    with caplog.at_level(logging.DEBUG):
        relay(jl, "2026-11-19 03:30:01 ERROR   leidiniai.job: iki: download failed for B47: 503")
        relay(jl, "2026-11-19 03:30:02 WARNING leidiniai.job: iki: x")
        relay(jl, "Traceback (most recent call last):")
    assert [(r.levelname, r.getMessage()) for r in caplog.records] == [
        ("ERROR", "iki: download failed for B47: 503"), ("WARNING", "iki: x"),
        ("INFO", "Traceback (most recent call last):")]


def test_panel_zip_and_run_page(settings):
    from leidiniai.web import create_app
    with db.session(settings) as conn:
        with conn:
            conn.execute("INSERT INTO runs(chain,trigger,started,finished,status,summary) VALUES"
                         "('lidl','night','2026-11-19T03:30:00+02:00','2026-11-19T03:31:00+02:00','warning',?)",
                         (json.dumps({"warnings": ["tik 10/12 pavadinimų"], "errors": [], "timings": {"total_s": 60}},
                                     ensure_ascii=False),))
    c = create_app(settings).test_client()
    r = c.get("/zurnalai.zip")
    assert r.status_code == 200 and r.mimetype == "application/zip"
    assert "attachment" in r.headers["Content-Disposition"]
    assert "env.json" in zipfile.ZipFile(io.BytesIO(r.data)).namelist()
    html = c.get("/busena").get_data(as_text=True)
    assert "Atsisiųsti žurnalus" in html
    html = c.get("/tikrinimas/1").get_data(as_text=True)
    assert "tik 10/12 pavadinimų" in html and "Lidl" in html
    assert c.get("/tikrinimas/99").status_code == 404
    assert "/tikrinimas/1" in c.get("/leidiniai").get_data(as_text=True)


def test_job_writes_summary_file(settings, monkeypatch):
    """A whole job run with a fake fetcher writes runs/<id>-<chain>.json."""
    from leidiniai import fetchers, job

    class Empty:
        def __init__(self, *a, **k):
            pass

        def discover(self):
            return []

    monkeypatch.setattr(fetchers, "get", lambda chain: Empty)
    s = job.run("norfa", "manual", settings)
    files = logs.run_summary_files(settings)
    assert files and files[0].name == f"{s['run_id']:06d}-norfa.json"
    assert json.loads(files[0].read_text(encoding="utf-8"))["status"] == "warning"
