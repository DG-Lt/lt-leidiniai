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
                     " VALUES('iki','B47-bazinis_www','bazinis','B47','2026-11-16','2026-11-22',?,?, 'parsed')",
                     ("2026-11-14T03:30:00+02:00", "2026-11-14T03:30:00+02:00"))
        conn.execute("INSERT INTO chain_state(chain,last_check) VALUES('iki','2026-11-14T03:31:00+02:00')")
    is_due, _, nxt = due(conn, "iki", REF)
    assert not is_due and nxt == date(2026, 11, 20)  # 2 days before Sunday 11-22
    assert due(conn, "iki", date(2026, 11, 20))[0]
    # 0.8.0: a leaflet that waits to be read again (stored files, e.g. after a parser update) makes the chain due
    with conn:
        conn.execute("UPDATE issues SET status='downloaded'")
    assert due(conn, "iki", REF)[:2] == (True, "a leaflet waits to be read again")


def test_leaflets_page(settings):
    from leidiniai.schedule import Runner
    from leidiniai.web import create_app
    db.open_db(settings).close()
    c = create_app(settings, Runner(settings)).test_client()
    r = c.get("/leidiniai")
    assert r.status_code == 200 and "Tikrinti dabar" in r.get_data(as_text=True)
    assert c.post("/tikrinti", data={"chain": "iki"}).status_code == 302


IKI_MAIN = """<html><body><header><a href="https://iki.lt/leidiniai/">Leidiniai</a></header>
<div class="page-content publications pb-0"><h1>Akcijų leidiniai</h1>
 <h2 class="title">IKI Kainų leidinys Nr. 47</h2>
 <div class="date-block">Pasiūlymai galioja 2026 11 16 - 2026 11 22</div>
 <div class="mt-4"><a href="https://iki.lt/wp-content/uploads/2026/11/18/IKI-Nr_47-2026-11-16-11-22-d-koreguotas.pdf">ATSIŲSTI LEIDINĮ</a></div>
</div>
<h2>Kiti IKI leidiniai</h2>
<a href="https://iki.lt/leidiniai/specialus-pasiulymai-204/">Specialūs pasiūlymai</a>
<a href="https://iki.lt/leidiniai/specialus-pasiulymai-204/">ŽIŪRĖTI</a>
<a href="https://iki.lt/leidiniai/vynu-kolekcija-2025/">Vynų kolekcija</a>
<footer><a href="https://iki.lt/wp-content/uploads/2025/07/15/Vartotoju-uzklausu-nagrinejimo-tvarka_20180827.pdf">Tvarka</a>
<a href="https://iki.lt/wp-content/uploads/2025/12/15/Socialiniu-tinklu-privatumo-politika.pdf">Politika</a>
<a href="https://iki.lt/leidiniai/nuoroda-apacioje/">x</a></footer></body></html>"""


def iki_sub(title, date_text, pdf):
    return (f'<div class="page-content publications"><h2 class="title">{title}</h2>'
            f'<div class="date-block">{date_text}</div><a href="{pdf}">ATSIŲSTI LEIDINĮ</a></div>'
            '<footer><a href="https://iki.lt/wp-content/uploads/2025/12/15/Socialiniu-tinklu-privatumo-politika.pdf">p</a></footer>')


def test_iki_discover_only_leaflet_blocks():
    import logging
    from leidiniai.fetchers import iki
    h = FakeHttp({
        iki.Iki.listing_url: IKI_MAIN,
        "https://iki.lt/leidiniai/specialus-pasiulymai-204/": iki_sub(
            "Specialūs pasiūlymai IKI parduotuvės klientams", "Pasiūlymai galioja 2026 11 16 - 2026 11 22",
            "https://iki.lt/wp-content/uploads/2026/11/13/A4-Dienos-pasiulymu-palaikymas-W47-Stotis-Vilnius-Ringaudai.pdf"),
        "https://iki.lt/leidiniai/vynu-kolekcija-2025/": iki_sub(
            "IKI apdovanotų vynų ir šampanų kolekcija 2025", "",
            "https://iki.lt/wp-content/uploads/2025/12/12/IKI-apdovanotu-vynu-ir-sampanu-kolekcija-2025.pdf"),
    })
    out = iki.Iki(h, logging.getLogger("t"), REF).discover()
    assert [i.key for i in out] == ["IKI-Nr_47-2026-11-16-11-22-d-koreguotas",
                                    "A4-Dienos-pasiulymu-palaikymas-W47-Stotis-Vilnius-Ringaudai",
                                    "IKI-apdovanotu-vynu-ir-sampanu-kolekcija-2025"]
    m = out[0]
    assert (m.title, m.number, m.series, m.valid_from, m.valid_to) == \
        ("IKI Kainų leidinys Nr. 47", "47", "kainu-leidinys", date(2026, 11, 16), date(2026, 11, 22))
    assert (out[1].series, out[1].number, out[1].valid_to) == \
        ("a4-dienos-pasiulymu-palaikymas-stotis-vilnius-ringaudai", "47", date(2026, 11, 22))
    assert (out[2].valid_from, out[2].valid_to, out[2].number) == (None, None, None)


