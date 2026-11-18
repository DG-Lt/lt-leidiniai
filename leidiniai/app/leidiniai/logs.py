"""Logging setup (step 1: stdout only; step 4 adds rotating files and the download zip)."""
from __future__ import annotations

import logging
import sys

FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup_logging(settings) -> None:
    root = logging.getLogger()
    root.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
    for h in list(root.handlers):
        root.removeHandler(h)
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(logging.Formatter(FORMAT, "%Y-%m-%d %H:%M:%S"))
    root.addHandler(h)
    logging.getLogger("waitress").setLevel(logging.WARNING)
