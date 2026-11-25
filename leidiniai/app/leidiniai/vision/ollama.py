"""Ollama vision reader (Qwen2.5-VL by default).

External (`ollama_url` set): nothing is installed here; the model must already be on that Ollama
(`ollama pull qwen2.5vl:7b` on the PC) – a 6 GB download on someone else's machine is not started from here.

Local: the Ollama runtime is downloaded into /data/ollama (the CPU part only: GPU libraries are skipped while
unpacking, ~100 MB on disk; the download itself is the full package, ~1.5 GB) and the model is pulled into
/data/ollama/models (~6 GB for 7B). `ollama serve` runs only while a leaflet is read (and during the first pull),
at the lowest CPU priority, one request at a time, and unloads the model after every page (memory, see read_page).
"""
from __future__ import annotations

import base64
import contextlib
import json
import os
import re
import signal
import subprocess
import threading
import time
from pathlib import Path

import requests

from ..parsers import Offer, finish

DOWNLOAD = "https://ollama.com/download/ollama-linux-amd64.tar.zst"
SKIP_LIBS = ("lib/ollama/cuda_*", "lib/ollama/rocm*", "lib/ollama/vulkan*", "lib/ollama/mlx*", "lib/ollama/*jetpack*")
LOCAL_PORT = 11435  # not the usual 11434: never talk to some other Ollama by mistake
PAGE_TIMEOUT = 1800  # CPU: 1–3 min a page expected; generous for a slow night

PROMPT_VERSION = 2  # part of the saved page results' signature: a new prompt reads the pages again
PICTURE_THREADS = 3  # CPU threads while reading pictures (the box has 4 cores / 8 threads; Ollama runs at nice 19)

PROMPT = """This is one page of a Lithuanian supermarket discount leaflet ({chain}).
List every product offer on the page, in reading order, each offer once. Keys of an offer, in this order; leave a key
out when it is not printed:
- bbox_2d: [x1, y1, x2, y2] pixel box of the whole offer (photo, name and price) on this image.
- name: the product name exactly as printed, in Lithuanian with its letters (ą č ę ė į š ų ū ž), with brand and
  pack size if printed next to it ("Pienas DVARO, 2,5 % rieb., 1 l"). No invented words.
- price: the big current price in euros as a number (1,99 € → 1.99).
- old: the crossed-out / regular price in euros.
- disc: the discount badge as printed ("-25%", "1+1").
- unit_price and unit: price per kg / l / vnt. when printed ("1 kg – 5,98 €" → 5.98 and "kg").
- card: true when the price is only with a loyalty card or app.
- dates: the offer's own dates when printed on it ("LAPKRIČIO 19–21 d."), not the leaflet's dates.
Skip headings, store addresses, opening hours and adverts without a product price or discount.
If the page has no offers, return an empty list."""

SCHEMA = {
    "type": "object",
    "properties": {"offers": {"type": "array", "items": {
        "type": "object",
        "properties": {  # order matters: Qwen2.5-VL was trained to give bbox_2d first
            "bbox_2d": {"type": "array", "items": {"type": "integer"}, "minItems": 4, "maxItems": 4},
            "name": {"type": "string"},
            "price": {"type": "number"},
            "old": {"type": "number"},
            "disc": {"type": "string"},
            "unit_price": {"type": "number"},
            "unit": {"type": "string"},
            "card": {"type": "boolean"},
            "dates": {"type": "string"},
        },
        "required": ["bbox_2d", "name"],
    }}},
    "required": ["offers"],
}

# llama-server writes a progress line every few seconds while answering (n_gen = …): 0.7.0's 200 KB log kept only
# the last two pages. These lines are dropped; timings, errors and the rest stay.
LOG_DROP = re.compile(r"\bn_gen\s*=|decoding image batch|image slice encoded|^\s*$")


# --------------------------------------------------------------------------- local runtime

def _bin(settings) -> Path:
    return settings.ollama_dir / "bin" / "ollama"


def _pidfile(settings) -> Path:
    return settings.ollama_dir / "serve.pid"


def base_url(settings) -> str:
    return settings.ollama_url or f"http://127.0.0.1:{LOCAL_PORT}"


def _alive(url: str) -> bool:
    try:
        return requests.get(url + "/api/version", timeout=3).ok
    except requests.RequestException:
        return False


