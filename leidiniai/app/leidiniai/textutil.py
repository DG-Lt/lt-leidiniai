"""Text helpers: plain-letter search key and Lithuanian date parsing."""
from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta

# CLAUDE.md: ą→a, č→c, ę→e, ė→e, į→i, š→s, ų→u, ū→u, ž→z, lower case
_LT = str.maketrans({"ą": "a", "č": "c", "ę": "e", "ė": "e", "į": "i", "š": "s", "ų": "u", "ū": "u", "ž": "z",
                     "Ą": "a", "Č": "c", "Ę": "e", "Ė": "e", "Į": "i", "Š": "s", "Ų": "u", "Ū": "u", "Ž": "z"})


def fold(text: str | None) -> str:
    """Plain-letter key for search and matching. The printed text is always stored next to it."""
    if not text:
        return ""
    s = text.translate(_LT).lower()
    # other accents (é, ü, ö …) → base letter
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    s = s.replace(" ", " ")
    s = re.sub(r"[^\w%+]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


_MONTHS = {"saus": 1, "vasa": 2, "kov": 3, "bala": 4, "gegu": 5, "birz": 6, "liep": 7,
           "rugp": 8, "rugs": 9, "spal": 10, "lapk": 11, "gruo": 12}


def month_number(word: str) -> int | None:
    w = fold(word)
    for k, v in _MONTHS.items():
        if w.startswith(k):
            return v
    return None


def _near_year(month: int, day: int, ref: date) -> date:
    """Pick the year that puts month/day closest to ref (handles December → January)."""
    best = None
    for y in (ref.year - 1, ref.year, ref.year + 1):
        try:
            d = date(y, month, day)
        except ValueError:
            continue
        if best is None or abs((d - ref).days) < abs((best - ref).days):
            best = d
    return best


_RE_DATE = re.compile(
    r"(?P<iso>(?P<y1>20\d\d)(?P<sep>[.\-/]|\s)(?P<m1>\d{1,2})(?P=sep)(?P<d1>\d{1,2})(?!\d))"
    r"|(?P<lt>(?:(?P<y2>20\d\d)\s*m\.?\s*)?(?P<mon>[A-Za-zĄČĘĖĮŠŲŪŽąčęėįšųūž]{3,})\s+(?P<d2>\d{1,2})\s*d\b\.?)"
    r"|(?P<md>\b(?P<m3>\d{1,2})\.(?P<d3>\d{1,2})\b)",
)


def find_dates(text: str, ref: date) -> list[tuple[int, date]]:
    """All dates in text in order, as (position, date). Years carried from an earlier full date."""
    out: list[tuple[int, date]] = []
    year_hint = None
    for m in _RE_DATE.finditer(text or ""):
        try:
            if m.group("iso"):
                d = date(int(m.group("y1")), int(m.group("m1")), int(m.group("d1")))
                year_hint = d.year
            elif m.group("lt"):
                mon = month_number(m.group("mon"))
                if not mon:
                    continue
                day = int(m.group("d2"))
                if m.group("y2"):
                    year_hint = int(m.group("y2"))
                if year_hint:
                    d = date(year_hint, mon, day)
                    if out and d < out[-1][1]:  # "gruodžio 28 d. – sausio 3 d."
                        d = date(year_hint + 1, mon, day)
                else:
                    d = _near_year(mon, day, ref)
            else:
                mon, day = int(m.group("m3")), int(m.group("d3"))
                if not (1 <= mon <= 12 and 1 <= day <= 31):
                    continue
                if year_hint:
                    d = date(year_hint, mon, day)
                    if out and d < out[-1][1]:
                        d = date(year_hint + 1, mon, day)
                else:
                    d = _near_year(mon, day, ref)
        except ValueError:
            continue
        out.append((m.start(), d))
    return out


def parse_range(text: str, ref: date) -> tuple[date | None, date | None]:
    """'2026.11.12 - 2026.11.25', '2026 m. lapkričio 18 d. – gruodžio 1 d.', 'Nuo lapkričio 16 d.', 'Iki 11.23'."""
    ds = find_dates(text, ref)
    if not ds:
        return None, None
    if len(ds) >= 2:
        return ds[0][1], ds[1][1]
    pos, d = ds[0]
    before = fold(text[:pos])[-12:]
    if re.search(r"\biki\b|\bki\b", before):
        return None, d
    return d, None


def iso_week_range(year: int, week: int, start_weekday: int = 0) -> tuple[date, date]:
    """Seven days of ISO week `week`, starting on start_weekday (0=Mon, 1=Tue …)."""
    monday = date.fromisocalendar(year, week, 1)
    start = monday + timedelta(days=start_weekday)
    return start, start + timedelta(days=6)
