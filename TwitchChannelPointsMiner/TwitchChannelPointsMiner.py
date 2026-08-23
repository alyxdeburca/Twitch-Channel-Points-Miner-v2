# -*- coding: utf-8 -*-

import logging
import os
import random
import signal
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from TwitchChannelPointsMiner.classes.AnalyticsServer import AnalyticsServer
from TwitchChannelPointsMiner.classes.Chat import ChatPresence, ThreadChat
from TwitchChannelPointsMiner.dashboard_server import DashboardServer
from TwitchChannelPointsMiner.classes.entities.PubsubTopic import PubsubTopic
from TwitchChannelPointsMiner.classes.entities.Streamer import (
    Streamer,
    StreamerSettings,
)
from TwitchChannelPointsMiner.classes.Exceptions import StreamerDoesNotExistException
from TwitchChannelPointsMiner.classes.Settings import FollowersOrder, Priority, Settings
from TwitchChannelPointsMiner.classes.entities.Bet import (
    Condition,
    DelayMode,
    FilterCondition,
    OUTCOME_KEYS_BY_NAME,
    Strategy,
)
from TwitchChannelPointsMiner.classes.Twitch import Twitch
from TwitchChannelPointsMiner.classes.WebSocketsPool import WebSocketsPool
from TwitchChannelPointsMiner.logger import LoggerSettings, configure_loggers
from TwitchChannelPointsMiner.utils import (
    _millify,
    at_least_one_value_in_settings_is,
    check_versions,
    get_user_agent,
    internet_connection_available,
    set_default_settings,
)

logger = logging.getLogger(__name__)

# Suppress:
#   - chardet.charsetprober - [feed]
#   - chardet.charsetprober - [get_confidence]
#   - requests - [Starting new HTTPS connection (1)]
#   - Flask (werkzeug) logs
#   - irc.client - [process_data]
#   - irc.client - [_dispatcher]
#   - irc.client - [_handle_message]
logging.getLogger("chardet.charsetprober").setLevel(logging.ERROR)
logging.getLogger("requests").setLevel(logging.ERROR)
logging.getLogger("werkzeug").setLevel(logging.ERROR)
logging.getLogger("irc.client").setLevel(logging.ERROR)


