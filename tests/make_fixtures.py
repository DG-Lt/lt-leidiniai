"""Build the small parser fixtures in tests/fixtures/ from full leaflet files (dev tool, not run by CI).

The output is shop material and is NOT committed (tests/fixtures/ is in .gitignore); the real-page
parser tests run only where it exists.

    python tests/make_fixtures.py <folder with the test files>

PDFs: only the pages listed below, every image replaced by a 1×1 grey JPEG (positions and sizes on the
page stay the same, so photo-based crops still work); Maxima HTML and Rimi JSON: gzipped as they are.
"""
from __future__ import annotations

import gzip
import shutil
import sys
from pathlib import Path

import pikepdf

OUT = Path(__file__).resolve().parent / "fixtures"
PDFS = {  # source file → (fixture name, 1-based pages)
    "B47-bazinis_www.pdf": ("iki_b47_p4-10-24-37.pdf", [4, 10, 24, 37]),
    "MAISTO-PREKIU-PASIULYMAI-Nuo-lapkricio-16-d-00.pdf": ("lidl_kw47_p4-6.pdf", [4, 6]),
    "Norfa523-Web2.pdf": ("norfa_523_p4.pdf", [4]),
}
COPIES = {
    "maxima_pasiulymai.html": "maxima_pasiulymai.html.gz",
    "rimi_nr46_enrichments.json": "rimi_nr46_enrichments.json.gz",
    "rimi_nr46_eshop.json": "rimi_nr46_eshop.json.gz",
}
GREY_JPEG = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb004300080606070605080707070909080a0c140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c"
    "20242e2720222c231c1c2837292c30313434341f27393d38323c2e333432ffc0000b080001000101011100ffc4001f0000010501010101010100"
    "000000000000000102030405060708090a0bffc400b5100002010303020403050504040000017d01020300041105122131410613516107227114"
    "328191a1082342b1c11552d1f02433627282090a161718191a25262728292a3435363738393a434445464748494a535455565758595a63646566"
    "6768696a737475767778797a838485868788898a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3"
    "d4d5d6d7d8d9dae1e2e3e4e5e6e7e8e9eaf1f2f3f4f5f6f7f8f9faffda0008010100003f00fbfcffd9")


def shrink(src: Path, dst: Path, pages: list[int]) -> None:
    with pikepdf.open(src) as pdf:
        out = pikepdf.new()
        for p in pages:
            out.pages.append(pdf.pages[p - 1])
        out.save(dst)
    with pikepdf.open(dst, allow_overwriting_input=True) as out:
        for obj in out.objects:  # every image, also inside forms, patterns and soft masks
            if isinstance(obj, pikepdf.Stream) and obj.get("/Subtype") == pikepdf.Name.Image:
                obj.write(GREY_JPEG, filter=pikepdf.Name.DCTDecode)
                obj.Width, obj.Height = 1, 1
                obj.ColorSpace = pikepdf.Name.DeviceGray
                obj.BitsPerComponent = 8
                for k in ("/SMask", "/Mask", "/Decode", "/DecodeParms", "/Metadata"):
                    if k in obj:
                        del obj[k]
        if "/Metadata" in out.Root:
            del out.Root.Metadata
        out.remove_unreferenced_resources()
        out.save(dst, compress_streams=True, object_stream_mode=pikepdf.ObjectStreamMode.generate)


def main(src_dir: str) -> None:
    src = Path(src_dir)
    OUT.mkdir(exist_ok=True)
    for name, (fx, pages) in PDFS.items():
        shrink(src / name, OUT / fx, pages)
        print(fx, (OUT / fx).stat().st_size // 1024, "KB")
    for name, fx in COPIES.items():
        with open(src / name, "rb") as fi, gzip.open(OUT / fx, "wb", compresslevel=9) as fo:
            shutil.copyfileobj(fi, fo)
        print(fx, (OUT / fx).stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main(sys.argv[1])
