# -*- coding: utf-8 -*-
"""Optional 'Sign in with Twitch' authentication for the web dashboard.

Two flows are supported (chosen automatically):

- Authorization Code flow: needs TWITCH_CLIENT_ID + TWITCH_CLIENT_SECRET
  and TWITCH_REDIRECT_URI (default: http://<host>:<port>/auth/callback).
- Device flow: needs only TWITCH_CLIENT_ID. Twitch shows an activation
  code at https://www.twitch.tv/activate - handy when the dashboard is
  behind SSH tunnels / Tailscale where a public redirect URI is awkward.

Sessions are random ids stored server-side; the browser only receives an
HMAC-signed cookie. Access control = Twitch username allowlist
(DASHBOARD_ALLOWED_USERS, comma separated; defaults to the miner's own
username when a miner is attached).
"""
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from http import cookies as http_cookies
from pathlib import Path
from threading import Lock

import requests

logger = logging.getLogger(__name__)

AUTH_SCOPE = "user:read:email"
ID_BASE = "https://id.twitch.tv/oauth2"
HELIX_USERS = "https://api.twitch.tv/helix/users"
SESSION_TTL_SECONDS = 7 * 24 * 3600


def _validate_token_and_get_user(access_token, client_id):
    """Return the twitch username owning this token, or None."""
    try:
        r = requests.get(
            f"{ID_BASE}/validate",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        if r.status_code != 200:
            return None
        client_id_for_helix = r.json().get("client_id") or client_id
        r = requests.get(
            HELIX_USERS,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Client-Id": client_id_for_helix,
            },
            timeout=10,
        )
        if r.status_code != 200:
            return None
        data = r.json().get("data") or []
        return data[0]["login"].lower() if data else None
    except requests.RequestException:
        return None


