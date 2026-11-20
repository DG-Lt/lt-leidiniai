"""Tesseract OCR reader. The binary is in the image (apt tesseract-ocr, a few MB); the language data
(`lit` + `eng`, tessdata_best, ~25 MB) is downloaded into /data/models/tessdata when the reader is selected.

OCR words (pixels) are scaled to A4 points and handed to the same price/name grouping as the PDF text layer
(`pdf_text.parse_words`). Stylised big prices are often not read – then the offer is missed; use Ollama for those.
"""
from __future__ import annotations

import contextlib
import csv
import io
import os
import re
import shutil
import subprocess
from pathlib import Path

from ..parsers import pdf_text

LANGS = ("lit", "eng")
URL = "https://github.com/tesseract-ocr/tessdata_best/raw/main/{lang}.traineddata"
A4_W = 595.0
UPSCALE_BELOW = 700  # only very small page pictures are enlarged ×2 (enlarging loses the big price digits)

# sizes are word heights in points / 0.75 (≈ font size); measured roughly, a weak box gets what it can
CFG = pdf_text.ChainCfg(price_min=24, old_min=7, old_max=16, disc_min=18, text_max=17, maxd=120,
                        card_words=("kortel",), noise=(r"^Akcija$", r"^AKCIJA$"))


def binary() -> str | None:
    return shutil.which("tesseract")


def prepare(settings, log) -> str:
    if not binary():
        raise RuntimeError("tesseract is not in this app image (update the app)")
    import requests
    d = settings.tessdata_dir
    d.mkdir(parents=True, exist_ok=True)
    for lang in LANGS:
        f = d / f"{lang}.traineddata"
        if f.exists() and f.stat().st_size > 1_000_000:
            continue
        log.info("Picture reader: downloading Tesseract language '%s'", lang)
        tmp = f.with_suffix(".part")
        with requests.get(URL.format(lang=lang), stream=True, timeout=(15, 300)) as r:
            r.raise_for_status()
            with open(tmp, "wb") as fh:
                for chunk in r.iter_content(1 << 20):
                    fh.write(chunk)
        if tmp.stat().st_size < 1_000_000:
            tmp.unlink()
            raise RuntimeError(f"language file '{lang}' looks wrong (too small)")
        tmp.replace(f)
    mb = sum(p.stat().st_size for p in d.iterdir()) / 1e6
    return f"Tesseract, kalbos {'+'.join(LANGS)} ({mb:.0f} MB)"


def ocr_words(img_path: Path, settings) -> tuple[list[dict], float]:
    """Words in A4 points: [{text, x0, x1, top, bottom, size, i}], and the points-per-pixel factor."""
    from PIL import Image
    img = Image.open(img_path)
    src = img_path
    zoom = 1.0
    if img.width < UPSCALE_BELOW:
        zoom = 2.0
        src = img_path.with_name(img_path.stem + "_x2.png")
        img.resize((img.width * 2, img.height * 2), Image.LANCZOS).save(src)
    env = dict(os.environ, TESSDATA_PREFIX=str(settings.tessdata_dir), OMP_THREAD_LIMIT=str(settings.threads))
    r = subprocess.run([binary(), str(src), "-", "-l", "+".join(LANGS), "--psm", "11", "tsv"],
                       capture_output=True, env=env, timeout=600)
    if r.returncode != 0:
        raise RuntimeError(f"tesseract: {r.stderr.decode(errors='replace')[-300:]}")
    k = A4_W / (img.width * zoom)
    return words_from_tsv(r.stdout.decode("utf-8", errors="replace"), k), k * zoom


def words_from_tsv(tsv: str, k: float, min_conf: float = 30) -> list[dict]:
    out = []
    for row in csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE):
        if row.get("level") != "5" or not (row.get("text") or "").strip():
            continue
        try:
            conf = float(row["conf"])
        except (TypeError, ValueError):
            continue
        if conf < min_conf:
            continue
        x, y, w, h = (int(row[c]) * k for c in ("left", "top", "width", "height"))
        size = round(h / 0.75, 1)
        out.append({"text": price_text(row["text"].strip(), size), "x0": x, "x1": x + w, "top": y, "bottom": y + h,
                    "size": size, "i": len(out)})
    return out


def price_text(t: str, size: float) -> str:
    """OCR of a big price: '1.99' → '1,99'; euros + superscript cents read as one number '199' → '1,99'."""
    if re.fullmatch(r"\d{1,3}[.,]\d\d", t):
        return t.replace(".", ",")
    if size >= CFG.price_min and re.fullmatch(r"\d{3,5}", t):
        return f"{int(t[:-2])},{t[-2:]}"
    return t


@contextlib.contextmanager
def session(settings, log):
    def read_page(img: Path, pno: int, chain: str):
        ws, pt_per_px = ocr_words(img, settings)
        offers = pdf_text.parse_words(ws, [], pno, chain, CFG)
        for o in offers:  # crops are taken from the page picture: points → pixels
            if o.crop:
                o.crop = {key: v / pt_per_px for key, v in o.crop.items()}
            o.flags.append("ocr")
            o.extra["reader"] = "tesseract"
        return offers
    yield read_page
