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


def parse_issue(settings, issue, files: list[dict], log):
    """Read an image-only leaflet. Returns (offers, {offer index: crop path relative to img_dir})."""
    from . import pages
    rel = Path(issue["chain"]) / str(issue["id"])
    work = settings.tmp_dir / "vision" / str(issue["id"])
    imgs = pages.page_images(files, work, log)
    if not imgs:
        raise NoPictures("no page pictures stored for this leaflet")
    if settings.picture_reader == "tesseract":
        from . import tesseract as reader
    else:
        from . import ollama as reader
    offers = []
    try:
        with reader.session(settings, log) as read_page:
            for n, img in enumerate(imgs, start=1):
                got = read_page(img, n, issue["chain"])
                log.info("%s %s: page %d/%d – %d offer(s)", issue["chain"], issue["key"], n, len(imgs), len(got))
                offers += got
        out_dir = settings.img_dir / rel
        if out_dir.exists():
            shutil.rmtree(out_dir)
        names = pages.crops(offers, imgs, out_dir)
        return offers, {i: str(rel / fn) for i, fn in names.items()}
    finally:
        shutil.rmtree(work, ignore_errors=True)
