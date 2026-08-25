# -*- coding: utf-8 -*-
# Replacement web UI for Twitch Channel Points Miner v2.
#
# Zero extra dependencies: uses only the Python standard library
# (http.server + json), so it works even without Flask installed.
# Serves a single-page dark dashboard on top of a read-only JSON API
# backed by the *live* miner state (streamers, bets, events).
import json
import logging
import os
import time
import copy
import base64
import json as _json
from urllib.parse import parse_qs, urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock, Thread

from TwitchChannelPointsMiner.dashboard_auth import (
    LOGIN_PAGE_TEMPLATE,
    SessionStore,
    TwitchAuth,
)
from TwitchChannelPointsMiner.classes.entities.Bet import OUTCOME_KEYS_BY_NAME

logger = logging.getLogger(__name__)

# Choices exposed to the dashboard settings editor.
SETTINGS_OPTIONS = {
    "chat": ["ALWAYS", "NEVER", "ONLINE", "OFFLINE"],
    "strategy": ["MOST_VOTED", "HIGH_ODDS", "PERCENTAGE", "SMART_MONEY", "SMART"],
    "delay_mode": ["FROM_START", "FROM_END", "PERCENTAGE"],
    "filter_by": [
        "NONE",
        "PERCENTAGE_USERS",
        "ODDS_PERCENTAGE",
        "ODDS",
        "TOP_POINTS",
        "TOTAL_USERS",
        "TOTAL_POINTS",
    ],
    "filter_where": ["GT", "LT", "GTE", "LTE"],
}

# Millify is an existing dependency of the miner; fall back to raw numbers
try:
    from millify import millify

    def _millify(value):
        try:
            return millify(value, precision=2)
        except Exception:
            return str(value)
except ImportError:  # pragma: no cover
    def _millify(value):
        return str(value)


def _safe(fn, default=None):
    """Evaluate fn() swallowing every exception (live objects mutate
    concurrently in other miner threads)."""
    try:
        return fn()
    except Exception:
        return default


def _parse_settings_payload(update):
    """Validate a dashboard settings payload (string-typed enums).

    Raises ValueError with a user-readable message on bad input.
    Used by the demo mode; the live miner applies its own stricter
    typed validation in TwitchChannelPointsMiner.update_streamer_settings.
    """
    if not isinstance(update, dict):
        raise ValueError("settings payload must be an object")
    parsed = {}

    for flag in ("make_predictions", "follow_raid", "claim_drops", "watch_streak"):
        if flag in update and update[flag] is not None:
            parsed[flag] = bool(update[flag])

    if "chat" in update and update["chat"] is not None:
        chat = str(update["chat"]).upper()
        if chat not in SETTINGS_OPTIONS["chat"]:
            raise ValueError("chat must be one of " + ", ".join(SETTINGS_OPTIONS["chat"]))
        parsed["chat"] = chat

    bet_update = update.get("bet") or {}
    if not isinstance(bet_update, dict):
        raise ValueError("bet must be an object")
    bet = {}

    if "strategy" in bet_update and bet_update["strategy"] is not None:
        strategy = str(bet_update["strategy"]).upper()
        if strategy not in SETTINGS_OPTIONS["strategy"]:
            raise ValueError(
                "bet.strategy must be one of " + ", ".join(SETTINGS_OPTIONS["strategy"])
            )
        bet["strategy"] = strategy

    for field in ("percentage", "percentage_gap", "max_points", "minimum_points"):
        if field in bet_update and bet_update[field] is not None:
            try:
                value = int(bet_update[field])
            except (TypeError, ValueError):
                raise ValueError(f"bet.{field} must be an integer")
            limits = {
                "percentage": (1, 100),
                "percentage_gap": (0, 100),
                "max_points": (0, 10**9),
                "minimum_points": (0, 10**9),
            }
            low, high = limits[field]
            if not low <= value <= high:
                raise ValueError(f"bet.{field} must be between {low} and {high}")
            bet[field] = value

    if "stealth_mode" in bet_update and bet_update["stealth_mode"] is not None:
        bet["stealth_mode"] = bool(bet_update["stealth_mode"])

    if "delay" in bet_update and bet_update["delay"] is not None:
        try:
            delay = float(bet_update["delay"])
        except (TypeError, ValueError):
            raise ValueError("bet.delay must be a number")
        if not 0 <= delay <= 1200:
            raise ValueError("bet.delay must be between 0 and 1200 seconds")
        bet["delay"] = delay

    if "delay_mode" in bet_update and bet_update["delay_mode"] is not None:
        mode = str(bet_update["delay_mode"]).upper()
        if mode not in SETTINGS_OPTIONS["delay_mode"]:
            raise ValueError(
                "bet.delay_mode must be one of " + ", ".join(SETTINGS_OPTIONS["delay_mode"])
            )
        bet["delay_mode"] = mode

    if "filter_condition" in bet_update:
        fc = bet_update["filter_condition"]
        if fc is None or (isinstance(fc, dict) and str(fc.get("by", "")).upper() == "NONE"):
            bet["filter_condition"] = None
        elif isinstance(fc, dict):
            by = str(fc.get("by", "")).upper()
            where = str(fc.get("where", "")).upper()
            if by != "NONE" and by not in SETTINGS_OPTIONS["filter_by"]:
                raise ValueError(
                    "filter_condition.by must be one of " + ", ".join(SETTINGS_OPTIONS["filter_by"])
                )
            if where not in SETTINGS_OPTIONS["filter_where"]:
                raise ValueError(
                    "filter_condition.where must be one of "
                    + ", ".join(SETTINGS_OPTIONS["filter_where"])
                )
            try:
                value = float(fc.get("value"))
            except (TypeError, ValueError):
                raise ValueError("filter_condition.value must be a number")
            bet["filter_condition"] = {"by": by, "where": where, "value": value}
        else:
            raise ValueError("filter_condition must be null or an object")

    parsed["bet"] = bet
    return parsed


