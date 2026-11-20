"""0.5.2: Rimi images-only leaflets filed by 0.4.6 are downloaded again; learnt meta survives the listing;
IKI names lose the vertical SUPERKAINA badge letters and the promo sentence."""
import json
from datetime import date, timedelta

from leidiniai import db


def _issue(conn, key, status, meta, valid_to):
    with conn:
        return conn.execute(
            "INSERT INTO issues(chain,key,series,title,valid_to,meta,status,first_seen,last_seen,attempts)"
            " VALUES('rimi',?,?,?,?,?,?,'2026-11-18','2026-11-18',1)",
            (key, key, key, valid_to, json.dumps(meta), status)).lastrowid


def test_migration_retries_rimi_waiting_without_parser(settings):
    conn = db.connect(settings.db_path)
    for sql in db.MIGRATIONS[:4]:
        conn.executescript(sql)
    conn.execute("PRAGMA user_version=4")
    future = (date.today() + timedelta(days=5)).isoformat()
    a = _issue(conn, "alko", "waiting_parser", {"type": "alko"}, future)
    b = _issue(conn, "pics", "waiting_parser", {"type": "x", "parser": "vision"}, future)
    c = _issue(conn, "old", "waiting_parser", {"type": "x"}, "2026-01-01")
    db.migrate(conn)
    st = {r["id"]: (r["status"], r["attempts"]) for r in conn.execute("SELECT * FROM issues")}
    assert st[a] == ("new", 0) and st[b][0] == "waiting_parser" and st[c][0] == "waiting_parser"


def test_new_issue_makes_chain_due(settings):
    from leidiniai import schedule
    conn = db.open_db(settings)
    future = (date.today() + timedelta(days=9)).isoformat()
    _issue(conn, "alko", "new", {}, future)
    with conn:
        conn.execute("INSERT INTO chain_state(chain,last_check) VALUES('rimi',?)", (db.now_iso(),))
    assert schedule.due(conn, "rimi", date.today())[:2] == (True, "a leaflet waits to be downloaded or read")


def test_listing_keeps_learnt_parser():
    from leidiniai.job import merge_meta
    assert merge_meta('{"type": "alko", "parser": "catalogue_pdf"}', {"type": "alko"}) == \
        {"type": "alko", "parser": "catalogue_pdf"}
    assert merge_meta(None, {"type": "weekly"}) == {"type": "weekly"}


def test_iki_name_cleanup():
    from leidiniai.parsers.pdf_text import clean_name
    assert clean_name("Sultys CIDO, 1 l A K I E P R U S") == "Sultys CIDO, 1 l"
    assert clean_name("A N I A K R A E P U S Kava JACOBS, 500 g") == "Kava JACOBS, 500 g"
    assert clean_name("Šokoladas ROSHEN, 90 g Pasiūlymas galioja iki 2026 12 13. "
                      "Nuolaida suteikiama tik pažymėtoms prekėms.") == "Šokoladas ROSHEN, 90 g"
    assert clean_name("Vitaminas C B grupės") == "Vitaminas C B grupės"  # short runs stay
