"""Home Assistant entities over MQTT discovery (paho-mqtt 2).

Credentials come from the Supervisor (`services: mqtt:need`): GET http://supervisor/services/mqtt with
$SUPERVISOR_TOKEN. Outside HA set LEIDINIAI_MQTT_HOST (+ _PORT, _USER, _PASSWORD) or MQTT stays off.

Entities (device "Leidiniai"):
  sensor.leidiniai_<chain>_leaflet   title of the leaflet valid today; attributes: dates, offers, url, upcoming
  event.leidiniai_new_leaflet        event_type new_leaflet, once per leaflet that is ready to look at
  sensor.leidiniai_watched_on_sale   number of watched offers valid today; attributes: the offers
  binary_sensor.leidiniai_problem    on = a check or a leaflet failed; attributes: problems
  button.leidiniai_check_now         queue a check of all chains
  sensor.leidiniai_last_run          timestamp of the last finished check (+ chain, status, counts)
  sensor.leidiniai_next_check        timestamp of the next check (+ per chain)
  sensor.leidiniai_activity          what runs now: 'laukia', 'tikrinamas IKI', 'Šilas: puslapis 3/12' (0.8.0)
  sensor.leidiniai_picture_reader    picture reader: paruoštas / ruošiamas / klaida / išjungtas; message (0.8.0)
  event.leidiniai_watch_hit          event_type watch_hit, once per new watched offer (0.8.0)
  button.leidiniai_read_pictures     read the picture leaflets that wait now instead of at night (0.8.0)
Availability: leidiniai/status online|offline (last will). Discovery is sent again when HA restarts
(homeassistant/status online). The password is never logged.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import date

from . import CHAIN_NAMES, __version__, db, ha_state

log = logging.getLogger("leidiniai.mqtt")

BASE = "leidiniai"
AVAIL = f"{BASE}/status"
CMD_CHECK = f"{BASE}/cmd/check_now"
CMD_PICTURES = f"{BASE}/cmd/read_pictures"
FAST_S = 10                # activity and picture reader state are looked at this often (published only on change)
WATCH_KEEP = 2000
HA_STATUS = "homeassistant/status"
DISCOVERY_PREFIX = "homeassistant"
REFRESH_S = 600            # states are re-published this often (dates roll over, next check moves)
ANNOUNCED_KEEP = 300


def supervisor_credentials(timeout: float = 10) -> dict | None:
    """MQTT service details from the Supervisor, or env overrides for local runs. None = MQTT off."""
    if os.environ.get("LEIDINIAI_MQTT_HOST"):
        return {"host": os.environ["LEIDINIAI_MQTT_HOST"], "port": int(os.environ.get("LEIDINIAI_MQTT_PORT", "1883")),
                "username": os.environ.get("LEIDINIAI_MQTT_USER") or None,
                "password": os.environ.get("LEIDINIAI_MQTT_PASSWORD") or None, "ssl": False}
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        log.info("MQTT off: no SUPERVISOR_TOKEN and no LEIDINIAI_MQTT_HOST")
        return None
    import requests
    try:
        r = requests.get("http://supervisor/services/mqtt", headers={"Authorization": f"Bearer {token}"}, timeout=timeout)
        r.raise_for_status()
        d = r.json().get("data") or {}
    except Exception as e:
        log.error("MQTT off: could not read the MQTT service from the Supervisor (%s). Is Mosquitto installed?", e)
        return None
    if not d.get("host"):
        log.error("MQTT off: the Supervisor has no MQTT service (install the Mosquitto broker app)")
        return None
    return {"host": d["host"], "port": int(d.get("port") or 1883), "username": d.get("username"),
            "password": d.get("password"), "ssl": bool(d.get("ssl"))}


def panel_path(timeout: float = 10) -> str | None:
    """The app's sidebar page in HA (/hassio/ingress/<slug>), for links in events. None outside HA."""
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return None
    import requests
    try:
        r = requests.get("http://supervisor/addons/self/info", headers={"Authorization": f"Bearer {token}"},
                         timeout=timeout)
        r.raise_for_status()
        slug = (r.json().get("data") or {}).get("slug")
    except Exception as e:
        log.warning("MQTT: the app's slug is unknown (%s): events carry no link", e)
        return None
    return f"/hassio/ingress/{slug}" if slug else None


def paho_client(client_id: str):
    import paho.mqtt.client as mqtt
    return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, protocol=mqtt.MQTTv311)


