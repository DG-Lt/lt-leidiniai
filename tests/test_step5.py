"""Step 5: Home Assistant entities over MQTT discovery (fake paho client, no broker needed)."""
import json
from datetime import date

from leidiniai import db, ha_state, mqtt

TODAY = date(2026, 11, 19)


class Msg:
    def __init__(self, topic, payload):
        self.topic, self.payload = topic, payload.encode()


class FakeClient:
    def __init__(self, client_id):
        self.pubs, self.subs, self.will, self.auth, self.connect_args = [], [], None, None, None

    def username_pw_set(self, u, p):
        self.auth = (u, p)

    def tls_set(self):
        pass

    def will_set(self, topic, payload, qos=0, retain=False):
        self.will = (topic, payload, retain)

    def reconnect_delay_set(self, a, b):
        pass

    def connect_async(self, host, port, keepalive=60):
        self.connect_args = (host, port)

    def loop_start(self):
        pass

    def loop_stop(self):
        pass

    def disconnect(self):
        pass

    def subscribe(self, topics):
        self.subs.extend(t for t, _ in topics)

    def publish(self, topic, payload, qos=0, retain=False):
        self.pubs.append((topic, payload, retain))

    def last(self, topic):
        v = [p for t, p, _ in self.pubs if t == topic]
        return v[-1] if v else None


class FakeRunner:
    current = None

    def __init__(self):
        self.requests = []

    def request(self, chain, trigger):
        self.requests.append((chain, trigger))

    def next_checks(self):
        return {"iki": "2026-11-20T03:30:00+02:00", "norfa": "2026-11-24T03:30:00+02:00"}


def seed(conn):
    now = "2026-11-19T03:30:00+02:00"
    with conn:
        for i, (chain, key, title, vf, vt, status, offers, meta) in enumerate([
            ("iki", "B46", "IKI leidinys Nr. 46", "2026-11-09", "2026-11-15", "parsed", 400, {}),
            ("iki", "B47", "IKI leidinys Nr. 47", "2026-11-16", "2026-11-22", "parsed", 445, {}),
            ("iki", "B48", "IKI leidinys Nr. 48", "2026-11-23", "2026-11-29", "parsed", 430, {}),
            ("lidl", "kw47", "Maisto prekių pasiūlymai", "2026-11-16", "2026-11-22", "parsed", 233, {}),
            ("lidl", "store", "Parduotuvė", None, None, "new", None, {"listed_only": True}),
            ("norfa", "523", "NORFA Nr. 23 (523)", "2026-11-12", "2026-11-25", "parse_failed", None, {}),
            ("silas", "2026-23", "Leidinys Nr. 23", "2026-11-18", "2026-12-01", "waiting_parser", None, {}),
        ], start=1):
            conn.execute("INSERT INTO issues(id,chain,key,series,title,valid_from,valid_to,status,offers,meta,first_seen,last_seen,error,source_url)"
                         " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (i, chain, key, "s", title, vf, vt, status, offers, json.dumps(meta), now, now,
                          "parse: bad page" if status == "parse_failed" else None, f"https://x/{key}"))
        conn.execute("INSERT INTO products(id,chain,ident,name,name_key,first_seen,last_seen) VALUES(1,'iki','a','Sviestas','sviestas',?,?)", (now, now))
        for oid, (iid, name, key, price, old, pct, vf, vt) in enumerate([
            (2, "ROKIŠKIO sviestas, 82 %", "rokiskio sviestas 82 %", 199, 289, 31, None, None),
            (2, "Šviežia višta", "sviezia vista", 350, None, None, None, None),
            (4, "Sviestas Pilos", "sviestas pilos", 249, None, None, None, None),
            (3, "Sviestas kitą savaitę", "sviestas kita savaite", 150, None, None, "2026-11-23", "2026-11-29"),
        ], start=1):
            conn.execute("INSERT INTO offers(id,issue_id,product_id,chain,seq,kind,name,name_key,price,old_price,discount_pct,valid_from,valid_to)"
                         " SELECT ?,?,1,chain,?,'price',?,?,?,?,?,COALESCE(?,valid_from),COALESCE(?,valid_to) FROM issues WHERE id=?",
                         (oid, iid, oid, name, key, price, old, pct, vf, vt, iid))
        conn.execute("INSERT INTO watch(id,term,term_key,created) VALUES(1,'sviest','sviest',?)", (now,))
        conn.execute("INSERT INTO watch(id,term,term_key,chain,created) VALUES(2,'višta','vista','lidl',?)", (now,))
        conn.execute("INSERT INTO chain_state(chain,last_check,last_error) VALUES('lidl',?,'HTTP 503')", (now,))
        conn.execute("INSERT INTO runs(chain,trigger,started,finished,status,summary) VALUES('iki','night',?,?,'ok',?)",
                     (now, "2026-11-19T03:31:10+02:00", json.dumps({"new_issues": [{"id": 3}], "timings": {"total_s": 70}})))


