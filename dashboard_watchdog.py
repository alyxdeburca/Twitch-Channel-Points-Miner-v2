# -*- coding: utf-8 -*-
"""Dashboard watchdog: alerts if the miner dashboard shows no activity.

Runs from cron every few minutes. Tracks a 'change signature' composed of
real activity signals (total points, online count, streamer count, active
bets, miner session id, log-file modification time).

If the signature is unchanged for >= STALE_MINUTES (default 30), or the
API is unreachable for that long, sends an iMessage alert via Sendblue.
After an alert it enters a 60-minute re-alert cooldown (per condition).
"""
import json
import os
import sys
import time
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, ".dashboard_watchdog.json")
LOG_FILE = os.path.join(BASE_DIR, "logs", "ggalyx.log")
STATUS_URL = os.environ.get("MINER_STATUS_URL", "http://127.0.0.1:8181/api/status")
STALE_MINUTES = float(os.environ.get("WATCHDOG_STALE_MINUTES", "30"))
REALERT_MINUTES = float(os.environ.get("WATCHDOG_REALERT_MINUTES", "60"))


def log(msg):
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}", flush=True)


def load_env_file(path):
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    os.environ.setdefault(key.strip(), val.strip())
    except OSError:
        pass


def fetch_status():
    try:
        with urllib.request.urlopen(STATUS_URL, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return data
    except Exception as e:
        return {"__down": str(e)[:120]}


def build_signature(status):
    if "__down" in status:
        return "API-DOWN"
    return "|".join(
        str(
            (
                status.get("total_points"),
                status.get("online_count"),
                status.get("streamer_count"),
                status.get("active_bets"),
                status.get("session_id"),
            )
        )
    )


def log_mtime():
    try:
        return int(os.path.getmtime(LOG_FILE))
    except OSError:
        return 0


def send_imessage(text):
    api_key = os.environ.get("SENDBLUE_API_KEY")
    api_secret = os.environ.get("SENDBLUE_API_SECRET")
    to_number = os.environ.get("MINER_IMESSAGE_TO") or os.environ.get(
        "SENDBLUE_HOME_CHANNEL"
    )
    from_number = os.environ.get("SENDBLUE_PHONE_NUMBER")
    if not (api_key and api_secret and to_number):
        log("alert skipped: missing Sendblue credentials/number")
        return False
    body = {"number": to_number, "content": text}
    if from_number:
        body["from_number"] = from_number
    import requests

    try:
        r = requests.post(
            "https://api.sendblue.com/api/send-message",
            headers={
                "sb-api-key-id": api_key,
                "sb-api-secret-key": api_secret,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json=body,
            timeout=30,
        )
        ok = r.status_code in (200, 201, 202)
        log(f"alert queued={ok} (HTTP {r.status_code})")
        return ok
    except requests.RequestException as e:
        log(f"Sendblue request failed: {e}")
        return False


def main():
    load_env_file("/home/ubuntu/.hermes/.env")

    now = time.time()
    status = fetch_status()
    sig = build_signature(status)
    mtime = log_mtime()

    state = {"signature": None, "first_seen": now, "last_alert": 0, "down": False}
    try:
        with open(STATE_FILE) as fh:
            state.update(json.load(fh))
    except (OSError, ValueError):
        pass

    changed = sig != state.get("signature")
    if changed:
        # Activity! Reset the tracker.
        state["signature"] = sig
        state["first_seen"] = now
        state["down"] = sig == "API-DOWN"
        state.pop("alerted_condition", None)
        log(f"state change -> {sig[:80]} (mtime={mtime})")
    else:
        stale_for_min = (now - state.get("first_seen", now)) / 60
        down = sig == "API-DOWN"
        condition = "API DOWN" if down else "NO CHANGE"
        log(
            f"unchanged ({condition}) for {stale_for_min:.0f} min "
            f"(sig={sig[:60]})"
        )
        if stale_for_min >= STALE_MINUTES:
            since_last_alert_min = (now - state.get("last_alert", 0)) / 60
            if (
                state.get("alerted_condition") != condition
                or since_last_alert_min >= REALERT_MINUTES
            ):
                pid_line = ""
                extra = ""
                if not down:
                    last_log = time.strftime(
                        "%H:%M", time.localtime(mtime)
                    ) if mtime else "never"
                    extra = f" Last log line: {last_log}."
                msg = (
                    f"⚠️ Miner watchdog: {condition} for {int(stale_for_min)} min. "
                    f"Dashboard: https://miner.alyx.site{extra} "
                    f"(total_points={status.get('total_points', '?')})"
                )
                if send_imessage(msg):
                    state["last_alert"] = now
                    state["alerted_condition"] = condition
            else:
                log("still stale - re-alert cooldown active")
        # unchanged-but-not-stale: keep waiting silently

    state["checked_at"] = now
    with open(STATE_FILE, "w") as fh:
        json.dump(state, fh, indent=2)


if __name__ == "__main__":
    main()
