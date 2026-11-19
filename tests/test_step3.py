"""Step 3: parsers, schema v2, store, categories, offer pages.

Two kinds of test files:
- tests/synthetic/ (committed, made-up content, built by tests/make_synthetic.py): a Norfa-like PDF page and a
  Maxima-like offers page. Pipeline, store, panel and job tests use these, so CI needs no shop material.
- tests/fixtures/ (NOT committed – shop material): pages of the 2026-11 leaflets with the photos blanked, built
  locally by `python tests/make_fixtures.py <folder with the test files>`. The parser accuracy tests on real pages
  run only when they are there (or LEIDINIAI_FIXTURES points to them); expected values were checked by eye.
Full-file thresholds run only when LEIDINIAI_TESTDATA points to a folder with the full test files.
"""
from __future__ import annotations

import gzip
import json
import logging
import os
import shutil
from datetime import date
from pathlib import Path

import pytest

from leidiniai import db, pipeline, store
from leidiniai.categories import CATEGORIES, Classifier
from leidiniai.parsers import cents, maxima, pdf_text, rimi

FX = Path(os.environ.get("LEIDINIAI_FIXTURES") or Path(__file__).resolve().parent / "fixtures")
SYN = Path(__file__).resolve().parent / "synthetic"
NORFA_SYN = SYN / "norfa_synthetic.pdf"
needs_fx = pytest.mark.skipif(not (FX / "norfa_523_p4.pdf").exists(),
                              reason="real leaflet fixtures not present (local only: tests/make_fixtures.py)")
LOG = logging.getLogger("test")
NAME_KEY = "saltupio saltai rukyta desra 300 g"


def by_name(offers, start):
    hits = [o for o in offers if o.name.startswith(start)]
    assert hits, f"no offer named {start!r}: {[o.name for o in offers]}"
    return hits[0]


def gunzip(name, tmp_path) -> Path:
    out = tmp_path / name.removesuffix(".gz")
    out.write_bytes(gzip.decompress((FX / name).read_bytes()))
    return out


# ---------------------------------------------------------------- money and helpers

def test_cents():
    assert cents("1,99") == 199 and cents("2,49 €") == 249 and cents("4.49") == 449 and cents("12") == 1200
    assert cents("") is None and cents("abc") is None


# ---------------------------------------------------------------- PDF parsers

@pytest.fixture(scope="module")
def iki():
    return pdf_text.parse(FX / "iki_b47_p4-10-24-37.pdf", "iki")


@needs_fx
def test_iki_category_badges(iki):
    p1 = [o for o in iki if o.page == 1]  # leaflet p. 4: eight "-40 % / -50 %" brand offers, no prices
    assert len(p1) == 8 and all(o.kind == "badge" and o.price is None for o in p1)
    assert by_name(p1, "Šampūnui SEBAMED").discount_pct == 50
    assert by_name(p1, "Kosmetikai GARNIER").discount_pct == 40


@needs_fx
def test_iki_name_above_photo_price_below(iki):
    p2 = [o for o in iki if o.page == 2]  # leaflet p. 10
    assert len(p2) == 7
    assert by_name(p2, "Avokadas").price == 49
    assert by_name(p2, "Raudonieji ridikėliai").price == 99
    assert by_name(p2, "IKI mažieji špinatai").price == 99
    assert by_name(p2, "Lietuviški ilgavaisiai agurkai").price == 99
    assert by_name(p2, "BON VIA slyviniai pomidorai").price == 249
    d = by_name(p2, "Šviežių krapų")
    assert (d.price, d.unit_price, d.unit) == (79, 1580, "kg")


@needs_fx
def test_iki_split_badge_digits_and_old_prices(iki):
    p3 = [o for o in iki if o.page == 3]  # leaflet p. 24
    assert len(p3) == 7
    o = by_name(p3, "Kiaulienos dešrelės su kmynais")
    assert (o.price, o.old_price, o.discount_pct) == (299, 599, 50)
    o = by_name(p3, "IKI švieži viščiukų broilerių sparnelių peteliai")
    assert (o.price, o.old_price, o.discount_text) == (179, 349, "-48%")
    assert by_name(p3, "Marinuotas ančiukas").discount_pct == 45


