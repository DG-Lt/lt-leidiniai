"""0.8.0: names (size-only, Lidl terms, short name + Aprašymas), picture reader (cards, dates, saved pages, night-only
lane, memory, log), details page links, Home Assistant entities (activity, picture reader, watch hit, short names)."""
import json
import logging
import shutil
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

import pytest

from leidiniai import db

log = logging.getLogger("t")
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


# --------------------------------------------------------------------------- names

@pytest.mark.parametrize("name,weak", [("cm", True), ("24 cm", True), ("2 vnt./rink. ml", True), ("3 rūšių", True),
                                       ("Pienas DVARO, 1 l", False), ("Knygoms įvairių rūšių", False)])
def test_size_only_names_are_weak(name, weak):
    from leidiniai.parsers import Offer, finish
    o = finish(Offer(chain="iki", name=name, price=799))
    assert ("weak_name" in o.flags) is weak


def test_stray_unit_and_short_name():
    from leidiniai.parsers import Offer, finish
    o = finish(Offer(chain="iki", name="Dvigubo stiklo puodelių rinkinys ml", price=399))
    assert o.name == "Dvigubo stiklo puodelių rinkinys" and "desc" not in o.extra
    assert finish(Offer(chain="iki", name="Pienas DVARO, 2,5 % rieb., 1 l", price=1)).name.endswith("1 l")
    o = finish(Offer(chain="iki", price=1099, name="Plaukų trumpinimo mašinėlė VIVESS Lankstūs dvigubi peiliukai. "
                     "Nerūdijančio plieno ašmenys. 3 keičiami kirpimo antgaliai."))
    assert o.name == "Plaukų trumpinimo mašinėlė VIVESS Lankstūs dvigubi peiliukai"
    assert o.extra["desc"].startswith("Nerūdijančio plieno ašmenys. 3 keičiami")
    # abbreviations and brand initials do not end the name; a short rest stays in the name
    for n in ("Sūris 45 % rieb. Pagamintas Lietuvoje iš karvių pieno", "Šaldyta pica DR. OETKER FELICIANA 3 rūšių",
              "Kava JACOBS. Malta"):
        o = finish(Offer(chain="iki", name=n, price=1))
        assert o.name == n and "desc" not in o.extra, n


def test_lidl_terms_and_codes_leave_the_name():
    from leidiniai.parsers.pdf_text import clean_name
    raw = ("DELUXE Šveicariškas sūris Tête de Moine AOP Ieškoti šaldytuve 400 g 7602258, 7602256 "
           "Akcijos limitas vieno pirkimo metu – 2 vnt. Nuolaidos nesumuojamos. "
           "Pasiūlymas galioja tik nurodytos akcijos metu arba kol bus prekių.")
    assert clean_name(raw, "lidl") == "DELUXE Šveicariškas sūris Tête de Moine AOP 400 g"
    assert clean_name("Powerbank 10000 mAh", "lidl") == "Powerbank 10000 mAh"
    assert "7602258" in clean_name("Sūris 7602258", "iki")  # other chains untouched


def test_search_uses_name_and_description(settings):
    from leidiniai import store
    from leidiniai.parsers import Offer, finish
    conn = db.open_db(settings)
    with conn:
        iid = conn.execute("INSERT INTO issues(chain,key,series,title,first_seen,last_seen,status)"
                           " VALUES('iki','k','s','t','x','x','parsed')").lastrowid
    issue = conn.execute("SELECT * FROM issues WHERE id=?", (iid,)).fetchone()
    o = finish(Offer(chain="iki", price=1099, name="Plaukų kirpimo mašinėlė VIVESS. Nerūdijančio plieno ašmenys ir peiliukai"))
    store.save_offers(conn, issue, [o])
    r = conn.execute("SELECT o.name, o.name_key, p.name_key AS pkey FROM offers o JOIN products p ON p.id=o.product_id").fetchone()
    assert r["name"] == "Plaukų kirpimo mašinėlė VIVESS" and "nerudijancio" in r["name_key"]
    assert r["pkey"] == "plauku kirpimo masinele vivess"