def test_states(settings):
    with db.session(settings) as conn:
        seed(conn)
        st, a = ha_state.chain_leaflet(conn, "iki", TODAY)
        assert st == "IKI leidinys Nr. 47" and a["valid_to"] == "2026-11-22" and a["offers"] == 445
        assert [x["title"] for x in a["upcoming"]] == ["IKI leidinys Nr. 48"]
        st, a = ha_state.chain_leaflet(conn, "lidl", TODAY)
        assert st == "Maisto prekių pasiūlymai" and a["last_error"] == "HTTP 503"  # listed_only store page left out
        assert ha_state.chain_leaflet(conn, "maxima", TODAY)[0] == "nėra"
        n, a = ha_state.watched_on_sale(conn, TODAY, mark_hits=True)
        # IKI + Lidl butter valid today; next week's not; the chicken is IKI but the term is Lidl-only
        assert n == 2 and [x["name"] for x in a["items"]] == ["ROKIŠKIO sviestas, 82 %", "Sviestas Pilos"]
        assert a["items"][0]["price"] == 1.99 and a["items"][0]["old_price"] == 2.89 and a["items"][0]["chain"] == "IKI"
        assert a["by_term"] == {"sviest": 2, "višta": 0}
        assert conn.execute("SELECT last_hit FROM watch WHERE id=1").fetchone()[0]
        p = ha_state.problems(conn, ["iki", "lidl", "norfa"], TODAY)
        assert p[0] == "Lidl: HTTP 503" and "NORFA Nr. 23 (523)" in p[1] and "neperskaitytas" in p[1]
        ts, a = ha_state.last_run(conn)
        assert ts == "2026-11-19T03:31:10+02:00" and a["status"] == "ok" and a["new_leaflets"] == 1


def test_discovery_payloads(settings):
    d = dict(mqtt.discovery(["iki", "silas"]))
    cfg = d["homeassistant/sensor/leidiniai/silas_leaflet/config"]
    assert cfg["default_entity_id"] == "sensor.leidiniai_silas_leaflet" and cfg["name"] == "Šilas leidinys"
    assert cfg["unique_id"] == "leidiniai_silas_leaflet" and cfg["availability_topic"] == "leidiniai/status"
    assert d["homeassistant/event/leidiniai/new_leaflet/config"]["event_types"] == ["new_leaflet"]
    assert d["homeassistant/binary_sensor/leidiniai/problem/config"]["device_class"] == "problem"
    assert d["homeassistant/button/leidiniai/check_now/config"]["command_topic"] == mqtt.CMD_CHECK
    assert d["homeassistant/sensor/leidiniai/last_run/config"]["device_class"] == "timestamp"
    assert "homeassistant/sensor/leidiniai/next_check/config" in d
    for topic, c in d.items():
        comp = topic.split("/")[1]
        assert c["default_entity_id"].startswith(comp + ".leidiniai_") and c["device"]["identifiers"] == ["leidiniai"]
    assert len(d) == 2 + 6


def make_bridge(settings, runner=None):
    settings.chains = ["iki", "lidl", "norfa", "silas"]
    b = mqtt.Bridge(settings, runner or FakeRunner(), credentials={"host": "core-mosquitto", "port": 1883,
                                                                    "username": "addons", "password": "pw", "ssl": False},
                    client_factory=FakeClient, today=lambda: TODAY)
    return b


def test_bridge_connect_publishes_everything(settings):
    with db.session(settings) as conn:
        seed(conn)
    b = make_bridge(settings)
    b._refresh_loop = lambda: None
    assert b.start()
    c = b.client
    assert c.connect_args == ("core-mosquitto", 1883) and c.auth == ("addons", "pw")
    assert c.will == ("leidiniai/status", "offline", True)
    b._on_connect(c, None, {}, 0, None)
    assert set(c.subs) == {mqtt.CMD_CHECK, mqtt.HA_STATUS}
    assert c.last("leidiniai/status") == "online"
    assert c.last("leidiniai/iki/leaflet/state") == "IKI leidinys Nr. 47"
    assert json.loads(c.last("leidiniai/iki/leaflet/attributes"))["valid_to"] == "2026-11-22"
    assert c.last("leidiniai/watched/state") == "2"
    assert c.last("leidiniai/problem/state") == "ON"
    assert c.last("leidiniai/last_run/state") == "2026-11-19T03:31:10+02:00"
    assert c.last("leidiniai/next_check/state") == "2026-11-20T03:30:00+02:00"
    assert json.loads(c.last("leidiniai/next_check/attributes")) == {"IKI": "2026-11-20T03:30:00+02:00",
                                                                     "Norfa": "2026-11-24T03:30:00+02:00"}
    # disabled chains lose their entity
    assert c.last("homeassistant/sensor/leidiniai/maxima_leaflet/config") == ""
    # leaflets already there before MQTT was set up are not announced
    assert c.last("leidiniai/event/new_leaflet") is None
    assert all(r for t, _, r in c.pubs if t.startswith("leidiniai/") and "event" not in t)