@needs_fx
def test_iki_multibuy(iki):
    p4 = [o for o in iki if o.page == 4]  # leaflet p. 37: "1+1" / "2+1" drawn plus sign
    assert len(p4) == 8
    assert by_name(p4, "Vytinta dešra FUET").discount_text == "1+1"
    assert by_name(p4, "BILLA jogurtinis gėrimas").discount_text == "2+1"
    assert all(not o.name.startswith(("SUTAUPOTE",)) for o in p4)


@pytest.fixture(scope="module")
def lidl():
    return pdf_text.parse(FX / "lidl_kw47_p4-6.pdf", "lidl")


@needs_fx
def test_lidl_text_left_of_price(lidl):
    p2 = [o for o in lidl if o.page == 2]  # leaflet p. 6: bread
    assert len(p2) == 5 and all(o.ext_id for o in p2)
    o = by_name(p2, "DELUXE Kriaušių, figų ir lazdyno riešutų bagetė")
    assert (o.price, o.old_price, o.unit_price, o.quantity) == (299, None, 748, "400 g")  # 7,48 is the unit price
    assert by_name(p2, "PREMIUM Tamsi duona su kalendra").ext_id == "7613360"
    assert by_name(p2, "DELUXE Citrinų ir aguonų keksas").price == 199


@needs_fx
def test_lidl_plus_second_item(lidl):
    p1 = [o for o in lidl if o.page == 1]  # leaflet p. 4
    assert all(o.name for o in p1), "the 'PERKANT 1 VNT.' price must merge into its deal"
    a = by_name(p1, "Žaliasis avokadas")
    assert (a.price, a.card, a.discount_pct, a.extra.get("single_price")) == (45, True, 68, 139)
    s = by_name(p1, "Lietuviški salierų stiebai")
    assert (s.price, s.old_price) == (99, 139)


@needs_fx
def test_norfa(tmp_path):
    offers = pdf_text.parse(FX / "norfa_523_p4.pdf", "norfa")
    assert len(offers) == 13
    o = by_name(offers, "ĄŽUOLYNO šaltai rūkyta dešra")
    assert (o.price, o.old_price, o.discount_pct, o.unit_price) == (199, 299, 33, 765)
    assert by_name(offers, "Vytinta JUBILIEJAUS dešra").price == 319
    assert by_name(offers, "Virtam KLASIKINIAM kumpiui").kind == "badge"


def test_lidl_promotion_pages_skipped():
    meta = {"pages": [{"number": 1, "type": "STANDARD"}, {"number": 2, "type": "PROMOTION"}]}
    assert pdf_text.skip_pages("lidl", meta) == {2}
    assert pdf_text.skip_pages("iki", meta) == set()


@needs_fx
def test_lidl_promotion_page_not_parsed():
    assert [o.page for o in pdf_text.parse(FX / "lidl_kw47_p4-6.pdf", "lidl", skip_pages={2})] == [1] * 6


def test_synthetic_norfa():
    offers = pdf_text.parse(NORFA_SYN, "norfa")
    assert len(offers) == 6
    o = by_name(offers, "ŠALTUPIO šaltai rūkyta dešra")
    assert (o.price, o.old_price, o.discount_pct, o.unit_price) == (249, 349, 29, 830)
    assert by_name(offers, "Pienas ŪKIO").price == 109


def test_synthetic_maxima():
    offers = maxima.parse((SYN / "maxima_synthetic.html").read_text(encoding="utf-8"), date(2026, 11, 12))
    assert len(offers) == 3
    k = by_name(offers, "Kava ŠILAS")
    assert (k.price, k.old_price, k.discount_pct, k.card, k.unit_price, k.valid_to, k.ext_category) == \
        (699, 999, 30, True, 1398, date(2026, 11, 16), "Gėrimai")


def test_crops(tmp_path):
    offers = pdf_text.parse(NORFA_SYN, "norfa")
    names = pdf_text.render_crops(NORFA_SYN, offers, tmp_path)
    assert len(names) == len(offers)
    from PIL import Image
    im = Image.open(tmp_path / names[0])
    assert im.format == "JPEG" and max(im.size) <= 640


# ---------------------------------------------------------------- Maxima, Rimi