# --------------------------------------------------------------------------- offer dates

@pytest.mark.parametrize("text,want", [
    ("LAPKRIČIO 19–21 d. (Ketvirtadienį – šeštadienį)", ("2026-11-19", "2026-11-21")),
    ("LAPKRIČIO 29 – GRUODŽIO 1 d.", ("2026-11-29", "2026-12-01")),
    ("lapkričio 23–25", ("2026-11-23", "2026-11-25")),
    ("11.19–11.21", ("2026-11-19", "2026-11-21")),
    ("Iki 11.23", (None, "2026-11-23")),
    ("gruodžio 30 – sausio 2 d.", ("2026-12-30", "2027-01-02")),
    ("Tik 3 dienas", (None, None)),
])
def test_offer_range(text, want):
    from leidiniai.textutil import offer_range
    got = offer_range(text, date(2026, 11, 18))
    assert tuple(d.isoformat() if d else None for d in got) == want


def test_offer_dates_inside_the_leaflet_only():
    from leidiniai.parsers import Offer
    from leidiniai.vision import offer_dates
    issue = {"valid_from": "2026-11-18", "valid_to": "2026-12-01"}
    a = Offer(chain="silas", name="Sheba", extra={"dates_text": "LAPKRIČIO 19–21 d."})
    b = Offer(chain="silas", name="Kava", extra={"dates_text": "BIRŽELIO 3–5 d."})  # misread: far outside
    offer_dates([a, b], issue)
    assert (a.valid_from, a.valid_to) == (date(2026, 11, 19), date(2026, 11, 21))
    assert (b.valid_from, b.valid_to) == (None, None)


# --------------------------------------------------------------------------- cards on a page picture

