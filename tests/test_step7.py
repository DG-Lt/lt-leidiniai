"""0.6.0: picture reader for image-only leaflets (picture_reader: none | tesseract | ollama)."""
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


def _settings_with(settings, **kw):
    for k, v in kw.items():
        setattr(settings, k, v)
    return settings


def test_options(tmp_path):
    from leidiniai import config
    (tmp_path / "options.json").write_text(json.dumps({"picture_reader": "bad", "ollama_url": " http://pc:11434/ "}))
    s = config.load(tmp_path)
    assert (s.picture_reader, s.ollama_url, s.ollama_model) == ("none", "http://pc:11434", "qwen2.5vl:7b")


def test_ollama_json_to_offers():
    from leidiniai.vision.ollama import offers_from_json
    data = {"offers": [
        {"name": "Pienas  DVARO, 2,5 % rieb., 1 l", "price": 1.19, "old_price": "1,59", "discount": "-25 %",
         "unit_price": 1.19, "unit": "l.", "card_only": True, "box": [10, 20, 300, 400]},
        {"name": "Kava JACOBS", "price": None, "discount": "-30%", "box": [0, 0, 5000, 5000]},  # box off the page
        {"name": "Šilas", "price": None},          # heading: no price, no discount
        {"name": "12", "price": 3.0},               # no name
    ]}
    a, b = offers_from_json(data, 2, "silas", (992, 1404))
    assert (a.name, a.price, a.old_price, a.discount_pct, a.unit, a.unit_price, a.card, a.page) == \
        ("Pienas DVARO, 2,5 % rieb., 1 l", 119, 159, 25, "l", 119, True, 2)
    assert a.crop == {"x0": 10, "top": 20, "x1": 300, "bottom": 400} and "vision" in a.flags
    assert (b.kind, b.discount_text, b.crop) == ("badge", "-30%", None)


def test_tsv_words():
    from leidiniai.vision.tesseract import words_from_tsv
    tsv = ("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
           "5\t1\t1\t1\t1\t1\t100\t200\t50\t30\t91.2\tPienas\n"
           "5\t1\t1\t1\t1\t2\t160\t200\t20\t30\t12.0\t~~\n"
           "4\t1\t1\t1\t1\t0\t100\t200\t80\t30\t-1\t\n")
    (w,) = words_from_tsv(tsv, 0.5)
    assert (w["text"], w["x0"], w["top"], w["bottom"], w["size"]) == ("Pienas", 50, 100, 115, 20.0)


def _page(path: Path, items):
    """A Šilas-like page picture: per item a name (small) and a price (big euros + small cents)."""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (992, 1404), "white")
    d = ImageDraw.Draw(img)
    for x, y, name, eur, ct in items:
        d.text((x, y), name, fill="black", font=ImageFont.truetype(FONT, 22))
        d.text((x, y + 40), eur, fill="black", font=ImageFont.truetype(FONT, 90))
        d.text((x + 60 * len(eur), y + 50), ct, fill="black", font=ImageFont.truetype(FONT, 45))
    img.save(path)


@pytest.mark.skipif(not shutil.which("tesseract") or not Path(FONT).exists(), reason="no tesseract / font")
def test_tesseract_reads_a_page(settings, tmp_path, monkeypatch):
    from leidiniai.vision import tesseract
    sysdata = next((p for p in Path("/usr/share/tesseract-ocr").glob("*/tessdata") if (p / "eng.traineddata").exists()), None)
    if not sysdata:
        pytest.skip("no eng traineddata")
    monkeypatch.setattr(tesseract, "LANGS", ("eng",))
    monkeypatch.setattr(type(settings), "tessdata_dir", property(lambda s: sysdata))
    img = tmp_path / "p1.png"
    _page(img, [(80, 100, "Milk DVARO 1 l", "1", "99"), (560, 100, "Bread RUGELIS 800 g", "2", "49")])
    with tesseract.session(settings, log) as read:
        offers = read(img, 1, "silas")
    got = {o.price: o.name for o in offers if o.price}
    assert got.get(199, "").startswith("Milk") and got.get(249, "").startswith("Bread"), got
    a = next(o for o in offers if o.price == 199)
    assert a.crop and a.crop["x1"] <= 992 and "ocr" in a.flags


