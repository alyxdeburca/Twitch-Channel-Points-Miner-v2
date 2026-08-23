# -*- coding: utf-8 -*-
"""Mints Twitch Client-Integrity tokens using a real headless Chromium.

Twitch scores integrity tokens by how they were obtained. Tokens fetched
from plain HTTP clients (requests) carry a low trust score and are
rejected on protected mutations (bonus claims) with IntegrityCheckFailed,
even with correct cookies/headers. Running the request from inside a
real Chromium produces a trusted token.

Threading model: Playwright's sync API is bound to the thread that
created it ("Cannot switch to a different thread" otherwise). ALL browser
work therefore happens on ONE dedicated worker thread; other miner
threads request tokens through a queue and wait on a Future.

Requires the optional dependency:

    pip install playwright && python -m playwright install chromium
"""
import logging
import queue
import threading
import time
import concurrent.futures
from pathlib import Path

logger = logging.getLogger(__name__)


class BrowserUnavailable(Exception):
    pass


class BrowserIntegrity(object):
    """Headless-Chromium integrity-token minter, safe for multi-thread use."""

    def __init__(self, auth_token=None, data_dir=None, auth_token_provider=None):
        # Either a static token or (preferably) a callable returning the
        # current token - the miner's cookie file can be renamed/rotated.
        self.auth_token = auth_token
        self._auth_token_provider = auth_token_provider
        self.data_dir = str(data_dir) if data_dir else None

        self.token = None
        self.expires = 0

        self._lock = threading.Lock()
        self._jobs = queue.Queue()
        self._worker = None
        self._stopping = False
        # Browser objects - touched ONLY on the worker thread
        self._playwright = None
        self._context = None
        self._page = None

    def _current_auth_token(self):
        if self._auth_token_provider is not None:
            try:
                return self._auth_token_provider()
            except Exception:
                return None
        return self.auth_token

    # ------------------------------------------------------------------ #
    # Public API (any thread)
    # ------------------------------------------------------------------ #
    def get_token(self, force=False):
        """Return an integrity token. Thread-safe."""
        if not force and self.token and time.time() < self.expires - 120:
            return self.token

        with self._lock:
            if self._stopping:
                raise BrowserUnavailable("browser integrity is shutting down")
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(
                    target=self._worker_loop,
                    name="browser-integrity",
                    daemon=True,
                )
                self._worker.start()

        future = concurrent.futures.Future()
        self._jobs.put(({"kind": "mint"}, future))
        # Generous timeout: cold start launches Chromium + loads twitch.tv
        return future.result(timeout=150)

    def gql(self, json_data):
        """Execute a GQL operation INSIDE the page (trusted TLS+cookie
        context). Thread-safe; returns parsed JSON response dict."""
        if not isinstance(json_data, dict):
            raise ValueError("json_data must be a dict")
        with self._lock:
            if self._stopping:
                raise BrowserUnavailable("browser integrity is shutting down")
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(
                    target=self._worker_loop,
                    name="browser-integrity",
                    daemon=True,
                )
                self._worker.start()
        future = concurrent.futures.Future()
        self._jobs.put(({"kind": "gql", "payload": json_data}, future))
        return future.result(timeout=90)

    def stop(self):
        """Signal the worker to shut the browser down (best effort)."""
        self._stopping = True
        try:
            self._jobs.put_nowait(None)
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # Worker thread - owns every Playwright interaction
    # ------------------------------------------------------------------ #
    def _worker_loop(self):
        logger.info("Browser-integrity worker started")
        while True:
            job = self._jobs.get()
            if job is None or self._stopping:
                break
            spec, future = job
            if future.done():
                continue
            try:
                if spec.get("kind") == "gql":
                    future.set_result(self._gql_in_page(spec["payload"]))
                else:
                    future.set_result(self._mint())
            except Exception as e:
                message = str(e).splitlines()[0][:200]
                logger.warning(f"Browser job failed: {message}")
                future.set_exception(BrowserUnavailable(message))
        self._shutdown_browser()
        logger.info("Browser-integrity worker stopped")

    def _gql_in_page(self, payload):
        """POST a GQL operation from inside the loaded twitch.tv page.

        The request then carries Chromium's TLS fingerprint, the device
        cookies AND the auth cookie natively - the full trusted context
        that Python requests cannot provide."""
        self._ensure_browser()
        token = self.get_token(force=False)
        result = self._page.evaluate(
            """
(args) => {
  const x = new XMLHttpRequest();
  x.open('POST', 'https://gql.twitch.tv/gql', false);  // sync
  x.setRequestHeader('Client-Id', 'kimne78kx3ncx6brgo4mv6wki5h1ko');
  x.setRequestHeader('Authorization', 'OAuth ' + args.token);
  x.setRequestHeader('Content-Type', 'application/json');
  if (args.integrity) { x.setRequestHeader('Client-Integrity', args.integrity); }
  try { x.send(JSON.stringify(args.payload)); }
  catch (e) { return {__error: String(e)}; }
  try {
    const parsed = JSON.parse(x.responseText);
    parsed.__status = x.status;
    return parsed;
  } catch (e) {
    return {__error: 'parse ' + x.status, __body: x.responseText.slice(0,200)};
  }
}
""",
            {"token": self._current_auth_token(), "integrity": token, "payload": payload},
        )
        if not isinstance(result, dict) or result.get("__error"):
            raise BrowserUnavailable(f"in-page GQL failed: {str(result)[:160]}")
        result.pop("__status", None)
        return result

    def _mint(self):
        last_error = None
        payload = None
        for attempt in range(2):
            try:
                self._ensure_browser()
                payload = self._fetch_via_js()
                if payload and payload.get("token"):
                    break
                last_error = f"no token in payload: {str(payload)[:120]}"
                logger.warning(
                    f"Browser token attempt {attempt + 1}/2: {last_error}"
                )
                self._teardown_page()  # rebuild the page for the next try
            except Exception as e:
                last_error = str(e).splitlines()[0][:160]
                logger.warning(
                    f"Browser token attempt {attempt + 1}/2 failed: {last_error}"
                )
                self.stop_page_and_rebuild()

        token = (payload or {}).get("token")
        if not token:
            raise BrowserUnavailable(f"browser minting failed: {last_error}")

        exp_ms = int((payload or {}).get("expiration") or 0)
        if exp_ms > 10_000_000_000:  # epoch-ms
            self.expires = exp_ms / 1000
        else:
            self.expires = time.time() + 1800
        self.token = token
        logger.info(
            f"Browser integrity token acquired (valid ~{int(self.expires - time.time())}s)"
        )
        return token

    def stop_page_and_rebuild(self):
        """Tear down context so the next attempt starts clean."""
        try:
            if self._context:
                self._context.close()
        except Exception:
            pass
        try:
            if self._playwright:
                self._playwright.stop()
        except Exception:
            pass
        self._context = None
        self._playwright = None
        self._page = None

    def _teardown_page(self):
        try:
            if self._page:
                self._page.close()
        except Exception:
            pass
        self._page = None

    # ------------------------------------------------------------------ #
    # Browser internals (worker thread only!)
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
            # Realistic Chrome UA + steady locale/timezone so Twitch's
            # signal collection sees a coherent environment.
            ua = (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            )
            self._context = self._playwright.chromium.launch_persistent_context(
                self.data_dir,
                headless=True,
                user_agent=ua,
                locale="en-US",
                timezone_id="Europe/London",
                viewport={"width": 1280, "height": 800},
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--lang=en-US",
                    "--no-first-run",
                    "--no-default-browser-check",
                ],
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
            self._page.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
            )
            self._page.goto(
                "https://www.twitch.tv/",
                wait_until="domcontentloaded",
                timeout=60000,
            )
            # Give Twitch's own protection script (p.js) time to install -
            # fetching too early causes 'Failed to fetch'.
            try:
                self._page.wait_for_load_state("networkidle", timeout=30000)
            except Exception:
                pass
            self._page.wait_for_timeout(2500)
            logger.info("Headless Chromium ready")
        except Exception:
            self._shutdown_browser()
            raise

    def _fetch_via_js(self):
        """Synchronous in-page XHR to /integrity - PROVEN WORKING.

        (Async fetch/XHR via page.evaluate fails with network errors;
        a blocking sync XHR succeeds and returns the token payload.)"""
        js = """
() => {
  const x = new XMLHttpRequest();
  x.open('POST', 'https://gql.twitch.tv/integrity', false);  // sync
  x.setRequestHeader('Client-Id', 'kimne78kx3ncx6brgo4mv6wki5h1ko');
  try { x.send(null); }
  catch (e) { return {error: String(e)}; }
  if (x.status !== 200) return {error: 'HTTP ' + x.status, body: x.responseText.slice(0, 200)};
  try { return JSON.parse(x.responseText); }
  catch (e) { return {error: 'parse: ' + String(e), body: x.responseText.slice(0, 200)}; }
}
"""
        result = self._page.evaluate(js)
        if not isinstance(result, dict) or "token" not in result:
            raise BrowserUnavailable(f"page returned: {str(result)[:160]}")
        return result

    def _shutdown_browser(self):
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
