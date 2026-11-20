"""0.7.0: Vynoteka – publications from the home page menu, food leaflet PDF, gift set catalogue, drinks pages.
The PDFs here are made up (reportlab) with the font sizes and layout measured on the real ones (2026-11-20)."""
import logging
from datetime import date
from pathlib import Path

import pytest

REF = date(2026, 11, 20)
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
log = logging.getLogger("t")

HOME = """<nav>
<a href="/kalediniu-rinkiniu-katalogas-2026">Kalėdinių rinkinių katalogas 2026</a>
<a href="/nr-23-kainos-galioja-2026-11-09-2026-11-22">Maisto leidinys</a>
<a href="/gerimu-leidinys-2026-23">Leidinys online</a>
<a href="/gerimu-leidinys-2026-23?pdf=1">Leidinys PDF</a>
<a href="/ziemos-katalogas-2026">Žiemos katalogas 2026</a>
<a href="https://vynoteka.lt/eshop">Parduotuvė</a>
<a href="gerimu-leidinys-2026-23">PERŽIŪRĖTI</a></nav>"""
HDR = '<div class="mt-1">\n   Kainos galioja\n      {} \n</div>'
DRINKS = ("<title>Gėrimų leidinys</title>" + HDR.format("2026 11 16 - 2026 11 29") +
          '<main id="app__main"><Flyer pages="[&quot;325_slide_1.jpg&quot;,&quot;325_slide_2.jpg&quot;]" first-single '
          'front-cover="https://vynoteka.lt/cdn/media/image/415/2480/0?s=ab" back-cover="https://vynoteka.lt/cdn/media/image/416/2480/0?s=cd"'
          ' ></Flyer></main>')
FOOD = ("<title>Maisto leidinys</title>" + HDR.format("2026 11 09 - 2026 11 22") +
        '<main><div class="flip-book-container1" src="/upload/media/68b1_6ae4.pdf"><i></i></div></main>')
SETS = ("<title>Kalėdinių rinkinių katalogas 2026</title>" + HDR.format("2026 10 26 - 2026 12 31") +
        '<main><div class="flip-book-container1" src="/upload/media/f298_6ae1.pdf"><i></i></div></main>')
VIDEO = ("<title>Žiemos katalogas 2026</title>" + HDR.format("2026 11 16 - 2027 01 03") +
         '<main><publication-video src="/upload/media/6d5e.mp4"></publication-video></main>')


class FakeHttp:
    def __init__(self, pages):
        self.pages, self.asked = pages, []

    def text(self, url, **kw):
        self.asked.append(url)
        return self.pages[url]


def test_vynoteka_discover():
    from leidiniai.fetchers.vynoteka import Vynoteka
    h = FakeHttp({"https://vynoteka.lt/": HOME,
                  "https://vynoteka.lt/kalediniu-rinkiniu-katalogas-2026": SETS,
                  "https://vynoteka.lt/nr-23-kainos-galioja-2026-11-09-2026-11-22": FOOD,
                  "https://vynoteka.lt/gerimu-leidinys-2026-23": DRINKS,
                  "https://vynoteka.lt/ziemos-katalogas-2026": VIDEO})
    got = {i.title: i for i in Vynoteka(h, log, REF).discover()}
    assert set(got) == {"Kalėdinių rinkinių katalogas 2026", "Maisto leidinys", "Gėrimų leidinys"}
    assert "https://vynoteka.lt/eshop" not in h.asked and len(h.asked) == 5  # home + 4 publications, once each
    d = got["Gėrimų leidinys"]
    assert (d.key, d.series, d.number, d.valid_from, d.valid_to, d.parser) == \
        ("gerimu-leidinys-2026-23", "gerimu-leidinys", "23", date(2026, 11, 16), date(2026, 11, 29), "vision")
    assert [f.name for f in d.files] == ["p01.jpg", "p02.jpg", "p03.jpg", "p04.jpg"]
    assert d.files[1].url == "https://vynoteka.lt/upload/pdf/325_slide_1.jpg" and d.files[0].url.endswith("415/2480/0?s=ab")
    f = got["Maisto leidinys"]
    assert (f.key, f.series, f.number, f.valid_to, f.parser, f.meta["parser"]) == \
        ("nr-23-kainos-galioja-2026-11-09-2026-11-22", "maisto-leidinys", "23", date(2026, 11, 22), "vynoteka", "vynoteka")
    assert f.files[0].url == "https://vynoteka.lt/upload/media/68b1_6ae4.pdf"
    k = got["Kalėdinių rinkinių katalogas 2026"]
    assert (k.key, k.valid_from, k.valid_to) == ("kalediniu-rinkiniu-katalogas-2026", date(2026, 10, 26), date(2026, 12, 31))


# name lines, euros, cents, old price, badge ("-30" / "TIK")
FOOD_ITEMS = [
    (["ŠOKOLADO PLYTELĖ", "JUODASIS ŠOKOLADAS 70 %,", "100 g"], "2", "49", None, "TIK"),
    (["ŽELĖ DESERTAS", "VYŠNIŲ SKONIO, (2 rūšių),", "150 g"], "1", "39", "1,99", "-30"),
    (["SAUSAINIAI SU", "VANILĖS ĮDARU,", "176 g"], "1", "29", "1,89", "-31"),
    (["RIEŠUTŲ MIŠINYS", "SKRUDINTAS,", "200 g"], "3", "19", "3,99", "-20"),
]


