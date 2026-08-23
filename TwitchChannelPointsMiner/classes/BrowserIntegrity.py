# -*- coding: utf-8 -*-
"""Mints Twitch Client-Integrity tokens using a real headless Chromium.

Twitch scores integrity tokens by how they were obtained. Tokens fetched
from plain HTTP clients (requests) carry a low trust score and are
rejected on protected mutations (bonus claims) with IntegrityCheckFailed,
even with correct cookies/headers. Running the request from inside a
real Chromium produces a trusted token.

Requires the optional dependency:

    pip install playwright && python -m playwright install chromium
"""
import logging
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)


class BrowserUnavailable(Exception):
    pass


class BrowserIntegrity(object):
    """Lazily-started headless Chromium that returns integrity tokens."""

    def __init__(self, auth_token=None, data_dir=None, auth_token_provider=None):
        # Either a static token or (preferably) a callable returning the
        # current token - the miner's cookie file can be renamed/rotated.
        self.auth_token = auth_token
        self._auth_token_provider = auth_token_provider
        self.data_dir = str(data_dir) if data_dir else None
        self._lock = threading.Lock()
        self._playwright = None
        self._context = None
        self._page = None
        self.token = None
        self.expires = 0

    def _current_auth_token(self):
        if self._auth_token_provider is not None:
            try:
                return self._auth_token_provider()
            except Exception:
                return None
        return self.auth_token

    # ------------------------------------------------------------------ #
    def _ensure_browser(self):
        if self._page is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            raise BrowserUnavailable(
                "playwright is not installed. Run: "
                "pip install playwright && python -m playwright install chromium"
            ) from e

        Path(self.data_dir).mkdir(parents=True, exist_ok=True)
        logger.info("Starting headless Chromium for integrity tokens...")
        self._playwright = sync_playwright().start()
        try:
            self._context = self._playwright.chromium.launch_persistent_context(
                self.data_dir,
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            auth_token = self._current_auth_token()
            if auth_token:
                self._context.add_cookies(
                    [
                        {
                            "name": "auth-token",
                            "value": auth_token,
                            "domain": ".twitch.tv",
                            "path": "/",
                        }
                    ]
                )
            self._page = self._context.new_page()
            self._page.goto(
                "https://www.twitch.tv/", wait_until="domcontentloaded", timeout=60000
            )
            logger.info("Headless Chromium ready")
        except Exception:
            self.stop()
            raise

    # ------------------------------------------------------------------ #
    def get_token(self, force=False):
        """Return a (hopefully fresh) integrity token, or raise."""
        with self._lock:
            if (
                not force
                and self.token
                and time.time() < self.expires - 120
            ):
                return self.token
            self._ensure_browser()
            payload = self._page.evaluate(
                "fetch('https://gql.twitch.tv/integrity',"
                "{method:'POST',credentials:'include'})"
                ".then(r=>r.json())"
            )
            self.token = (payload or {}).get("token") or None
            if not self.token:
                raise BrowserUnavailable(f"Browser returned no token: {payload}")
            exp_ms = int((payload or {}).get("expiration") or 0)
            if exp_ms > 10_000_000_000:  # epoch-ms
                self.expires = exp_ms / 1000
            else:
                self.expires = time.time() + 1800
            logger.info(
                f"Browser integrity token acquired (valid ~"
                f"{int(self.expires - time.time())}s)"
            )
            return self.token

    # ------------------------------------------------------------------ #
    def stop(self):
        try:
            if self._context:
                self._context.close()
            if self._playwright:
                self._playwright.stop()
        except Exception:
            pass
        finally:
            self._context = None
            self._playwright = None
            self._page = None