def _silas_issue(conn, tmp_path, status="waiting_parser"):
    pics = []
    for n in (1, 2):
        p = tmp_path / f"silas_{n}.jpg"
        from PIL import Image
        Image.new("RGB", (992, 1404), "white").save(p)
        pics.append({"name": p.name, "path": str(p), "url": "x", "sha256": "", "bytes": 1})
    vt = (date.today() + timedelta(days=5)).isoformat()
    with conn:
        return conn.execute(
            "INSERT INTO issues(chain,key,series,title,valid_to,files,meta,status,first_seen,last_seen)"
            " VALUES('silas','2026-23','leidinys','Leidinys Nr. 23',?,?,'{}',?,'2026-11-18','2026-11-18')",
            (vt, json.dumps(pics), status)).lastrowid


def test_waiting_leaflet_read_when_reader_ready(settings, tmp_path, monkeypatch):
    from leidiniai import pipeline, schedule, vision
    from leidiniai.parsers import Offer
    from leidiniai.vision import ollama
    settings.picture_reader = "ollama"
    conn = db.open_db(settings)
    iid = _silas_issue(conn, tmp_path)
    with conn:
        conn.execute("INSERT INTO chain_state(chain,last_check) VALUES('silas',?)", (db.now_iso(),))
    assert not vision.ready(settings)
    assert not schedule.due(conn, "silas", date.today(), False)[0]

    vision.write_status(settings, state="ready", signature=vision._signature(settings), message="ok")
    assert vision.ready(settings)
    assert schedule.due(conn, "silas", date.today(), True)[1] == "an image-only leaflet waits for the picture reader"

    @contextmanager
    def fake_session(s, lg):
        def read(img, pno, chain):
            return [Offer(chain=chain, name=f"Sūris DŽIUGAS p{pno}", price=299, page=pno, flags=["vision"],
                          crop={"x0": 100, "top": 100, "x1": 400, "bottom": 500})]
        yield read
    monkeypatch.setattr(ollama, "session", fake_session)
    summary = {"warnings": [], "errors": []}
    pipeline.retry_parses(conn, settings, "silas", summary, log)
    row = conn.execute("SELECT * FROM issues WHERE id=?", (iid,)).fetchone()
    assert (row["status"], row["offers"]) == ("parsed", 2)
    offs = conn.execute("SELECT name, price, image FROM offers WHERE issue_id=? ORDER BY seq", (iid,)).fetchall()
    assert offs[0]["name"] == "Sūris DŽIUGAS p1" and offs[0]["price"] == 299
    assert all((settings.img_dir / o["image"]).exists() for o in offs)


def test_reader_off_keeps_waiting(settings, tmp_path):
    from leidiniai import pipeline
    conn = db.open_db(settings)
    iid = _silas_issue(conn, tmp_path, status="parse_failed")
    pipeline.retry_parses(conn, settings, "silas", {"warnings": [], "errors": []}, log)
    row = conn.execute("SELECT status, parse_attempts FROM issues WHERE id=?", (iid,)).fetchone()
    assert (row["status"], row["parse_attempts"]) == ("waiting_parser", 0)


def test_switching_away_deletes_files(settings):
    from leidiniai import vision
    settings.tessdata_dir.mkdir(parents=True)
    (settings.tessdata_dir / "lit.traineddata").write_bytes(b"x")
    (settings.ollama_dir / "models").mkdir(parents=True)
    st = vision.reconcile(settings, log)  # picture_reader none
    assert st["state"] == "off" and not settings.tessdata_dir.exists() and not settings.ollama_dir.exists()


def test_external_ollama_needs_the_model(settings, monkeypatch):
    from leidiniai import vision
    from leidiniai.vision import ollama
    _settings_with(settings, picture_reader="ollama", ollama_url="http://pc:11434")
    monkeypatch.setattr(ollama, "_alive", lambda url: True)
    monkeypatch.setattr(ollama, "models", lambda url: ["llava:latest"])
    st = vision.reconcile(settings, log)
    assert st["state"] == "error" and "ollama pull qwen2.5vl:7b" in st["message"]
    monkeypatch.setattr(ollama, "models", lambda url: ["qwen2.5vl:7b"])
    st = vision.reconcile(settings, log)
    assert st["state"] == "ready" and vision.ready(settings)
    settings.ollama_model = "qwen2.5vl:3b"  # another model: not ready until prepared again
    assert not vision.ready(settings)
