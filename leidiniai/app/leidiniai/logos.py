"""Chain logos for the offer cards.

No logo is stored in the repository (the logos are the shops' trademarks). Each box gets them itself:
- automatically: after a chain's check, its logo is downloaded once from the shop's own site (URLs below,
  checked 2026-11-20) and refreshed every 30 days – one small request, spaced like every other;
- by the user: Būsena → "Tinklų logotipai" uploads a file, which always wins over the automatic one.
Files live in <data>/logos/: `user-<chain>.<ext>` and `auto-<chain>.<ext>`. Without a file the card shows the
chain name as before.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

SOURCES = {
    "iki": "https://iki.lt/apple-touch-icon.png",
    "lidl": "https://www.lidl.lt/static/assets/lidl-shop-lietuva-271840.svg",
    "maxima": "https://www.maxima.lt/upl/media/x80/05/7595-MicrosoftTeams-image%20%2839%29.png?v=3-0",
    "norfa": "https://www.norfa.lt/assets/Uploads/Images/Norfa-logo.svg",
    "rimi": "https://www.rimi.lt/apple-touch-icon.png",
    "silas": "https://www.silas.lt/wp-content/themes/SILAS_Responsive/favicons/apple-touch-icon-152x152.png",
}
EXT = (".png", ".svg", ".webp", ".jpg")
MAX_BYTES = 512 * 1024
REFRESH_DAYS = 30
MIME = {".png": "image/png", ".svg": "image/svg+xml", ".webp": "image/webp", ".jpg": "image/jpeg"}


def folder(settings) -> Path:
    return settings.data_dir / "logos"


def kind_of(data: bytes) -> str | None:
    """File type from the content (not the name): .png .jpg .webp .svg, else None."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    head = data[:2048].lstrip().lower()
    if (head.startswith(b"<?xml") or head.startswith(b"<svg") or head.startswith(b"<!--")) and b"<svg" in data[:4096].lower():
        return ".svg"
    return None


def find(settings, chain: str, who: str | None = None) -> Path | None:
    """Best logo file: the user's upload, else the automatic one. who='user'/'auto' limits the search."""
    d = folder(settings)
    for w in ((who,) if who else ("user", "auto")):
        for e in EXT:
            p = d / f"{w}-{chain}{e}"
            if p.exists():
                return p
    return None


def clean(data: bytes, clear_white: bool = False) -> tuple[bytes, str]:
    """Raster logo → PNG with the empty margins cut off (white or transparent around the logo), so it fills the
    chip height. clear_white: also make the white background around the logo transparent (only the white that
    touches the edges – white letters inside the logo stay). SVG is returned unchanged."""
    ext = kind_of(data)
    if ext in (None, ".svg"):
        return data, ext
    import io
    from PIL import Image, ImageChops, ImageDraw
    im = Image.open(io.BytesIO(data))
    im.load()
    im = im.convert("RGBA")
    if clear_white:
        w, h = im.size
        rgb = im.convert("RGB")
        mask = Image.new("L", im.size, 0)
        seeds = [(x, y) for x in range(0, w, max(1, w // 40)) for y in (0, h - 1)] + \
                [(x, y) for y in range(0, h, max(1, h // 40)) for x in (0, w - 1)]
        for sx, sy in seeds:  # flood-fill near-white from the border
            r, g, b = rgb.getpixel((sx, sy))
            if min(r, g, b) >= 225 and mask.getpixel((sx, sy)) == 0:
                ImageDraw.floodfill(rgb, (sx, sy), (1, 2, 3), thresh=40)
        px = rgb.load()
        mp = mask.load()
        for y in range(h):
            for x in range(w):
                if px[x, y] == (1, 2, 3):
                    mp[x, y] = 255
        alpha = ImageChops.subtract(im.getchannel("A"), mask)
        im.putalpha(alpha)
    # margins: transparent pixels, or the corner colour when the picture has no transparency
    alpha = im.getchannel("A")
    box = alpha.point(lambda a: 255 if a > 16 else 0).getbbox()
    if box and alpha.getextrema()[0] >= 250:  # opaque picture: cut the plain border of the corner colour
        bg = Image.new("RGBA", im.size, im.getpixel((0, 0)))
        diff = ImageChops.difference(im, bg).convert("L").point(lambda v: 255 if v > 24 else 0)
        box = diff.getbbox() or box
    if box:
        im = im.crop(box)
    if im.height > 160:  # chips are ~20–28 px high; keep files small
        im = im.resize((max(1, round(im.width * 160 / im.height)), 160), Image.LANCZOS)
    out = io.BytesIO()
    im.save(out, "PNG", optimize=True)
    return out.getvalue(), ".png"


def _write(settings, who: str, chain: str, data: bytes, clear_white: bool = False) -> Path:
    ext = kind_of(data)
    if not ext:
        raise ValueError("ne paveikslėlis (tinka PNG, JPG, WEBP, SVG)")
    if len(data) > MAX_BYTES:
        raise ValueError(f"per didelis failas (daugiausia {MAX_BYTES // 1024} KB)")
    try:
        data, ext = clean(data, clear_white)
    except Exception as e:  # a picture Pillow can't read: refuse rather than store something broken
        raise ValueError(f"nepavyko apdoroti paveikslėlio ({e})") from e
    d = folder(settings)
    d.mkdir(parents=True, exist_ok=True)
    for e in EXT:
        (d / f"{who}-{chain}{e}").unlink(missing_ok=True)
    p = d / f"{who}-{chain}{ext}"
    p.write_bytes(data)
    return p


def save_upload(settings, chain: str, data: bytes, clear_white: bool = True) -> Path:
    return _write(settings, "user", chain, data, clear_white)


def tidy_existing(settings, log: logging.Logger) -> None:
    """At start: cut the margins of logos saved by 0.4.5 (no trimming then). Idempotent; never raises."""
    d = folder(settings)
    if not d.exists():
        return
    for p in d.glob("*.*"):
        if p.suffix not in (".png", ".jpg", ".webp") or (d / ".tidy-1").exists():
            continue
        try:
            data, ext = clean(p.read_bytes(), clear_white=False)
            p.unlink()
            p.with_suffix(ext).write_bytes(data)
        except Exception as e:
            log.warning("logo %s not tidied: %s", p.name, e)
    try:
        (d / ".tidy-1").touch()
    except OSError:
        pass


def remove_upload(settings, chain: str) -> None:
    for e in EXT:
        (folder(settings) / f"user-{chain}{e}").unlink(missing_ok=True)


def refresh(settings, chain: str, http, log: logging.Logger) -> None:
    """After a check: fetch the automatic logo if missing or older than REFRESH_DAYS. Never raises."""
    url = SOURCES.get(chain)
    if not url or find(settings, chain, "user"):
        return
    cur = find(settings, chain, "auto")
    if cur and time.time() - cur.stat().st_mtime < REFRESH_DAYS * 86400:
        return
    try:
        r = http._get(url)
        if r.status_code != 200:
            raise ValueError(f"HTTP {r.status_code}")
        _write(settings, "auto", chain, r.content)
        log.info("%s: logo saved from %s", chain, url)
    except Exception as e:  # a missing logo only means the name is shown instead
        log.warning("%s: logo not downloaded (%s): %s", chain, e, url)
        if cur:
            cur.touch()  # keep the old one, try again in 30 days