def _food_pdf(path: Path):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas
    pdfmetrics.registerFont(TTFont("DV", FONT))
    w, h = A4
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setFont("DV", 7)
    c.drawString(83, h - 26, "Nr. 23. Kainos galioja 2026 11 09 – 2026 11 22")
    for i, (lines, eur, ct, old, badge) in enumerate(FOOD_ITEMS):
        x, top = 40 + (i % 2) * 260, 120 + (i // 2) * 330    # top of the badge (from the page top)
        c.setFont("DV", 32 if badge != "TIK" else 30)
        c.drawString(x, h - (top + 30), badge)
        c.setFont("DV", 43)
        c.drawString(x + 5, h - (top + 75), eur)
        c.setFont("DV", 26)
        c.drawString(x + 5 + 27 * len(eur), h - (top + 63), ct)
        if old:
            c.setFont("DV", 13)
            c.drawString(x + 40, h - (top + 87), old)
        c.setFont("DV", 9)
        for j, ln in enumerate(lines):
            c.drawString(x - 5, h - (top + 115 + 11 * j), ln)
        c.setFont("DV", 14)
        c.drawString(x + 120, h - (top + 20), "NAUJIENA!")
    c.save()


@pytest.mark.skipif(not Path(FONT).exists(), reason="no DejaVu font")
def test_vynoteka_food_leaflet(tmp_path):
    from leidiniai.parsers import vynoteka
    p = tmp_path / "food.pdf"
    _food_pdf(p)
    assert not vynoteka.is_set_catalogue(p)
    offers = sorted(vynoteka.parse(p), key=lambda o: o.price)
    got = [(o.name, o.price, o.old_price, o.discount_pct, o.quantity) for o in offers]
    assert got == [
        ("SAUSAINIAI SU VANILĖS ĮDARU 176 g", 129, 189, 31, "176 g"),
        ("ŽELĖ DESERTAS VYŠNIŲ SKONIO, (2 rūšių) 150 g", 139, 199, 30, "150 g"),
        ("ŠOKOLADO PLYTELĖ JUODASIS ŠOKOLADAS 70 % 100 g", 249, None, None, "100 g"),
        ("RIEŠUTŲ MIŠINYS SKRUDINTAS 200 g", 319, 399, 20, "200 g"),
    ], got


def _sets_pdf(path: Path):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas
    pdfmetrics.registerFont(TTFont("DV", FONT))
    w, h = A4
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setFont("DV", 63)
    c.drawString(60, h - 317, "DOVANŲ")
    c.drawString(60, h - 378, "KATALOGAS")
    c.showPage()
    for n, title, price, items in ((2, ["ARBATA IR", "SALDAINIAI"], "13,99 €", [["Juodoji arbata", "MIŠKO UOGOS, 50 g"], ["Saldainiai", "PIENIŠKI, 150 g"]]),
                                    (3, ["SULTYS IR", "SŪRIS"], "26,99 €", [["Obuolių sultys", "SODO, 1 l"]])):
        c.setFont("DV", 52)
        for j, t in enumerate(title):
            c.drawString(46, h - (97 + 49 * j), t)
        c.setFont("DV", 20)
        c.drawString(46, h - 186, "R I N K I N Y S   N R .   " + str(n))
        c.setFont("DV", 48)
        c.drawString(380, h - 213, price)
        for k, lines in enumerate(items):
            c.setFont("DV", 23)
            c.drawString(36, h - (700 + 70 * k), f"0{k + 1}")
            c.setFont("DV", 13)
            for j, t in enumerate(lines):
                c.drawString(81, h - (688 + 70 * k + 15 * j), t)
        c.showPage()
        c.setFont("DV", 33)  # back side: the same number and price, no title
        c.drawString(54, h - 81, price)
        c.setFont("DV", 16)
        c.drawString(54, h - 43, "R I N K I N Y S   N R .   " + str(n))
        c.showPage()
    c.save()


@pytest.mark.skipif(not Path(FONT).exists(), reason="no DejaVu font")
def test_vynoteka_gift_sets(tmp_path):
    from leidiniai.categories import SHOP_MAP
    from leidiniai.parsers import vynoteka
    p = tmp_path / "sets.pdf"
    _sets_pdf(p)
    assert vynoteka.is_set_catalogue(p)
    a, b = vynoteka.parse(p)
    assert (a.name, a.price, a.kind, a.page, a.ext_id) == ("Rinkinys Nr. 2: Arbata ir saldainiai", 1399, "catalogue", 2, "rinkinys-2")
    assert a.extra["contents"] == ["Juodoji arbata MIŠKO UOGOS, 50 g", "Saldainiai PIENIŠKI, 150 g"]
    assert (b.name, b.price) == ("Rinkinys Nr. 3: Sultys ir sūris", 2699)
    assert SHOP_MAP[("vynoteka", a.ext_category)][0] == "alcohol"
