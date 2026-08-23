# Web Dashboard

A self-contained, read-only web UI for the miner: live channel points,
streamer status, active predictions/bets with outcome bars and countdowns,
and an event feed. Zero extra dependencies (Python stdlib only).

![demo](https://img.shields.io/badge/mode-demo%20available-orange)

## Quick start

### Demo mode (no Twitch account needed)

```bash
python -m TwitchChannelPointsMiner.dashboard_demo --demo --port 8181
```

Open http://127.0.0.1:8181 — you'll see fake data marked `DEMO DATA`.

### Attach it to your miner

```python
twitch_miner = TwitchChannelPointsMiner(username="your-twitch-username")

twitch_miner.dashboard(host="0.0.0.0", port=8181)   # start the web UI
twitch_miner.mine([ ... ])                          # then mine as usual
```

The dashboard reads live state directly from the miner object — no files,
no scraping.

## Sign in with Twitch (recommended)

By default the dashboard is open **only** while no Twitch OAuth app is
configured (`TWITCH_CLIENT_ID` unset) — e.g. quick local testing. As soon as
you provide a client ID, every page/API requires signing in with Twitch and
membership in the username allowlist.

1. Create an application at https://dev.twitch.tv/console/apps
   - OAuth redirect URLs:
     - Authorization-code flow: `http://localhost:8181/auth/callback`
       (or your public hostname/IP)
   - Category: whatever, e.g. "Other". Copy the **Client ID** and generate a
     **Client Secret**.
2. Export environment variables:

```bash
export TWITCH_CLIENT_ID="your-client-id"
export TWITCH_CLIENT_SECRET="your-client-secret"      # enables code flow
export TWITCH_REDIRECT_URI="http://localhost:8181/auth/callback"
export DASHBOARD_ALLOWED_USERS="your-twitch-username" # comma separated allowlist
```

3. Run your script — visiting the dashboard now redirects to Twitch login.

If you set only `TWITCH_CLIENT_ID` (no secret), the dashboard automatically
uses Twitch's **device flow**: you get a code to enter at
https://www.twitch.tv/activate — handy when the dashboard is behind SSH
tunnels or Tailscale where a public redirect URI is awkward.

Notes:

- Allowlist defaults to the miner's own username if
  `DASHBOARD_ALLOWED_USERS` is unset.
- Sessions are random IDs stored server-side; browsers only receive an
  HMAC-signed cookie. The signing secret is auto-generated to
  `.dashboard_session_secret` (gitignored).
- Logout: `/auth/logout`.

## Managing streamers from the dashboard

Cards show each channel's Twitch profile picture (fetched once via GQL
and cached under `.dashboard/avatars/`, with an initial-letter fallback).

The list of tracked channels is persisted to `.dashboard_channels.json`
in the working directory (updated on startup and after every add/remove).
Both are gitignored.

The Streamers panel has an **"＋ Add streamer"** button and a ✕ button on
each card. Adding a streamer at runtime validates the channel on Twitch,
loads its points context, joins its chat (per settings) and subscribes to
its WebSocket topics immediately - no restart needed. Removing stops
tracking it right away; points already earned stay in your account.

Note: the username shown in the dashboard header comes from the
authenticated Twitch token, not the `username=` in your run script - a
placeholder is corrected automatically on login (and the cookies file is
renamed accordingly).

The **⚙ button** on each card opens a full settings editor applied live:

- Mining: make predictions, follow raids, claim drops, watch streak,
  chat presence (ALWAYS / NEVER / ONLINE / OFFLINE - the IRC client is
  started/stopped accordingly)
- Betting: strategy (MOST_VOTED, HIGH_ODDS, PERCENTAGE, SMART_MONEY,
  SMART), bet % of points, SMART gap, max/minimum points, stealth mode,
  delay + delay mode
- Filter condition: by / where / value, or disabled entirely

All values are validated server-side with sensible ranges and clear error
messages; changes take effect on the next prediction for that channel.
These mutations call `twitch_miner.add_streamer(name)`,
`remove_streamer(name)` and `update_streamer_settings(name, settings)`,
which you can also use programmatically. The demo server supports them
too (in-memory only). Settings are per streamer and not persisted to your
run.py - restart resets to whatever the file defines.

## HTTP API

| Route | Description |
|---|---|
| `/api/status` | totals: points, online count, active bets, session info |
| `/api/streamers` | per-streamer state incl. history and settings |
| `/api/bets` | prediction events with outcomes/decisions/results |
| `/api/events` | recent log lines from the miner's log file |
| `/api/config` | capabilities + tracked usernames (`editable`, `demo`, `streamers`) |
| `/api/all` | everything above in one payload |
| `POST /api/streamers/add` | body `{"username": "name"}` — track a new streamer |
| `POST /api/streamers/remove` | body `{"username": "name"}` — stop tracking |
| `POST /api/streamers/settings` | body `{"username": "name", "settings": {...}}` — change settings live |

All require an authenticated session when OAuth is configured.

## Files

- `TwitchChannelPointsMiner/dashboard_server.py` — threaded stdlib HTTP server, API + auth wiring
- `TwitchChannelPointsMiner/dashboard_auth.py` — Twitch OAuth (code + device flow), sessions, allowlist
- `TwitchChannelPointsMiner/dashboard_page.py` — embedded single-file HTML/CSS/JS page
- `TwitchChannelPointsMiner/dashboard_demo.py` — standalone runner (`--demo`)
- `tests/test_dashboard_auth.py` — end-to-end auth tests (mocked Twitch endpoints)

Run tests:

```bash
python -m unittest tests.test_dashboard_auth -v
```

The legacy analytics chart server (`twitch_miner.analytics(...)`) is
unchanged and can run alongside the dashboard on a different port.