def test_new_leaflet_event_once(settings):
    b = make_bridge(settings)
    b._refresh_loop = lambda: None
    b.start()
    b._on_connect(b.client, None, {}, 0, None)
    with db.session(settings) as conn:
        seed(conn)  # leaflets appear after MQTT started
    b.on_run_done("iki", 1)
    ev = [json.loads(p) for t, p, r in b.client.pubs if t == "leidiniai/event/new_leaflet"]
    # current and upcoming parsed leaflets + Šilas waiting for the vision parser; not expired B46, not failed Norfa
    assert [e["title"] for e in ev] == ["IKI leidinys Nr. 47", "IKI leidinys Nr. 48", "Maisto prekių pasiūlymai",
                                        "Leidinys Nr. 23"]
    assert ev[0]["event_type"] == "new_leaflet" and ev[0]["chain"] == "iki" and ev[0]["offers"] == 445
    assert all(not r for t, _, r in b.client.pubs if t == "leidiniai/event/new_leaflet")
    n = len(b.client.pubs)
    b.on_run_done("iki", 2)
    assert not [p for t, p, _ in b.client.pubs[n:] if t == "leidiniai/event/new_leaflet"]
    # unchanged retained states are not sent again
    assert not [t for t, _, _ in b.client.pubs[n:] if t == "leidiniai/iki/leaflet/state"]


def test_button_and_ha_restart(settings):
    r = FakeRunner()
    b = make_bridge(settings, r)
    b._refresh_loop = lambda: None
    b.start()
    b._on_connect(b.client, None, {}, 0, None)
    b._on_message(b.client, None, Msg(mqtt.CMD_CHECK, "PRESS"))
    assert r.requests == [("all", "mqtt")]
    n = len(b.client.pubs)
    b._on_message(b.client, None, Msg(mqtt.HA_STATUS, "online"))
    topics = [t for t, _, _ in b.client.pubs[n:]]
    assert "homeassistant/button/leidiniai/check_now/config" in topics and "leidiniai/iki/leaflet/state" in topics


def test_no_credentials_means_off(settings, monkeypatch):
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    monkeypatch.delenv("LEIDINIAI_MQTT_HOST", raising=False)
    assert mqtt.supervisor_credentials() is None
    assert mqtt.Bridge(settings, client_factory=FakeClient).start() is False
    monkeypatch.setenv("LEIDINIAI_MQTT_HOST", "localhost")
    assert mqtt.supervisor_credentials()["port"] == 1883


def test_supervisor_credentials(monkeypatch):
    import requests

    class R:
        def raise_for_status(self):
            pass

        def json(self):
            return {"result": "ok", "data": {"host": "core-mosquitto", "port": 1883, "ssl": False,
                                             "username": "addons", "password": "secret", "protocol": "3.1.1"}}

    seen = {}
    monkeypatch.delenv("LEIDINIAI_MQTT_HOST", raising=False)
    monkeypatch.setenv("SUPERVISOR_TOKEN", "tok")
    monkeypatch.setattr(requests, "get", lambda url, headers, timeout: seen.update(url=url, h=headers) or R())
    c = mqtt.supervisor_credentials()
    assert seen == {"url": "http://supervisor/services/mqtt", "h": {"Authorization": "Bearer tok"}}
    assert c == {"host": "core-mosquitto", "port": 1883, "username": "addons", "password": "secret", "ssl": False}


def test_watch_change_refreshes_mqtt(settings):
    from leidiniai.web import create_app

    class M:
        connected = True
        n = 0

        def refresh(self):
            M.n += 1

    c = create_app(settings, None, M()).test_client()
    c.post("/stebimi", data={"term": "kava"})
    c.post("/stebimi/1/salinti")
    assert M.n == 2
    assert "prisijungta" in c.get("/busena").get_data(as_text=True)


