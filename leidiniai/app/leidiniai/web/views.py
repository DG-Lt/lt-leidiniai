"""Panel pages."""
from __future__ import annotations

from flask import Blueprint, current_app, render_template

bp = Blueprint("ui", __name__)


def settings():
    return current_app.config["SETTINGS"]


@bp.get("/")
def offers():
    return render_template("offers.html", offers=[], total=0)


@bp.get("/busena")
def status():
    return render_template("status.html", options=settings().public())
