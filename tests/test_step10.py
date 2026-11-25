"""0.8.1: watch list (all words any order, Tikslus žodis per word, Pagal tinklą view, events only for new
leaflets), Lidl offer dates in front of the name, offers ending soon (highlight + Besibaigiantys filter)."""
import json
from datetime import date, timedelta

import pytest

from leidiniai import db

TODAY = date.today()


def term(t, exact=0, chain=None):
    from leidiniai.textutil import fold
    return {"term": t, "term_key": fold(t), "exact": exact, "chain": chain}


@pytest.mark.parametrize("t,exact,name,chain,hit", [
    ("Natura aliejus", 0, "Saulėgrąžų aliejus NATURA*, 1,5 l", "maxima", True),   # the user's case: any order
    ("Natura aliejus", 0, "OBELIŲ aliejus RAPSŲ", "silas", False),
    ("alus", 0, "Natūralus jogurtas", "iki", True),
    ("alus", 1, "Natūralus jogurtas", "iki", False),                              # Tikslus žodis
    ("alus", 1, "Šviesusis alus ŠVYTURYS, 0,5 l", "iki", True),
    ("aliejus natura", 1, "Saulėgrąžų aliejus NATURA*, 1,5 l", "rimi", True),
])
def test_watch_words_any_order(t, exact, name, chain, hit):
    from leidiniai import watchmatch
    from leidiniai.textutil import fold
    assert watchmatch.matches(term(t, exact), fold(name), chain) is hit


def test_watch_chain_limit_and_sql(settings):
    from leidiniai import store, watchmatch
    from leidiniai.parsers import Offer, finish
    from leidiniai.textutil import fold
    assert not watchmatch.matches(term("Natura aliejus", chain="rimi"), fold("aliejus NATURA"), "maxima")
    conn = db.open_db(settings)
    with conn:
        iid = conn.execute("INSERT INTO issues(chain,key,series,title,first_seen,last_seen,status)"
                           " VALUES('maxima','k','s','t','x','x','parsed')").lastrowid
    issue = conn.execute("SELECT * FROM issues WHERE id=?", (iid,)).fetchone()
    store.save_offers(conn, issue, [finish(Offer(chain="maxima", name=n, price=1)) for n in
                                    ("Saulėgrąžų aliejus NATURA*, 1,5 l", "Natūralus jogurtas", "Alus GUBERNIJA")])
    for t, want in ((term("natura aliejus"), 1), (term("alus"), 2), (term("alus", 1), 1)):
        sql, a = watchmatch.sql(t)
        assert conn.execute(f"SELECT COUNT(*) FROM offers o WHERE {sql}", a).fetchone()[0] == want, t


def seed(conn, offers, chain="iki", first_seen="2026-11-21T03:30:00+02:00"):
    from leidiniai import store
    from leidiniai.parsers import Offer, finish
    with conn:
        iid = conn.execute("INSERT INTO issues(chain,key,series,title,valid_to,first_seen,last_seen,status,parsed_at)"
                           " VALUES(?,?,?,?,?,?,'x','parsed',?)",
                           (chain, f"k{chain}{first_seen}", "s", f"{chain} leidinys", "2099-01-01", first_seen,
                            first_seen)).lastrowid
    issue = conn.execute("SELECT * FROM issues WHERE id=?", (iid,)).fetchone()
    store.save_offers(conn, issue, [finish(Offer(chain=chain, page=n + 1, **o)) for n, o in enumerate(offers)])
    return iid


def test_watch_page_views(settings):
    from leidiniai.schedule import Runner
    from leidiniai.web import create_app
    conn = db.open_db(settings)
    seed(conn, [{"name": "Saulėgrąžų aliejus NATURA, 1,5 l", "price": 339}], "maxima")
    seed(conn, [{"name": "Saulėgrąžų aliejus NATURA, 1,5l", "price": 349}, {"name": "Sviestas ROKIŠKIO", "price": 119},
                {"name": "Sviestas PILOS", "price": 99}], "rimi")
    c = create_app(settings, Runner(settings)).test_client()
    c.post("/stebimi", data={"term": "Natura aliejus"})
    c.post("/stebimi", data={"term": "sviestas", "exact": "1"})
    html = c.get("/stebimi").get_data(as_text=True)
    assert "Natura aliejus" in html and "– 2 pasiūl." in html  # 0.8.0 found 0
    r = c.get("/stebimi?view=tinklas")
    html = r.get_data(as_text=True)
    assert "stebimi_view=tinklas" in r.headers.get("Set-Cookie", "")
    assert html.index("<summary>Rimi") < html.index("<summary>Maxima") and "– 3 pasiūl." in html and "sviestas (2)" in html
    assert "Pagal tinklą" in c.get("/stebimi").get_data(as_text=True)  # remembered (cookie)
    wid = conn.execute("SELECT id FROM watch WHERE term='sviestas'").fetchone()[0]
    assert conn.execute("SELECT exact FROM watch WHERE id=?", (wid,)).fetchone()[0] == 1
    c.post(f"/stebimi/{wid}/tikslus", data={})
    assert conn.execute("SELECT exact FROM watch WHERE id=?", (wid,)).fetchone()[0] == 0


