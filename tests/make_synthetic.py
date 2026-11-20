"""Build the made-up test leaflets in tests/synthetic/ (dev tool; output is committed, CI doesn't run this).

    python tests/make_synthetic.py      # needs reportlab and the DejaVu Sans font

Everything here is invented: product names, prices and layout only imitate the font sizes the parsers expect
(docs/findings.md), so the pipeline, store and panel tests run without any shop material in the repository.
Parser accuracy on real leaflet pages is tested with tests/fixtures/ (local only, see make_fixtures.py).
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

OUT = Path(__file__).resolve().parent / "synthetic"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

# name lines, euros, cents, old price, discount %, unit line, card only
NORFA = [
    (["ŠALTUPIO šaltai rūkyta", "dešra, 300 g"], 2, "49", "3,49", 29, "1 kg – 8,30 €", False),
    (["ŽALGIRIO virtas kumpis,", "400 g"], 3, "19", "4,59", 30, "1 kg – 7,98 €", False),
    (["Fermentinis sūris", "GIRELĖ, 200 g"], 1, "99", "2,79", 29, "1 kg – 9,95 €", False),
    (["Obuoliai LIGOL, 1 kg"], 0, "89", "1,29", 31, "1 kg – 0,89 €", False),
    (["Kvietinė duona RŪTA,", "500 g"], 0, "99", "1,39", 29, "1 kg – 1,98 €", False),
    (["Pienas ŪKIO, 2,5 %,", "1 l"], 1, "09", "1,49", 27, "1 l – 1,09 €", False),
]


def norfa_pdf(path: Path) -> None:
    pdfmetrics.registerFont(TTFont("DV", FONT))
    w, h = A4
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setTitle("Synthetic Norfa-like page")
    cw, ch = w / 2, h / 3
    for i, (lines, eur, ct, old, disc, unit, card) in enumerate(NORFA):
        x0, ytop = (i % 2) * cw + 30, h - (i // 2) * ch - 40
        c.setFillGray(0.85)
        c.rect(x0, ytop - 90, 160, 80, fill=1, stroke=0)   # "photo"
        c.setFillGray(0)
        c.setFont("DV", 8)
        for k, ln in enumerate(lines):
            c.drawString(x0, ytop - 108 - k * 10, ln)
        c.setFont("DV", 7)
        c.drawString(x0, ytop - 110 - len(lines) * 10, unit)
        if card:
            c.drawString(x0, ytop - 120 - len(lines) * 10, "Tik su AČIŪ kortele")
        px = x0 + 120
        c.setFont("DV", 33)
        c.drawString(px, ytop - 135, str(eur))
        c.setFont("DV", 23)
        c.drawString(px + c.stringWidth(str(eur), "DV", 33) + 2, ytop - 123, ct)
        c.setFont("DV", 9.4)
        c.drawString(px, ytop - 150, old)
        c.setFont("DV", 14)
        c.drawString(px + 60, ytop - 115, f"-{disc}%")
    c.showPage()
    c.save()


def maxima_html(path: Path) -> None:
    cards = []
    items = [("Bananai, 1 kg", "fruit_veg", "Vaisiai ir daržovės", "1", "19", "1,59", "-25%", "1 kg – 1,19 €", False),
             ("Kava ŠILAS PUPELĖSE, 500 g", "drinks", "Gėrimai", "6", "99", "9,99", "-30%", "1 kg – 13,98 €", True),
             ("Sviestas ŪKIO, 82 %, 200 g", "dairy", "Pieno produktai", "2", "29", "2,99", "-23%", "1 kg – 11,45 €", False)]
    sections = {}
    for n, (name, cat, sec, e, ct, old, disc, unit, card) in enumerate(items, 1):
        icon = '<span class="offer-price-tag__icon"><img alt="Tik su AČIŪ kortele" src="x.png"></span>' if card else ""
        sections.setdefault(sec, []).append(f"""
<div data-controller="offerCard" data-offercard-offer-id="0000000{n}-5e7a-4c1d-9b2e-synthetic{n:04d}" data-categories-multiple="{cat}">
  <img src="https://offers.maxima.lt/media/MarketingOffer/synthetic{n}.png" alt="{name}">
  <h4 class="offer-card__title">{name}</h4>
  <div class="offer-price-tag">{icon}
    <span class="offer-price-tag__price-integer">{e}</span><span class="offer-price-tag__price-fraction">{ct}</span>
    <span class="offer-price-tag__old-price">{old} €</span>
    <span class="offer-price-tag__bottom-discount">{disc}</span>
    <span class="offer-price-tag__meta-comparison">{unit}</span>
    <span class="offer-price-tag__meta-date">Iki 11.16</span>
  </div>
</div>""")
    for sec, cs in sections.items():
        cards.append(f"<section><h2>{sec}</h2>{''.join(cs)}</section>")
    path.write_text("<!doctype html><html lang=lt><body>" + "".join(cards) + "</body></html>", encoding="utf-8")


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    norfa_pdf(OUT / "norfa_synthetic.pdf")
    maxima_html(OUT / "maxima_synthetic.html")
    print("written to", OUT)