def grid_page(path: Path, cols=3, rows=4, size=(992, 1403)):
    """A Šilas-like page: grey wood background, white cards in a grid, a colour 'photo' across most of each card
    (from the card's top to its bottom on the right half, as on the real pages)."""
    from PIL import Image, ImageDraw
    W, H = size
    img = Image.new("RGB", size, (229, 229, 229))
    d = ImageDraw.Draw(img)
    for x in range(0, W, 40):
        d.line([(x, 0), (x, H)], fill=(238, 237, 235), width=6)  # light planks, still below card white
    cw, ch, gap, top = (W - 4 * 20) // cols, (H - 120 - 5 * 20) // rows, 20, 120
    cards = []
    for r in range(rows):
        for c in range(cols):
            x0, y0 = gap + c * (cw + gap), top + r * (ch + gap)
            box = (x0, y0, x0 + cw, y0 + ch)
            d.rounded_rectangle(box, 12, fill=(255, 255, 255))
            d.rectangle((x0 + cw // 2, y0 + 4, x0 + cw - 6, y0 + ch - 4), fill=(200, 60, 40))  # photo
            d.text((x0 + 10, y0 + 10), "3,99", fill=(220, 0, 0))
            cards.append(box)
    img.save(path)
    return cards


def test_cells_found_on_a_grid_page(tmp_path):
    from PIL import Image
    from leidiniai.vision import cells
    cards = grid_page(tmp_path / "p.png")
    found = cells.find_cells(Image.open(tmp_path / "p.png"))
    assert len(found) == 12
    for want, got in zip(cards, found):
        assert all(abs(a - b) <= 8 for a, b in zip(want, got)), (want, got)


def test_free_layout_page_has_no_cells(tmp_path):
    from PIL import Image, ImageDraw
    from leidiniai.vision import cells
    img = Image.new("RGB", (992, 1403), (180, 200, 230))
    d = ImageDraw.Draw(img)
    for k in range(30):
        d.ellipse((k * 30, k * 40, k * 30 + 200, k * 40 + 160), fill=(40 + k * 5, 90, 160))
    assert cells.find_cells(img) == []


def test_boxes_snap_to_their_card(tmp_path):
    from leidiniai.parsers import Offer
    from leidiniai.vision import place_offers
    cards = grid_page(tmp_path / "p.png")
    c = cards[4]
    # the model's box: shifted right into the neighbour and too small (as on the user's screenshot)
    w = c[2] - c[0]
    rough = Offer(chain="silas", name="A", crop={"x0": c[0] + w // 3, "top": c[1] + 40, "x1": c[2] + 60, "bottom": c[1] + 200})
    off_page = Offer(chain="silas", name="B", crop={"x0": 2, "top": 2, "x1": 60, "bottom": 60})  # heading area
    place_offers([rough, off_page], tmp_path / "p.png")
    assert (rough.crop["x0"], rough.crop["top"], rough.crop["x1"], rough.crop["bottom"]) == pytest.approx(c, abs=8)
    assert rough.extra["crop"] == "card"
    assert off_page.extra["crop"] == "model" and off_page.crop["x0"] == 0  # kept with a margin


# --------------------------------------------------------------------------- Ollama answer

def test_ollama_answer_new_keys():
    from leidiniai.vision.ollama import SCHEMA, offers_from_json
    assert list(SCHEMA["properties"]["offers"]["items"]["properties"])[0] == "bbox_2d"
    data = {"offers": [{"bbox_2d": [0, 0, 490, 700], "name": "SHEBA ėdalas katėms 4×85 g", "price": 1.75, "old": 3.55,
                        "disc": "-50 %", "unit_price": 5.15, "unit": "kg", "dates": "LAPKRIČIO 19–21 d."},
                       {"bbox_2d": [10, 10, 100, 100], "name": "FA kosmetikai", "disc": "-50%"}]}
    a, b = offers_from_json(data, 1, "silas", (993, 1403))  # the model saw 980×1400
    assert (a.price, a.old_price, a.discount_pct, a.unit_price, a.unit) == (175, 355, 50, 515, "kg")
    assert a.extra["dates_text"] == "LAPKRIČIO 19–21 d." and not a.card
    assert a.crop == {"x0": 0, "top": 0, "x1": 496, "bottom": 702}
    assert (b.kind, b.price, b.discount_text) == ("badge", None, "-50%")


def test_ollama_log_drops_progress_lines(tmp_path):
    import io
    from leidiniai.vision.ollama import _copy_log
    src = io.BytesIO(b"slot print_timing: id  0 | task 1 | n_gen =    788, tg =   2.46 t/s\n"
                     b"decoding image batch 1/3, n_tokens_batch = 1024\n"
                     b"slot print_timing: id  0 | task 1 | prompt eval time =  455876.27 ms /  2575 tokens\n"
                     b"[GIN] 2026/11/21 - 01:20:23 | 200 |   14m30s | POST \"/api/chat\"\n")
    _copy_log(src, tmp_path / "serve.log")
    assert (tmp_path / "serve.log").read_text().splitlines() == [
        "slot print_timing: id  0 | task 1 | prompt eval time =  455876.27 ms /  2575 tokens",
        "[GIN] 2026/11/21 - 01:20:23 | 200 |   14m30s | POST \"/api/chat\""]


def test_model_unloaded_after_every_page(tmp_path, monkeypatch):
    from PIL import Image
    from leidiniai.vision import ollama
    Image.new("RGB", (993, 1403), "white").save(tmp_path / "p.png")
    sent = {}

    class R:
        def raise_for_status(self):
            pass

        def json(self):
            return {"message": {"content": '{"offers": []}'}}

    def post(url, json=None, timeout=None):
        sent.update(json)
        return R()
    monkeypatch.setattr(ollama.requests, "post", post)
    ollama.read_page("http://x", "qwen2.5vl:7b", tmp_path / "p.png", 1, "silas", 3)
    assert sent["keep_alive"] == 0 and sent["options"]["num_thread"] == 3


# --------------------------------------------------------------------------- page pictures

def test_image_only_pdf_rendered_at_its_own_size(tmp_path):
    from PIL import Image
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from leidiniai.vision import pages
    Image.new("RGB", (700, 990), (200, 30, 30)).save(tmp_path / "pic.jpg")
    c = canvas.Canvas(str(tmp_path / "s.pdf"), pagesize=A4)
    c.drawImage(str(tmp_path / "pic.jpg"), 0, 0, *A4)
    c.showPage()
    c.save()
    (p,) = pages.page_images([{"name": "s.pdf", "path": str(tmp_path / "s.pdf")}], tmp_path / "w", log)
    assert max(Image.open(p).size) == 990  # not blown up to 1600


# --------------------------------------------------------------------------- saved pages, picture lane

def silas_issue(conn, tmp_path, pages=3, status="waiting_parser"):
    files = []
    for n in range(1, pages + 1):
        p = tmp_path / f"silas_{n}.jpg"
        grid_page(p)
        files.append({"name": p.name, "path": str(p), "url": "x", "sha256": "", "bytes": 1})
    vt = (date.today() + timedelta(days=5)).isoformat()
    vf = (date.today() - timedelta(days=2)).isoformat()
    with conn:
        return conn.execute(
            "INSERT INTO issues(chain,key,series,title,valid_from,valid_to,files,meta,status,first_seen,last_seen)"
            " VALUES('silas','2026-23','leidinys','Leidinys Nr. 23',?,?,?,'{}',?,'2026-11-18','2026-11-18')",
            (vf, vt, json.dumps(files), status)).lastrowid


def reader_ready(settings):
    from leidiniai import vision
    settings.picture_reader = "ollama"
    vision.write_status(settings, state="ready", signature=vision._signature(settings), message="ok")


def fake_reader(monkeypatch, calls, fail_on=None):
    from leidiniai.parsers import Offer
    from leidiniai.vision import ollama

    @contextmanager
    def session(s, lg):
        calls.append("start")

        def read(img, pno, chain):
            if pno == fail_on:
                raise RuntimeError("box restarted")
            calls.append(pno)
            return [Offer(chain=chain, name=f"Sūris p{pno}", price=299, page=pno, flags=["vision"],
                          crop={"x0": 400, "top": 300, "x1": 500, "bottom": 400})]
        yield read
    monkeypatch.setattr(ollama, "session", session)


def test_reading_continues_from_the_next_page(settings, tmp_path, monkeypatch):
    from leidiniai import job
    reader_ready(settings)
    conn = db.open_db(settings)
    iid = silas_issue(conn, tmp_path)
    calls = []
    fake_reader(monkeypatch, calls, fail_on=3)
    runs = job.run_pictures(settings, "night")
    # 0.8.2: a page that fails no longer fails the leaflet – the others are saved, the page is retried next time
    assert runs[0]["status"] == "warning" and calls == ["start", 1, 2]
    assert [r[0] for r in conn.execute("SELECT page FROM vision_pages WHERE issue_id=?", (iid,))] == [1, 2]
    row = conn.execute("SELECT status, offers, meta FROM issues WHERE id=?", (iid,)).fetchone()
    assert (row["status"], row["offers"], json.loads(row["meta"])["failed_pages"]) == ("parsed", 2, [3])
    calls.clear()
    fake_reader(monkeypatch, calls)
    runs = job.run_pictures(settings, "resume")
    assert calls == ["start", 3]  # pages 1 and 2 were not read again
    assert "failed_pages" not in json.loads(conn.execute("SELECT meta FROM issues WHERE id=?", (iid,)).fetchone()[0])
    row = conn.execute("SELECT status, offers FROM issues WHERE id=?", (iid,)).fetchone()
    assert (row["status"], row["offers"]) == ("parsed", 3)
    o1 = conn.execute("SELECT * FROM offers WHERE issue_id=? AND page=1", (iid,)).fetchone()
    ex = json.loads(o1["extra"])
    assert ex["crop"] == "card" and (settings.img_dir / o1["image"]).exists()


def test_reread_keeps_offers_until_done(settings, tmp_path, monkeypatch):
    from leidiniai import job, pipeline
    reader_ready(settings)
    conn = db.open_db(settings)
    iid = silas_issue(conn, tmp_path, pages=2)
    calls = []
    fake_reader(monkeypatch, calls)
    job.run_pictures(settings, "night")
    assert pipeline.picture_issues(conn) == []
    assert pipeline.request_reread(conn, iid)
    row = conn.execute("SELECT status, meta FROM issues WHERE id=?", (iid,)).fetchone()
    assert row["status"] == "parsed" and json.loads(row["meta"])["reread"] is True  # offers still on show
    assert conn.execute("SELECT COUNT(*) FROM vision_pages WHERE issue_id=?", (iid,)).fetchone()[0] == 0
    calls.clear()
    job.run_pictures(settings, "manual", iid)
    assert calls == ["start", 1, 2]
    row = conn.execute("SELECT status, meta FROM issues WHERE id=?", (iid,)).fetchone()
    assert row["status"] == "parsed" and "reread" not in json.loads(row["meta"])
    assert not pipeline.request_reread(conn, 999)


def test_chain_check_leaves_pictures_for_the_picture_lane(settings, tmp_path):
    from leidiniai import pipeline
    from leidiniai.fetchers.base import IssueInfo
    reader_ready(settings)
    conn = db.open_db(settings)
    iid = silas_issue(conn, tmp_path, status="downloaded")
    info = IssueInfo(chain="silas", key="2026-23", series="leidinys", title="t", parser="vision")
    summary = {"warnings": [], "errors": []}
    pipeline.after_download(conn, settings, iid, info, summary, log)
    assert conn.execute("SELECT status FROM issues WHERE id=?", (iid,)).fetchone()[0] == "waiting_parser"
    assert "parsed" not in summary


def test_runner_activity_and_picture_requests(settings):
    from leidiniai.schedule import Runner
    r = Runner(settings)
    assert r.activity()["state"] == "laukia"
    r.current = "iki"
    r.request_pictures("manual")
    assert r.activity()["state"] == "tikrinamas IKI; paveikslėliai laukia eilėje"
    r.current, r.pictures = None, {"chain": "silas", "issue_id": 1, "title": "t", "page": 3, "pages": 12}
    assert r.activity()["state"] == "Šilas: puslapis 3/12"


def test_nightly_queues_picture_reading_after_checks(settings, monkeypatch):
    from datetime import datetime
    from leidiniai import schedule
    reader_ready(settings)
    db.open_db(settings).close()
    r = schedule.Runner(settings)

    class Night(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 21, 3, 31)
    monkeypatch.setattr(schedule, "datetime", Night)
    r._nightly()
    assert not r.q.empty() and r.pq.get_nowait() == ("night", None)


# --------------------------------------------------------------------------- panel

def test_original_file_link_and_details_page(settings, tmp_path):
    from leidiniai import store
    from leidiniai.parsers import Offer, finish
    from leidiniai.schedule import Runner
    from leidiniai.web import create_app
    conn = db.open_db(settings)
    pdf = settings.pdf_dir / "iki" / "k" / "B47.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF-1.4 test")
    files = json.dumps([{"name": "B47.pdf", "path": str(pdf)}])
    with conn:
        iid = conn.execute("INSERT INTO issues(chain,key,series,title,valid_to,files,source_url,first_seen,last_seen,status)"
                           " VALUES('iki','k','bazinis','IKI Nr. 47','2099-01-01',?,'https://iki.lt/leidiniai/','x','x','parsed')",
                           (files,)).lastrowid
    issue = conn.execute("SELECT * FROM issues WHERE id=?", (iid,)).fetchone()
    a = finish(Offer(chain="iki", page=57, price=799, old_price=1799, name="cm"))
    b = finish(Offer(chain="iki", page=12, price=1099, name="Plaukų kirpimo mašinėlė VIVESS. Nerūdijančio plieno ašmenys ir peiliukai"))
    store.save_offers(conn, issue, [a, b], {1: "iki/1/v12_0001.jpg"})
    c = create_app(settings, Runner(settings)).test_client()
    html = c.get("/?when=all").get_data(as_text=True)
    assert "pavadinimas neatpažintas" in html and f"/leidinys/{iid}/originalas#page=57" in html
    pid = conn.execute("SELECT product_id FROM offers WHERE seq=1").fetchone()[0]
    html = c.get(f"/produktas/{pid}").get_data(as_text=True)
    assert "Aprašymas:" in html and "Nerūdijančio plieno" in html
    assert f"/leidinys/{iid}/originalas#page=12" in html and "Leidinys tinklo svetainėje" in html and "zoomable" in html
    r = c.get(f"/leidinys/{iid}/originalas")
    assert r.status_code == 200 and r.mimetype == "application/pdf"
    assert c.get("/leidinys/999/originalas").status_code == 404


def test_leaflets_page_picture_buttons(settings, tmp_path, monkeypatch):
    from leidiniai.schedule import Runner
    from leidiniai.web import create_app
    reader_ready(settings)
    conn = db.open_db(settings)
    iid = silas_issue(conn, tmp_path, pages=1, status="parsed")
    runner = Runner(settings)
    c = create_app(settings, runner).test_client()
    html = c.get("/leidiniai").get_data(as_text=True)
    assert "Skaityti paveikslėlius dabar" in html and "Skaityti iš naujo" in html
    assert c.post(f"/leidinys/{iid}/skaityti-is-naujo").status_code == 302
    assert runner.pq.empty()  # 0.8.1: only marked – read at night or with the button
    html = c.get("/leidiniai").get_data(as_text=True)
    assert "laukia skaitymo iš naujo" in html and "Skaityti paveikslėlius dabar (1)" in html
    assert c.post("/paveiksleliai").status_code == 302 and runner.pq.get_nowait() == ("manual", None)


# --------------------------------------------------------------------------- Home Assistant

def test_short_titles():
    from leidiniai.ha_state import short_title
    row = lambda chain, series, title, number=None: {"chain": chain, "series": series, "title": title, "number": number}
    assert short_title(row("lidl", "maisto-prekiu-pasiulymai", "MAISTO PREKIŲ PASIŪLYMAI – Nuo lapkričio 23 d.")) == "Maisto prekės"
    assert short_title(row("maxima", "pasiulymai", "Pasiūlymai (160) iki 2026-12-07")) == "Pasiūlymai"
    assert short_title(row("silas", "leidinys", "Leidinys Nr. 23. Kainos galioja 2026 m. lapkričio 18 d. – gruodžio 1 d.")) == "Leidinys Nr. 23"
    assert len(short_title(row("lidl", "x", "Bajorų kel. 6, Visoriai VILNIUS – Dvigubink su Lidl Plus!"))) <= 28


def test_watch_hits_only_for_leaflets_read_after_the_term(settings):
    from leidiniai import ha_state, store
    from leidiniai.parsers import Offer, finish
    conn = db.open_db(settings)
    with conn:
        conn.execute("INSERT INTO watch(term,term_key,created) VALUES('Sviestas','sviestas','2026-11-20T10:00:00+02:00')")
        # 0.8.1: "new" = leaflet first seen after the word was added (a re-read of an older one is not new)
        old = conn.execute("INSERT INTO issues(chain,key,series,title,valid_to,first_seen,last_seen,status,parsed_at)"
                           " VALUES('iki','a','s','IKI 46','2099-01-01','2026-11-19T03:30:00+02:00','x','parsed',"
                           " '2026-11-21T11:57:00+02:00')").lastrowid
        new = conn.execute("INSERT INTO issues(chain,key,series,title,valid_to,first_seen,last_seen,status,parsed_at)"
                           " VALUES('rimi','b','s','Rimi 47','2099-01-01','2026-11-21T03:30:00+02:00','x','parsed',"
                           " '2026-11-21T03:30:00+02:00')").lastrowid
    for iid, chain in ((old, "iki"), (new, "rimi")):
        issue = conn.execute("SELECT * FROM issues WHERE id=?", (iid,)).fetchone()
        store.save_offers(conn, issue, [finish(Offer(chain=chain, name="Sviestas ROKIŠKIO, 200 g", price=119, old_price=279))])
    hits = ha_state.watch_hits(conn, date(2026, 11, 21))
    assert [(h["chain"], h["price"], h["discount"]) for h in hits] == [("rimi", 1.19, "-57%")]
    assert hits[0]["path"].startswith("/produktas/")


def test_watch_hit_event_once(settings):
    from test_step5 import FakeClient, FakeRunner  # noqa: F401 (fake MQTT client of the 0.5 tests)
    from leidiniai import mqtt, store
    from leidiniai.parsers import Offer, finish
    conn = db.open_db(settings)
    b = mqtt.Bridge(settings, FakeRunner(), credentials={"host": "h", "port": 1883}, client_factory=FakeClient)
    b._refresh_loop = lambda: None
    b._fast_loop = lambda: None
    b.start()
    b._on_connect(b.client, None, {}, 0, None)
    with conn:
        conn.execute("INSERT INTO watch(term,term_key,created) VALUES('Sviestas','sviestas','2000-01-01')")
        iid = conn.execute("INSERT INTO issues(chain,key,series,title,valid_to,first_seen,last_seen,status,parsed_at)"
                           " VALUES('rimi','b','s','Rimi 47','2099-01-01',?,'x','parsed',?)", (db.now_iso(), db.now_iso())).lastrowid
    issue = conn.execute("SELECT * FROM issues WHERE id=?", (iid,)).fetchone()
    store.save_offers(conn, issue, [finish(Offer(chain="rimi", name="Sviestas ROKIŠKIO", price=119))])
    b.announce_watch_hits()
    b.announce_watch_hits()
    evs = [json.loads(p) for t, p, r in b.client.pubs if t == "leidiniai/event/watch_hit"]
    assert len(evs) == 1 and evs[0]["event_type"] == "watch_hit" and evs[0]["chain_name"] == "Rimi"
    store.save_offers(conn, issue, [finish(Offer(chain="rimi", name="Sviestas ROKIŠKIO", price=119))])  # read again
    b.announce_watch_hits()
    assert len([1 for t, _, _ in b.client.pubs if t == "leidiniai/event/watch_hit"]) == 1


def test_picture_reader_state(settings):
    from leidiniai import ha_state, vision
    assert ha_state.picture_reader(settings)[0] == "išjungtas"
    settings.picture_reader = "ollama"
    vision.write_status(settings, state="preparing", signature=vision._signature(settings),
                        message="atsisiunčiamas modelis qwen2.5vl:7b 40%")
    st, attrs = ha_state.picture_reader(settings)
    assert st == "ruošiamas" and attrs["message"].endswith("40%") and attrs["model"] == "qwen2.5vl:7b"


def test_migration_6_reads_valid_pdf_leaflets_again(settings):
    conn = db.connect(settings.db_path)
    for sql in db.MIGRATIONS[:5]:
        conn.executescript(sql)
    conn.execute("PRAGMA user_version=5")
    with conn:
        conn.execute("INSERT INTO issues(chain,key,series,title,valid_to,files,first_seen,last_seen,status)"
                     " VALUES('lidl','a','s','t','2099-01-01','[{\"name\":\"a.pdf\"}]','x','x','parsed')")
        conn.execute("INSERT INTO issues(chain,key,series,title,valid_to,files,first_seen,last_seen,status)"
                     " VALUES('silas','b','s','t','2099-01-01','[{\"name\":\"b.pdf\"}]','x','x','parsed')")
    assert db.migrate(conn) == len(db.MIGRATIONS)
    st = dict(conn.execute("SELECT chain, status FROM issues").fetchall())
    assert st == {"lidl": "downloaded", "silas": "parsed"}  # picture leaflets are re-read only on request
