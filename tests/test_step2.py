from datetime import date

from leidiniai import db
from leidiniai.textutil import fold, iso_week_range, parse_range

REF = date(2026, 11, 19)


def test_fold():
    assert fold("Šviežia VIŠČIUKŲ mėsa, 1 kg") == "sviezia visciuku mesa 1 kg"
    assert fold("Tête de Moine – 50 %") == "tete de moine 50 %"


def test_dates():
    assert parse_range("2026.11.12 - 2026.11.25", REF) == (date(2026, 11, 12), date(2026, 11, 25))
    assert parse_range("Kainos galioja 2026 m. lapkričio 18 d. – gruodžio 1 d.", REF) == (date(2026, 11, 18), date(2026, 12, 1))
    assert parse_range("Nuo lapkričio 16 d.", REF) == (date(2026, 11, 16), None)
    assert parse_range("Iki 11.23", REF) == (None, date(2026, 11, 23))
    assert parse_range("Iki 01.04", date(2026, 12, 29)) == (None, date(2027, 1, 4))
    assert parse_range("gruodžio 28 d. – sausio 3 d.", date(2026, 12, 20)) == (date(2026, 12, 28), date(2027, 1, 3))
    assert iso_week_range(2026, 47, 0) == (date(2026, 11, 16), date(2026, 11, 22))  # IKI B47
    assert iso_week_range(2026, 46, 1) == (date(2026, 11, 10), date(2026, 11, 16))  # Rimi Nr. 46


def test_lidl_series():
    from leidiniai.fetchers.lidl import series_of
    assert series_of("maisto-prekiu-pasiulymai-20261116-kw47-pr") == "maisto-prekiu-pasiulymai"
    assert series_of("ne-maisto-prekiu-pasiulymai-20261116-kw47") == "ne-maisto-prekiu-pasiulymai"
    assert series_of("bajoru-kel-6-visoriai-kw47") == "bajoru-kel-6-visoriai"


class FakeHttp:
    def __init__(self, pages):
        self.pages = pages

    def text(self, url, **kw):
        return self.pages[url]

    def json(self, url, **kw):
        return self.pages[url]


def test_norfa_silas_rimi_discover():
    import logging
    from leidiniai.fetchers import norfa, rimi, silas
    lg = logging.getLogger("t")
    h = FakeHttp({
        norfa.Norfa.listing_url: '<div>NORFA Nr. 23 (523)</div><div>2026.11.12 - 2026.11.25</div><a href="/leidiniai/download/1">x</a>',
        silas.Silas.listing_url: '<h4>Leidinys Nr. 23. Kainos galioja 2026 m. lapkričio 18 d. – gruodžio 1 d.</h4>'
                                 '<a href="https://www.silas.lt/wp-content/uploads/2026/11/SILAS_Nr23_2026.pdf">p</a>',
        rimi.Rimi.listing_url: '<a href="https://leidiniai.rimi.lt/2026/weekly/rimi-savaitinis-leidinys-nr-47/">Savaitinis akcijų leidinys Nr. 47 (2026)</a>'
                               '<a href="https://leidiniai.rimi.lt/2026/other/grozio-prekiu-katalogas-nr-12/">GROŽIO prekių katalogas Nr. 12</a>',
    })
    n = norfa.Norfa(h, lg, REF).discover()[0]
    assert (n.key, n.valid_from, n.valid_to) == ("523", date(2026, 11, 12), date(2026, 11, 25))
    s = silas.Silas(h, lg, REF).discover()[0]
    assert (s.key, s.valid_to, s.parser, s.files[0].name) == ("2026-23", date(2026, 12, 1), "vision", "SILAS_Nr23_2026.pdf")
    r = rimi.Rimi(h, lg, REF).discover()
    assert r[0].series == "weekly" and r[0].valid_from == date(2026, 11, 17) and r[0].valid_to == date(2026, 11, 23)
    assert r[1].series == "grozio-prekiu-katalogas" and r[1].valid_to is None


def test_due_rule(settings):
    from leidiniai.schedule import due
    conn = db.open_db(settings)
    assert due(conn, "iki", REF)[0]  # nothing yet
    with conn:
        conn.execute("INSERT INTO issues(chain,key,series,title,valid_from,valid_to,first_seen,last_seen,status)"
                     " VALUES('iki','B47-bazinis_www','bazinis','B47','2026-11-16','2026-11-22',?,?, 'downloaded')",
                     ("2026-11-14T03:30:00+02:00", "2026-11-14T03:30:00+02:00"))
        conn.execute("INSERT INTO chain_state(chain,last_check) VALUES('iki','2026-11-14T03:31:00+02:00')")
    is_due, _, nxt = due(conn, "iki", REF)
    assert not is_due and nxt == date(2026, 11, 20)  # 2 days before Sunday 11-22
    assert due(conn, "iki", date(2026, 11, 20))[0]


def test_leaflets_page(settings):
    from leidiniai.schedule import Runner
    from leidiniai.web import create_app
    db.open_db(settings).close()
    c = create_app(settings, Runner(settings)).test_client()
    r = c.get("/leidiniai")
    assert r.status_code == 200 and "Tikrinti dabar" in r.get_data(as_text=True)
    assert c.post("/tikrinti", data={"chain": "iki"}).status_code == 302