class StateProvider(object):
    """Bridge between the running TwitchChannelPointsMiner instance and
    the dashboard. Also supports demo mode (no miner attached)."""

    def __init__(self, miner=None):
        self.miner = miner
        self.demo = miner is None
        self.demo_streamers = [
            {
                "username": "demo_streamer",
                "url": "https://twitch.tv/demo_streamer",
                "online": True,
                "channel_points": 128450,
                "points_gained": 1250,
                "viewers": 4210,
                "game": "Software & Game Development",
                "title": "Building a channel points miner dashboard",
                "chat": True,
                "watch_streak_missing": False,
                "multipliers": 1.5,
                "settings": {
                    "make_predictions": True,
                    "follow_raid": True,
                    "claim_drops": True,
                    "watch_streak": True,
                    "chat": "ALWAYS",
                    "bet": {
                        "strategy": "SMART",
                        "percentage": 5,
                        "percentage_gap": 20,
                        "max_points": 50000,
                        "minimum_points": 0,
                        "stealth_mode": True,
                        "delay": 6,
                        "delay_mode": "FROM_END",
                        "filter_condition": {
                            "by": "TOTAL_USERS",
                            "where": "LTE",
                            "value": 800,
                        },
                    },
                },
                "history": {
                    "WATCH": {"counter": 214, "amount": 10700},
                    "CLAIM": {"counter": 42, "amount": 4200},
                    "WIN": {"counter": 7, "amount": 3120},
                    "LOSE": {"counter": 3, "amount": -950},
                    "WATCH_STREAK": {"counter": 4, "amount": 800},
                },
            },
            {
                "username": "second_channel",
                "url": "https://twitch.tv/second_channel",
                "online": False,
                "channel_points": 55320,
                "points_gained": 0,
                "viewers": 0,
                "game": None,
                "title": None,
                "chat": False,
                "watch_streak_missing": True,
                "multipliers": 0,
                "settings": {
                    "make_predictions": False,
                    "follow_raid": True,
                    "claim_drops": False,
                    "watch_streak": True,
                    "chat": "NEVER",
                    "bet": {
                        "strategy": "PERCENTAGE",
                        "percentage": 5,
                        "percentage_gap": 20,
                        "max_points": 1234,
                        "minimum_points": 0,
                        "stealth_mode": False,
                        "delay": 6,
                        "delay_mode": "FROM_END",
                        "filter_condition": None,
                    },
                },
                "history": {
                    "WATCH": {"counter": 96, "amount": 4800},
                    "CLAIM": {"counter": 18, "amount": 1800},
                },
            },
        ]
        self.demo_events = [
            {"time": time.time() - 60 * 8, "type": "BONUS_CLAIM", "streamer": "demo_streamer", "text": "Bonus claimed +50"},
            {"time": time.time() - 60 * 5, "type": "STREAMER_ONLINE", "streamer": "demo_streamer", "text": "demo_streamer is Online!"},
            {"time": time.time() - 60 * 2, "type": "BET_START", "streamer": "demo_streamer", "text": "Will it rain tomorrow?"},
        ]

    # ------------------------------------------------------------------ #
    def streamers(self):
        if self.demo:
            return copy.deepcopy(self.demo_streamers)

        streamers = getattr(self.miner, "streamers", None) or []
        result = []
        for s in streamers:
            stream = getattr(s, "stream", None)
            history = {}
            for key, value in _safe(lambda: s.history, {}).items():
                history[str(key)] = {
                    "counter": _safe(lambda: value["counter"], 0),
                    "amount": _safe(lambda: value["amount"], 0),
                }

            settings_obj = getattr(s, "settings", None)
            bet_obj = getattr(settings_obj, "bet", None)
            filter_obj = getattr(bet_obj, "filter_condition", None)
            by_name = {v: k for k, v in OUTCOME_KEYS_BY_NAME.items()}
            settings = {
                "make_predictions": bool(_safe(lambda: settings_obj.make_predictions)),
                "follow_raid": bool(_safe(lambda: settings_obj.follow_raid)),
                "claim_drops": bool(_safe(lambda: settings_obj.claim_drops)),
                "watch_streak": bool(_safe(lambda: settings_obj.watch_streak)),
                "chat": str(_safe(lambda: settings_obj.chat)) or "NEVER",
                "bet": {
                    "strategy": str(_safe(lambda: bet_obj.strategy)) or "SMART",
                    "percentage": _safe(lambda: bet_obj.percentage, 5),
                    "percentage_gap": _safe(lambda: bet_obj.percentage_gap, 20),
                    "max_points": _safe(lambda: bet_obj.max_points, 50000),
                    "minimum_points": _safe(lambda: bet_obj.minimum_points, 0),
                    "stealth_mode": bool(_safe(lambda: bet_obj.stealth_mode, False)),
                    "delay": _safe(lambda: bet_obj.delay, 6),
                    "delay_mode": str(_safe(lambda: bet_obj.delay_mode)) or "FROM_END",
                    "filter_condition": None
                    if filter_obj is None
                    else {
                        "by": by_name.get(
                            _safe(lambda: filter_obj.by), "TOTAL_USERS"
                        ),
                        "where": _safe(lambda: str(filter_obj.where)) or "LTE",
                        "value": _safe(lambda: filter_obj.value, 0),
                    },
                },
            }

            result.append(
                {
                    "username": _safe(lambda: s.username, ""),
                    "url": _safe(lambda: s.streamer_url, "#"),
                    "online": bool(_safe(lambda: s.is_online, False)),
                    "channel_points": _safe(lambda: s.channel_points, 0),
                    "points_gained": _safe(
                        lambda: s.channel_points - self._original_points(s), 0
                    ),
                    "viewers": _safe(lambda: stream.viewers_count, 0) if stream else 0,
                    "game": _safe(lambda: stream.game["displayName"]) if stream else None,
                    "title": _safe(lambda: stream.title) if stream else None,
                    "chat": bool(_safe(lambda: s.irc_chat is not None, False)),
                    "watch_streak_missing": _safe(
                        lambda: stream.watch_streak_missing, True
                    )
                    if stream
                    else True,
                    "multipliers": _safe(lambda: s.total_points_multiplier(), 0),
                    "settings": settings,
                    "history": history,
                }
            )
        return result

    def _original_points(self, streamer):
        originals = getattr(self.miner, "original_streamers", None) or []
        streamers = getattr(self.miner, "streamers", None) or []
        try:
            index = [id(x) for x in streamers].index(id(streamer))
            return originals[index] if index < len(originals) else 0
        except ValueError:
            return 0

    # ------------------------------------------------------------------ #
    def bets(self):
        if self.demo:
            return [
                {
                    "streamer": "demo_streamer",
                    "title": "Will the stream hit 5k viewers today?",
                    "status": "ACTIVE",
                    "closed_in": 143,
                    "decision": {"choice": "A", "amount": 5000, "title": "Yes", "color": "blue"},
                    "outcomes": [
                        {"title": "Yes", "color": "blue", "users": 182, "points": 912000, "odds": 1.94, "odds_percentage": 51.5, "percentage_users": 58.2},
                        {"title": "No", "color": "pink", "users": 131, "points": 861000, "odds": 2.06, "odds_percentage": 48.5, "percentage_users": 41.8},
                    ],
                    "total_users": 313,
                    "total_points": 1773000,
                    "result": None,
                },
                {
                    "streamer": "second_channel",
                    "title": "Subathon hour 12: more coffee?",
                    "status": "RESOLVED",
                    "closed_in": 0,
                    "decision": {"choice": "B", "amount": 2500, "title": "No", "color": "pink"},
                    "outcomes": [
                        {"title": "Yes", "color": "blue", "users": 90, "points": 300000, "odds": 3.1, "odds_percentage": 32.2, "percentage_users": 45.0},
                        {"title": "No", "color": "pink", "users": 110, "points": 630000, "odds": 1.47, "odds_percentage": 67.8, "percentage_users": 55.0},
                    ],
                    "total_users": 200,
                    "total_points": 930000,
                    "result": {"type": "WIN", "gained": 5250},
                },
            ]

        events = getattr(self.miner, "events_predictions", None) or {}
        result = []
        for event_id, event in list(events.items())[-50:]:
            bet = _safe(lambda: event.bet)
            decision = _safe(lambda: bet.decision, {}) or {}
            choice = decision.get("choice")
            chosen_title = None
            chosen_color = None
            if choice and bet:
                try:
                    outcome = bet.outcomes[0 if choice == "A" else 1]
                    chosen_title = outcome.get("title")
                    chosen_color = outcome.get("color")
                except Exception:
                    pass

            status = "ACTIVE"
            if _safe(lambda: event.result["type"]) is not None:
                status = "RESOLVED"
            elif _safe(lambda: event.bet_placed, False):
                status = "BET PLACED"
            elif _safe(lambda: event.bet_confirmed, False):
                status = "CONFIRMED"

            result.append(
                {
                    "streamer": _safe(lambda: event.streamer.username, ""),
                    "title": _safe(lambda: event.title, ""),
                    "status": status,
                    "closed_in": _safe(lambda: event.closing_bet_after(time.time())),
                    "decision": {
                        "choice": choice,
                        "amount": decision.get("amount", 0),
                        "title": chosen_title,
                        "color": chosen_color,
                    },
                    "outcomes": [
                        {
                            "title": _safe(lambda: o["title"]),
                            "color": _safe(lambda: o["color"]),
                            "users": _safe(lambda: o.get("total_users"), 0),
                            "points": _safe(lambda: o.get("total_points"), 0),
                            "odds": _safe(lambda: o.get("odds"), 0),
                            "odds_percentage": _safe(lambda: o.get("odds_percentage"), 0),
                            "percentage_users": _safe(lambda: o.get("percentage_users"), 0),
                        }
                        for o in (_safe(lambda: bet.outcomes, []) or [])
                    ],
                    "total_users": _safe(lambda: bet.total_users, 0),
                    "total_points": _safe(lambda: bet.total_points, 0),
                    "result": _safe(lambda: event.result),
                }
            )
        return result

    # ------------------------------------------------------------------ #
    def events(self):
        if self.demo:
            return self.demo_events
        # Live miner: the logger writes structured lines to the log file;
        # we tail the most recent ones for the feed.
        logs_file = getattr(self.miner, "logs_file", None)
        entries = []
        if logs_file and os.path.isfile(logs_file):
            try:
                with open(logs_file, "r", encoding="utf-8", errors="replace") as fh:
                    lines = fh.readlines()[-200:]
                for line in lines:
                    entries.append({"raw": line.rstrip()})
            except Exception:
                pass
            return entries[-50:]
        return entries


