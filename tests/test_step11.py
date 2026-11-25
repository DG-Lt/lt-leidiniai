"""0.8.2: cut-off picture answers (salvage + halves, failed pages), Nutildyti, Atsargoms, accordions."""
import json
from datetime import date, timedelta

from leidiniai import db
from test_step10 import seed

TODAY = date.today()


def test_salvage_keeps_complete_offers():
    from leidiniai.vision.ollama import salvage
    cut = '{"offers": [{"bbox_2d": [1, 2, 3, 4], "name": "A \\"x\\" {b}", "price": 1.5}, {"bbox_2d": [5, 6, 7, 8], "na'
    data, complete = salvage(cut)
    assert not complete and [o["name"] for o in data["offers"]] == ['A "x" {b}']
    assert salvage('{"offers": []}') == ({"offers": []}, True)
    assert salvage("garbage") == ({"offers": []}, False)


def test_cut_page_read_in_halves(tmp_path, monkeypatch):
    from PIL import Image
    from leidiniai.vision import ollama
    Image.new("RGB", (1000, 1400), "white").save(tmp_path / "p.png")
    answers = [
        ('{"offers": [{"bbox_2d": [0, 0, 100, 100], "name": "Sūris A", "price": 1.0}, {"name": "Sūr', "length"),
        ('{"offers": [{"bbox_2d": [0, 0, 100, 100], "name": "Sūris A", "price": 1.0}]}', "stop"),
        ('{"offers": [{"bbox_2d": [0, 100, 100, 200], "name": "Kava B", "price": 2.0}]}', "stop"),
    ]
    sizes = []

    class R:
        def __init__(self, a):
            self.a = a

        def raise_for_status(self):
            pass

        def json(self):
            return {"message": {"content": self.a[0]}, "done_reason": self.a[1]}

    def post(url, json=None, timeout=None):
        import base64, io
        sizes.append(Image.open(io.BytesIO(base64.b64decode(json["messages"][0]["images"][0]))).size)
        return R(answers.pop(0))
    monkeypatch.setattr(ollama.requests, "post", post)
    got = ollama.read_page("http://x", "m", tmp_path / "p.png", 2, "silas", 3, raw_dir=tmp_path / "raw")
    assert sorted(o.name for o in got) == ["Kava B", "Sūris A"]  # A from page + top half kept once
    kava = next(o for o in got if o.name == "Kava B")
    assert kava.crop["top"] > 600 and kava.extra["read"] == "halves"  # moved down to the bottom half's place
    assert sizes[1][1] < 1400 and (tmp_path / "raw" / "silas-p02-page.txt").exists()


def test_mute_word(settings):
    from leidiniai import ha_state
    from leidiniai.schedule import Runner
    from leidiniai.web import create_app
    conn = db.open_db(settings)
    seed(conn, [{"name": "Makaronai BARILLA", "price": 99}, {"name": "Sviestas PILOS", "price": 199}])
    c = create_app(settings, Runner(settings)).test_client()
    c.post("/stebimi", data={"term": "makaronai"})
    c.post("/stebimi", data={"term": "sviestas"})
    wid = conn.execute("SELECT id FROM watch WHERE term='makaronai'").fetchone()[0]
    c.post(f"/stebimi/{wid}/nutildyti", data={"weeks": "3"})
    until = conn.execute("SELECT muted_until FROM watch WHERE id=?", (wid,)).fetchone()[0]
    assert until == (TODAY + timedelta(weeks=3)).isoformat()
    n, attrs = ha_state.watched_on_sale(conn, TODAY)
    assert n == 1 and attrs["items"][0]["name"] == "Sviestas PILOS"
    html = c.get("/stebimi").get_data(as_text=True)
    assert "nutildyta iki" in html and "Atšaukti nutildymą" in html and 'data-keep="zodis-' in html
    assert html.index("sviestas") < html.index("muted-term")  # muted word last
    html = c.get("/stebimi?view=tinklas").get_data(as_text=True)
    assert "makaronai (" not in html.split("Stebimi žodžiai")[0]
    assert ha_state.watched_on_sale(conn, TODAY + timedelta(weeks=4))[0] == 2  # unmuted by itself
    c.post(f"/stebimi/{wid}/nutildyti", data={"weeks": "0"})
    assert conn.execute("SELECT muted_until FROM watch WHERE id=?", (wid,)).fetchone()[0] is None


def test_stock_badge_rules(settings):
    from leidiniai import stock
    from leidiniai.schedule import Runner
    from leidiniai.web import create_app
    conn = db.open_db(settings)
    seed(conn, [{"name": "Makaronai BARILLA 500 g", "price": 99, "old_price": 199, "discount_pct": 50},
                {"name": "Grikių kruopos 800 g", "price": 150, "discount_pct": 10},
                {"name": "Šaldyti koldūnai 1 kg", "price": 199, "discount_pct": 35},
                {"name": "Šviežia jautiena", "price": 599, "discount_pct": 40},
                {"name": "Sūris GRIKIOS", "price": 199, "discount_pct": 40}], "iki", "2026-11-01T03:30:00+02:00")
    rows = conn.execute("SELECT * FROM offers ORDER BY seq").fetchall()
    b = stock.annotate(conn, rows)
    assert [b.get(r["id"]) for r in rows] == ["long", None, "frozen", None, None]
    # the same groats earlier at 1.55 → 1.50 now is within 5 % of the lowest → badge
    seed(conn, [{"name": "Grikių kruopos 800 g", "price": 155}], "iki", "2026-10-01T03:30:00+02:00")
    rows = conn.execute("SELECT * FROM offers WHERE name LIKE 'Grikių%' AND price=150").fetchall()
    assert stock.annotate(conn, rows) == {rows[0]["id"]: "long"}
    c = create_app(settings, Runner(settings)).test_client()
    html = c.get("/?when=all&stock=1").get_data(as_text=True)
    assert "Makaronai BARILLA" in html and "koldūnai" in html and "Grikių kruopos" in html and "jautiena" not in html
    assert "📦 Atsargoms" in html and "❄️ Atsargoms" in html
    c.post("/atsargoms", data={"long": "makaron", "frozen": "", "exclude": "", "min_discount": "60", "near_low_pct": "0"})
    r = stock.rules(conn)
    assert r["long"] == ["makaron"] and r["min_discount"] == 60
    assert "📦 Atsargoms" not in c.get("/?when=all").get_data(as_text=True)  # 50 % < 60 %
    html = c.get("/busena").get_data(as_text=True)
    assert 'data-keep="busena-atsargoms"' in html and "makaron" in html
    c.post("/atsargoms", data={"reset": "1"})
    assert stock.rules(conn)["min_discount"] == stock.DEFAULTS["min_discount"]


def test_failed_pages_are_a_problem(settings):
    from leidiniai import ha_state
    conn = db.open_db(settings)
    with conn:
        conn.execute("INSERT INTO issues(chain,key,series,title,valid_to,meta,first_seen,last_seen,status)"
                     " VALUES('silas','k','s','Leidinys Nr. 23','2099-01-01',?,'x','x','parsed')",
                     (json.dumps({"failed_pages": [2], "reread_error": "cut"}),))
    p = ha_state.problems(conn, ["silas"], TODAY)
    assert any("neperskaityti puslapiai 2" in x for x in p) and any("iš naujo" in x for x in p)
