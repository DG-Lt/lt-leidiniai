"""Picture reader for image-only leaflets (Šilas, Rimi catalogues without text): option `picture_reader`.

- `none`      – image-only leaflets wait ("laukia skaitytuvo").
- `tesseract` – local OCR (binary in the image, `lit` + `eng` traineddata downloaded into /data/models, ~25 MB).
                Light enough for any box, but reads only plainly printed prices.
- `ollama`    – a local vision model (Qwen2.5-VL). With `ollama_url` set it uses an Ollama running elsewhere
                (a PC) and installs nothing here; otherwise the Ollama runtime (CPU part, ~100 MB on disk) and the
                model (~6 GB for 7B) are downloaded into /data/ollama and Ollama runs only while a leaflet is read.

`reconcile()` runs at start-up (in a background thread): it downloads what the selected reader needs and deletes
the files of a reader no longer selected. `parse_issue()` runs inside the low-priority job process.
"""
from __future__ import annotations

import json
import shutil
import threading
from pathlib import Path

from ..db import now_iso

_lock = threading.Lock()


class NoPictures(Exception):
    """The leaflet has no page pictures stored (Rimi images-only catalogue): nothing to read yet."""


def status_file(settings) -> Path:
    return settings.data_dir / "picture_reader.json"


def read_status(settings) -> dict:
    try:
        return json.loads(status_file(settings).read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_status(settings, **kw) -> dict:
    st = read_status(settings) | kw | {"updated": now_iso()}
    status_file(settings).write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    return st


def ready(settings) -> bool:
    """Can image-only leaflets be read now?"""
    st = read_status(settings)
    if settings.picture_reader == "none":
        return False
    want = _signature(settings)
    return st.get("state") == "ready" and st.get("signature") == want


def _signature(settings) -> str:
    if settings.picture_reader == "ollama":
        return f"ollama|{settings.ollama_url or 'local'}|{settings.ollama_model}"
    return settings.picture_reader


def reconcile(settings, log) -> dict:
    """Make the files on disk match the option. Safe to call again (does nothing when ready)."""
    with _lock:
        sel = settings.picture_reader
        local_ollama = sel == "ollama" and not settings.ollama_url
        if sel != "tesseract" and settings.tessdata_dir.exists():
            shutil.rmtree(settings.tessdata_dir.parent, ignore_errors=True)
            log.info("Picture reader: Tesseract language files deleted (reader is now '%s')", sel)
        if not local_ollama and settings.ollama_dir.exists():
            from . import ollama
            ollama.stop_local(settings, log)
            shutil.rmtree(settings.ollama_dir, ignore_errors=True)
            log.info("Picture reader: local Ollama and its models deleted (reader is now '%s'%s)", sel,
                     ", external Ollama" if sel == "ollama" else "")
        if sel == "none":
            return write_status(settings, state="off", signature="none", message="išjungtas")
        if ready(settings):
            return read_status(settings)
        write_status(settings, state="preparing", signature=_signature(settings), message="ruošiamas")
        try:
            if sel == "tesseract":
                from . import tesseract
                msg = tesseract.prepare(settings, log)
            else:
                from . import ollama
                msg = ollama.prepare(settings, log, progress=lambda m: write_status(settings, message=m))
        except Exception as e:
            log.error("Picture reader '%s' not ready: %s", sel, e)
            return write_status(settings, state="error", message=str(e)[:300])
        log.info("Picture reader '%s' ready: %s", sel, msg)
        return write_status(settings, state="ready", signature=_signature(settings), message=msg)


def start_background(settings, log) -> threading.Thread:
    t = threading.Thread(target=reconcile, args=(settings, log), name="picture-reader", daemon=True)
    t.start()
    return t


def _reader(settings):
    if settings.picture_reader == "tesseract":
        from . import tesseract as reader
    else:
        from . import ollama as reader
    return reader


def offer_from_dict(d: dict):
    from datetime import date as _date

    from ..parsers import Offer
    d = dict(d)
    for k in ("valid_from", "valid_to"):
        if d.get(k):
            d[k] = _date.fromisoformat(d[k])
    return Offer(**d)


def place_offers(offers, img_path: Path) -> None:
    """Snap each offer's box (model pixels of its page picture) to the product card it sits in (cells.py).
    Pages without cards (free collage) keep the model's box with a margin."""
    from PIL import Image

    from . import cells
    img = Image.open(img_path)
    W, H = img.size
    found = cells.find_cells(img)
    areas = sorted((c[2] - c[0]) * (c[3] - c[1]) for c in found)
    median = areas[len(areas) // 2] if areas else 0
    pad = round(0.02 * W)
    for o in offers:
        if not o.crop:
            continue
        box = (o.crop["x0"], o.crop["top"], o.crop["x1"], o.crop["bottom"])
        c = cells.snap(box, found)
        if c:
            area = (c[2] - c[0]) * (c[3] - c[1])
            barea = max(1, (box[2] - box[0]) * (box[3] - box[1]))
            # one big region holding several cards (few cells found on the page): not a card
            if (len(found) >= 3 and area > 1.6 * median) or (len(found) < 3 and barea < 0.25 * area):
                c = None
        if c:
            o.crop = {"x0": c[0], "top": c[1], "x1": c[2], "bottom": c[3]}
            o.extra["crop"] = "card"
        else:
            o.crop = {"x0": max(0, box[0] - pad), "top": max(0, box[1] - pad),
                      "x1": min(W, box[2] + pad), "bottom": min(H, box[3] + pad)}
            o.extra["crop"] = "model"


def offer_dates(offers, issue) -> None:
    """Offers with their own dates printed ('LAPKRIČIO 19–21 d.', Šilas 3D akcija) get them, if inside the leaflet's
    validity (± a week, a wrong reading must not hide or extend an offer)."""
    from datetime import date as _date, timedelta

    from ..textutil import offer_range
    vf = _date.fromisoformat(issue["valid_from"]) if issue["valid_from"] else None
    vt = _date.fromisoformat(issue["valid_to"]) if issue["valid_to"] else None
    ref = vf or _date.today()
    for o in offers:
        t = o.extra.get("dates_text")
        if not t:
            continue
        a, b = offer_range(t, ref)
        lo = (vf - timedelta(days=7)) if vf else None
        hi = (vt + timedelta(days=7)) if vt else None
        ok = all(x is None or ((lo is None or x >= lo) and (hi is None or x <= hi)) for x in (a, b))
        if (a or b) and ok and (not a or not b or a <= b):
            o.valid_from, o.valid_to = a or o.valid_from, b or o.valid_to


def parse_issue(settings, issue, files: list[dict], log, conn=None, progress=lambda page, pages: None):
    """Read an image-only leaflet. Returns (offers, {offer index: crop path relative to img_dir}).

    With `conn`, each page's result is saved as soon as it is read (table vision_pages) and pages already read with
    the same reader, model, prompt and picture size are not read again: a restart or an update continues from the
    next page. The reader (Ollama) is started only when a page has to be read."""
    import contextlib
    import time

    from . import pages
    rel = Path(issue["chain"]) / str(issue["id"])
    work = settings.tmp_dir / "vision" / str(issue["id"])
    imgs = pages.page_images(files, work, log)
    if not imgs:
        raise NoPictures("no page pictures stored for this leaflet")
    reader = _reader(settings)
    base_sig = reader.signature(settings)
    offers = []
    try:
        with contextlib.ExitStack() as stack:
            read_page = None
            for n, img in enumerate(imgs, start=1):
                from PIL import Image
                sig = f"{base_sig}|{'x'.join(map(str, Image.open(img).size))}"
                row = conn.execute("SELECT sig, offers FROM vision_pages WHERE issue_id=? AND page=?",
                                   (issue["id"], n)).fetchone() if conn is not None else None
                progress(n, len(imgs))
                if row and row["sig"] == sig:
                    got = [offer_from_dict(d) for d in json.loads(row["offers"])]
                    log.info("%s %s: page %d/%d – %d offer(s) (read earlier)", issue["chain"], issue["key"], n,
                             len(imgs), len(got))
                else:
                    if read_page is None:
                        read_page = stack.enter_context(reader.session(settings, log))
                    t = time.monotonic()
                    got = read_page(img, n, issue["chain"])
                    secs = time.monotonic() - t
                    log.info("%s %s: page %d/%d – %d offer(s) in %.0f s", issue["chain"], issue["key"], n, len(imgs),
                             len(got), secs)
                    if conn is not None:
                        with conn:
                            conn.execute("INSERT OR REPLACE INTO vision_pages(issue_id,page,sig,offers,seconds,read_at)"
                                         " VALUES(?,?,?,?,?,?)",
                                         (issue["id"], n, sig, json.dumps([o.as_dict() for o in got], ensure_ascii=False),
                                          round(secs, 1), now_iso()))
                place_offers(got, img)
                offers += got
        offer_dates(offers, issue)
        out_dir = settings.img_dir / rel
        if out_dir.exists():
            shutil.rmtree(out_dir)
        names = pages.crops(offers, imgs, out_dir)
        return offers, {i: str(rel / fn) for i, fn in names.items()}
    finally:
        shutil.rmtree(work, ignore_errors=True)