class DashboardServer(Thread):
    """Threaded dashboard for the miner.

    Usage inside your run script:

        twitch_miner.dashboard(host="0.0.0.0", port=8181)   # before .mine()
        twitch_miner.mine([...])

    Or standalone (demo data):

        python -m TwitchChannelPointsMiner.dashboard_demo --demo
    """

    def __init__(
        self,
        miner=None,
        host: str = "127.0.0.1",
        port: int = 8181,
        require_auth: bool = True,
        channels_file: str = None,
    ):
        super(DashboardServer, self).__init__()
        self.host = host
        self.port = port
        self.state = StateProvider(miner)
        self.provider = self.state  # alias
        self.channels_file = channels_file or os.path.join(
            os.getcwd(), ".dashboard_channels.json"
        )
        self.auth = TwitchAuth(host=host, port=port)
        self.sessions = SessionStore()
        # Auth is enforced only when a Twitch client id is configured;
        # otherwise the dashboard stays open (e.g. quick local demo).
        self.require_auth = require_auth and self.auth.enabled
        # Serializes streamers add/remove/settings so concurrent HTTP
        # requests can't interleave with each other.
        self.mutation_lock = Lock()
        self.daemon = True
        self.name = "Dashboard Thread"
        self._lock = Lock()
        self._html_cache = None

    def _load_channels_file(self):
        try:
            if os.path.isfile(self.channels_file):
                with open(self.channels_file, "r", encoding="utf-8") as fh:
                    return _json.load(fh)
        except (OSError, ValueError):
            pass
        return []

    def sync_channels_file(self):
        """Persist the tracked channel list to disk (best effort).

        Written after every mutation and once at startup."""
        usernames = [s["username"] for s in self.state.streamers()]
        payload = {
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "count": len(usernames),
            "channels": sorted(usernames),
        }
        try:
            with open(self.channels_file, "w", encoding="utf-8") as fh:
                _json.dump(payload, fh, indent=2)
        except OSError:
            logger.debug(f"Could not write {self.channels_file}")
        return self.channels_file

    def get_avatar_path(self, username):
        """Fetch (or reuse) the avatar for username; returns local path or None."""
        fetcher = getattr(self.state.miner.twitch, "get_profile_picture", None) if not self.state.demo else None
        if fetcher is None:
            return None
        try:
            return fetcher(username)
        except Exception:
            return None

    # --------------------------- API ---------------------------------- #
    def get_config(self):
        """Dashboard capabilities + tracked usernames (for the manage UI)."""
        if self.state.demo:
            return {
                "editable": True,
                "demo": True,
                "streamers": [s["username"] for s in self.state.streamers()],
                "options": SETTINGS_OPTIONS,
            }
        return {
            "editable": _safe(lambda: self.state.miner.running, False) is not None,
            "demo": False,
            "streamers": [
                s.username for s in (_safe(lambda: list(self.state.miner.streamers), []) or [])
            ],
            "options": SETTINGS_OPTIONS,
        }

    def add_streamer(self, username):
        """Validate + track a new streamer on the attached miner."""
        username = str(username or "").strip()
        if self.state.demo:
            if not username:
                return False, "empty username"
            streamers = self.state.demo_streamers
            if any(s["username"] == username.lower() for s in streamers):
                return False, f"'{username}' is already being tracked"
            streamers.append(
                {
                    "username": username.lower(),
                    "url": f"https://twitch.tv/{username.lower()}",
                    "online": False,
                    "channel_points": 0,
                    "points_gained": 0,
                    "viewers": 0,
                    "game": None,
                    "title": None,
                    "chat": False,
                    "watch_streak_missing": True,
                    "multipliers": 0,
                    "settings": {
                        "make_predictions": True,
                        "follow_raid": True,
                        "claim_drops": True,
                        "watch_streak": True,
                        "bet": {"strategy": "SMART", "percentage": 5, "max_points": 50000},
                    },
                    "history": {},
                }
            )
            return True, None
        with self.mutation_lock:
            method = getattr(self.state.miner, "add_streamer", None)
            if method is None:
                return False, "attached miner does not support runtime changes"
            _, error = method(username)
            if error is None:
                self.sync_channels_file()
            return error is None, error

    def update_streamer_settings(self, username, update):
        """Apply a settings update. Returns (ok, error)."""
        username = str(username or "").strip()
        if self.state.demo:
            target = next(
                (
                    s
                    for s in self.state.demo_streamers
                    if s["username"] == username.lower()
                ),
                None,
            )
            if target is None:
                return False, f"'{username}' is not being tracked"
            try:
                parsed = _parse_settings_payload(update)
            except ValueError as e:
                return False, str(e)
            bet_update = parsed.pop("bet", {})
            for field, value in bet_update.items():
                target["settings"]["bet"][field] = value
            for field, value in parsed.items():
                target["settings"][field] = value
            return True, None

        with self.mutation_lock:
            method = getattr(self.state.miner, "update_streamer_settings", None)
            if method is None:
                return False, "attached miner does not support runtime changes"
            try:
                method(username, update)
            except ValueError as e:
                return False, str(e)
            except Exception as e:
                return False, f"failed to apply: {e}"
            return True, None

    def refresh_online_status(self):
        """Force an online/offline re-check of every tracked channel.

        Uses check_streamer_online when available (full spade/stream
        update); falls back to load_channel_points_context otherwise.
        Returns (checked, online_count)."""
        miner = getattr(self.state, "miner", None)
        if miner is None:
            return 0, 0
        twitch = getattr(miner, "twitch", None)
        streamers = getattr(miner, "streamers", None) or []
        checked = 0
        online = 0
        for streamer in streamers:
            try:
                if hasattr(twitch, "check_streamer_online"):
                    # bypass the 60s offline cache so a refresh really refreshes
                    streamer.offline_at = 0
                    twitch.check_streamer_online(streamer)
                else:
                    twitch.load_channel_points_context(streamer)
                checked += 1
                if getattr(streamer, "is_online", False):
                    online += 1
            except Exception as e:
                logging.getLogger(__name__).warning(
                    f"refresh failed for {getattr(streamer, 'username', '?')}: {e}"
                )
        return checked, online

    def remove_streamer(self, username):
        """Remove a tracked streamer. Returns (ok, error)."""
        username = str(username or "").strip()
        if self.state.demo:
            before = len(self.state.demo_streamers)
            self.state.demo_streamers = [
                s for s in self.state.demo_streamers if s["username"] != username.lower()
            ]
            if len(self.state.demo_streamers) == before:
                return False, "streamer not tracked"
            return True, None
        with self.mutation_lock:
            method = getattr(self.state.miner, "remove_streamer", None)
            if method is None:
                return False, "attached miner does not support runtime changes"
            ok = bool(method(username))
            if ok:
                self.sync_channels_file()
            return ok, None if ok else "streamer not tracked"

    def _api_status(self):
        streamers = self.state.streamers()
        bets = self.state.bets()
        active = [b for b in bets if b["status"] in ("ACTIVE", "CONFIRMED", "BET PLACED")]
        return {
            "demo": self.state.demo,
            "running": self.state.demo or bool(_safe(lambda: self.state.miner.running, False)),
            "session_id": "demo"
            if self.state.demo
            else _safe(lambda: self.state.miner.session_id, None),
            "username": "demo"
            if self.state.demo
            else _safe(lambda: self.state.miner.username, None),
            "started_at": 0
            if self.state.demo
            else (_safe(lambda: self.state.miner.start_datetime.timestamp(), 0) or 0),
            "total_points": sum(s["channel_points"] for s in streamers),
            "online_count": sum(1 for s in streamers if s["online"]),
            "streamer_count": len(streamers),
            "active_bets": len(active),
            "server_time": time.time(),
        }

    # --------------------------- HTTP --------------------------------- #
    def _make_handler(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                logger.debug(f"{self.address_string()} {fmt % args}")

            def _send(self, status, content_type, body, extra_headers=None):
                if isinstance(body, str):
                    body = body.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                for name, value in extra_headers or []:
                    self.send_header(name, value)
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def _json(self, obj, status=200):
                self._send(status, "application/json", json.dumps(obj))

            def _html(self):
                if server._html_cache is None:
                    from TwitchChannelPointsMiner.dashboard_page import DASHBOARD_HTML
                    server._html_cache = DASHBOARD_HTML
                self._send(200, "text/html; charset=utf-8", server._html_cache)

            # -------------------- auth helpers ---------------------- #
            def _set_session_cookie(self, signed_value):
                self.send_response(302)
                self.send_header("Location", "/")
                self.send_header(
                    "Set-Cookie",
                    f"dashboard_session={signed_value}; Path=/; HttpOnly; "
                    f"SameSite=Lax; Max-Age={7 * 24 * 3600}",
                )
                self.send_header("Content-Length", "0")
                self.end_headers()

            def _page(self, inner_html, status=200):
                self._send(
                    status,
                    "text/html; charset=utf-8",
                    LOGIN_PAGE_TEMPLATE.format(body=inner_html),
                )

            def _route_auth(self, path, qs):
                auth, sessions = server.auth, server.sessions
                if not auth.enabled:
                    # No Twitch OAuth configured -> nothing to protect with.
                    return self._send(302, "text/html", "", extra_headers=[("Location", "/")])
                if path == "/auth/login":
                    if auth.use_device_flow:
                        return self._page("""<p>Sign in using Twitch's device flow:</p>
                          <ol><li>Open <b>twitch.tv/activate</b> (any device/browser)</li>
                          <li>Enter this code:</li></ol>
                          <p style="font-size:26px;letter-spacing:4px"><code id="uc">…</code></p>
                          <p id="st">Requesting code…</p>
                          <script>
                          const q = new URLSearchParams();
                          fetch('/auth/device/start').then(r => r.json()).then(d => {
                            if (d.error) { document.getElementById('st').textContent = 'Failed: ' + d.error; return; }
                            document.getElementById('uc').textContent = d.user_code;
                            document.getElementById('st').innerHTML =
                              'Waiting for approval at <a href="' + d.verification_uri + '" target="_blank" rel="noopener">' + d.verification_uri + '</a> …';
                            const poll = () => fetch('/auth/device/poll?state=' + encodeURIComponent(d.state))
                              .then(r => r.json()).then(p => {
                                if (p.status === 'ok') { location.href = '/'; }
                                else if (p.status === 'waiting') { setTimeout(poll, (d.interval || 2) * 1000); }
                                else { document.getElementById('st').textContent =
                                  p.status === 'denied' ? 'Sign-in denied (not whitelisted).' : 'Login expired - refresh.'; }
                              }).catch(() => setTimeout(poll, 3000));
                            poll();
                          });
                          </script>""")
                    return self._send(302, "text/html", "", extra_headers=[("Location", auth.authorize_url())])
                if path == "/auth/callback":
                    username = auth.exchange_code(
                        (qs.get("code") or [None])[0], (qs.get("state") or [None])[0]
                    )
                    if username:
                        return self._set_session_cookie(sessions.create(username))
                    return self._page('<p class="err">Sign-in failed or account not allowed.</p>', status=403)
                if path == "/auth/device/start":
                    result = auth.device_start()
                    if result is None:
                        return self._json({"error": "device flow unavailable"}, status=502)
                    return self._json(result)
                if path == "/auth/device/poll":
                    outcome = auth.device_poll((qs.get("state") or [""])[0])
                    if outcome.get("status") == "ok":
                        signed = sessions.create(outcome["username"])
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.send_header(
                            "Set-Cookie",
                            f"dashboard_session={signed}; Path=/; HttpOnly; "
                            f"SameSite=Lax; Max-Age={7 * 24 * 3600}",
                        )
                        self.send_header("Content-Length", str(len(b'{"status":"ok"}')))
                        self.end_headers()
                        return self.wfile.write(b'{"status":"ok"}')
                    return self._json(outcome)
                if path == "/auth/logout":
                    sessions.drop(auth.parse_session_cookie(self.headers.get("Cookie")))
                    self.send_response(302)
                    self.send_header("Location", "/auth/login")
                    self.send_header("Set-Cookie", "dashboard_session=; Path=/; Max-Age=0")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return None
                return self._json({"error": "not found"}, status=404)

            def do_GET(self):
                parsed = urlparse(self.path)
                path = parsed.path.rstrip("/") or "/"
                qs = parse_qs(parsed.query)
                if path.startswith("/auth/"):
                    return self._route_auth(path, qs)
                if server.require_auth:
                    username = server.sessions.resolve(
                        server.auth.parse_session_cookie(self.headers.get("Cookie"))
                    )
                    if username is None:
                        if path.startswith("/api/"):
                            return self._json({"error": "unauthorized"}, status=401)
                        return self._send(302, "text/html", "", extra_headers=[("Location", "/auth/login")])
                if path == "/":
                    return self._html()
                if path.startswith("/avatars/"):
                    name = os.path.basename(path[len("/avatars/"):])
                    local = server.get_avatar_path(name) if name else None
                    if local and os.path.isfile(local):
                        with open(local, "rb") as fh:
                            return self._send(200, "image/png", fh.read())
                    # 1x1 transparent PNG placeholder (UI shows initials)
                    return self._send(
                        200,
                        "image/png",
                        base64.b64decode(
                            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAABzenr0"
                            "AAAADUlEQVR4nGNgYGBgAAAABQABh6FO1AAAAABJRU5ErkJggg=="
                        ),
                    )
                if path == "/api/status":
                    return self._json(server._api_status())
                if path == "/api/streamers":
                    return self._json(server.state.streamers())
                if path == "/api/bets":
                    return self._json(server.state.bets())
                if path == "/api/events":
                    return self._json(server.state.events())
                if path == "/api/config":
                    return self._json(server.get_config())
                if path == "/api/all":
                    return self._json(
                        {
                            "status": server._api_status(),
                            "streamers": server.state.streamers(),
                            "bets": server.state.bets(),
                            "events": server.state.events(),
                            "config": server.get_config(),
                        }
                    )
                return self._json({"error": "not found"}, status=404)

            def do_POST(self):
                parsed = urlparse(self.path)
                path = parsed.path.rstrip("/") or "/"
                if server.require_auth:
                    username = server.sessions.resolve(
                        server.auth.parse_session_cookie(self.headers.get("Cookie"))
                    )
                    if username is None:
                        return self._json({"error": "unauthorized"}, status=401)

                length = int(self.headers.get("Content-Length") or 0)
                try:
                    payload = json.loads(self.rfile.read(length) or b"{}")
                    if not isinstance(payload, dict):
                        raise ValueError
                except ValueError:
                    return self._json({"error": "invalid JSON body"}, status=400)

                if path == "/api/streamers/add":
                    ok, error = server.add_streamer(str(payload.get("username", "")))
                    return self._json(
                        {"success": ok, "error": error}, status=200 if ok else 400
                    )
                if path == "/api/streamers/remove":
                    ok, error = server.remove_streamer(str(payload.get("username", "")))
                    return self._json(
                        {"success": ok, "error": error},
                        status=200 if ok else 404,
                    )
                if path == "/api/streamers/settings":
                    ok, error = server.update_streamer_settings(
                        str(payload.get("username", "")),
                        payload.get("settings") or {},
                    )
                    return self._json(
                        {"success": ok, "error": error},
                        status=200 if ok else 400,
                    )
                if path == "/api/streamers/refresh":
                    checked, online = server.refresh_online_status()
                    return self._json(
                        {
                            "success": True,
                            "checked": checked,
                            "online": online,
                        }
                    )
                return self._json({"error": "not found"}, status=404)

        return Handler

    # --------------------------- Thread ------------------------------- #
    def run(self):
        httpd = ThreadingHTTPServer((self.host, self.port), self._make_handler())
        self.httpd = httpd  # exposed for tests / graceful shutdown
        httpd.daemon_threads = True
        # Persist the initial tracked-channels list
        self.sync_channels_file()
        logger.info(
            f"Dashboard running on http://{self.host}:{self.port}/",
            extra={"emoji": ":desktop_computer:"},
        )
        try:
            httpd.serve_forever()
        except Exception:
            logger.exception("Dashboard server crashed")
        finally:
            httpd.server_close()