def install_runtime(settings, log, progress=lambda m: None) -> None:
    ok = settings.ollama_dir / "runtime.ok"  # written only after a complete unpack
    if ok.exists() and _bin(settings).exists():
        return
    import shutil
    if not shutil.which("zstd"):
        raise RuntimeError("zstd is not in this app image (update the app)")
    d = settings.ollama_dir
    d.mkdir(parents=True, exist_ok=True)
    log.info("Picture reader: downloading the Ollama runtime (about 1.5 GB download, ~100 MB kept)")
    progress("atsisiunčiamas Ollama")
    cmd = ["tar", "--zstd", "-x", "-C", str(d)] + [f"--exclude={p}" for p in SKIP_LIBS]
    tar = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    got, last = 0, 0
    try:
        with requests.get(DOWNLOAD, stream=True, timeout=(15, 300)) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length") or 0)
            for chunk in r.iter_content(1 << 20):
                tar.stdin.write(chunk)
                got += len(chunk)
                if total and got * 10 // total > last:
                    last = got * 10 // total
                    progress(f"atsisiunčiamas Ollama {last * 10}%")
        tar.stdin.close()
        err = tar.stderr.read().decode(errors="replace")
        if tar.wait() != 0:
            raise RuntimeError(f"unpacking Ollama failed: {err[-300:]}")
    except BaseException:
        tar.kill()
        raise
    if not _bin(settings).exists():
        raise RuntimeError("the Ollama package had no bin/ollama")
    mb = sum(p.stat().st_size for p in d.rglob("*") if p.is_file()) / 1e6
    ok.write_text(DOWNLOAD)
    log.info("Picture reader: Ollama runtime unpacked (%.0f MB)", mb)


def start_local(settings, log) -> subprocess.Popen | None:
    """Start `ollama serve` unless one of ours already runs. Returns the process we started (or None)."""
    url = base_url(settings)
    if _alive(url):
        return None
    d = settings.ollama_dir
    env = dict(os.environ, OLLAMA_HOST=f"127.0.0.1:{LOCAL_PORT}", OLLAMA_MODELS=str(d / "models"),
               OLLAMA_KEEP_ALIVE="0", OLLAMA_NUM_PARALLEL="1", OLLAMA_MAX_LOADED_MODELS="1",
               OLLAMA_NOPRUNE="1", HOME=str(d))
    p = subprocess.Popen([str(_bin(settings)), "serve"], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         preexec_fn=lambda: os.nice(19), start_new_session=True)
    threading.Thread(target=_copy_log, args=(p.stdout, d / "serve.log"), name="ollama-log", daemon=True).start()
    _pidfile(settings).write_text(str(p.pid))
    for _ in range(60):
        if _alive(url):
            log.info("Ollama started (pid %d)", p.pid)
            return p
        if p.poll() is not None:
            break
        time.sleep(1)
    p.kill()
    raise RuntimeError(f"Ollama did not start; see {d / 'serve.log'}")


def _copy_log(stream, path: Path) -> None:
    """Ollama's output → serve.log without llama-server's progress lines (LOG_DROP)."""
    with open(path, "ab") as f:
        for line in iter(stream.readline, b""):
            if not LOG_DROP.search(line.decode("utf-8", "replace")):
                f.write(line)
                f.flush()


def stop_local(settings, log, proc: subprocess.Popen | None = None) -> None:
    """Stop our `ollama serve`: the process we started, or the one in the pid file (only if it is Ollama)."""
    if proc:
        proc.terminate()
        try:
            proc.wait(15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(5)
        _pidfile(settings).unlink(missing_ok=True)
        log.info("Ollama stopped")
        return
    try:
        pid = int(_pidfile(settings).read_text())
        cmd = Path(f"/proc/{pid}/cmdline").read_bytes()
    except (OSError, ValueError):
        _pidfile(settings).unlink(missing_ok=True)
        return
    if b"ollama" in cmd:  # a pid from an earlier container start may belong to something else now
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGTERM)
            time.sleep(3)
            os.kill(pid, signal.SIGKILL)
        log.info("Ollama stopped (pid %d)", pid)
    _pidfile(settings).unlink(missing_ok=True)


def models(url: str) -> list[str]:
    r = requests.get(url + "/api/tags", timeout=15)
    r.raise_for_status()
    return [m.get("name") or m.get("model") for m in r.json().get("models", [])]


def has_model(names: list[str], model: str) -> bool:
    want = model if ":" in model else model + ":latest"
    return want in names


def pull(url: str, model: str, log, progress=lambda m: None) -> None:
    log.info("Picture reader: pulling model %s (several GB, this takes a while)", model)
    last = -1
    with requests.post(url + "/api/pull", json={"model": model, "stream": True}, stream=True,
                       timeout=(15, 600)) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line:
                continue
            ev = json.loads(line)
            if ev.get("error"):
                raise RuntimeError(f"pull {model}: {ev['error']}")
            if ev.get("total") and ev.get("completed"):
                pct = ev["completed"] * 100 // ev["total"]
                if pct // 10 != last // 10:
                    last = pct
                    progress(f"atsisiunčiamas modelis {model} {pct}%")
                    log.info("Picture reader: %s %d%% of %.1f GB", model, pct, ev["total"] / 1e9)
            elif ev.get("status") == "success":
                return


