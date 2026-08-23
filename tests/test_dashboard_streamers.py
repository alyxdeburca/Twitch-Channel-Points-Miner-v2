# -*- coding: utf-8 -*-
"""End-to-end tests for runtime streamer management via the dashboard API.

Covers demo mode (mutable backing list), settings editing/validation,
and a live miner path (fake miner delegating to the real settings
validator, so no network calls are made).
"""
import json
import os
import time
import unittest
import urllib.error
import urllib.request
from unittest import mock

from TwitchChannelPointsMiner.dashboard_server import DashboardServer

HOST, PORT = "127.0.0.1", 8183
BASE = f"http://{HOST}:{PORT}"

AUTH_VARS = ("TWITCH_CLIENT_ID", "TWITCH_CLIENT_SECRET", "DASHBOARD_ALLOWED_USERS")


class FakeStreamer(object):
    def __init__(self, username):
        self.username = username.lower()
        self.channel_id = f"id-{self.username}"
        self.history = {}


class FakeMiner(object):
    """Mimics real miner semantics; uses the REAL settings validator."""

    running = True
    session_id = "fake"
    username = "fakeuser"

    def __init__(self):
        self.streamers = [FakeStreamer("existing")]
        self.original_streamers = [100]
        self.calls = {"add": [], "remove": []}
        self.settings_applied = []

    def add_streamer(self, username):
        self.calls["add"].append(str(username).lower().strip())
        username = str(username).lower().strip()
        if any(s.username == username for s in self.streamers):
            return None, f"'{username}' is already being tracked"
        if username == "ghost":
            return None, f"Twitch user '{username}' does not exist"
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

    def update_streamer_settings(self, username, update):
        from TwitchChannelPointsMiner.TwitchChannelPointsMiner import (
            TwitchChannelPointsMiner as MinerClass,
        )

        username = str(username).lower().strip()
        if not any(s.username == username for s in self.streamers):
            raise ValueError(f"'{username}' is not being tracked")
        # Delegate to the REAL typed validator - this is what we want to test.
        parsed = MinerClass._parse_streamer_settings(update)
        self.settings_applied.append(parsed)


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


class StreamerManagementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Other suites may export OAuth env vars; force auth off here.
        with mock.patch.dict(os.environ):
            for var in AUTH_VARS:
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
        _, all_data = request("/api/all", expect_status=200)
        names = [s["username"] for s in all_data["streamers"]]
        self.assertIn("new_guy", names)
        _, body = request("/api/streamers/add", {"username": "new_guy"}, 400)
        self.assertFalse(body["success"])
        _, body = request("/api/streamers/remove", {"username": "new_guy"}, 200)
        self.assertTrue(body["success"], body)
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
            for var in AUTH_VARS:
                os.environ.pop(var, None)
            httpd = DashboardServer(miner=miner, host="127.0.0.1", port=PORT + 1)
        httpd.daemon = True
        httpd.start()
        try:
            time.sleep(0.4)
            base = f"http://127.0.0.1:{PORT + 1}"

            _, cfg = _get(base, "/api/config")
            self.assertEqual(cfg["streamers"], ["existing"])

            _, body = _post(base, "/api/streamers/add", {"username": "Someone"})
            self.assertTrue(body["success"])

            _, body = _post(base, "/api/streamers/add", {"username": "someone"})
            self.assertEqual(body["success"], False)  # duplicate

            _, body = _post(base, "/api/streamers/remove", {"username": "SOMEONE"})
            self.assertTrue(body["success"], body)

            _, cfg = _get(base, "/api/config")
            self.assertEqual(cfg["streamers"], ["existing"])
            self.assertEqual(miner.calls["remove"], ["someone"])
        finally:
            inner = getattr(httpd, "httpd", None)
            if inner is not None:
                inner.shutdown()
                inner.server_close()

    def test_06_settings_update_roundtrip_demo(self):
        _, body = _post(
            BASE,
            "/api/streamers/settings",
            {
                "username": "demo_streamer",
                "settings": {"bet": {"strategy": "HIGH_ODDS", "percentage": 7}},
            },
        )
        self.assertTrue(body["success"], body)
        _, streamers = request("/api/streamers", expect_status=200)
        demo = next(s for s in streamers if s["username"] == "demo_streamer")
        self.assertEqual(demo["settings"]["bet"]["strategy"], "HIGH_ODDS")
        self.assertEqual(demo["settings"]["bet"]["percentage"], 7)

    def test_07_settings_validation_errors(self):
        cases = [
            {"bet": {"strategy": "YOLO"}},
            {"bet": {"percentage": 500}},
            {"chat": "SOMETIMES"},
        ]
        for settings in cases:
            status, body = _post(
                BASE,
                "/api/streamers/settings",
                {"username": "demo_streamer", "settings": settings},
            )
            self.assertEqual(status, 400, f"{settings}: {body}")
            self.assertFalse(body["success"])

    def test_08_settings_filter_condition_set_and_clear(self):
        _, body = _post(
            BASE,
            "/api/streamers/settings",
            {
                "username": "second_channel",
                "settings": {
                    "bet": {
                        "filter_condition": {
                            "by": "TOTAL_POINTS",
                            "where": "GTE",
                            "value": 250,
                        }
                    }
                },
            },
        )
        self.assertTrue(body["success"], body)
        _, streamers = request("/api/streamers")
        second = next(s for s in streamers if s["username"] == "second_channel")
        fc = second["settings"]["bet"]["filter_condition"]
        self.assertEqual(fc["by"], "TOTAL_POINTS")
        self.assertEqual(fc["where"], "GTE")
        # clear it again
        _, body = _post(
            BASE,
            "/api/streamers/settings",
            {
                "username": "second_channel",
                "settings": {"bet": {"filter_condition": None}},
            },
        )
        self.assertTrue(body["success"])
        _, streamers = request("/api/streamers")
        second = next(s for s in streamers if s["username"] == "second_channel")
        self.assertIsNone(second["settings"]["bet"]["filter_condition"])

    def test_09_settings_unknown_streamer_rejected(self):
        status, body = _post(
            BASE,
            "/api/streamers/settings",
            {"username": "who_dis", "settings": {"chat": "ALWAYS"}},
        )
        self.assertEqual(status, 400)
        self.assertIn("not being tracked", body["error"])

    def test_10_live_miner_settings_via_real_validator(self):
        miner = FakeMiner()
        with mock.patch.dict(os.environ):
            for var in AUTH_VARS:
                os.environ.pop(var, None)
            httpd = DashboardServer(miner=miner, host="127.0.0.1", port=PORT + 2)
        httpd.daemon = True
        httpd.start()
        try:
            time.sleep(0.4)
            ok, err = httpd.update_streamer_settings(
                "existing",
                {
                    "make_predictions": True,
                    "chat": "ONLINE",
                    "bet": {
                        "strategy": "SMART_MONEY",
                        "percentage": 9,
                        "filter_condition": {
                            "by": "ODDS_PERCENTAGE",
                            "where": "GT",
                            "value": 55,
                        },
                    },
                },
            )
            self.assertTrue(ok, err)
            applied = miner.settings_applied[-1]
            self.assertEqual(applied["bet"]["strategy"].name, "SMART_MONEY")
            self.assertEqual(applied["bet"]["percentage"], 9)
            # OutcomeKeys values are lowercase strings - what Bet.skip() uses
            from TwitchChannelPointsMiner.classes.entities.Bet import OutcomeKeys
            self.assertEqual(
                applied["bet"]["filter_condition"].by, OutcomeKeys.ODDS_PERCENTAGE
            )

            ok, err = httpd.update_streamer_settings(
                "existing", {"bet": {"strategy": "NOPE"}}
            )
            self.assertFalse(ok)
            self.assertIn("strategy", err)

            ok, err = httpd.update_streamer_settings("ghost2", {"chat": "ONLINE"})
            self.assertFalse(ok)
            self.assertIn("not being tracked", err)
        finally:
            inner = getattr(httpd, "httpd", None)
            if inner is not None:
                inner.shutdown()
                inner.server_close()


    def test_11_live_miner_state_serialization_regression(self):
        """Regression: /api/streamers on a LIVE miner crashed with NameError
        (_OUTCOME_KEYS_BY_NAME) because the demo path never exercised the
        real-settings serialization branch."""
        from TwitchChannelPointsMiner.classes.entities.Bet import (
            BetSettings,
            Condition,
            FilterCondition,
            OutcomeKeys,
            Strategy,
        )
        from TwitchChannelPointsMiner.classes.entities.Streamer import (
            Streamer,
            StreamerSettings,
        )

        miner = FakeMiner()
        real = Streamer("real_channel")
        real.settings = StreamerSettings(make_predictions=True)
        real.settings.default()
        real.settings.bet = BetSettings(
            strategy=Strategy.SMART,
            percentage=5,
            stealth_mode=True,
            filter_condition=FilterCondition(
                by=OutcomeKeys.TOTAL_USERS, where=Condition.LTE, value=800
            ),
        )
        real.settings.bet.default()
        miner.streamers = [real]
        miner.original_streamers = [0]

        with mock.patch.dict(os.environ):
            for var in AUTH_VARS:
                os.environ.pop(var, None)
            httpd = DashboardServer(miner=miner, host="127.0.0.1", port=PORT + 3)
        httpd.daemon = True
        httpd.start()
        try:
            time.sleep(1.0)
            status, streamers = _get(f"http://127.0.0.1:{PORT + 3}", "/api/streamers")
            self.assertEqual(status, 200)
            entry = next(s for s in streamers if s["username"] == "real_channel")
            bet = entry["settings"]["bet"]
            self.assertEqual(bet["strategy"], "SMART")
            self.assertEqual(bet["filter_condition"]["by"], "TOTAL_USERS")
            self.assertEqual(bet["filter_condition"]["where"], "LTE")
            self.assertEqual(bet["filter_condition"]["value"], 800)
            # full payload endpoint must work too (this is what the UI polls)
            status, _ = _get(f"http://127.0.0.1:{PORT + 3}", "/api/all")
            self.assertEqual(status, 200)
        finally:
            inner = getattr(httpd, "httpd", None)
            if inner is not None:
                inner.shutdown()
                inner.server_close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
