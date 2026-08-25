#!/bin/bash
# Launches the miner with the right env; used by Hermes background terminal.
cd /home/ubuntu/workspace/Twitch-Channel-Points-Miner-v2
set -a
source /home/ubuntu/.hermes/.env
set +a
export MINER_IMESSAGE_TO="$SENDBLUE_HOME_CHANNEL"
export DASHBOARD_BROWSER_INTEGRITY=0
export MINER_AUTOCLAIM=0
exec .venv/bin/python run_server.py