def prepare(settings, log, progress=lambda m: None) -> str:
    model = settings.ollama_model
    if settings.ollama_url:
        url = settings.ollama_url
        if not _alive(url):
            raise RuntimeError(f"Ollama does not answer at {url}")
        if not has_model(models(url), model):
            raise RuntimeError(f"model {model} is not on {url} – run `ollama pull {model}` there")
        return f"išorinis Ollama {url}, modelis {model}"
    install_runtime(settings, log, progress)
    proc = start_local(settings, log)
    try:
        if not has_model(models(base_url(settings)), model):
            pull(base_url(settings), model, log, progress)
    finally:
        if proc:
            stop_local(settings, log, proc)
    gb = sum(p.stat().st_size for p in (settings.ollama_dir / "models").rglob("*") if p.is_file()) / 1e9
    return f"Ollama šioje mašinoje, modelis {model} ({gb:.1f} GB)"


# --------------------------------------------------------------------------- reading

def _num(v) -> float | None:
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        m = re.search(r"\d+(?:[.,]\d+)?", v)
        if m:
            return float(m.group(0).replace(",", "."))
    return None


def _cents(v, hi=100000) -> int | None:
    x = _num(v)
    if x is None or x <= 0:
        return None
    c = round(x * 100)
    return c if c < hi else None


def model_size(W: int, H: int) -> tuple[int, int]:
    """The size Qwen2.5-VL sees: each side rounded to a multiple of 28 (its boxes are in these pixels)."""
    return max(28, round(W / 28) * 28), max(28, round(H / 28) * 28)


def offers_from_json(data: dict, pno: int, chain: str, size: tuple[int, int]) -> list[Offer]:
    """The model's answer → offers. `crop` is the model's box in pixels of the page picture (snapped to the
    product card later, see cells.py); `extra.dates_text` the offer's own dates as printed."""
    W, H = size
    mw, mh = model_size(W, H)
    sx, sy = W / mw, H / mh
    out = []
    for it in (data or {}).get("offers") or []:
        if not isinstance(it, dict):
            continue
        name = re.sub(r"\s+", " ", str(it.get("name") or "")).strip()
        if not re.search(r"[^\W\d_]{3,}", name):
            continue
        o = Offer(chain=chain, name=name, page=pno)
        o.price = _cents(it.get("price"))
        o.old_price = _cents(it.get("old", it.get("old_price")))
        d = it.get("disc", it.get("discount"))
        if isinstance(d, str) and re.search(r"\d", d):
            o.discount_text = d.strip().replace("–", "-").replace(" ", "")
        o.unit_price = _cents(it.get("unit_price"))
        u = it.get("unit")
        if o.unit_price and isinstance(u, str):
            u = u.strip(" ./").lower()
            o.unit = {"vnt": "vnt", "kg": "kg", "l": "l", "m": "m"}.get(u)
            if not o.unit:
                o.unit_price = None
        if o.price is None:
            if not o.discount_text:
                continue  # neither price nor discount: not an offer
            o.kind = "badge"
        o.card = bool(it.get("card", it.get("card_only")))
        if o.card:
            o.card_text = "kortelė"
        dt = it.get("dates")
        if isinstance(dt, str) and re.search(r"\d", dt):
            o.extra["dates_text"] = dt.strip()[:80]
        b = it.get("bbox_2d", it.get("box"))
        if isinstance(b, list) and len(b) == 4 and all(isinstance(v, (int, float)) for v in b):
            x0, y0, x1, y1 = b[0] * sx, b[1] * sy, b[2] * sx, b[3] * sy
            if 0 <= x0 < x1 <= W * 1.02 and 0 <= y0 < y1 <= H * 1.02 and (x1 - x0) * (y1 - y0) < 0.6 * W * H:
                o.crop = {"x0": round(x0), "top": round(y0), "x1": round(min(x1, W)), "bottom": round(min(y1, H))}
        o.flags.append("vision")
        o.extra["reader"] = "ollama"
        out.append(finish(o))
    return out


class PageCut(Exception):
    """The answer was cut off (answer-length limit) even after reading the page in halves."""


