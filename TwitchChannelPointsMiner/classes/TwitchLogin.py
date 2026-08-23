# Based on https://github.com/derrod/twl.py
# Original Copyright (c) 2020 Rodney
# The MIT License (MIT)

import copy
import logging
import os
import pickle

import browser_cookie3
import requests

from TwitchChannelPointsMiner.classes.Exceptions import WrongCookiesException
from TwitchChannelPointsMiner.constants import GQLOperations

logger = logging.getLogger(__name__)


class TwitchLogin(object):
    __slots__ = [
        "client_id",
        "token",
        "login_check_result",
        "session",
        "username",
        "user_id",
        "email",
        "cookies",
    ]

    def __init__(self, client_id, username, user_agent):
        self.client_id = client_id
        self.token = None
        self.login_check_result = False
        self.session = requests.session()
        self.session.headers.update(
            {"Client-ID": self.client_id, "User-Agent": user_agent}
        )
        self.username = username
        self.user_id = None
        self.email = None

        self.cookies = []

    def login_flow(self):
        """Cookie-only login: import the twitch.tv session from your browser.

        Console/password logins are no longer attempted - Twitch answers
        them with CAPTCHA challenges. Log in to twitch.tv in your normal
        browser once; the miner copies that session and caches it locally
        (cookies/<username>.pkl) so later runs skip this step.
        """
        logger.info(
            f"No cookies found for {self.username} - importing your Twitch login from your browser."
        )
        token = self.login_flow_backup()
        if token is None:
            return False
        self.set_token(token)
        if self.check_login() is False:
            # The GQL sanity check can fail transiently while the imported
            # session itself is perfectly valid. Save the cookies anyway -
            # otherwise a working login would never be cached and every
            # run would repeat the browser import.
            logger.warning(
                "Imported session could not be verified right now - saving cookies anyway. "
                f"If mining fails later, delete the cookies file for {self.username} and retry."
            )
        return True

    def set_token(self, new_token):
        self.token = new_token
        self.session.headers.update({"Authorization": f"Bearer {self.token}"})

    def login_flow_backup(self):
        """Backup OAuth login flow in case manual captcha solving is required"""

        def _safari():
            try:
                return browser_cookie3.safari(domain_name=twitch_domain)
            except TypeError:
                # Older browser_cookie3 releases have no domain_name kwarg
                return browser_cookie3.safari()

        browser = input(
            "What browser do you use? Chrome (1), Firefox (2), "
            "Auto-detect any installed (3), Safari (4): "
        ).strip()
        twitch_domain = ".twitch.tv"
        loaders = {
            "1": ("Chrome", lambda: browser_cookie3.chrome(domain_name=twitch_domain)),
            "2": ("Firefox", lambda: browser_cookie3.firefox(domain_name=twitch_domain)),
            "3": (
                "your installed browsers",
                lambda: browser_cookie3.load(domain_name=twitch_domain),
            ),
            "4": ("Safari", _safari),
        }
        if browser not in loaders:
            logger.info("Your browser is unsupported, sorry.")
            return None

        browser_name, load_cookies = loaders[browser]
        input(
            f"Please log in to twitch.tv inside {browser_name} "
            "(NOT a private/incognito window) and press Enter..."
        )
        logger.info(f"Loading cookies saved on your computer ({browser_name})...")
        try:
            cookies_dict = requests.utils.dict_from_cookiejar(load_cookies())
        except Exception as e:
            logger.error(
                f"Could not read cookies from {browser_name}: {e}. "
                "On macOS, allow Full Disk Access for your terminal app "
                "(System Settings > Privacy & Security > Full Disk Access), "
                "then run this again."
            )
            return None

        if not cookies_dict.get("auth-token"):
            logger.error(
                f"No Twitch auth-token found - log in to twitch.tv in {browser_name} first."
            )
            return None

        # Only override the configured username if the browser told us one,
        # otherwise check_login() would later query GQL with channelLogin=None.
        if cookies_dict.get("login"):
            self.username = cookies_dict["login"]
        return cookies_dict["auth-token"]

    def get_authenticated_username(self):
        """Return the login name that owns the current auth token, or None.

        Queries Twitch GQL with the imported browser token - authoritative,
        unlike the 'login' cookie which can be stale."""
        if self.token is None:
            return None
        try:
            response = requests.post(
                "https://gql.twitch.tv/gql",
                json={"query": "{ currentUser { login id } }"},
                headers={
                    "Client-ID": self.client_id,
                    "Authorization": f"OAuth {self.token}",
                },
                timeout=10,
            )
            if response.status_code == 200:
                current_user = (response.json().get("data") or {}).get("currentUser")
                if current_user and current_user.get("login"):
                    return current_user["login"].lower()
        except (requests.RequestException, ValueError):
            pass
        return None

    def check_login(self):
        if self.login_check_result:
            return self.login_check_result
        if self.token is None:
            return False

        self.login_check_result = self.__set_user_id()
        return self.login_check_result

    def save_cookies(self, cookies_file):
        cookies_dict = self.session.cookies.get_dict()
        cookies_dict["auth-token"] = self.token
        if "persistent" not in cookies_dict:  # saving user id cookies
            cookies_dict["persistent"] = self.user_id

        self.cookies = []
        for cookie_name, value in cookies_dict.items():
            self.cookies.append({"name": cookie_name, "value": value})
        pickle.dump(self.cookies, open(cookies_file, "wb"))

    def get_cookie_value(self, key):
        for cookie in self.cookies:
            if cookie["name"] == key:
                if cookie["value"] is not None:
                    return cookie["value"]
        return None

    def load_cookies(self, cookies_file):
        if os.path.isfile(cookies_file):
            self.cookies = pickle.load(open(cookies_file, "rb"))
        else:
            raise WrongCookiesException("There must be a cookies file!")

    def get_user_id(self):
        persistent = self.get_cookie_value("persistent")
        user_id = (
            int(persistent.split("%")[0]) if persistent is not None else self.user_id
        )
        if user_id is None:
            if self.__set_user_id() is True:
                return self.user_id
        return user_id

    def __set_user_id(self):
        json_data = copy.deepcopy(GQLOperations.ReportMenuItem)
        json_data["variables"] = {"channelLogin": self.username}
        response = self.session.post(GQLOperations.url, json=json_data)

        if response.status_code == 200:
            json_response = response.json()
            if (
                "data" in json_response
                and "user" in json_response["data"]
                and json_response["data"]["user"]["id"] is not None
            ):
                self.user_id = json_response["data"]["user"]["id"]
                return True
        return False

    def get_auth_token(self):
        return self.get_cookie_value("auth-token")
