"""Page pictures of an image-only leaflet (PDF pages rendered, or the shop's JPEG/PNG pages) and offer crops."""
from __future__ import annotations

from pathlib import Path

MAX_SIDE = 1600  # long side of a page picture given to a reader at most
IMG_EXT = (".jpg", ".jpeg", ".png", ".webp")


def native_long_side(page) -> int | None:
    """Image-only PDF page: long side in pixels of its biggest picture (Šilas: 992×1403 JPEG per page), so the page
    is not blown up beyond what was printed into it (0.7: 1600 px = 23 % more picture tokens, no more detail)."""
    import pypdfium2.raw as raw
    best = None
    for obj in page.get_objects(filter=(raw.FPDF_PAGEOBJ_IMAGE,), max_depth=2):
        try:
            w, h = obj.get_px_size()
        except Exception:
            continue
        if not best or w * h > best[0] * best[1]:
            best = (w, h)
    return max(best) if best and min(best) >= 300 else None


def page_images(files: list[dict], work: Path, log) -> list[Path]:
    """PDFs first (all pages), else the picture files in name order. Saved as PNG under `work`."""
    from PIL import Image
    work.mkdir(parents=True, exist_ok=True)
    out: list[Path] = []
    pdfs = [f for f in files if f["name"].lower().endswith(".pdf")]
    if pdfs:
        import pypdfium2 as pdfium
        for f in pdfs:
            doc = pdfium.PdfDocument(f["path"])
            try:
                for i in range(len(doc)):
                    page = doc[i]
                    w, h = page.get_size()
                    side = min(MAX_SIDE, native_long_side(page) or MAX_SIDE)
                    img = page.render(scale=side / max(w, h)).to_pil().convert("RGB")
                    p = work / f"{Path(f['name']).stem}_p{i + 1:02d}.png"
                    img.save(p)
                    out.append(p)
                    page.close()
            finally:
                doc.close()
        return out
    for f in sorted((f for f in files if f["name"].lower().endswith(IMG_EXT)), key=lambda f: f["name"]):
        img = Image.open(f["path"]).convert("RGB")
        img.thumbnail((MAX_SIDE, MAX_SIDE))
        p = work / (Path(f["name"]).stem + ".png")
        img.save(p)
        out.append(p)
    if not out:
        log.info("no PDF or page pictures among %s", [f["name"] for f in files])
    return out


def crops(offers, imgs: list[Path], out_dir: Path, pad: int = 6, max_side: int = 900) -> dict[int, str]:
    """offer.crop is in pixels of its page picture (offer.page, 1-based). Returns {index: file name}."""
    from PIL import Image
    by_page: dict[int, list[int]] = {}
    for i, o in enumerate(offers):
        if o.crop and o.page and o.page <= len(imgs):
            by_page.setdefault(o.page, []).append(i)
    names: dict[int, str] = {}
    if not by_page:
        return names
    out_dir.mkdir(parents=True, exist_ok=True)
    for p, idx in by_page.items():
        img = Image.open(imgs[p - 1])
        for i in idx:
            c = offers[i].crop
            bx = (max(0, int(c["x0"]) - pad), max(0, int(c["top"]) - pad),
                  min(img.width, int(c["x1"]) + pad), min(img.height, int(c["bottom"]) + pad))
            if bx[2] - bx[0] < 20 or bx[3] - bx[1] < 20:
                continue
            im = img.crop(bx)
            im.thumbnail((max_side, max_side))
            fn = f"v{p:02d}_{i:04d}.jpg"
            im.save(out_dir / fn, quality=80, optimize=True)
            names[i] = fn
    return names
