# -*- coding: utf-8 -*-
"""End-to-end tests for the dashboard auth flow.

Twitch's OAuth endpoints are mocked (requests.patched inside
dashboard_auth), everything else - HTTP server, routing, cookies,
sessions, allowlist - runs for real against a live DashboardServer.
"""
import os
import time
import unittest
import urllib.error
import urllib.request
from unittest import mock
from urllib.parse import parse_qs, urlparse

os.environ["TWITCH_CLIENT_ID"] = "test-client-id"
os.environ["TWITCH_CLIENT_SECRET"] = "test-client-secret"
os.environ["DASHBOARD_ALLOWED_USERS"] = "allowed_user"

from TwitchChannelPointsMiner.dashboard_auth import (
    SessionStore,
    TwitchAuth,
    _validate_token_and_get_user,
)
from TwitchChannelPointsMiner.dashboard_server import DashboardServer

HOST, PORT = "127.0.0.1", 8182
BASE = f"http://{HOST}:{PORT}"


class FakeResponse(object):
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


def fake_requests_post(url, data=None, timeout=None):
    if url.endswith("/token"):
        if data.get("grant_type") == "authorization_code":
            return FakeResponse(200, {"access_token": "tok-123"})
        if data.get("device_code"):
            return FakeResponse(200, {"access_token": "tok-device"})
    return FakeResponse(400)


def fake_requests_get(url, headers=None, timeout=None):
    if url.endswith("/validate"):
        return FakeResponse(200, {"client_id": "test-client-id", "login": "allowed_user"})
    if url == "https://api.twitch.tv/helix/users":
        return FakeResponse(200, {"data": [{"login": "Allowed_User", "id": "42"}]})
    return FakeResponse(404)


@mock.patch("TwitchChannelPointsMiner.dashboard_auth.requests.get", fake_requests_get)
@mock.patch("TwitchChannelPointsMiner.dashboard_auth.requests.post", fake_requests_post)
class AuthFlowTests(unittest.TestCase):
    httpd = None

    @classmethod
    def setUpClass(cls):
        cls.httpd = DashboardServer(miner=None, host=HOST, port=PORT, require_auth=True)
        assert cls.httpd.require_auth, "auth must be enforced"
        cls.httpd.daemon = True
        cls.httpd.start()

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **kw):
                return None

        cls.opener = urllib.request.build_opener(NoRedirect)
        time.sleep(0.5)

    def get(self, path, cookie=None):
        req = urllib.request.Request(BASE + path)
        if cookie:
            req.add_header("Cookie", cookie)
        try:
            resp = self.opener.open(req, timeout=10)
            return resp.status, dict(resp.headers), resp.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read().decode()

    def test_01_unauthenticated_redirects_and_api_401(self):
        status, headers, _ = self.get("/")
        self.assertEqual(status, 302)
        self.assertEqual(headers.get("Location"), "/auth/login")
        status, _, _ = self.get("/api/status")
        self.assertEqual(status, 401)

    def test_02_full_authorization_code_flow(self):
        status, headers, _ = self.get("/auth/login")
        self.assertEqual(status, 302)
        location = headers.get("Location", "")
        self.assertIn("id.twitch.tv/oauth2/authorize", location)
        state = parse_qs(urlparse(location).query)["state"][0]

        status, headers, _ = self.get(f"/auth/callback?code=abc&state={state}")
        self.assertEqual(status, 302)
        self.assertEqual(headers.get("Location"), "/")
        set_cookie = headers.get("Set-Cookie", "")
        self.assertIn("dashboard_session=", set_cookie)
        self.assertIn("HttpOnly", set_cookie)
        cookie = set_cookie.split(";")[0]

        status, headers, body = self.get("/", cookie=cookie)
        self.assertEqual(status, 200)
        self.assertIn("Twitch Miner Dashboard", body)

        # The signed session must resolve back to the twitch username
        username = self.httpd.sessions.resolve(cookie.split("=", 1)[1])
        self.assertEqual(username, "allowed_user")

    def test_03_bad_state_rejected(self):
        status, _, _ = self.get("/auth/callback?code=abc&state=forged")
        self.assertEqual(status, 403)

    def test_04_tampered_cookie_rejected(self):
        status, headers, _ = self.get("/auth/login")
        state = parse_qs(urlparse(headers["Location"]).query)["state"][0]
        _, headers, _ = self.get(f"/auth/callback?code=abc&state={state}")
        cookie = headers["Set-Cookie"].split(";")[0]
        name, value = cookie.split("=", 1)
        tampered = f"{name}={value[:-4]}aaaa"
        status, _, _ = self.get("/", cookie=tampered)
        self.assertEqual(status, 302)

    def test_05_logout_clears_session(self):
        _, headers, _ = self.get("/auth/login")
        state = parse_qs(urlparse(headers["Location"]).query)["state"][0]
        _, headers, _ = self.get(f"/auth/callback?code=abc&state={state}")
        cookie = headers["Set-Cookie"].split(";")[0]
        status, headers, _ = self.get("/auth/logout", cookie=cookie)
        self.assertEqual(status, 302)
        status, _, _ = self.get("/", cookie=cookie)
        self.assertEqual(status, 302)  # session gone -> back to login

    def test_06_allowlist_blocks_other_users(self):
        store_sessions = SessionStore()
        auth = TwitchAuth()
        with mock.patch(
            "TwitchChannelPointsMiner.dashboard_auth._validate_token_and_get_user",
            return_value="some_other_user",
        ):
            self.assertIsNone(auth._authorize_username("tok-x"))
        with mock.patch(
            "TwitchChannelPointsMiner.dashboard_auth._validate_token_and_get_user",
            return_value="ALLOWED_USER",  # case-insensitive match
        ):
            self.assertEqual(auth._authorize_username("tok-x"), "allowed_user")

    def test_07_session_store_roundtrip_and_tamper(self):
        store = SessionStore(secret_file="/tmp/test_dash_secret")
        signed = store.create("bob")
        self.assertEqual(store.resolve(signed), "bob")
        sid, sig = signed.rsplit(".", 1)
        self.assertIsNone(store.resolve(f"{sid}.{'0' * len(sig)}"))
        self.assertIsNone(store.resolve("garbage"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