class SessionStore(object):
    """In-memory sessions + signed cookie value ('sid.signature')."""

    def __init__(self, secret_file=".dashboard_session_secret"):
        self._lock = Lock()
        self._sessions = {}  # sid -> {"username":..., "expires": float}
        self.secret = os.environ.get("DASHBOARD_SECRET")
        if not self.secret:
            path = Path(secret_file)
            try:
                if path.is_file():
                    self.secret = path.read_text(encoding="utf-8").strip()
                if not self.secret:
                    self.secret = secrets.token_hex(32)
                    path.write_text(self.secret, encoding="utf-8")
                    try:
                        os.chmod(path, 0o600)
                    except OSError:
                        pass
            except OSError:
                self.secret = secrets.token_hex(32)

    def create(self, username):
        sid = secrets.token_urlsafe(32)
        with self._lock:
            # Opportunistic cleanup
            now = time.time()
            for k in [k for k, v in self._sessions.items() if v["expires"] < now]:
                del self._sessions[k]
            self._sessions[sid] = {
                "username": username.lower(),
                "expires": now + SESSION_TTL_SECONDS,
            }
        return self._sign(sid)

    def resolve(self, cookie_value):
        """cookie_value -> username or None."""
        if not cookie_value or "." not in cookie_value:
            return None
        sid, signature = cookie_value.rsplit(".", 1)
        if not hmac.compare_digest(self._sign(sid), cookie_value):
            return None
        with self._lock:
            session = self._sessions.get(sid)
            if session is None:
                return None
            if session["expires"] < time.time():
                del self._sessions[sid]
                return None
            return session["username"]

    def drop(self, cookie_value):
        if cookie_value and "." in cookie_value:
            sid = cookie_value.rsplit(".", 1)[0]
            with self._lock:
                self._sessions.pop(sid, None)

    def _sign(self, sid):
        digest = hmac.new(
            self.secret.encode("utf-8"), sid.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        return f"{sid}.{digest}"


class TwitchAuth(object):
    """Configuration + OAuth flows. disabled=True -> dashboard open."""

    def __init__(self, host="127.0.0.1", port=8181, allowed_users=None):
        self.client_id = os.environ.get("TWITCH_CLIENT_ID")
        self.client_secret = os.environ.get("TWITCH_CLIENT_SECRET")
        self.redirect_uri = os.environ.get(
            "TWITCH_REDIRECT_URI", f"http://{host}:{port}/auth/callback"
        )
        raw_allowed = os.environ.get("DASHBOARD_ALLOWED_USERS", "")
        users = [
            u.strip().lower()
            for u in (allowed_users or raw_allowed.split(","))
            if u and u.strip()
        ]
        self.allowed_users = [u for u in users if u]
        self.use_device_flow = bool(self.client_id) and not (
            self.client_secret and self.redirect_uri
        )
        # Pending device-flow logins: state -> {...}
        self._pending = {}
        self._lock = Lock()

    @property
    def enabled(self):
        return bool(self.client_id)

    # --------------------------- helpers ------------------------------ #
    def _authorize_username(self, access_token):
        username = _validate_token_and_get_user(access_token, self.client_id)
        if username is None:
            return None
        username = username.lower()
        if self.allowed_users and username not in self.allowed_users:
            logger.warning(f"Twitch user '{username}' authenticated but is not whitelisted")
            return None
        return username

    # ---------------------- authorization code ------------------------ #
    def authorize_url(self):
        state = secrets.token_urlsafe(16)
        with self._lock:
            self._pending[state] = time.time()
        return (
            f"{ID_BASE}/authorize"
            f"?client_id={self.client_id}"
            f"&redirect_uri={requests.utils.quote(self.redirect_uri, safe='')}"
            f"&response_type=code&scope={requests.utils.quote(AUTH_SCOPE, safe='')}"
            f"&state={state}"
        )

    def exchange_code(self, code, state):
        with self._lock:
            expected_state = self._pending.pop(state, None)
        if expected_state is None or expected_state < time.time() - 600:
            return None  # unknown/expired CSRF state
        try:
            r = requests.post(
                f"{ID_BASE}/token",
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": self.redirect_uri,
                },
                timeout=10,
            )
            token = r.json().get("access_token")
        except requests.RequestException:
            return None
        return self._authorize_username(token) if token else None

    # -------------------------- device flow ---------------------------- #
    def device_start(self):
        try:
            r = requests.post(
                f"{ID_BASE}/device",
                data={"client_id": self.client_id, "scopes": AUTH_SCOPE},
                timeout=10,
            )
            payload = r.json()
        except (requests.RequestException, ValueError):
            return None
        if r.status_code != 200 or "device_code" not in payload:
            return None
        state = secrets.token_urlsafe(16)
        with self._lock:
            self._pending[state] = {
                "device_code": payload["device_code"],
                "interval": max(1, int(payload.get("interval", 1))),
                "expires": time.time() + int(payload.get("expires_in", 600)),
            }
        return {
            "state": state,
            "user_code": payload.get("user_code"),
            "verification_uri": payload.get("verification_uri"),
            "interval": max(1, int(payload.get("interval", 1))),
        }

    def device_poll(self, state):
        with self._lock:
            entry = self._pending.get(state)
        if entry is None or entry["expires"] < time.time():
            with self._lock:
                self._pending.pop(state, None)
            return {"status": "expired"}
        try:
            r = requests.post(
                f"{ID_BASE}/token",
                data={
                    "client_id": self.client_id,
                    "device_code": entry["device_code"],
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
                timeout=10,
            )
            payload = r.json()
        except requests.RequestException:
            return {"status": "waiting"}
        error = payload.get("error")
        if error == "authorization_pending":
            return {"status": "waiting"}
        if error == "slow_down":
            with self._lock:
                entry["interval"] = entry["interval"] + 5
            return {"status": "waiting"}
        token = payload.get("access_token")
        if not token:
            with self._lock:
                self._pending.pop(state, None)
            return {"status": "expired"}
        username = self._authorize_username(token)
        with self._lock:
            self._pending.pop(state, None)
        return {"status": "ok", "username": username} if username else {"status": "denied"}

    # ---------------------------- misc -------------------------------- #
    @staticmethod
    def parse_session_cookie(header_value):
        if not header_value:
            return None
        jar = http_cookies.SimpleCookie()
        try:
            jar.load(header_value)
        except http_cookies.CookieError:
            return None
        morsel = jar.get("dashboard_session")
        return morsel.value if morsel else None


LOGIN_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sign in · Twitch Miner Dashboard</title>
<style>
  body {{ background:#0e0e10; color:#efeff1; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
         display:flex; align-items:center; justify-content:center; min-height:100vh; margin:0; }}
  .box {{ background:#18181b; border:1px solid #2f2f35; border-radius:12px; padding:36px; width:min(420px,90vw); text-align:center; }}
  h1 {{ font-size:18px; margin-bottom:8px; }}
  p {{ color:#adadb8; font-size:13px; line-height:1.6; }}
  .tw {{ display:inline-block; margin-top:18px; padding:12px 26px; border-radius:8px; background:#9147ff;
         color:#fff; font-weight:700; text-decoration:none; font-size:15px; }}
  .tw:hover {{ background:#a970ff; }}
  .err {{ color:#ef4444; margin-top:14px; }}
  code {{ background:#1f1f23; padding:2px 6px; border-radius:4px; font-size:12px; }}
  ol {{ text-align:left; color:#adadb8; font-size:13px; line-height:1.8; margin:14px 0 0; padding-left:20px; }}
</style></head>
<body><div class="box">
  <h1>🎮 Twitch Miner Dashboard</h1>
  <p>Private dashboard &mdash; please sign in with Twitch.</p>
  {body}
</div></body></html>
"""
