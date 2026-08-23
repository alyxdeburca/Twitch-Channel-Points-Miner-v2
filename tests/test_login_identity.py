# -*- coding: utf-8 -*-
"""Tests for username reconciliation after cookie login.

The run script may contain a placeholder ("your-twitch-username") or a
stale name; the imported browser token is authoritative, so login()
asks GQL who the token belongs to and renames the cookies file.
"""
import os
import shutil
import tempfile
import unittest
from unittest import mock

from TwitchChannelPointsMiner.classes.Twitch import Twitch
from TwitchChannelPointsMiner.classes.TwitchLogin import TwitchLogin


class FakeResp(object):
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class GetAuthenticatedUsernameTests(unittest.TestCase):
    def setUp(self):
        self.login = TwitchLogin("client-id", "placeholder", "agent/1.0")

    def test_parses_current_user_from_gql(self):
        self.login.set_token("tok")
        with mock.patch(
            "TwitchChannelPointsMiner.classes.TwitchLogin.requests.post",
            return_value=FakeResp(
                200, {"data": {"currentUser": {"login": "Real_User", "id": "123"}}}
            ),
        ):
            self.assertEqual(self.login.get_authenticated_username(), "real_user")

    def test_none_without_token(self):
        self.assertIsNone(self.login.get_authenticated_username())

    def test_none_on_http_error(self):
        self.login.set_token("tok")
        with mock.patch.object(
            self.login.session, "post", return_value=FakeResp(401)
        ):
            self.assertIsNone(self.login.get_authenticated_username())

    def test_none_on_malformed_payload(self):
        self.login.set_token("tok")
        with mock.patch.object(
            self.login.session, "post", return_value=FakeResp(200, {"data": {}})
        ):
            self.assertIsNone(self.login.get_authenticated_username())


class LoginReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.tmp)  # Twitch() puts cookies/ under cwd
        self.twitch = Twitch("your-twitch-username", "agent/1.0")
        # Pretend an already-cached cookie file exists under the placeholder name
        with open(self.twitch.cookies_file, "wb") as fh:
            fh.write(b"stub")

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_login_fixes_placeholder_and_renames_cookie_file(self):
        with mock.patch.object(
            TwitchLogin,
            "load_cookies",
            lambda self, f: setattr(
                self,
                "cookies",
                [
                    {"name": "auth-token", "value": "tok"},
                    {"name": "persistent", "value": "42"},
                ],
            ),
        ), mock.patch.object(
            TwitchLogin,
            "get_authenticated_username",
            lambda self: "alyx_real",
        ):
            result = self.twitch.login()

        self.assertEqual(result, "alyx_real")
        self.assertEqual(self.twitch.twitch_login.username, "alyx_real")
        expected = os.path.abspath(os.path.join("cookies", "alyx_real.pkl"))
        self.assertEqual(self.twitch.cookies_file, expected)
        self.assertTrue(os.path.isfile(expected))
        self.assertFalse(
            os.path.isfile(os.path.join("cookies", "your-twitch-username.pkl"))
        )

    def test_login_keeps_name_when_gql_unavailable(self):
        with mock.patch.object(
            TwitchLogin,
            "load_cookies",
            lambda self, f: None,
        ), mock.patch.object(
            TwitchLogin,
            "get_authenticated_username",
            lambda self: None,
        ):
            result = self.twitch.login()
        self.assertIsNone(result)
        self.assertEqual(self.twitch.twitch_login.username, "your-twitch-username")


if __name__ == "__main__":
    unittest.main(verbosity=2)
