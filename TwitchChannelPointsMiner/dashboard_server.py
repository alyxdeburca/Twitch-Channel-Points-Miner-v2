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
from urllib.parse import parse_qs, urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock, Thread

from TwitchChannelPointsMiner.dashboard_auth import (
    LOGIN_PAGE_TEMPLATE,
    SessionStore,
    TwitchAuth,
)

logger = logging.getLogger(__name__)

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


class StateProvider(object):
    """Bridge between the running TwitchChannelPointsMiner instance and
    the dashboard. Also supports demo mode (no miner attached)."""

    def __init__(self, miner=None):
        self.miner = miner
        self.demo = miner is None
        self.demo_events = [
            {"time": time.time() - 60 * 8, "type": "BONUS_CLAIM", "streamer": "demo_streamer", "text": "Bonus claimed +50"},
            {"time": time.time() - 60 * 5, "type": "STREAMER_ONLINE", "streamer": "demo_streamer", "text": "demo_streamer is Online!"},
            {"time": time.time() - 60 * 2, "type": "BET_START", "streamer": "demo_streamer", "text": "Will it rain tomorrow?"},
        ]

    # ------------------------------------------------------------------ #
    def streamers(self):
        if self.demo:
            return [
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
                        "bet": {"strategy": "SMART", "percentage": 5, "max_points": 50000},
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
                        "bet": {"strategy": "PERCENTAGE", "percentage": 5, "max_points": 1234},
                    },
                    "history": {
                        "WATCH": {"counter": 96, "amount": 4800},
                        "CLAIM": {"counter": 18, "amount": 1800},
                    },
                },
            ]

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
            settings = {
                "make_predictions": _safe(lambda: settings_obj.make_predictions),
                "follow_raid": _safe(lambda: settings_obj.follow_raid),
                "claim_drops": _safe(lambda: settings_obj.claim_drops),
                "watch_streak": _safe(lambda: settings_obj.watch_streak),
                "bet": {
                    "strategy": _safe(lambda: str(bet_obj.strategy)),
                    "percentage": _safe(lambda: bet_obj.percentage),
                    "max_points": _safe(lambda: bet_obj.max_points),
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
    """Threaded, read-only dashboard for the miner.

    Usage inside your run script:

        twitch_miner.dashboard(host="0.0.0.0", port=8181)   # before .mine()
        twitch_miner.mine([...])

    Or standalone (demo data):

        python -m TwitchChannelPointsMiner.dashboard_server --demo
    """

    def __init__(
        self,
        miner=None,
        host: str = "127.0.0.1",
        port: int = 8181,
        require_auth: bool = True,
    ):
        super(DashboardServer, self).__init__()
        self.host = host
        self.port = port
        self.state = StateProvider(miner)
        self.provider = self.state  # alias
        self.auth = TwitchAuth(host=host, port=port)
        self.sessions = SessionStore()
        # Auth is enforced only when a Twitch client id is configured;
        # otherwise the dashboard stays open (e.g. quick local demo).
        self.require_auth = require_auth and self.auth.enabled
        self.daemon = True
        self.name = "Dashboard Thread"
        self._lock = Lock()
        self._html_cache = None

    # --------------------------- API ---------------------------------- #
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
                if path == "/api/status":
                    return self._json(server._api_status())
                if path == "/api/streamers":
                    return self._json(server.state.streamers())
                if path == "/api/bets":
                    return self._json(server.state.bets())
                if path == "/api/events":
                    return self._json(server.state.events())
                if path == "/api/all":
                    return self._json(
                        {
                            "status": server._api_status(),
                            "streamers": server.state.streamers(),
                            "bets": server.state.bets(),
                            "events": server.state.events(),
                        }
                    )
                return self._json({"error": "not found"}, status=404)

        return Handler

    # --------------------------- Thread ------------------------------- #
    def run(self):
        httpd = ThreadingHTTPServer((self.host, self.port), self._make_handler())
        httpd.daemon_threads = True
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
