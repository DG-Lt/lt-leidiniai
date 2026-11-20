"""Entry point: `python -m leidiniai` starts the web panel, the scheduler and the MQTT bridge."""
from __future__ import annotations

import logging
import signal
import sys

from . import __version__, config
from .logs import setup_logging


def main() -> int:
    settings = config.load()
    settings.ensure_dirs()
    setup_logging(settings)
    log = logging.getLogger("leidiniai")
    log.info("Leidiniai %s starting, data in %s, chains %s", __version__, settings.data_dir,
             ", ".join(settings.chains))

    from . import db
    from .schedule import Runner
    with db.session(settings) as conn:
        log.info("Database schema version %s", conn.execute("PRAGMA user_version").fetchone()[0])
    from . import logos
    logos.tidy_existing(settings, log)
    runner = Runner(settings)
    from .mqtt import Bridge
    bridge = Bridge(settings, runner)
    try:
        if bridge.start():
            runner.on_start = bridge.on_run_start
            runner.on_done = bridge.on_run_done
        else:
            bridge = None
    except Exception:
        log.exception("MQTT could not start; the panel still works")
        bridge = None
    runner.start()

    from .web import create_app
    app = create_app(settings, runner, bridge)

    from waitress import serve

    def stop(*_):
        log.info("Stopping")
        if bridge:
            bridge.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, stop)
    serve(app, host="0.0.0.0", port=settings.port, threads=8, ident=None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
