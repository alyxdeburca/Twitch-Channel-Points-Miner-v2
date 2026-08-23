# -*- coding: utf-8 -*-
"""Standalone runner for the miner web dashboard.

Demo mode (no Twitch account needed):

    python -m TwitchChannelPointsMiner.dashboard_demo --demo --port 8181

(Without --demo you still get demo data; attaching a live miner is done
from your own run script via twitch_miner.dashboard().)
"""
import argparse
import logging

from TwitchChannelPointsMiner.dashboard_server import DashboardServer


def main():
    parser = argparse.ArgumentParser(description="Twitch Miner web dashboard")
    parser.add_argument("--host", default="127.0.0.1", help="bind host")
    parser.add_argument("--port", type=int, default=8181, help="bind port")
    parser.add_argument(
        "--demo", action="store_true", help="serve fake data instead of a live miner"
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    server = DashboardServer(miner=None if args.demo else None,
                             host=args.host, port=args.port)
    if not args.demo:
        print(
            "NOTE: standalone mode always serves demo data.\n"
            "To attach a live miner, call twitch_miner.dashboard(host, port) "
            "in your run script before .mine()."
        )
    server.run()


if __name__ == "__main__":
    main()
