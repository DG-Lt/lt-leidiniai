"""Dev tool: python -m leidiniai.parsers <chain> <file> [eshop.json] [--pages 3,4] → offers as JSON on stdout."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date

from . import maxima, pdf_text, rimi


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("chain")
    ap.add_argument("files", nargs="+")
    ap.add_argument("--pages", help="comma-separated 1-based pages (PDF)")
    ap.add_argument("--ref", default=date.today().isoformat(), help="reference date for 'Iki 11.16'")
    a = ap.parse_args(argv)
    log = logging.getLogger("parsers")
    if a.chain == "maxima":
        offers = maxima.parse(open(a.files[0], encoding="utf-8").read(), date.fromisoformat(a.ref))
    elif a.chain == "rimi":
        offers = rimi.parse(a.files[0], a.files[1])
    else:
        pages = {int(x) for x in a.pages.split(",")} if a.pages else None
        offers = pdf_text.parse(a.files[0], a.chain, pages=pages, log=log)
    json.dump([o.as_dict() for o in offers], sys.stdout, ensure_ascii=False, indent=1)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
