"""Number/date formats shown to the user: `10 050.53`, `2026-11-02`, `19:04`, € only on money."""
from __future__ import annotations

from datetime import date, datetime


def number(v, decimals: int = 0) -> str:
    if v is None:
        return "–"
    s = f"{v:,.{decimals}f}"
    return s.replace(",", " ")


def money_cents(c) -> str:
    if c is None:
        return "–"
    return f"{number(c / 100, 2)} €"


def day(v) -> str:
    if not v:
        return "–"
    if isinstance(v, (date, datetime)):
        return v.strftime("%Y-%m-%d")
    return str(v)[:10]


def dt(v) -> str:
    if not v:
        return "–"
    if isinstance(v, str):
        try:
            v = datetime.fromisoformat(v)
        except ValueError:
            return v
    if v.tzinfo:
        v = v.astimezone()
    return v.strftime("%Y-%m-%d %H:%M")


def duration(seconds) -> str:
    if seconds is None:
        return "–"
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds} s"
    m, s = divmod(seconds, 60)
    if m < 60:
        return f"{m} min {s} s"
    h, m = divmod(m, 60)
    return f"{h} h {m} min"


def fromjson(s):
    import json
    try:
        return json.loads(s or '{}')
    except ValueError:
        return {}


FILTERS = {"fromjson": fromjson, "number": number, "money": money_cents, "day": day, "dt": dt, "duration": duration}