def test_iki_old_week_code_names():
    import logging
    from leidiniai.fetchers import iki
    page = iki_sub("IKI Kainų leidinys", "", "https://iki.lt/wp-content/uploads/2026/11/13/B47-bazinis_www.pdf")
    i = iki.Iki(FakeHttp({iki.Iki.listing_url: page}), logging.getLogger("t"), REF).discover()[0]
    assert (i.number, i.valid_from, i.valid_to, i.series) == ("47", date(2026, 11, 16), date(2026, 11, 22), "kainu-leidinys")


def test_migration_3_drops_iki_footer_pdfs(tmp_path):
    conn = db.connect(tmp_path / "x.db")
    db.migrate(conn)
    with conn:
        for key in ("Vartotoju-uzklausu-nagrinejimo-tvarka_20180827", "Socialiniu-tinklu-privatumo-politika",
                    "IKI-Nr_47-2026-11-16-11-22-d-koreguotas"):
            conn.execute("INSERT INTO issues(chain,key,series,title,status,offers,first_seen,last_seen)"
                         " VALUES('iki',?,?,?,'parsed',?,'t','t')", (key, key.lower(), key, 0 if "Nr_47" not in key else 445))
        conn.execute("PRAGMA user_version=2")
    assert db.migrate(conn) == len(db.MIGRATIONS)
    assert [r[0] for r in conn.execute("SELECT key FROM issues")] == ["IKI-Nr_47-2026-11-16-11-22-d-koreguotas"]


def test_maxima_discover_uuid_ids():
    import logging
    from pathlib import Path
    from leidiniai.fetchers import maxima
    html = (Path(__file__).parent / "synthetic" / "maxima_synthetic.html").read_text(encoding="utf-8")
    out = maxima.Maxima(FakeHttp({maxima.Maxima.listing_url: html}), logging.getLogger("t"), REF).discover()
    assert len(out) == 1 and out[0].meta["offers"] == 3 and out[0].valid_to == date(2026, 11, 16)
    assert out[0].title == "Pasiūlymai (3) iki 2026-11-16"


def test_rimi_lookups_progress_and_cache(tmp_path, caplog):
    import json
    import logging
    from types import SimpleNamespace
    from leidiniai.fetchers import rimi
    from leidiniai.fetchers.base import IssueInfo

    spots = [{"pageIndex": 0, "x": 0, "y": 0, "width": 1, "height": 1,
              "url": f"https://www.rimi.lt/e-parduotuve/lt/paieska?query={i}"} for i in range(30)]

    class H:
        delay = 0.0
        browser_pages = 0
        asked = []
        browser = SimpleNamespace(render=lambda *a, **k: SimpleNamespace(
            captured=[{"url": "x/Enrichments/1", "body": json.dumps({"enrichments": spots})}]))

        def text(self, url, **kw):
            self.asked.append(url)
            return '<div class="card"><div data-gtm-eec-product=\'{"id": "1", "name": "X", "price": 1.0}\'></div></div>'

    h = H()
    f = rimi.Rimi(h, logging.getLogger("t.rimi"), REF)
    caplog.set_level(logging.INFO, "t.rimi")
    for k in ("a", "b"):
        info = IssueInfo(chain="rimi", key=k, series="weekly", title=k, source_url="https://leidiniai.rimi.lt/x/")
        (tmp_path / k).mkdir()
        f.download(info, tmp_path / k)
    assert len(h.asked) == 30  # the second leaflet's identical spots come from the cache
    assert "e-shop lookups 25/30" in caplog.text and "(0 new)" in caplog.text
    assert len(json.loads((tmp_path / "b" / "eshop.json").read_text())) == 30


def test_rimi_catalogue_without_product_links_waits_for_picture_reader(tmp_path):
    import json
    import logging
    from types import SimpleNamespace
    from leidiniai.fetchers import rimi
    from leidiniai.fetchers.base import IssueInfo
    for captured in ([], [{"url": "x/Enrichments/1", "body": json.dumps({"enrichments": [
            {"pageIndex": 0, "url": "https://www.rimi.lt/vynai"}]})}]):
        h = SimpleNamespace(delay=0, browser_pages=0,
                            browser=SimpleNamespace(render=lambda *a, c=captured, **k: SimpleNamespace(captured=c)))
        info = IssueInfo(chain="rimi", key="2026/alko/x", series="x", title="x", source_url="https://leidiniai.rimi.lt/x/",
                         parser="rimi")
        d = tmp_path / str(len(captured))
        files = rimi.Rimi(h, logging.getLogger("t"), REF).download(info, d)
        assert info.parser == "vision" and [f["name"] for f in files] == ["enrichments.json"]


