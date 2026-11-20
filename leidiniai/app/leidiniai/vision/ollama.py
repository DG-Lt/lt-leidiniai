"""Ollama vision reader (Qwen2.5-VL by default).

External (`ollama_url` set): nothing is installed here; the model must already be on that Ollama
(`ollama pull qwen2.5vl:7b` on the PC) – a 6 GB download on someone else's machine is not started from here.

Local: the Ollama runtime is downloaded into /data/ollama (the CPU part only: GPU libraries are skipped while
unpacking, ~100 MB on disk; the download itself is the full package, ~1.5 GB) and the model is pulled into
/data/ollama/models (~6 GB for 7B). `ollama serve` runs only while a leaflet is read (and during the first pull),
at the lowest CPU priority, one request at a time, and unloads the model 2 minutes after the last page.
"""
from __future__ import annotations

import base64
import contextlib
import json
import os
import re
import signal
import subprocess
import time
from pathlib import Path

import requests

from ..parsers import Offer, finish

DOWNLOAD = "https://ollama.com/download/ollama-linux-amd64.tar.zst"
SKIP_LIBS = ("lib/ollama/cuda_*", "lib/ollama/rocm*", "lib/ollama/vulkan*", "lib/ollama/mlx*", "lib/ollama/*jetpack*")
LOCAL_PORT = 11435  # not the usual 11434: never talk to some other Ollama by mistake
PAGE_TIMEOUT = 1800  # CPU: 1–3 min a page expected; generous for a slow night

PROMPT = """This is one page of a Lithuanian supermarket discount leaflet ({chain}).
List every product offer on the page. For each offer give:
- name: the product name exactly as printed, in Lithuanian with its letters (ą č ę ė į š ų ū ž), including brand
  and pack size if printed next to it ("Pienas DVARO, 2,5 % rieb., 1 l"). No invented words.
- price: the big current price in euros as a number (1,99 € → 1.99). null when only a discount is printed.
- old_price: the crossed-out / regular price in euros, or null.
- discount: the discount badge as printed ("-25%", "1+1"), or null.
- unit_price and unit: the price per kg / l / vnt. if printed ("1 kg – 5,98 €" → 5.98, "kg"), else null.
- card_only: true when the price is only with a loyalty card or app.
- box: [x0, y0, x1, y1] pixel coordinates of the offer (photo, name and price) on this image.
Skip headings, store addresses, opening hours and adverts without a product price or discount.
If the page has no offers, return an empty list."""

SCHEMA = {
    "type": "object",
    "properties": {"offers": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "price": {"type": ["number", "null"]},
            "old_price": {"type": ["number", "null"]},
            "discount": {"type": ["string", "null"]},
            "unit_price": {"type": ["number", "null"]},
            "unit": {"type": ["string", "null"]},
            "card_only": {"type": "boolean"},
            "box": {"type": ["array", "null"], "items": {"type": "number"}},
        },
        "required": ["name", "price"],
    }}},
    "required": ["offers"],
}


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
               OLLAMA_KEEP_ALIVE="2m", OLLAMA_NUM_PARALLEL="1", OLLAMA_MAX_LOADED_MODELS="1",
               OLLAMA_NOPRUNE="1", HOME=str(d))
    logf = open(d / "serve.log", "ab")
    p = subprocess.Popen([str(_bin(settings)), "serve"], env=env, stdout=logf, stderr=subprocess.STDOUT,
                         preexec_fn=lambda: os.nice(19), start_new_session=True)
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


def offers_from_json(data: dict, pno: int, chain: str, size: tuple[int, int]) -> list[Offer]:
    W, H = size
    out = []
    for it in (data or {}).get("offers") or []:
        if not isinstance(it, dict):
            continue
        name = re.sub(r"\s+", " ", str(it.get("name") or "")).strip()
        if not re.search(r"[^\W\d_]{3,}", name):
            continue
        o = Offer(chain=chain, name=name, page=pno)
        o.price = _cents(it.get("price"))
        o.old_price = _cents(it.get("old_price"))
        d = it.get("discount")
        if isinstance(d, str) and d.strip():
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
        o.card = bool(it.get("card_only"))
        if o.card:
            o.card_text = "kortelė"
        b = it.get("box")
        if isinstance(b, list) and len(b) == 4 and all(isinstance(v, (int, float)) for v in b):
            x0, y0, x1, y1 = b
            if 0 <= x0 < x1 <= W * 1.02 and 0 <= y0 < y1 <= H * 1.02 and (x1 - x0) * (y1 - y0) < 0.6 * W * H:
                o.crop = {"x0": x0, "top": y0, "x1": min(x1, W), "bottom": min(y1, H)}
        o.flags.append("vision")
        o.extra["reader"] = "ollama"
        out.append(finish(o))
    return out


def read_page(url: str, model: str, img: Path, pno: int, chain: str, threads: int) -> list[Offer]:
    from PIL import Image
    size = Image.open(img).size
    body = {
        "model": model, "stream": False, "format": SCHEMA, "keep_alive": "2m",
        "messages": [{"role": "user", "content": PROMPT.format(chain=chain),
                      "images": [base64.b64encode(img.read_bytes()).decode()]}],
        "options": {"temperature": 0, "num_ctx": 8192, "num_predict": 4096, "num_thread": threads},
    }
    r = requests.post(url + "/api/chat", json=body, timeout=(15, PAGE_TIMEOUT))
    r.raise_for_status()
    content = r.json().get("message", {}).get("content") or "{}"
    try:
        data = json.loads(content)
    except ValueError:
        m = re.search(r"\{.*\}", content, re.S)
        data = json.loads(m.group(0)) if m else {}
    return offers_from_json(data, pno, chain, size)


@contextlib.contextmanager
def session(settings, log):
    url = base_url(settings)
    proc = None
    if not settings.ollama_url:
        proc = start_local(settings, log)
    try:
        yield lambda img, pno, chain: read_page(url, settings.ollama_model, img, pno, chain, settings.threads)
    finally:
        if proc:
            stop_local(settings, log, proc)