DEVICE = {"identifiers": ["leidiniai"], "name": "Leidiniai", "manufacturer": "lt-leidiniai",
          "model": "Leidinių rinkiklis", "sw_version": __version__}
ORIGIN = {"name": "Leidiniai", "sw_version": __version__, "support_url": "https://github.com/DG-Lt/lt-leidiniai"}


def discovery(chains) -> list[tuple[str, dict]]:
    """(topic, payload) for every entity."""
    common = {"availability_topic": AVAIL, "device": DEVICE, "origin": ORIGIN, "has_entity_name": True}
    out = []

    def add(component, oid, name, **kw):
        cfg = {"name": name, "unique_id": f"leidiniai_{oid}", "default_entity_id": f"{component}.leidiniai_{oid}",
               **common, **kw}
        out.append((f"{DISCOVERY_PREFIX}/{component}/leidiniai/{oid}/config", cfg))

    for c in chains:
        add("sensor", f"{c}_leaflet", f"{CHAIN_NAMES[c]} leidinys", icon="mdi:newspaper-variant-outline",
            state_topic=f"{BASE}/{c}/leaflet/state", json_attributes_topic=f"{BASE}/{c}/leaflet/attributes")
    add("event", "new_leaflet", "Naujas leidinys", icon="mdi:newspaper-plus", state_topic=f"{BASE}/event/new_leaflet",
        event_types=["new_leaflet"])
    add("sensor", "watched_on_sale", "Stebimi akcijose", icon="mdi:tag-heart", state_topic=f"{BASE}/watched/state",
        json_attributes_topic=f"{BASE}/watched/attributes", unit_of_measurement="pasiūl.")
    add("binary_sensor", "problem", "Problema", device_class="problem", state_topic=f"{BASE}/problem/state",
        json_attributes_topic=f"{BASE}/problem/attributes", payload_on="ON", payload_off="OFF",
        entity_category="diagnostic")
    add("button", "check_now", "Tikrinti dabar", icon="mdi:refresh", command_topic=CMD_CHECK, payload_press="PRESS")
    add("sensor", "last_run", "Paskutinis tikrinimas", device_class="timestamp", state_topic=f"{BASE}/last_run/state",
        json_attributes_topic=f"{BASE}/last_run/attributes", entity_category="diagnostic")
    add("sensor", "next_check", "Kitas tikrinimas", device_class="timestamp", state_topic=f"{BASE}/next_check/state",
        json_attributes_topic=f"{BASE}/next_check/attributes", entity_category="diagnostic")
    add("sensor", "activity", "Veikla", icon="mdi:progress-clock", state_topic=f"{BASE}/activity/state",
        json_attributes_topic=f"{BASE}/activity/attributes")
    add("sensor", "picture_reader", "Paveikslėlių skaitytuvas", icon="mdi:image-text",
        state_topic=f"{BASE}/picture_reader/state", json_attributes_topic=f"{BASE}/picture_reader/attributes",
        entity_category="diagnostic")
    add("event", "watch_hit", "Stebima prekė akcijoje", icon="mdi:tag-heart-outline",
        state_topic=f"{BASE}/event/watch_hit", event_types=["watch_hit"])
    add("button", "read_pictures", "Skaityti paveikslėlius dabar", icon="mdi:image-search-outline",
        command_topic=CMD_PICTURES, payload_press="PRESS")
    return out