@needs_fx
def test_maxima(tmp_path):
    html = gunzip("maxima_pasiulymai.html.gz", tmp_path).read_text(encoding="utf-8")
    offers = maxima.parse(html, date(2026, 11, 12))
    assert len(offers) == 116 and len({o.ext_id for o in offers}) == 116
    m = by_name(offers, "Mandarinai")
    assert (m.price, m.old_price, m.discount_pct, m.valid_to, m.card, m.ext_category) == \
        (149, 249, 40, date(2026, 11, 16), True, "Vaisiai ir daržovės")
    c = by_name(offers, "CITRUSINIAMS VAISIAMS")
    assert (c.kind, c.price, c.discount_pct) == ("badge", None, 20)
    t = by_name(offers, "Negazuotas mineralinis vanduo TICHĖ")
    assert (t.discount_text, t.valid_to, t.unit, t.unit_price) == ("1+1", date(2026, 12, 7), "l", 35)
    assert by_name(offers, "Glaistytas varškės sūrelis MAGIJA").discount_text == "3 vnt. už"
    assert {o.ext_category for o in offers} <= {k[1] for k in __import__("leidiniai.categories").categories.SHOP_MAP if k[0] == "maxima"}


@needs_fx
def test_rimi(tmp_path):
    offers = rimi.parse(gunzip("rimi_nr46_enrichments.json.gz", tmp_path), gunzip("rimi_nr46_eshop.json.gz", tmp_path))
    assert len(offers) == 792 and len({o.ext_id for o in offers}) == 792
    r = by_name(offers, "Saldainiai RAFFAELLO")
    assert (r.price, r.old_price, r.card, r.unit_price, r.unit, r.quantity) == (349, 449, True, 2327, "kg", "150g")
    lt = by_name(offers, "Lietiniai RIMI su varške")
    assert (lt.price, lt.old_price, lt.card, lt.discount_pct) == (287, 359, False, 20)
    assert "unavailable" in by_name(offers, "Ledjūrio menkės").flags
    assert all(o.page and o.page >= 1 for o in offers)


# ---------------------------------------------------------------- categories

def test_categories():
    c = Classifier()
    assert c.keyword("Vytinta kiaulienos dešra su ŽALIAIS PIPIRAIS, 200 g") == "meat_products"
    assert c.keyword("Lietiniai RIMI su varške 4x90g") == "ready_meals"
    assert c.keyword("Pomidorų padažas NATURAL") == "pantry"
    assert c.keyword("Nealk.UTENOS alaus kokt.RADLER, 0,5 l") == "drinks"
    assert c.keyword("Marinuotas ančiukas įdarytas obuoliais 1 kg") == "meat"
    assert c.keyword("DELUXE Kriaušių, figų ir lazdyno riešutų bagetė") == "bakery"
    assert c.classify("rimi", "Natūralus DVARO pienas", "SH-11-2-3") == ("dairy", "shop")
    assert c.classify("rimi", "Kalakutienos faršas RIMI", "SH-9-1-1") == ("meat", "keyword")
    assert c.classify("maxima", "Kažkas visiškai nežinomo", "Pramonės prekės") == ("home", "shop_weak")
    assert c.classify("iki", "Kažkas", None) == ("other", "none")
    assert set(CATEGORIES) >= {v[0] for v in __import__("leidiniai.categories").categories.SHOP_MAP.values()}


# ---------------------------------------------------------------- store + pipeline

def add_issue(conn, chain, key, files, vf="2026-11-16", vt="2099-12-31", status="downloaded"):
    with conn:
        return conn.execute("INSERT INTO issues(chain,key,series,title,valid_from,valid_to,files,status,first_seen,last_seen)"
                            " VALUES(?,?,?,?,?,?,?,?,?,?)",
                            (chain, key, "s", key, vf, vt, json.dumps(files), status, db.now_iso(), db.now_iso())).lastrowid


def pdf_issue(conn, settings, chain="norfa", src=NORFA_SYN, key="523"):
    d = settings.pdf_dir / chain / key
    d.mkdir(parents=True)
    fx = src.name
    shutil.copy(src, d / fx)
    return add_issue(conn, chain, key, [{"name": fx, "path": str(d / fx), "bytes": 1}])


