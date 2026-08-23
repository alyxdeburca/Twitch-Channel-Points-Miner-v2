# -*- coding: utf-8 -*-
"""End-to-end tests for runtime streamer management via the dashboard API.

Covers the demo mode (mutable backing list) and a live miner (fake miner
object exercising TwitchChannelPointsMiner.add_streamer /
remove_streamer semantics without touching Twitch).
"""
import json
import os
import time
import unittest
import urllib.request
from unittest import mock

from TwitchChannelPointsMiner.dashboard_server import DashboardServer

HOST, PORT = "127.0.0.1", 8183
BASE = f"http://{HOST}:{PORT}"


class FakeStreamer(object):
    def __init__(self, username):
        self.username = username.lower()
        self.channel_id = f"id-{self.username}"
        self.history = {}


class FakeMiner(object):
    """Mimics the real add/remove semantics without network calls."""

    running = True
    session_id = "fake"
    username = "fakeuser"

    def __init__(self):
        self.streamers = [FakeStreamer("existing")]
        self.original_streamers = [100]
        self.calls = {"add": [], "remove": []}

    def add_streamer(self, username):
        self.calls["add"].append(username)
        username = str(username).lower().strip()
        if any(s.username == username for s in self.streamers):
            return None, f"'{username}' is already being tracked"
        if username == "ghost":
            return None, "Twitch user 'ghost' does not exist"
        self.streamers.append(FakeStreamer(username))
        self.original_streamers.append(0)
        return self.streamers[-1], None

    def remove_streamer(self, username):
        username = str(username).lower().strip()
        self.calls["remove"].append(username)
        for i, s in enumerate(self.streamers):
            if s.username == username:
                self.streamers.pop(i)
                if i < len(self.original_streamers):
                    self.original_streamers.pop(i)
                return True
        return False


def request(path, payload=None, expect_status=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        status, body = resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        status, body = e.code, json.loads(e.read().decode())
    if expect_status is not None:
        assert status == expect_status, f"{path}: {status} != {expect_status}: {body}"
    return status, body


class StreamerManagementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Other test modules (e.g. test_dashboard_auth) may export Twitch
        # OAuth env vars; this suite must run with auth disabled regardless
        # of import order. DashboardServer snapshots config in __init__,
        # so clearing the vars just around construction is enough.
        with mock.patch.dict(os.environ):
            for var in ("TWITCH_CLIENT_ID", "TWITCH_CLIENT_SECRET", "DASHBOARD_ALLOWED_USERS"):
                os.environ.pop(var, None)
            cls.httpd = DashboardServer(miner=None, host=HOST, port=PORT)
        cls.httpd.daemon = True
        cls.httpd.start()
        time.sleep(0.5)

    def test_01_demo_add_remove_roundtrip(self):
        _, body = request("/api/streamers/add", {"username": "New_Guy"}, 200)
        self.assertTrue(body["success"])
        _, cfg = request("/api/config", expect_status=200)
        self.assertIn("new_guy", cfg["streamers"])
        # /api/all must include the new streamer too
        _, all_data = request("/api/all", expect_status=200)
        names = [s["username"] for s in all_data["streamers"]]
        self.assertIn("new_guy", names)
        # duplicate rejected
        _, body = request("/api/streamers/add", {"username": "new_guy"}, 400)
        self.assertFalse(body["success"])
        # remove works
        _, body = request("/api/streamers/remove", {"username": "new_guy"}, 200)
        self.assertTrue(body["success"])
        _, cfg = request("/api/config")
        self.assertNotIn("new_guy", cfg["streamers"])

    def test_02_demo_remove_unknown_fails_with_404(self):
        status, body = request("/api/streamers/remove", {"username": "nobody"}, 404)
        self.assertFalse(body["success"])
        self.assertEqual(body["error"], "streamer not tracked")

    def test_03_empty_username_rejected(self):
        _, body = request("/api/streamers/add", {"username": ""}, 400)
        self.assertFalse(body["success"])

    def test_04_invalid_json_body_rejected(self):
        req = urllib.request.Request(
            BASE + "/api/streamers/add",
            data=b"this is not json",
            headers={"Content-Type": "application/json"},
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=10)
        self.assertEqual(ctx.exception.code, 400)

    def test_05_live_miner_add_and_remove(self):
        miner = FakeMiner()
        with mock.patch.dict(os.environ):
            for var in ("TWITCH_CLIENT_ID", "TWITCH_CLIENT_SECRET", "DASHBOARD_ALLOWED_USERS"):
                os.environ.pop(var, None)
            httpd = DashboardServer(miner=miner, host="127.0.0.1", port=PORT + 1)
        httpd.daemon = True
        httpd.start()
        try:
            time.sleep(0.4)
            base = f"http://127.0.0.1:{PORT + 1}"
            old_base = BASE
            # temporarily point helper at the live-miner server
            globals()["_live_base"] = base

            _, cfg = _get(base, "/api/config")
            self.assertEqual(cfg["streamers"], ["existing"])

            _, body = _post(base, "/api/streamers/add", {"username": "Someone"})
            self.assertTrue(body["success"])

            _, body = _post(base, "/api/streamers/add", {"username": "someone"})
            self.assertFalse(body["success"])  # duplicate

            _, body = _post(base, "/api/streamers/remove", {"username": "SOMEONE"})
            self.assertTrue(body["success"])

            _, cfg = _get(base, "/api/config")
            self.assertEqual(cfg["streamers"], ["existing"])
            self.assertEqual(miner.calls["remove"], ["someone"])
        finally:
            inner = getattr(httpd, "httpd", None)
            if inner is not None:
                inner.shutdown()
                inner.server_close()


def _get(base, path):
    resp = urllib.request.urlopen(base + path, timeout=10)
    return resp.status, json.loads(resp.read().decode())


def _post(base, path, payload):
    req = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


if __name__ == "__main__":
    unittest.main(verbosity=2)
