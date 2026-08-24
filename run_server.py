# -*- coding: utf-8 -*-
# Server-side miner run script: real session, real streamers, dashboard
# exposed via Cloudflare Tunnel, iMessage notify on available bonuses.
import logging

from TwitchChannelPointsMiner import TwitchChannelPointsMiner
from TwitchChannelPointsMiner.logger import LoggerSettings

twitch_miner = TwitchChannelPointsMiner(
    username="ggalyx",  # corrected automatically from the cookie if stale
    claim_drops_startup=False,
    priority=["STREAK", "DROPS", "ORDER"],
    logger_settings=LoggerSettings(
        save=True,
        console_level=logging.INFO,
        file_level=logging.INFO,
        emoji=True,
        less=False,
        colored=False,
    ),
)

# Dashboard reachable at https://miner.alyx.site (Cloudflare Tunnel)
twitch_miner.dashboard(host="127.0.0.1", port=8181)

twitch_miner.mine(
    [
        "ohnepixel",
        "eslcs",
        "arrowcs",
        "jamesbardolph",
        "franzj",
        "vince",
        "dima_wallhacks",
        "johnstone",
        "iateyourpie",
        "saltybet",
    ],
    followers=False,
)
