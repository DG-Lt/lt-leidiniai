"""Ingress web panel (Flask). Labels are Lithuanian; code and routes are English."""
from __future__ import annotations

import logging

from flask import Flask, abort, request

from .. import CHAIN_NAMES, __version__
from . import fmt

log = logging.getLogger(__name__)

# Home Assistant ingress gateway address (Supervisor docs: only accept this peer).
INGRESS_PEER = "172.30.32.2"


class IngressPrefix:
    """Make url_for() build links under the ingress path that HA proxies us at."""

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        prefix = environ.get("HTTP_X_INGRESS_PATH", "")
        if prefix:
            environ["SCRIPT_NAME"] = prefix.rstrip("/")
        return self.wsgi_app(environ, start_response)


def create_app(settings, runner=None) -> Flask:
    app = Flask(__name__)
    app.config["SETTINGS"] = settings
    app.config["RUNNER"] = runner
    app.secret_key = "leidiniai-ingress"  # flash messages only; access is limited to HA ingress
    app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024
    app.wsgi_app = IngressPrefix(app.wsgi_app)
    app.jinja_env.filters.update(fmt.FILTERS)
    app.jinja_env.globals.update(CHAIN_NAMES=CHAIN_NAMES, version=__version__)

    @app.before_request
    def only_ingress():
        if settings.dev:
            return None
        if request.remote_addr != INGRESS_PEER:
            log.warning("Refused request from %s (not the ingress gateway)", request.remote_addr)
            abort(403)
        return None

    from .offers import bp as offers_bp
    from .views import bp
    app.register_blueprint(bp)
    app.register_blueprint(offers_bp)
    return app
