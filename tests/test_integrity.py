# -*- coding: utf-8 -*-
"""Tests for the Client-Integrity token handling in post_gql_request.

Twitch rejects sensitive mutations (bonus claims) with
IntegrityCheckFailed unless a Client-Integrity token + X-Device-Id are
attached. The miner fetches tokens from gql.twitch.tv/integrity,
caches them by TTL and retries once on failure.
"""
import unittest
from unittest import mock

from TwitchChannelPointsMiner.classes.Twitch import Twitch


class FakeResp(object):
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = str(self._payload)

    def json(self):
        return self._payload


def make_twitch(tmpdir):
    twitch = Twitch.__new__(Twitch)
    twitch.cookies_file = "unused.pkl"
    twitch.user_agent = "agent/1.0"
    twitch.running = True
    twitch.device_id = None
    twitch.integrity_token = None
    twitch.integrity_expires = 0
    twitch.twitch_login = mock.MagicMock()
    twitch.twitch_login.get_auth_token.return_value = "tok"
    import requests

    twitch.http_session = requests.Session()
    twitch._session_primed = True  # never hit the network in unit tests
    twitch.browser_integrity = None  # browser path off in unit tests
    return twitch


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.twitch = make_twitch("/tmp")

    def test_integrity_headers_fetch_and_cache(self):
        with mock.patch.object(
            self.twitch.http_session,
            "post",
            return_value=FakeResp(200, {"token": "abc", "expiration": 1800}),
        ) as mock_post:
            headers = self.twitch._integrity_headers()
            # /integrity must be POST (GET returns 405)
            self.assertEqual(mock_post.call_args[0][0], "https://gql.twitch.tv/integrity")
        self.assertEqual(headers.get("Client-Integrity"), "abc")
        self.assertIn("X-Device-Id", headers)
        # Second call must NOT re-fetch (cached by TTL)
        with mock.patch.object(
            self.twitch.http_session, "post"
        ) as mock_post:
            headers = self.twitch._integrity_headers()
            mock_post.assert_not_called()
        self.assertEqual(headers["Client-Integrity"], "abc")

    def test_expired_token_refetched(self):
        self.twitch.integrity_token = "old"
        self.twitch.integrity_expires = 0  # expired
        with mock.patch.object(
            self.twitch.http_session,
            "post",
            return_value=FakeResp(200, {"token": "new", "expiration": 1800}),
        ):
            headers = self.twitch._integrity_headers()
        self.assertEqual(headers["Client-Integrity"], "new")

    def test_failed_fetch_sends_nothing(self):
        """Regression: a lone X-Device-Id without a token made Twitch gate
        ordinary queries ('user not found' on valid channels). When the
        token is unavailable, send NO integrity headers at all."""
        with mock.patch.object(
            self.twitch.http_session,
            "post",
            return_value=FakeResp(403),
        ):
            headers = self.twitch._integrity_headers()
        self.assertEqual(headers, {})
        # Within negative-cache window: no refetch attempt, still bare
        with mock.patch.object(
            self.twitch.http_session, "post"
        ) as mock_post:
            self.assertEqual(self.twitch._integrity_headers(), {})
            mock_post.assert_not_called()

    def test_post_gql_attaches_headers_and_retries_on_integrity_fail(self):
        gql_calls = []

        def fake_post(url, json=None, headers=None, timeout=None):
            gql_calls.append(headers)
            if len(gql_calls) == 1:
                # First attempt lacks integrity -> rejected
                self.assertNotIn("Client-Integrity", headers or {})
                return FakeResp(
                    200,
                    {
                        "errors": [
                            {
                                "message": "failed integrity check",
                                "extensions": {"code": "IntegrityCheckFailed"},
                            }
                        ]
                    },
                )
            # Retry must carry the integrity token
            self.assertEqual((headers or {}).get("Client-Integrity"), "fresh")
            return FakeResp(200, {"data": {"claimCommunityPoints": {"error": None}}})

        header_states = [{}, {"X-Device-Id": "d", "Client-Integrity": "fresh"}]
        with mock.patch.object(
            Twitch,
            "_integrity_headers",
            side_effect=lambda *a, **k: header_states[min(len(gql_calls), 1)],
        ), mock.patch.object(
            self.twitch.http_session, "post", side_effect=fake_post
        ), mock.patch.object(
            Twitch,
            "refresh_integrity_token",
            side_effect=lambda: setattr(self.twitch, "integrity_token", "fresh"),
        ):
            result = self.twitch.post_gql_request({"operationName": "ClaimCommunityPoints"})

        self.assertEqual(len(gql_calls), 2)
        self.assertEqual(result, {"data": {"claimCommunityPoints": {"error": None}}})

    def test_device_id_persisted_and_reused(self):
        import tempfile
        import os

        with tempfile.TemporaryDirectory() as tmp:
            old = os.getcwd()
            os.chdir(tmp)
            try:
                device1 = self.twitch._load_device_id()
                file_path = os.path.join(".dashboard", "device_id")
                self.assertTrue(os.path.isfile(file_path))
                # A fresh instance reads the same id
                twitch2 = make_twitch(tmp)
                device2 = twitch2._load_device_id()
                self.assertEqual(device1, device2)
            finally:
                os.chdir(old)


if __name__ == "__main__":
    unittest.main(verbosity=2)