def test_real_paho_client_api():
    """Runs in CI (paho installed): the client is built with the version-2 callback API."""
    import pytest
    paho = pytest.importorskip("paho.mqtt.client")
    c = mqtt.paho_client("leidiniai-test")
    assert c._callback_api_version == paho.CallbackAPIVersion.VERSION2
    b = mqtt.Bridge.__new__(mqtt.Bridge)
    c.on_connect, c.on_message, c.on_disconnect = b._on_connect, b._on_message, b._on_disconnect


# ---------------------------------------------------------------- 0.4.5: logos, "Stebimi viršuje"

PNG_1PX = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                        "1f15c4890000000d49444154789c6360f8cfc0f01f0005000201a8d6b1d40000000049454e44ae426082")


def test_logos_kind_upload_and_refresh(settings, tmp_path, monkeypatch):
    import logging
    from types import SimpleNamespace
    from leidiniai import logos
    monkeypatch.setattr(logos, "SOURCES", {"iki": "https://example.invalid/logo.png"})
    assert logos.kind_of(PNG_1PX) == ".png" and logos.kind_of(b"<svg xmlns='x'></svg>") == ".svg"
    assert logos.kind_of(b"<html>not a logo</html>") is None
    assert logos.find(settings, "iki") is None

    class H:
        calls = 0

        def _get(self, url):
            H.calls += 1
            return SimpleNamespace(status_code=200, content=PNG_1PX)

    logos.refresh(settings, "iki", H(), logging.getLogger("t"))
    assert logos.find(settings, "iki").name == "auto-iki.png" and H.calls == 1
    logos.refresh(settings, "iki", H(), logging.getLogger("t"))  # fresh: no second request
    assert H.calls == 1
    logos.save_upload(settings, "iki", b"<svg xmlns='http://www.w3.org/2000/svg'/>")
    assert logos.find(settings, "iki").name == "user-iki.svg"
    import pytest
    with pytest.raises(ValueError):
        logos.save_upload(settings, "iki", b"MZ\x90\x00 not an image")
    logos.remove_upload(settings, "iki")
    assert logos.find(settings, "iki").name == "auto-iki.png"


def test_panel_logo_and_watched_first(settings):
    import io
    from leidiniai import db, logos
    from leidiniai.web import create_app
    conn = db.open_db(settings)
    with conn:
        iid = conn.execute("INSERT INTO issues(chain,key,series,title,status,first_seen,last_seen,valid_to)"
                           " VALUES('norfa','1','s','t','parsed','t','t','2099-01-01')").lastrowid
        for seq, (name, disc) in enumerate([("Bananai 1 kg", 50), ("Sviestas ŪKIO 200 g", 10), ("Obuoliai 1 kg", 30)]):
            pid = conn.execute("INSERT INTO products(chain,ident,name,name_key,first_seen,last_seen) VALUES('norfa',?,?,?,'t','t')",
                               (name, name, name.lower().replace("ū", "u"))).lastrowid
            conn.execute("INSERT INTO offers(issue_id,product_id,chain,seq,kind,name,name_key,price,discount_pct,category,flags,extra)"
                         " VALUES(?,?,?,?,'price',?,?,?,?,?,?,?)",
                         (iid, pid, "norfa", seq, name, name.lower().replace("ū", "u"), 100, disc, "other", "[]", "{}"))
    c = create_app(settings).test_client()
    c.post("/stebimi", data={"term": "sviest"})
    names = lambda html: [n for n in ("Bananai", "Sviestas", "Obuoliai") if n in html]
    order = lambda html: sorted(names(html), key=html.index)
    assert order(c.get("/?sort=disc").get_data(as_text=True)) == ["Bananai", "Obuoliai", "Sviestas"]
    assert order(c.get("/?sort=disc&top=1").get_data(as_text=True)) == ["Sviestas", "Bananai", "Obuoliai"]
    assert order(c.get("/?sort=disc&top=1&q=obuol").get_data(as_text=True)) == ["Obuoliai"]  # filters still apply
    # logo: upload on Būsena, shown on the card, served with a safe CSP
    assert 'class="logo"' not in c.get("/").get_data(as_text=True)
    r = c.post("/logotipai/norfa", data={"file": (io.BytesIO(PNG_1PX), "n.png")}, content_type="multipart/form-data")
    assert r.status_code == 302 and logos.find(settings, "norfa")
    assert 'img class="logo" src="/logo/norfa"' in c.get("/").get_data(as_text=True)
    r = c.get("/logo/norfa")
    assert r.mimetype == "image/png" and "default-src 'none'" in r.headers["Content-Security-Policy"]
    assert c.get("/logo/nope").status_code == 404
    assert "Tinklų logotipai" in c.get("/busena").get_data(as_text=True)
