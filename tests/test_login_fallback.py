# -*- coding: utf-8 -*-
"""Regression tests for the Twitch login fallback.

passport.twitch.tv/login now often replies with a CAPTCHA challenge
(HTML or empty body) instead of JSON. The miner must fall back to the
browser-cookie flow instead of crashing with a JSONDecodeError.
"""
import unittest
from unittest import mock

from TwitchChannelPointsMiner.classes.Exceptions import (
    BadCredentialsException,
)
from TwitchChannelPointsMiner.classes.TwitchLogin import TwitchLogin

CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"


def make_login():
    login = TwitchLogin(CLIENT_ID, "testuser", "test-agent", password="pw")
    return login


class FakeResp(object):
    def __init__(self, payload=None, raw=None, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = raw or ""

    def json(self):
        if self._payload is None:
            raise ValueError("Expecting value")  # what requests raises on bad JSON
        return self._payload


class LoginFallbackTests(unittest.TestCase):
    def test_non_json_response_maps_to_captcha_error_1000(self):
        login = make_login()
        with mock.patch.object(
            login.session, "post", return_value=FakeResp(raw="<html>captcha</html>")
        ):
            result = login.send_login_request({"username": "x", "password": "y"})
        self.assertEqual(result, {"error_code": 1000})

    def test_empty_body_maps_to_captcha_error_1000(self):
        login = make_login()
        with mock.patch.object(login.session, "post", return_value=FakeResp(raw="")):
            result = login.send_login_request({})
        self.assertEqual(result, {"error_code": 1000})

    def test_valid_json_passthrough(self):
        login = make_login()
        with mock.patch.object(
            login.session,
            "post",
            return_value=FakeResp(payload={"access_token": "tok"}),
        ):
            result = login.send_login_request({})
        self.assertEqual(result, {"access_token": "tok"})

    def test_login_flow_uses_backup_when_captcha_required(self):
        login = make_login()
        # TwitchLogin defines __slots__, so patch at class level, not instance
        with mock.patch.object(
            login.session, "post", return_value=FakeResp(raw="")
        ), mock.patch.object(
            TwitchLogin,
            "login_flow_backup",
            mock.MagicMock(return_value="browser-token"),
        ) as backup, mock.patch.object(
            TwitchLogin,
            "check_login",
            mock.MagicMock(return_value=True),
        ):
            self.assertTrue(login.login_flow())
            backup.assert_called_once()
            self.assertEqual(login.token, "browser-token")

    def test_safari_option_loads_cookies(self):
        login = make_login()
        fake_bc3 = mock.MagicMock()
        fake_bc3.safari.return_value = object()
        answers = iter(["4", ""])  # browser choice, then "press Enter"
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
        fake_bc3.safari.assert_called_once()

    def test_missing_auth_token_returns_none_with_hint(self):
        login = make_login()
        fake_bc3 = mock.MagicMock()
        fake_bc3.chrome.return_value = object()
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

    def test_bad_credentials_still_raise_when_password_configured(self):
        login = make_login()  # password configured -> no interactive retry
        with mock.patch.object(
            login.session,
            "post",
            return_value=FakeResp(payload={"error_code": 3001}),
        ):
            with self.assertRaises(BadCredentialsException):
                login.login_flow()


if __name__ == "__main__":
    unittest.main(verbosity=2)