def test_watch_events_only_for_new_leaflets_and_stable_keys(settings):
    from leidiniai import ha_state, store
    from leidiniai.parsers import Offer, finish
    conn = db.open_db(settings)
    with conn:
        conn.execute("INSERT INTO watch(term,term_key,created) VALUES('sviestas','sviestas','2026-11-20T10:00:00+02:00')")
    old = seed(conn, [{"name": "Sviestas ROKIŠKIO", "price": 119}], "iki", "2026-11-19T03:30:00+02:00")
    new = seed(conn, [{"name": "Sviestas PILOS", "price": 99}], "lidl", "2026-11-21T03:30:00+02:00")
    hits = ha_state.watch_hits(conn, TODAY)
    assert [h["chain"] for h in hits] == ["lidl"]
    k = hits[0]["key"]
    # the leaflet read again with a better name (0.8.0 announced these again): same key
    issue = conn.execute("SELECT * FROM issues WHERE id=?", (new,)).fetchone()
    store.save_offers(conn, issue, [finish(Offer(chain="lidl", page=1, name="PILOS Sviestas 82 %", price=99))])
    assert [h["key"] for h in ha_state.watch_hits(conn, TODAY)] == [k]
    store.save_offers(conn, conn.execute("SELECT * FROM issues WHERE id=?", (old,)).fetchone(),
                      [finish(Offer(chain="iki", page=1, name="Sviestas ROKIŠKIO 82 %", price=119))])
    assert len(ha_state.watch_hits(conn, TODAY)) == 1


def test_lidl_dates_in_front_of_the_name():
    from leidiniai.parsers.pdf_text import LIDL_DATES, LIDL_DATES_AGAIN
    from leidiniai.parsers import Offer
    from leidiniai.vision import offer_dates
    name = "11 21–11 22 PILOS / POLMLEK SVIESTAS 82 % riebumo Nuo šeštadienio, 11 21, iki 11 22"
    m = LIDL_DATES.match(name)
    rest = LIDL_DATES_AGAIN.sub("", name[m.end():]).strip()
    assert rest == "PILOS / POLMLEK SVIESTAS 82 % riebumo"
    o = Offer(chain="lidl", name=rest, extra={"dates_text": f"{m.group(1)}.{m.group(2)}–{m.group(3)}.{m.group(4)}"})
    offer_dates([o], {"valid_from": "2026-11-16", "valid_to": "2026-11-22"})
    assert (o.valid_from, o.valid_to) == (date(2026, 11, 21), date(2026, 11, 22))


def test_ending_soon_highlight_and_filter(settings):
    from leidiniai import ha_state
    from leidiniai.schedule import Runner
    from leidiniai.web import create_app
    assert settings.ending_soon_days == 3
    assert ha_state.ending_soon((TODAY + timedelta(days=3)).isoformat(), TODAY, 3)
    assert not ha_state.ending_soon((TODAY + timedelta(days=4)).isoformat(), TODAY, 3)
    assert not ha_state.ending_soon((TODAY - timedelta(days=1)).isoformat(), TODAY, 3)
    conn = db.open_db(settings)
    seed(conn, [{"name": "Pienas DVARO greitai", "price": 99, "valid_to": TODAY + timedelta(days=1)},
                {"name": "Kefyras ilgai", "price": 89, "valid_to": TODAY + timedelta(days=10)}])
    c = create_app(settings, Runner(settings)).test_client()
    html = c.get("/").get_data(as_text=True)
    assert html.count('class="ending"') == 1 and "Besibaigiantys" in html
    html = c.get("/?ending=1").get_data(as_text=True)
    assert "Pienas DVARO greitai" in html and "Kefyras ilgai" not in html
    pid = conn.execute("SELECT product_id FROM offers WHERE name='Pienas DVARO greitai'").fetchone()[0]
    assert 'class="ending"' in c.get(f"/produktas/{pid}").get_data(as_text=True)
    with conn:
        conn.execute("INSERT INTO watch(term,term_key,created) VALUES('pienas','pienas','2000-01-01')")
    n, attrs = ha_state.watched_on_sale(conn, TODAY, ending_days=3)
    assert n == 1 and attrs["items"][0]["ending_soon"] and attrs["ending_soon"] == 1
    assert attrs["by_chain"] == {"IKI": 1}


def test_ending_soon_off(settings):
    from leidiniai.schedule import Runner
    from leidiniai.web import create_app
    settings.ending_soon_days = 0
    conn = db.open_db(settings)
    seed(conn, [{"name": "Pienas DVARO", "price": 99, "valid_to": TODAY}])
    html = create_app(settings, Runner(settings)).test_client().get("/").get_data(as_text=True)
    assert 'class="ending"' not in html and "Besibaigiantys" not in html
