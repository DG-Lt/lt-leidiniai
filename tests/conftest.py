import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "leidiniai" / "app"))


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("LEIDINIAI_DEV", "1")
    from leidiniai import config
    s = config.load(tmp_path)
    s.ensure_dirs()
    return s


@pytest.fixture(autouse=True)
def no_logo_downloads(monkeypatch):
    """Job tests must not fetch the shops' logos from the internet; test_logos_* sets its own source."""
    from leidiniai import logos
    monkeypatch.setattr(logos, "SOURCES", {})