def salvage(content: str) -> tuple[dict, bool]:
    """Answer → (data, complete). A cut-off answer keeps every offer that was complete before the cut
    (Šilas Nr. 23 page 2, 0.8.1: 3 072 tokens, "Expecting ',' delimiter")."""
    try:
        return json.loads(content), True
    except ValueError:
        pass
    i = content.find("[")
    if i < 0:
        return {"offers": []}, False
    depth, in_str, esc, last = 0, False, False, None
    for k in range(i + 1, len(content)):
        ch = content[k]
        if in_str:
            esc = (ch == "\\" and not esc)
            if ch == '"' and not esc:
                in_str = False
            elif ch != "\\":
                esc = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
            if depth == 0 and ch == "}":
                last = k
            if depth < 0:
                break
    if last is None:
        return {"offers": []}, False
    try:
        return json.loads(content[:last + 1] + "]}"), False
    except ValueError:
        return {"offers": []}, False


def _ask(url, model, img_bytes, chain, threads, keep_alive) -> tuple[dict, bool, str]:
    body = {
        "model": model, "stream": False, "format": SCHEMA, "keep_alive": keep_alive,
        "messages": [{"role": "user", "content": PROMPT.format(chain=chain),
                      "images": [base64.b64encode(img_bytes).decode()]}],
        "options": {"temperature": 0, "num_ctx": 8192, "num_predict": NUM_PREDICT, "num_thread": threads,
                    "repeat_penalty": 1.05},
    }
    r = requests.post(url + "/api/chat", json=body, timeout=(15, PAGE_TIMEOUT))
    r.raise_for_status()
    j = r.json()
    content = j.get("message", {}).get("content") or "{}"
    data, complete = salvage(content)
    if j.get("done_reason") == "length":
        complete = False
    return data, complete, content


NUM_PREDICT = 3072
HALF_OVERLAP = 0.12   # halves overlap by this share of the page height (an offer on the cut is whole in one half)


def read_page(url: str, model: str, img: Path, pno: int, chain: str, threads: int,
              keep_alive: str | int = 0, raw_dir: Path | None = None) -> list[Offer]:
    """One page. keep_alive 0 (local): the model is unloaded after the page, which also drops llama-server's
    prompt cache (0.7.0: +~200 MB per page, 8 GB allowed). Loading it again takes seconds; a page takes minutes.
    A cut-off answer (0.8.2): the complete offers are kept and the page is read again as a top and a bottom half
    (overlapping); offers seen in both are kept once."""
    import io

    from PIL import Image
    im = Image.open(img).convert("RGB")
    W, H = im.size
    data, complete, raw = _ask(url, model, img.read_bytes(), chain, threads, keep_alive)
    offers = offers_from_json(data, pno, chain, (W, H))
    if complete:
        return offers
    _save_raw(raw_dir, chain, pno, "page", raw)
    halves, cut = [], False
    mid = H // 2
    ov = int(H * HALF_OVERLAP / 2)
    for top, bottom in ((0, min(H, mid + ov)), (max(0, mid - ov), H)):
        part = im.crop((0, top, W, bottom))
        buf = io.BytesIO()
        part.save(buf, "JPEG", quality=92)
        d, ok, raw = _ask(url, model, buf.getvalue(), chain, threads, keep_alive)
        if not ok:
            cut = True
            _save_raw(raw_dir, chain, pno, f"half{top}", raw)
        for o in offers_from_json(d, pno, chain, part.size):
            if o.crop:
                o.crop = {**o.crop, "top": o.crop["top"] + top, "bottom": o.crop["bottom"] + top}
            halves.append(o)
    merged = _dedupe(halves + offers)
    if cut and not merged:
        raise PageCut(f"page {pno}: the answer was cut off even in halves")
    for o in merged:
        o.extra["read"] = "halves"
    return merged


def _dedupe(offers: list[Offer]) -> list[Offer]:
    from ..textutil import fold
    out, seen = [], set()
    for o in offers:
        k = (fold(o.name)[:40], o.price, o.discount_text)
        if k in seen:
            continue
        seen.add(k)
        out.append(o)
    return out


def _save_raw(raw_dir, chain, pno, what, raw) -> None:
    if not raw_dir:
        return
    try:
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / f"{chain}-p{pno:02d}-{what}.txt").write_text(raw or "", encoding="utf-8")
    except OSError:
        pass


def signature(settings) -> str:
    return f"ollama|{settings.ollama_model}|p{PROMPT_VERSION}"


@contextlib.contextmanager
def session(settings, log):
    url = base_url(settings)
    proc = None
    if not settings.ollama_url:
        proc = start_local(settings, log)
    try:
        threads = max(settings.threads, min(PICTURE_THREADS, (os.cpu_count() or 4) - 1))
        # an external Ollama (a PC) keeps its model loaded between pages as usual
        keep = 0 if not settings.ollama_url else "2m"
        raw_dir = settings.log_dir / "vision-raw"
        yield lambda img, pno, chain: read_page(url, settings.ollama_model, img, pno, chain, threads, keep, raw_dir)
    finally:
        if proc:
            stop_local(settings, log, proc)