NORFA_PROMO = """<div class="c-discount-item"><img src="/assets/Uploads/Offers/Eserys.jpg">
<div class="c-discount-item__details"><a href="/akciju-puslapiai/akcijos/jurinis-eserys/" class="c-discount-item__title">Jūrinio ešerio pasiūlymas 11 18-11 22 d.</a>
<div class="c-discount-item__description">Didžiausiose parduotuvėse NORFA H, XXL, XL 2026 m. 11 18-11 22 d. &nbsp;žuvies ant ledo skyriuose Atšildytas didysis jūrinis ešerys (skrostas), 1 kg - tik 6,49 Eur.</div></div></div>
<div class="c-discount-item"><div class="c-discount-item__details"><a href="/akciju-puslapiai/akcijos/rivona/" class="c-discount-item__title">SAVAITGALIO 11,20-11,22 d. NUOLAIDA - RIVONA gaminiams</a>
<div class="c-discount-item__description">Savaitgalio 11 20-11 22 d. nuolaida perkantiems su NORFA nuolaidų kortele: - 30% RIVONA gamintojo virtiems, rūkytiems ir vytintiems mėsos gaminiams*. *Nuolaida taikoma kasoje</div></div></div>"""
NORFA_NEWS = """<div class="c-discount-item"><div class="c-discount-item__details"><a href="/akciju-puslapiai/akcijos/gritte/" class="c-discount-item__title">GRITTE žaidimas</a>
<div class="c-discount-item__description">ŽAIDIMAS su GRITE prekėmis! Pirkdami už 4,99 Eur ir daugiau – registruokite kvitą</div></div></div>"""


def test_norfa_promotions_page(tmp_path):
    import logging
    from leidiniai.fetchers import norfa
    from leidiniai.parsers import parse_issue
    N = norfa.Norfa
    h = FakeHttp({N.listing_url: '<div>NORFA Nr. 23 (523)</div><div>2026.11.12 - 2026.11.25</div>',
                  N.PROMOS_URL.format(n=0): NORFA_PROMO, N.PROMOS_URL.format(n=4): NORFA_NEWS,
                  N.PROMOS_URL.format(n=8): "<p>nothing</p>"})
    out = N(h, logging.getLogger("t"), REF).discover()
    assert [i.series for i in out] == ["leidinys", "akcijos"]
    p = out[1]
    assert p.meta["offers"] == 2 and p.meta["snapshot"] and p.valid_to == date(2026, 11, 22)
    assert p.meta["min_to"] == "2026-11-22" and len(p.prefetched) == 2
    files = []
    for name, data in p.prefetched.items():
        (tmp_path / name).write_bytes(data)
        files.append({"name": name, "path": str(tmp_path / name)})
    offers = parse_issue("norfa", p.parser, files, p.meta, REF, logging.getLogger("t"))
    e, r = offers
    assert (e.name, e.price, e.valid_from, e.valid_to, e.card) == \
        ("Atšildytas didysis jūrinis ešerys (skrostas), 1 kg", 649, date(2026, 11, 18), date(2026, 11, 22), False)
    assert e.image_url == "https://www.norfa.lt/assets/Uploads/Offers/Eserys.jpg"
    assert (r.kind, r.discount_pct, r.card, r.name) == \
        ("badge", 30, True, "RIVONA gamintojo virtiems, rūkytiems ir vytintiems mėsos gaminiams")


def test_rimi_catalogue_pdf_from_viewer_button(tmp_path):
    from pathlib import Path
    """A catalogue without product links whose viewer offers the PDF: read as a price catalogue."""
    import json
    import logging
    from types import SimpleNamespace
    from leidiniai.fetchers import rimi
    from leidiniai.fetchers.base import IssueInfo
    pdf = (Path(__file__).parent / "synthetic" / "norfa_synthetic.pdf").read_bytes()  # has prices ("€")
    h = SimpleNamespace(delay=0, browser_pages=0, browser=SimpleNamespace(
        render=lambda *a, **k: SimpleNamespace(captured=[]),
        download_by_button=lambda url, button: (pdf, "Alkoholinių gėrimų katalogas Nr 23.pdf")))
    info = IssueInfo(chain="rimi", key="2026/alko/x", series="x", title="x", source_url="https://leidiniai.rimi.lt/x/",
                     parser="rimi")
    files = rimi.Rimi(h, logging.getLogger("t"), REF).download(info, tmp_path / "d")
    assert info.parser == "catalogue_pdf" and info.meta["parser"] == "catalogue_pdf"
    assert files[0]["name"].endswith(".pdf") and (tmp_path / "d" / files[0]["name"]).exists()