class Bridge:
    """Keeps the HA entities up to date. All DB access opens its own connection (called from several threads)."""

    def __init__(self, settings, runner=None, credentials=None, client_factory=paho_client, today=date.today):
        self.settings = settings
        self.runner = runner
        self.creds = credentials
        self.client_factory = client_factory
        self.today = today
        self.client = None
        self.connected = False
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._last: dict[str, str] = {}   # topic → last retained payload (skip unchanged)
        self.panel_path: str | None = None  # /hassio/ingress/<slug>, for links in events
        self._removed_chains: list[str] = []

    # -- life cycle ----------------------------------------------------------
    def start(self) -> bool:
        if self.creds is None:
            self.creds = supervisor_credentials()
        if not self.creds:
            return False
        self._init_announced()
        self._init_watch_hits()
        self.panel_path = panel_path()
        c = self.client = self.client_factory("leidiniai")
        c.on_connect = self._on_connect
        c.on_disconnect = self._on_disconnect
        c.on_message = self._on_message
        if self.creds.get("username"):
            c.username_pw_set(self.creds["username"], self.creds.get("password"))
        if self.creds.get("ssl"):
            c.tls_set()
        c.will_set(AVAIL, "offline", qos=1, retain=True)
        c.reconnect_delay_set(1, 120)
        log.info("MQTT: connecting to %s:%s as %s", self.creds["host"], self.creds["port"],
                 self.creds.get("username") or "(anonymous)")
        c.connect_async(self.creds["host"], int(self.creds["port"]), keepalive=60)
        c.loop_start()
        threading.Thread(target=self._refresh_loop, name="mqtt-refresh", daemon=True).start()
        threading.Thread(target=self._fast_loop, name="mqtt-activity", daemon=True).start()
        return True

    def stop(self):
        self._stop.set()
        if self.client:
            try:
                self.client.publish(AVAIL, "offline", qos=1, retain=True)
                self.client.disconnect()
                self.client.loop_stop()
            except Exception:
                pass

    # -- paho callbacks (paho-mqtt 2, CallbackAPIVersion.VERSION2) --------------
    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if getattr(reason_code, "is_failure", False) or (isinstance(reason_code, int) and reason_code):
            log.error("MQTT: connection refused: %s", reason_code)
            return
        self.connected = True
        log.info("MQTT: connected")
        client.subscribe([(CMD_CHECK, 1), (CMD_PICTURES, 1), (HA_STATUS, 1)])
        self.publish_discovery()
        client.publish(AVAIL, "online", qos=1, retain=True)
        self.publish_states(force=True)
        self.publish_activity(force=True)
        self.announce_new()

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        self.connected = False
        if not self._stop.is_set():
            log.warning("MQTT: disconnected (%s), reconnecting", reason_code)

    def _on_message(self, client, userdata, msg):
        payload = msg.payload.decode("utf-8", errors="replace").strip()
        if msg.topic == CMD_CHECK:
            log.info("MQTT: check requested from Home Assistant")
            if self.runner:
                self.runner.request("all", "mqtt")
        elif msg.topic == CMD_PICTURES:
            from . import vision
            if not vision.ready(self.settings):
                log.warning("MQTT: picture reading requested, but the picture reader is not ready")
            elif self.runner:
                log.info("MQTT: picture reading requested from Home Assistant")
                self.runner.request_pictures("mqtt")
        elif msg.topic == HA_STATUS and payload == "online":
            log.info("MQTT: Home Assistant restarted, sending discovery again")
            self.publish_discovery()
            self.client.publish(AVAIL, "online", qos=1, retain=True)
            self.publish_states(force=True)
            self.publish_activity(force=True)

    # -- publishing ----------------------------------------------------------
    def _pub(self, topic: str, payload, retain: bool = True, force: bool = False):
        s = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, default=str)
        if retain and not force and self._last.get(topic) == s:
            return
        self.client.publish(topic, s, qos=1, retain=retain)
        if retain:
            self._last[topic] = s

    def publish_discovery(self):
        for topic, cfg in discovery(self.settings.chains):
            self._pub(topic, cfg, force=True)
        # chains switched off in the options: remove their entity
        for c in CHAIN_NAMES:
            if c not in self.settings.chains:
                self.client.publish(f"{DISCOVERY_PREFIX}/sensor/leidiniai/{c}_leaflet/config", "", qos=1, retain=True)

    def publish_states(self, force: bool = False):
        if not self.client or not self.connected:
            return
        with self._lock:
            today = self.today()
            with db.session(self.settings) as conn:
                for c in self.settings.chains:
                    st, attrs = ha_state.chain_leaflet(conn, c, today)
                    self._pub(f"{BASE}/{c}/leaflet/attributes", attrs, force=force)
                    self._pub(f"{BASE}/{c}/leaflet/state", st, force=force)
                n, attrs = ha_state.watched_on_sale(conn, today, mark_hits=True)
                self._pub(f"{BASE}/watched/attributes", attrs, force=force)
                self._pub(f"{BASE}/watched/state", str(n), force=force)
                probs = ha_state.problems(conn, self.settings.chains, today)
                self._pub(f"{BASE}/problem/attributes", {"problems": probs}, force=force)
                self._pub(f"{BASE}/problem/state", "ON" if probs else "OFF", force=force)
                ts, attrs = ha_state.last_run(conn)
                attrs["running"] = CHAIN_NAMES.get(self.runner.current) if self.runner and self.runner.current else None
                self._pub(f"{BASE}/last_run/attributes", attrs, force=force)
                self._pub(f"{BASE}/last_run/state", ts or "None", force=force)
            nxt = self.runner.next_checks() if self.runner else {}
            self._pub(f"{BASE}/next_check/attributes", {CHAIN_NAMES[c]: v for c, v in nxt.items()}, force=force)
            self._pub(f"{BASE}/next_check/state", min(nxt.values()) if nxt else "None", force=force)

    def publish_activity(self, force: bool = False):
        """Activity and picture reader state: cheap (no database), looked at every FAST_S seconds."""
        if not self.client or not self.connected:
            return
        act = self.runner.activity() if self.runner else {"state": "laukia"}
        st = act.pop("state")
        self._pub(f"{BASE}/activity/attributes", act, force=force)
        self._pub(f"{BASE}/activity/state", st[:255], force=force)
        st, attrs = ha_state.picture_reader(self.settings)
        self._pub(f"{BASE}/picture_reader/attributes", attrs, force=force)
        self._pub(f"{BASE}/picture_reader/state", st, force=force)

    # -- watched offers on sale: one event each --------------------------------
    def _init_watch_hits(self):
        """First start of 0.8.0: watched offers already there are not announced."""
        with db.session(self.settings) as conn:
            if db.kv_get(conn, "watch_announced") is None:
                db.kv_set(conn, "watch_announced", [h["key"] for h in ha_state.watch_hits(conn, self.today())])

    def announce_watch_hits(self):
        if not self.client or not self.connected:
            return
        with self._lock, db.session(self.settings) as conn:
            done = list(db.kv_get(conn, "watch_announced", []))
            have = set(done)
            for h in ha_state.watch_hits(conn, self.today()):
                if h["key"] in have:
                    continue
                ev = {"event_type": "watch_hit", **{k: v for k, v in h.items() if k != "key"},
                      "url": f"{self.panel_path}{h['path']}" if self.panel_path else None}
                self._pub(f"{BASE}/event/watch_hit", ev, retain=False)
                log.info("MQTT: watched offer event – %s %s %s", h["chain_name"], h["name"], h["price"])
                done.append(h["key"])
                have.add(h["key"])
            db.kv_set(conn, "watch_announced", done[-WATCH_KEEP:])

    # -- new leaflet events ----------------------------------------------------
    def _init_announced(self):
        """First start with MQTT (e.g. update from 0.3): leaflets already there are not announced again."""
        with db.session(self.settings) as conn:
            if db.kv_get(conn, "mqtt_announced") is None:
                ids = [r[0] for r in conn.execute("SELECT id FROM issues WHERE status IN ('parsed','waiting_parser')")]
                db.kv_set(conn, "mqtt_announced", ids[-ANNOUNCED_KEEP:])

    def announce_new(self):
        if not self.client or not self.connected:
            return
        with self._lock, db.session(self.settings) as conn:
            done = list(db.kv_get(conn, "mqtt_announced", []))
            for lf in ha_state.leaflets_to_announce(conn, self.today(), set(done)):
                self._pub(f"{BASE}/event/new_leaflet", {"event_type": "new_leaflet", **lf}, retain=False)
                log.info("MQTT: new leaflet event – %s %s", lf["chain_name"], lf["title"])
                done.append(lf["issue_id"])
            db.kv_set(conn, "mqtt_announced", done[-ANNOUNCED_KEEP:])

    # -- hooks -------------------------------------------------------------
    def on_run_start(self, chain):  # also called on every page of a picture reading
        self._safe(self.publish_activity)
        self._safe(self.publish_states)

    def on_run_done(self, chain, run_id):
        self._safe(self.announce_new)
        self._safe(self.announce_watch_hits)
        self._safe(self.publish_states)
        self._safe(self.publish_activity)

    def refresh(self):
        """Watch list changed in the panel etc. Runs in the background so the page answers at once."""
        threading.Thread(target=self._safe, args=(self.publish_states,), daemon=True).start()

    def _safe(self, fn):
        try:
            fn()
        except Exception:
            log.exception("MQTT: %s failed", fn.__name__)

    def _refresh_loop(self):
        while not self._stop.wait(REFRESH_S):
            self._safe(self.announce_new)
            self._safe(self.announce_watch_hits)
            self._safe(self.publish_states)

    def _fast_loop(self):
        while not self._stop.wait(FAST_S):
            self._safe(self.publish_activity)
