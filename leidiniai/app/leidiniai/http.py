"""Gentle HTTP for the shops' sites.

- one request at a time, `request_delay` seconds (+ up to 30 % jitter) between requests to the same host
- an honest User-Agent naming the app
- one retry on connection errors / 5xx
- blocked (403/429/503, Cloudflare challenge) or JavaScript-only pages → headless browser (if allowed)
"""
from __future__ import annotations

import hashlib
import logging
import random
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

from . import __version__

UA = f"Mozilla/5.0 (X11; Linux x86_64) lt-leidiniai/{__version__} (Home Assistant app; +https://github.com/DG-Lt/lt-leidiniai)"
TIMEOUT = (15, 120)


class FetchError(Exception):
    pass


class Blocked(FetchError):
    """The site refused a plain request (bot protection)."""


def looks_blocked(status: int, headers, text: str) -> bool:
    if status in (403, 429, 503):
        return True
    if headers.get("cf-mitigated") == "challenge":
        return True
    head = text[:4000]
    return "Just a moment..." in head and "cloudflare" in head.lower()


class Http:
    def __init__(self, settings, log: logging.Logger | None = None):
        self.settings = settings
        self.log = log or logging.getLogger("leidiniai.http")
        self.delay = float(settings.request_delay)
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "lt-LT,lt;q=0.9,en;q=0.5"})
        self._last: dict[str, float] = {}
        self._browser = None
        self.requests = 0
        self.bytes = 0
        self.browser_pages = 0

    # -- spacing -------------------------------------------------------------
    def _wait(self, url: str) -> None:
        host = urlparse(url).hostname or ""
        last = self._last.get(host)
        if last is not None:
            gap = self.delay * (1 + random.random() * 0.3)
            left = last + gap - time.monotonic()
            if left > 0:
                time.sleep(left)
        self._last[host] = time.monotonic()

    def _get(self, url: str, stream=False, **kw) -> requests.Response:
        for attempt in (1, 2):
            self._wait(url)
            try:
                r = self.s.get(url, timeout=TIMEOUT, stream=stream, **kw)
                self.requests += 1
            except requests.RequestException as e:
                if attempt == 2:
                    raise FetchError(f"{url}: {e}") from e
                self.log.warning("Request failed (%s), retrying once: %s", e.__class__.__name__, url)
                time.sleep(10)
                continue
            if 500 <= r.status_code < 600 and r.status_code != 503 and attempt == 1:
                self.log.warning("HTTP %s, retrying once: %s", r.status_code, url)
                time.sleep(10)
                continue
            return r
        raise FetchError(url)

    # -- public --------------------------------------------------------------
    def text(self, url: str, need: str | re.Pattern | None = None, browser_ok: bool = True,
             wait_for: str | None = None) -> str:
        """Page text. If blocked or `need` (regex) is missing, try the headless browser."""
        reason = None
        try:
            r = self._get(url)
            body = r.text
            self.bytes += len(r.content)
            if looks_blocked(r.status_code, r.headers, body):
                reason = f"blocked (HTTP {r.status_code})"
            elif r.status_code >= 400:
                raise FetchError(f"HTTP {r.status_code}: {url}")
            elif need is not None and not re.search(need, body):
                reason = "expected content missing (JavaScript page?)"
            else:
                return body
        except Blocked:
            reason = "blocked"
        if not (browser_ok and self.settings.browser_fallback):
            raise Blocked(f"{url}: {reason}; browser fallback is off")
        self.log.info("Plain request not enough (%s) → headless browser: %s", reason, url)
        page = self.browser.render(url, wait_for=wait_for, need=need)
        self.browser_pages += 1
        return page.html

    def json(self, url: str, **kw):
        r = self._get(url, headers={"Accept": "application/json"}, **kw)
        if r.status_code >= 400:
            raise FetchError(f"HTTP {r.status_code}: {url}")
        self.bytes += len(r.content)
        return r.json()

    def download(self, url: str, dest: Path, referer: str | None = None, expect_binary: bool = True) -> dict:
        """Stream to dest (via .part). Returns {url, name, path, sha256, bytes}."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_suffix(dest.suffix + ".part")
        h = hashlib.sha256()
        n = 0
        headers = {"Referer": referer} if referer else {}
        r = self._get(url, stream=True, headers=headers)
        ctype = r.headers.get("content-type", "")
        html_instead = r.status_code < 400 and "text/html" in ctype and expect_binary
        if r.status_code >= 400 or html_instead:
            head = r.text[:4000] if (r.status_code >= 400 or html_instead) else ""
            r.close()
            if (html_instead or looks_blocked(r.status_code, r.headers, head)) and self.settings.browser_fallback:
                self.log.info("Download blocked (HTTP %s, %s) → headless browser: %s", r.status_code, ctype, url)
                data = self.browser.fetch_bytes(url, referer=referer)
                part.write_bytes(data)
                h.update(data)
                n = len(data)
            else:
                raise FetchError(f"HTTP {r.status_code} ({ctype}): {url}")
        else:
            with part.open("wb") as f:
                for chunk in r.iter_content(1 << 16):
                    f.write(chunk)
                    h.update(chunk)
                    n += len(chunk)
        part.replace(dest)
        self.bytes += n
        return {"url": url, "name": dest.name, "path": str(dest), "sha256": h.hexdigest(), "bytes": n}

    # -- browser -------------------------------------------------------------
    @property
    def browser(self):
        if self._browser is None:
            if not self.settings.browser_fallback:
                raise Blocked("headless browser fallback is off in the app options")
            from .browser import Browser
            self._browser = Browser(self.settings, self.log, before_request=self._wait)
        return self._browser

    def close(self) -> None:
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        self.s.close()

    def stats(self) -> dict:
        return {"requests": self.requests, "browser_pages": self.browser_pages, "bytes": self.bytes}
