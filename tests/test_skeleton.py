import json
import re
from pathlib import Path

import yaml

from leidiniai import __version__, config

ROOT = Path(__file__).resolve().parents[1]


def test_version_matches_config_yaml():
    cfg = yaml.safe_load((ROOT / "leidiniai" / "config.yaml").read_text(encoding="utf-8"))
    assert cfg["version"] == __version__
    assert cfg["ingress"] is True and cfg["arch"] == ["amd64"]
    assert "mqtt:need" in cfg["services"]
    # every option has a schema entry and a translation
    tr = yaml.safe_load((ROOT / "leidiniai" / "translations" / "lt.yaml").read_text(encoding="utf-8"))
    assert set(cfg["options"]) == set(cfg["schema"]) == set(tr["configuration"])
    assert set(cfg["options"]) == set(config.DEFAULTS)


def test_options_loaded(tmp_path):
    (tmp_path / "options.json").write_text(json.dumps({"check_time": "02:10", "chains": ["rimi", "iki"], "threads": 3}))
    s = config.load(tmp_path)
    assert s.check_time == "02:10" and s.threads == 3
    assert s.chains == ["iki", "rimi"]  # canonical order


def test_ingress_prefix_and_peer_check(settings):
    from leidiniai.web import create_app
    app = create_app(settings)
    c = app.test_client()
    r = c.get("/", headers={"X-Ingress-Path": "/api/hassio_ingress/abc"})
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'href="/api/hassio_ingress/abc/static/style.css' in html
    assert "Pasiūlymai" in html
    settings.dev = False
    r = c.get("/", environ_base={"REMOTE_ADDR": "192.168.1.50"})
    assert r.status_code == 403
    r = c.get("/", environ_base={"REMOTE_ADDR": "172.30.32.2"})
    assert r.status_code == 200


def test_formats():
    from leidiniai.web import fmt
    assert fmt.number(10050.531, 2) == "10 050.53"
    assert fmt.money_cents(199) == "1.99 €"
    assert fmt.duration(75) == "1 min 15 s"