def test_pipeline_parse_store_reparse(settings):
    conn = db.open_db(settings)
    iid = pdf_issue(conn, settings)
    summ = {"warnings": [], "errors": []}
    assert pipeline.parse_stored(conn, settings, iid, None, summ, LOG)
    row = conn.execute("SELECT * FROM issues WHERE id=?", (iid,)).fetchone()
    assert (row["status"], row["offers"]) == ("parsed", 6) and summ["parsed"][0]["images"] == 6
    o = conn.execute("SELECT * FROM offers WHERE name LIKE 'ŠALTUPIO%'").fetchone()
    assert (o["price"], o["old_price"], o["name_key"], o["valid_to"]) == (249, 349, NAME_KEY, "2099-12-31")
    assert (settings.img_dir / o["image"]).exists()
    # user correction survives a re-parse; products are not duplicated
    store.set_category(conn, o["product_id"], "pantry")
    n_products = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    assert pipeline.parse_stored(conn, settings, iid, None, {"warnings": [], "errors": []}, LOG)
    assert conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == n_products
    assert conn.execute("SELECT COUNT(*) FROM offers WHERE issue_id=?", (iid,)).fetchone()[0] == 6
    assert conn.execute("SELECT category FROM offers WHERE name LIKE 'ŠALTUPIO%'").fetchone()[0] == "pantry"


def test_keyword_learning_recategorises(settings):
    conn = db.open_db(settings)
    pipeline.parse_stored(conn, settings, pdf_issue(conn, settings), None, {"warnings": [], "errors": []}, LOG)
    pid = conn.execute("SELECT product_id FROM offers WHERE name LIKE 'Kvietinė duona%'").fetchone()[0]
    store.set_category(conn, pid, "other", keyword="Kvietinė")
    cats = {r[0] for r in conn.execute("SELECT category FROM offers WHERE name_key LIKE 'kvietine%'")}
    assert cats == {"other"}


def test_parse_failure_keeps_files_and_retries(settings):
    conn = db.open_db(settings)
    iid = add_issue(conn, "iki", "B47", [{"name": "B47.pdf", "path": str(settings.pdf_dir / "missing.pdf"), "bytes": 1}])
    summ = {"warnings": [], "errors": []}
    assert not pipeline.parse_stored(conn, settings, iid, None, summ, LOG)
    r = conn.execute("SELECT status, parse_attempts, error FROM issues WHERE id=?", (iid,)).fetchone()
    assert r["status"] == "parse_failed" and r["parse_attempts"] == 1 and "missing" in r["error"] and summ["errors"]
    for _ in range(4):
        pipeline.retry_parses(conn, settings, "iki", {"warnings": [], "errors": []}, LOG)
    assert conn.execute("SELECT parse_attempts FROM issues WHERE id=?", (iid,)).fetchone()[0] == pipeline.MAX_PARSE_ATTEMPTS


def test_housekeep(settings):
    conn = db.open_db(settings)
    iid = add_issue(conn, "norfa", "500", [], vf="2026-01-01", vt="2026-01-14", status="parsed")
    (settings.pdf_dir / "norfa" / "500").mkdir(parents=True)
    (settings.img_dir / "norfa" / str(iid)).mkdir(parents=True)
    out = pipeline.housekeep(conn, settings, LOG, today=date(2026, 3, 20))  # 9.5 weeks later: PDFs go, crops stay
    assert out == {"pdf_dirs": 1, "img_dirs": 0}
    out = pipeline.housekeep(conn, settings, LOG, today=date(2026, 5, 1))
    assert out == {"pdf_dirs": 0, "img_dirs": 1}


def test_migration_from_v1(settings):
    conn = db.connect(settings.db_path)
    with conn:
        conn.executescript(db.MIGRATIONS[0])
        conn.execute("PRAGMA user_version=1")
        conn.execute("INSERT INTO issues(chain,key,series,title,first_seen,last_seen) VALUES('iki','x','s','t','a','a')")
    assert db.migrate(conn) == len(db.MIGRATIONS)
    assert conn.execute("SELECT parse_attempts FROM issues").fetchone()[0] == 0


# ---------------------------------------------------------------- panel

