"""Headless Chromium (Playwright) for pages that need JavaScript or block plain requests.

Started only when needed, one page at a time, closed at the end of the job.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from .http import UA, Blocked, FetchError


@dataclass
class Page:
    url: str
    html: str
    captured: list[dict] = field(default_factory=list)  # [{url, status, body(bytes)}]


class Browser:
    def __init__(self, settings, log: logging.Logger, before_request=None):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:  # pragma: no cover - image always has it
            raise Blocked("Playwright is not installed") from e
        self.log = log
        self.before = before_request or (lambda url: None)
        self._pw = sync_playwright().start()
        self._b = self._pw.chromium.launch(headless=True, args=[
            "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
            f"--renderer-process-limit={max(1, int(settings.threads))}",
        ])
        self._ctx = self._b.new_context(user_agent=UA.replace("lt-leidiniai", "HeadlessChrome lt-leidiniai"),
                                        accept_downloads=True,
                                        locale="lt-LT", timezone_id="Europe/Vilnius",
                                        viewport={"width": 1280, "height": 1800})
        # images/fonts/media are not needed for reading the page
        self._ctx.route(re.compile(r".*\.(png|jpe?g|gif|webp|svg|woff2?|ttf|mp4)(\?.*)?$"),
                        lambda route: route.abort())
        log.info("Headless browser started")

    def render(self, url: str, wait_for: str | None = None, need=None, capture: str | None = None,
               timeout_ms: int = 60000, settle_ms: int = 2500) -> Page:
        """Open url, wait for network idle (+ optional selector), return HTML and captured responses."""
        self.before(url)
        page = self._ctx.new_page()
        captured: list[dict] = []
        cap = re.compile(capture) if capture else None

        def on_response(resp):
            if cap and cap.search(resp.url):
                try:
                    captured.append({"url": resp.url, "status": resp.status, "body": resp.body()})
                except Exception as e:  # body may be gone after navigation
                    self.log.debug("capture failed %s: %s", resp.url, e)

        page.on("response", on_response)
        try:
            resp = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=timeout_ms)
            except Exception:
                self.log.debug("networkidle not reached: %s", url)
            if wait_for:
                page.wait_for_selector(wait_for, timeout=timeout_ms)
            page.wait_for_timeout(settle_ms)
            html = page.content()
            status = resp.status if resp else 0
            if "Just a moment..." in html[:4000]:
                # Cloudflare JS challenge: give it one more chance to pass by itself (no CAPTCHA solving)
                page.wait_for_timeout(8000)
                html = page.content()
                if "Just a moment..." in html[:4000]:
                    raise Blocked(f"{url}: bot protection page even in the headless browser")
            if status >= 400 and not html:
                raise FetchError(f"HTTP {status}: {url}")
            if need is not None and not re.search(need, html):
                self.log.warning("Expected content still missing after rendering: %s", url)
            return Page(url=page.url, html=html, captured=captured)
        finally:
            page.close()

    def download_by_button(self, url: str, button: str, timeout_ms: int = 90000) -> tuple[bytes, str] | None:
        """Open url, press the button whose accessible name matches `button` (regex) and return the file it
        downloads (bytes, suggested name) – for viewers that make the PDF link only on click (iPaper
        "Atsiųsti PDF rinkmeną"). A cookie banner is answered with "only necessary". None if nothing came."""
        self.before(url)
        page = self._ctx.new_page()
        pdf_responses: list = []
        page.on("response", lambda r: pdf_responses.append(r)
                if "application/pdf" in (r.headers.get("content-type") or "") else None)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=timeout_ms)
            except Exception:
                pass
            for name in (r"tik būtin", r"Naudoti tik", r"Atmesti"):
                b = page.get_by_role("button", name=re.compile(name, re.I))
                if b.count():
                    try:
                        b.first.click(timeout=3000)
                        break
                    except Exception:
                        pass
            target = page.get_by_role("button", name=re.compile(button, re.I))
            if not target.count():
                self.log.info("No '%s' button on %s", button, url)
                return None
            try:
                with page.expect_download(timeout=timeout_ms) as dl:
                    target.first.click(timeout=10000)
                d = dl.value
                p = d.path()
                return (open(p, "rb").read(), d.suggested_filename) if p else None
            except Exception as e:  # some viewers open the PDF instead of downloading it
                page.wait_for_timeout(3000)
                for r in pdf_responses:
                    try:
                        return r.body(), r.url.rsplit("/", 1)[-1].split("?")[0] or "leidinys.pdf"
                    except Exception:
                        continue
                self.log.info("Button '%s' gave no file on %s (%s)", button, url, e)
                return None
        finally:
            page.close()

    def fetch_bytes(self, url: str, referer: str | None = None) -> bytes:
        """GET with the browser's cookies (after a challenge was passed on the site)."""
        self.before(url)
        r = self._ctx.request.get(url, headers={"Referer": referer} if referer else None, timeout=180000)
        if not r.ok:
            raise FetchError(f"HTTP {r.status} (browser): {url}")
        return r.body()

    def close(self) -> None:
        for f in (self._ctx.close, self._b.close, self._pw.stop):
            try:
                f()
            except Exception:
                pass
        self.log.info("Headless browser closed")