class TwitchChannelPointsMiner:
    __slots__ = [
        "username",
        "twitch",
        "claim_drops_startup",
        "priority",
        "streamers",
        "events_predictions",
        "minute_watcher_thread",
        "sync_campaigns_thread",
        "ws_pool",
        "dashboard_server",
        "session_id",
        "running",
        "start_datetime",
        "original_streamers",
        "logs_file",
        "queue_listener",
    ]

    def __init__(
        self,
        username: str,
        claim_drops_startup: bool = False,
        # Settings for logging and selenium as you can see.
        priority: list = [Priority.STREAK, Priority.DROPS, Priority.ORDER],
        # This settings will be global shared trought Settings class
        logger_settings: LoggerSettings = LoggerSettings(),
        # Default values for all streamers
        streamer_settings: StreamerSettings = StreamerSettings(),
    ):
        Settings.analytics_path = os.path.join(Path().absolute(), "analytics", username)
        Path(Settings.analytics_path).mkdir(parents=True, exist_ok=True)

        self.username = username

        # Set as global config
        Settings.logger = logger_settings

        # Init as default all the missing values
        streamer_settings.default()
        streamer_settings.bet.default()
        Settings.streamer_settings = streamer_settings

        user_agent = get_user_agent("FIREFOX")
        self.twitch = Twitch(self.username, user_agent)

        self.claim_drops_startup = claim_drops_startup
        self.priority = priority if isinstance(priority, list) else [priority]

        self.streamers = []
        self.events_predictions = {}
        self.minute_watcher_thread = None
        self.sync_campaigns_thread = None
        self.ws_pool = None
        self.dashboard_server = None

        self.session_id = str(uuid.uuid4())
        self.running = False
        self.start_datetime = None
        self.original_streamers = []

        self.logs_file, self.queue_listener = configure_loggers(
            self.username, logger_settings
        )

        # Check for the latest version of the script
        current_version, github_version = check_versions()
        if github_version == "0.0.0":
            logger.error(
                "Unable to detect if you have the latest version of this script"
            )
        elif current_version != github_version:
            logger.info(f"You are running the version {current_version} of this script")
            logger.info(f"The latest version on GitHub is: {github_version}")

        for sign in [signal.SIGINT, signal.SIGSEGV, signal.SIGTERM]:
            signal.signal(sign, self.end)

    def analytics(
        self,
        host: str = "127.0.0.1",
        port: int = 5000,
        refresh: int = 5,
        days_ago: int = 7,
    ):
        http_server = AnalyticsServer(
            host=host, port=port, refresh=refresh, days_ago=days_ago
        )
        http_server.daemon = True
        http_server.name = "Analytics Thread"
        http_server.start()

    def dashboard(self, host: str = "127.0.0.1", port: int = 8181):
        """Start the live web dashboard (read-only) for this miner."""
        self.dashboard_server = DashboardServer(miner=self, host=host, port=port)
        self.dashboard_server.start()

    def add_streamer(self, username: str):
        """Track a new streamer at runtime (also used by the web dashboard).

        Returns (streamer, None) on success or (None, reason) on failure.
        """
        username = str(username).lower().strip()
        if not username:
            return None, "empty username"
        if any(s.username == username for s in self.streamers):
            return None, f"'{username}' is already being tracked"

        streamer = Streamer(username)
        try:
            streamer.channel_id = self.twitch.get_channel_id(username)
        except StreamerDoesNotExistException:
            return None, f"Twitch user '{username}' does not exist"

        streamer.settings = set_default_settings(
            streamer.settings, Settings.streamer_settings
        )
        streamer.settings.bet = set_default_settings(
            streamer.settings.bet, Settings.streamer_settings.bet
        )
        if streamer.settings.chat != ChatPresence.NEVER:
            streamer.irc_chat = ThreadChat(
                self.username,
                self.twitch.twitch_login.get_auth_token(),
                streamer.username,
            )

        self.twitch.load_channel_points_context(streamer)
        self.twitch.check_streamer_online(streamer)

        self.streamers.append(streamer)
        # Keep original_streamers index-aligned for the session-gain report.
        self.original_streamers.append(streamer.channel_points)

        if self.ws_pool is not None:
            self.ws_pool.submit(PubsubTopic("video-playback-by-id", streamer=streamer))
            if streamer.settings.follow_raid is True:
                self.ws_pool.submit(PubsubTopic("raid", streamer=streamer))
            if streamer.settings.make_predictions is True:
                self.ws_pool.submit(
                    PubsubTopic("predictions-channel-v1", streamer=streamer)
                )
        logger.info(
            f"Now tracking {username} ({len(self.streamers)} streamers)",
            extra={"emoji": ":heavy_plus_sign:"},
        )
        return streamer, None

    def remove_streamer(self, username: str) -> bool:
        """Stop tracking a streamer at runtime (also used by the web dashboard)."""
        username = str(username).lower().strip()
        for index, streamer in enumerate(self.streamers):
            if streamer.username == username:
                try:
                    if streamer.irc_chat is not None:
                        streamer.leave_chat()
                except Exception:
                    pass
                self.streamers.pop(index)
                if index < len(self.original_streamers):
                    self.original_streamers.pop(index)
                logger.info(
                    f"Stopped tracking {username} ({len(self.streamers)} streamers)",
                    extra={"emoji": ":heavy_minus_sign:"},
                )
                return True
        return False

    @staticmethod
    def _parse_streamer_settings(update: dict) -> dict:
        """Validate a settings payload from the dashboard into typed values.

        Raises ValueError with a user-readable message on any bad input.
        Returns {field: value} ready to apply onto StreamerSettings/bet.
        """
        from TwitchChannelPointsMiner.classes.Chat import ChatPresence

        if not isinstance(update, dict):
            raise ValueError("settings payload must be an object")
        parsed = {}

        for flag in ("make_predictions", "follow_raid", "claim_drops", "watch_streak"):
            if flag in update and update[flag] is not None:
                parsed[flag] = bool(update[flag])

        if "chat" in update and update["chat"] is not None:
            chat = str(update["chat"]).upper()
            try:
                parsed["chat"] = ChatPresence[chat]
            except KeyError:
                raise ValueError(f"chat must be one of ALWAYS, NEVER, ONLINE, OFFLINE")

        bet_update = update.get("bet") or {}
        if not isinstance(bet_update, dict):
            raise ValueError("bet must be an object")
        bet = {}

        if "strategy" in bet_update and bet_update["strategy"] is not None:
            strategy = str(bet_update["strategy"]).upper()
            try:
                bet["strategy"] = Strategy[strategy]
            except KeyError:
                raise ValueError(
                    "bet.strategy must be one of MOST_VOTED, HIGH_ODDS, PERCENTAGE, SMART_MONEY, SMART"
                )

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
            try:
                bet["delay_mode"] = DelayMode[mode]
            except KeyError:
                raise ValueError("bet.delay_mode must be one of FROM_START, FROM_END, PERCENTAGE")

        if "filter_condition" in bet_update:
            fc = bet_update["filter_condition"]
            if fc is None or (isinstance(fc, dict) and str(fc.get("by", "")).upper() == "NONE"):
                bet["filter_condition"] = None
            elif isinstance(fc, dict):
                by = str(fc.get("by", "")).upper()
                where = str(fc.get("where", "")).upper()
                try:
                    by_key = OUTCOME_KEYS_BY_NAME[by]
                except KeyError:
                    raise ValueError(
                        "filter_condition.by must be one of PERCENTAGE_USERS, ODDS_PERCENTAGE, ODDS, TOP_POINTS, TOTAL_USERS, TOTAL_POINTS"
                    )
                try:
                    where_cond = Condition[where]
                except KeyError:
                    raise ValueError("filter_condition.where must be one of GT, LT, GTE, LTE")
                try:
                    value = float(fc.get("value"))
                except (TypeError, ValueError):
                    raise ValueError("filter_condition.value must be a number")
                bet["filter_condition"] = FilterCondition(
                    by=by_key, where=where_cond, value=value
                )
            else:
                raise ValueError("filter_condition must be null or an object")

        parsed["bet"] = bet
        return parsed

    def update_streamer_settings(self, username: str, update: dict):
        """Change settings for one tracked streamer at runtime.

        Handles side effects: IRC chat start/stop when `chat` changes,
        prediction topic subscribe/unsubscribe when make_predictions flips.
        Returns the updated Streamer or raises ValueError.
        """
        username = str(username).lower().strip()
        target = next((s for s in self.streamers if s.username == username), None)
        if target is None:
            raise ValueError(f"'{username}' is not being tracked")

        parsed = self._parse_streamer_settings(update)

        old_chat = target.settings.chat
        old_make_predictions = target.settings.make_predictions

        for field, value in parsed.items():
            if field == "bet":
                for bet_field, bet_value in value.items():
                    setattr(target.settings.bet, bet_field, bet_value)
            else:
                setattr(target.settings, field, value)

        # Chat thread reconciliation
        if "chat" in parsed:
            new_chat = parsed["chat"]
            try:
                if new_chat == ChatPresence.NEVER and target.irc_chat is not None:
                    target.leave_chat()
                    target.irc_chat = None
                elif new_chat != ChatPresence.NEVER and target.irc_chat is None:
                    target.irc_chat = ThreadChat(
                        self.username,
                        self.twitch.twitch_login.get_auth_token(),
                        target.username,
                    )
            except Exception as e:
                logger.warning(f"Issue reconciling chat for {username}: {e}")

        # Prediction topic reconciliation
        if self.ws_pool is not None and "make_predictions" in parsed:
            new_flag = parsed["make_predictions"]
            if new_flag != old_make_predictions:
                topic_type = "predictions-channel-v1"
                try:
                    if new_flag is True:
                        self.ws_pool.submit(PubsubTopic(topic_type, streamer=target))
                    else:
                        for ws in self.ws_pool.ws:
                            ws.topics = [
                                t
                                for t in ws.topics
                                if not (
                                    t.type == topic_type
                                    and getattr(t, "streamer", None) is target
                                )
                            ]
                except Exception as e:
                    logger.warning(f"Issue updating prediction topics for {username}: {e}")

        logger.info(
            f"Settings updated for {username}",
            extra={"emoji": ":wrench:"},
        )
        return target

    def mine(
        self,
        streamers: list = [],
        blacklist: list = [],
        followers: bool = False,
        followers_order: FollowersOrder = FollowersOrder.ASC,
    ):
        self.run(streamers=streamers, blacklist=blacklist, followers=followers)

    def run(
        self,
        streamers: list = [],
        blacklist: list = [],
        followers: bool = False,
        followers_order: FollowersOrder = FollowersOrder.ASC,
    ):
        if self.running:
            logger.error("You can't start multiple sessions of this instance!")
        else:
            logger.info(
                f"Start session: '{self.session_id}'", extra={"emoji": ":bomb:"}
            )
            self.running = True
            self.start_datetime = datetime.now()

            authenticated_username = self.twitch.login()
            if authenticated_username:
                # The token is authoritative: fix any placeholder/stale
                # username from the run script so the dashboard, chat
                # threads and future logins all use the real account.
                self.username = authenticated_username

            if self.claim_drops_startup is True:
                self.twitch.claim_all_drops_from_inventory()

            streamers_name: list = []
            streamers_dict: dict = {}

            for streamer in streamers:
                username = (
                    streamer.username
                    if isinstance(streamer, Streamer)
                    else streamer.lower().strip()
                )
                if username not in blacklist:
                    streamers_name.append(username)
                    streamers_dict[username] = streamer

            if followers is True:
                followers_array = self.twitch.get_followers(order=followers_order)
                logger.info(
                    f"Load {len(followers_array)} followers from your profile!",
                    extra={"emoji": ":clipboard:"},
                )
                for username in followers_array:
                    if username not in streamers_dict and username not in blacklist:
                        streamers_name.append(username)
                        streamers_dict[username] = username.lower().strip()

            logger.info(
                f"Loading data for {len(streamers_name)} streamers. Please wait...",
                extra={"emoji": ":nerd_face:"},
            )
            for username in streamers_name:
                if username in streamers_name:
                    time.sleep(random.uniform(0.3, 0.7))
                    try:
                        streamer = (
                            streamers_dict[username]
                            if isinstance(streamers_dict[username], Streamer) is True
                            else Streamer(username)
                        )
                        streamer.channel_id = self.twitch.get_channel_id(username)
                        streamer.settings = set_default_settings(
                            streamer.settings, Settings.streamer_settings
                        )
                        streamer.settings.bet = set_default_settings(
                            streamer.settings.bet, Settings.streamer_settings.bet
                        )
                        if streamer.settings.chat != ChatPresence.NEVER:
                            streamer.irc_chat = ThreadChat(
                                self.username,
                                self.twitch.twitch_login.get_auth_token(),
                                streamer.username,
                            )
                        self.streamers.append(streamer)
                    except StreamerDoesNotExistException:
                        logger.info(
                            f"Streamer {username} does not exist",
                            extra={"emoji": ":cry:"},
                        )

            # Populate the streamers with default values.
            # 1. Load channel points and auto-claim bonus
            # 2. Check if streamers are online
            # 3. DEACTIVATED: Check if the user is a moderator. (was used before the 5th of April 2021 to deactivate predictions)
            for streamer in self.streamers:
                time.sleep(random.uniform(0.3, 0.7))
                self.twitch.load_channel_points_context(streamer)
                self.twitch.check_streamer_online(streamer)
                # self.twitch.viewer_is_mod(streamer)

            self.original_streamers = [
                streamer.channel_points for streamer in self.streamers
            ]

            # If we have at least one streamer with settings = make_predictions True
            make_predictions = at_least_one_value_in_settings_is(
                self.streamers, "make_predictions", True
            )

            # If we have at least one streamer with settings = claim_drops True
            # Spawn a thread for sync inventory and dashboard
            if (
                at_least_one_value_in_settings_is(self.streamers, "claim_drops", True)
                is True
            ):
                self.sync_campaigns_thread = threading.Thread(
                    target=self.twitch.sync_campaigns,
                    args=(self.streamers,),
                )
                self.sync_campaigns_thread.name = "Sync campaigns/inventory"
                self.sync_campaigns_thread.start()
                time.sleep(30)

            self.minute_watcher_thread = threading.Thread(
                target=self.twitch.send_minute_watched_events,
                args=(self.streamers, self.priority),
            )
            self.minute_watcher_thread.name = "Minute watcher"
            self.minute_watcher_thread.start()

            self.ws_pool = WebSocketsPool(
                twitch=self.twitch,
                streamers=self.streamers,
                events_predictions=self.events_predictions,
            )

            # Subscribe to community-points-user. Get update for points spent or gains
            user_id = self.twitch.twitch_login.get_user_id()
            self.ws_pool.submit(
                PubsubTopic(
                    "community-points-user-v1",
                    user_id=user_id,
                )
            )

            # Going to subscribe to predictions-user-v1. Get update when we place a new prediction (confirm)
            if make_predictions is True:
                self.ws_pool.submit(
                    PubsubTopic(
                        "predictions-user-v1",
                        user_id=user_id,
                    )
                )

            for streamer in self.streamers:
                self.ws_pool.submit(
                    PubsubTopic("video-playback-by-id", streamer=streamer)
                )

                if streamer.settings.follow_raid is True:
                    self.ws_pool.submit(PubsubTopic("raid", streamer=streamer))

                if streamer.settings.make_predictions is True:
                    self.ws_pool.submit(
                        PubsubTopic("predictions-channel-v1", streamer=streamer)
                    )

            refresh_context = time.time()
            while self.running:
                time.sleep(random.uniform(20, 60))
                # Do an external control for WebSocket. Check if the thread is running
                # Check if is not None because maybe we have already created a new connection on array+1 and now index is None
                for index in range(0, len(self.ws_pool.ws)):
                    if (
                        self.ws_pool.ws[index].is_reconneting is False
                        and self.ws_pool.ws[index].elapsed_last_ping() > 10
                        and internet_connection_available() is True
                    ):
                        logger.info(
                            f"#{index} - The last PING was sent more than 10 minutes ago. Reconnecting to the WebSocket..."
                        )
                        WebSocketsPool.handle_reconnection(self.ws_pool.ws[index])

                if ((time.time() - refresh_context) // 60) >= 30:
                    refresh_context = time.time()
                    for index in range(0, len(self.streamers)):
                        if self.streamers[index].is_online:
                            self.twitch.load_channel_points_context(
                                self.streamers[index]
                            )

    def end(self, signum, frame):
        logger.info("CTRL+C Detected! Please wait just a moment!")

        for streamer in self.streamers:
            if (
                streamer.irc_chat is not None
                and streamer.settings.chat != ChatPresence.NEVER
            ):
                streamer.leave_chat()
                if streamer.irc_chat.is_alive() is True:
                    streamer.irc_chat.join()

        self.running = self.twitch.running = False
        if self.ws_pool is not None:
            self.ws_pool.end()

        if self.minute_watcher_thread is not None:
            self.minute_watcher_thread.join()

        if self.sync_campaigns_thread is not None:
            self.sync_campaigns_thread.join()

        # Check if all the mutex are unlocked.
        # Prevent breaks of .json file
        for streamer in self.streamers:
            if streamer.mutex.locked():
                streamer.mutex.acquire()
                streamer.mutex.release()

        self.__print_report()

        # Stop the queue listener to make sure all messages have been logged
        self.queue_listener.stop()

        sys.exit(0)

    def __print_report(self):
        print("\n")
        logger.info(
            f"Ending session: '{self.session_id}'", extra={"emoji": ":stop_sign:"}
        )
        if self.logs_file is not None:
            logger.info(
                f"Logs file: {self.logs_file}", extra={"emoji": ":page_facing_up:"}
            )
        logger.info(
            f"Duration {datetime.now() - self.start_datetime}",
            extra={"emoji": ":hourglass:"},
        )

        if self.events_predictions != {}:
            print("")
            for event_id in self.events_predictions:
                event = self.events_predictions[event_id]
                if (
                    event.bet_confirmed is True
                    and event.streamer.settings.make_predictions is True
                ):
                    logger.info(
                        f"{event.streamer.settings.bet}",
                        extra={"emoji": ":wrench:"},
                    )
                    if event.streamer.settings.bet.filter_condition is not None:
                        logger.info(
                            f"{event.streamer.settings.bet.filter_condition}",
                            extra={"emoji": ":pushpin:"},
                        )
                    logger.info(
                        f"{event.print_recap()}",
                        extra={"emoji": ":bar_chart:"},
                    )

        print("")
        for streamer_index in range(0, len(self.streamers)):
            if self.streamers[streamer_index].history != {}:
                gained = (
                    self.streamers[streamer_index].channel_points
                    - self.original_streamers[streamer_index]
                )
                logger.info(
                    f"{repr(self.streamers[streamer_index])}, Total Points Gained (after farming - before farming): {_millify(gained)}",
                    extra={"emoji": ":robot:"},
                )
                if self.streamers[streamer_index].history != {}:
                    logger.info(
                        f"{self.streamers[streamer_index].print_history()}",
                        extra={"emoji": ":moneybag:"},
                    )