def test_offer_pages(settings, tmp_path):
    from leidiniai.web import create_app
    conn = db.open_db(settings)
    iid = pdf_issue(conn, settings)
    pipeline.parse_stored(conn, settings, iid, None, {"warnings": [], "errors": []}, LOG)
    mx = tmp_path / "mx" / "pasiulymai.html"
    mx.parent.mkdir()
    shutil.copy(SYN / "maxima_synthetic.html", mx)
    mid = add_issue(conn, "maxima", "abc", [{"name": "pasiulymai.html", "path": str(mx), "bytes": 1}], vf="2026-11-12")
    pipeline.parse_stored(conn, settings, mid, None, {"warnings": [], "errors": []}, LOG)
    with conn:  # Maxima's 'Iki 11.16' is in the past for the test clock: move it
        conn.execute("UPDATE offers SET valid_to='2099-01-01' WHERE chain='maxima'")
    c = create_app(settings).test_client()
    t = c.get("/").get_data(as_text=True)
    assert "Rasta: 9" in t and "ŠALTUPIO" in t and "kortel" in t
    t = c.get("/?q=saltupio&chain=norfa").get_data(as_text=True)
    assert "Rasta: 1" in t
    assert "Rasta: 3" in c.get("/?chain=maxima").get_data(as_text=True)
    assert c.get("/?cat=fruit_veg&disc=1&sort=price&p=1").status_code == 200
    pid = conn.execute("SELECT product_id FROM offers WHERE name LIKE 'ŠALTUPIO%'").fetchone()[0]
    t = c.get(f"/produktas/{pid}").get_data(as_text=True)
    assert "Kainų istorija" in t and "3.49 €" in t
    img = conn.execute("SELECT image FROM offers WHERE chain='norfa' LIMIT 1").fetchone()[0]
    assert c.get(f"/img/{img}").mimetype == "image/jpeg"
    assert c.get("/img/../leidiniai.db").status_code == 404
    # watch list
    assert c.post("/stebimi", data={"term": "Šaltai rūkyta", "back": "//evil.example"}).location.endswith("/stebimi")
    t = c.get("/stebimi").get_data(as_text=True)
    assert "Šaltai rūkyta" in t and "ŠALTUPIO" in t
    wid = conn.execute("SELECT id FROM watch").fetchone()[0]
    c.post(f"/stebimi/{wid}/salinti")
    assert conn.execute("SELECT COUNT(*) FROM watch").fetchone()[0] == 0
    # category correction
    assert c.post(f"/produktas/{pid}/kategorija", data={"category": "fish"}).status_code == 302
    assert conn.execute("SELECT category, category_locked FROM products WHERE id=?", (pid,)).fetchone()[:] == ("fish", 1)
    assert c.post(f"/produktas/{pid}/kategorija", data={"category": "nope"}).status_code == 400


# ---------------------------------------------------------------- full files (optional)

FULL = os.environ.get("LEIDINIAI_TESTDATA")


@pytest.mark.skipif(not FULL, reason="LEIDINIAI_TESTDATA not set")
@pytest.mark.parametrize("name,chain,minimum,named", [
    ("MAISTO-PREKIU-PASIULYMAI-Nuo-lapkricio-16-d-00.pdf", "lidl", 220, 0.97),
    ("Norfa523-Web2.pdf", "norfa", 330, 0.95),
    ("B47-bazinis_www.pdf", "iki", 420, 0.92),
])
def test_full_pdf(name, chain, minimum, named):
    offers = pdf_text.parse(Path(FULL) / name, chain)
    assert len(offers) >= minimum
    assert sum(1 for o in offers if o.name and "weak_name" not in o.flags) >= named * len(offers)


# ---------------------------------------------------------------- job → pipeline wiring

def test_job_downloads_and_parses(settings, monkeypatch):
    from leidiniai import fetchers, job
    from leidiniai.fetchers.base import Fetcher, IssueInfo

    class FakeNorfa(Fetcher):
        chain = "norfa"

        def discover(self):
            return [IssueInfo(chain="norfa", key="523", series="norfa", title="NORFA Nr. 23 (523)", number="23 (523)",
                              valid_from=date(2026, 11, 12), valid_to=date(2099, 11, 25), parser="pdf",
                              prefetched={"Norfa523-Web2.pdf": NORFA_SYN.read_bytes()})]

    monkeypatch.setattr(fetchers, "get", lambda chain: FakeNorfa)
    s = job.run("norfa", "manual", settings)
    assert s["status"] == "ok", s
    assert s["parsed"][0]["offers"] == 6 and s["parsed"][0]["images"] == 6
    conn = db.open_db(settings)
    assert conn.execute("SELECT status, offers FROM issues").fetchone()[:] == ("parsed", 6)
    s2 = job.run("norfa", "manual", settings)  # nothing new: no second parse
    assert s2["status"] == "ok" and not s2.get("parsed")
