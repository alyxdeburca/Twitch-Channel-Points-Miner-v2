# -*- coding: utf-8 -*-
"""Tests for the cookie-only login flow.

Password/console login was removed (Twitch answers it with CAPTCHA);
the miner imports the twitch.tv session from your browser instead and
caches it in cookies/<username>.pkl.
"""
import unittest
from unittest import mock

from TwitchChannelPointsMiner.classes.TwitchLogin import TwitchLogin

CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"


def make_login():
    return TwitchLogin(CLIENT_ID, "testuser", "test-agent")


class FakeBc3(object):
    """Stand-in for the browser_cookie3 module."""

    def __init__(self, jar=None):
        self._jar = jar or object()
        self.calls = []

    def _make(self, name):
        def loader(**kwargs):
            self.calls.append((name, kwargs))
            return self._jar

        return loader

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self._make(name)


class CookieOnlyFlowTests(unittest.TestCase):
    def test_login_flow_returns_false_when_browser_import_fails(self):
        login = make_login()
        with mock.patch.object(
            TwitchLogin,
            "login_flow_backup",
            mock.MagicMock(return_value=None),
        ) as backup:
            self.assertFalse(login.login_flow())
            backup.assert_called_once()
            self.assertIsNone(login.token)

    def test_login_flow_success_sets_token(self):
        login = make_login()
        with mock.patch.object(
            TwitchLogin,
            "login_flow_backup",
            mock.MagicMock(return_value="browser-token"),
        ), mock.patch.object(
            TwitchLogin,
            "check_login",
            mock.MagicMock(return_value=True),
        ):
            self.assertTrue(login.login_flow())
            self.assertEqual(login.token, "browser-token")
            self.assertEqual(
                login.session.headers["Authorization"], "Bearer browser-token"
            )

    def test_cookies_saved_even_when_verification_flakes(self):
        # Regression: a transient GQL failure used to mean the imported
        # session was never cached, forcing a browser re-import every run.
        login = make_login()
        with mock.patch.object(
            TwitchLogin,
            "login_flow_backup",
            mock.MagicMock(return_value="browser-token"),
        ), mock.patch.object(
            TwitchLogin,
            "check_login",
            mock.MagicMock(return_value=False),
        ):
            self.assertTrue(login.login_flow())

    def test_backup_prompts_and_loads_chrome_cookies(self):
        login = make_login()
        fake_bc3 = FakeBc3()
        answers = iter(["1", ""])  # browser choice, then "press Enter"
        with mock.patch(
            "TwitchChannelPointsMiner.classes.TwitchLogin.browser_cookie3", fake_bc3
        ), mock.patch(
            "builtins.input", side_effect=lambda *a: next(answers)
        ), mock.patch(
            "TwitchChannelPointsMiner.classes.TwitchLogin.requests.utils.dict_from_cookiejar",
            return_value={"login": "chromeuser", "auth-token": "tok-chr"},
        ):
            token = login.login_flow_backup()
        self.assertEqual(token, "tok-chr")
        self.assertEqual(login.username, "chromeuser")
        self.assertEqual(fake_bc3.calls[0][0], "chrome")

    def test_safari_option_loads_cookies(self):
        login = make_login()
        fake_bc3 = FakeBc3()
        answers = iter(["4", ""])
        with mock.patch(
            "TwitchChannelPointsMiner.classes.TwitchLogin.browser_cookie3", fake_bc3
        ), mock.patch(
            "builtins.input", side_effect=lambda *a: next(answers)
        ), mock.patch(
            "TwitchChannelPointsMiner.classes.TwitchLogin.requests.utils.dict_from_cookiejar",
            return_value={"login": "safariuser", "auth-token": "tok-saf"},
        ):
            token = login.login_flow_backup()
        self.assertEqual(token, "tok-saf")
        self.assertEqual(login.username, "safariuser")
        self.assertEqual(fake_bc3.calls[0][0], "safari")

    def test_missing_auth_token_returns_none_with_hint(self):
        login = make_login()
        fake_bc3 = FakeBc3()
        answers = iter(["1", ""])
        with mock.patch(
            "TwitchChannelPointsMiner.classes.TwitchLogin.browser_cookie3", fake_bc3
        ), mock.patch(
            "builtins.input", side_effect=lambda *a: next(answers)
        ), mock.patch(
            "TwitchChannelPointsMiner.classes.TwitchLogin.requests.utils.dict_from_cookiejar",
            return_value={"login": "someone"},  # no auth-token
        ):
            self.assertIsNone(login.login_flow_backup())

    def test_unreadable_cookie_jar_returns_none_with_hint(self):
        login = make_login()
        fake_bc3 = FakeBc3()
        answers = iter(["2", ""])
        with mock.patch(
            "TwitchChannelPointsMiner.classes.TwitchLogin.browser_cookie3", fake_bc3
        ), mock.patch(
            "builtins.input", side_effect=lambda *a: next(answers)
        ), mock.patch(
            "TwitchChannelPointsMiner.classes.TwitchLogin.requests.utils.dict_from_cookiejar",
            side_effect=PermissionError("keychain denied"),
        ):
            self.assertIsNone(login.login_flow_backup())


if __name__ == "__main__":
    unittest.main(verbosity=2)
