#!/bin/bash
# Wrapper that launchd calls once a day. Activates the venv, makes sure git is on
# PATH (launchd starts with a bare PATH), scrapes, and pushes social.json.
cd "$(dirname "$0")" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
# shellcheck disable=SC1091
source .venv/bin/activate
python mac_scraper.py --push >> scrape.log 2>&1
