"""App settings: /data/options.json written by the Supervisor, with defaults for local runs."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from . import CHAINS

DEFAULTS = {
    "check_time": "03:30",
    "request_delay": 2.0,
    "threads": 2,
    "chains": list(CHAINS),
    "browser_fallback": True,
    "keep_pdf_weeks": 8,
    "keep_images_weeks": 12,
    "log_level": "info",
}


@dataclass
class Settings:
    data_dir: Path
    check_time: str = DEFAULTS["check_time"]
    request_delay: float = DEFAULTS["request_delay"]
    threads: int = DEFAULTS["threads"]
    chains: list[str] = field(default_factory=lambda: list(CHAINS))
    browser_fallback: bool = True
    keep_pdf_weeks: int = 8
    keep_images_weeks: int = 12
    log_level: str = "info"
    port: int = 8099
    dev: bool = False  # local run outside HA: no ingress IP check

    # folders inside data_dir
    @property
    def db_path(self) -> Path:
        return self.data_dir / "leidiniai.db"

    @property
    def pdf_dir(self) -> Path:
        return self.data_dir / "pdf"

    @property
    def img_dir(self) -> Path:
        return self.data_dir / "img"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def tmp_dir(self) -> Path:
        return self.data_dir / "tmp"

    def ensure_dirs(self) -> None:
        for p in (self.data_dir, self.pdf_dir, self.img_dir, self.log_dir,
                  self.log_dir / "runs", self.cache_dir, self.tmp_dir):
            p.mkdir(parents=True, exist_ok=True)

    def public(self) -> dict:
        """Options without anything secret (for the logs zip and the panel)."""
        return {k: getattr(self, k) for k in DEFAULTS} | {"data_dir": str(self.data_dir)}


def load(data_dir: str | os.PathLike | None = None) -> Settings:
    data = Path(data_dir or os.environ.get("LEIDINIAI_DATA", "/data"))
    opts = dict(DEFAULTS)
    f = data / "options.json"
    if f.exists():
        opts.update(json.loads(f.read_text(encoding="utf-8")))
    s = Settings(data_dir=data)
    for k in DEFAULTS:
        setattr(s, k, opts[k])
    s.request_delay = float(s.request_delay)
    s.threads = int(s.threads)
    s.chains = [c for c in CHAINS if c in (s.chains or [])]
    s.port = int(os.environ.get("LEIDINIAI_PORT", "8099"))
    s.dev = os.environ.get("LEIDINIAI_DEV") == "1"
    return s
