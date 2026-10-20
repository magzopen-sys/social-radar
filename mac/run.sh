#!/bin/bash
# Daily driver, run by launchd. Runs the whole radar locally on this Mac:
#   1) TikTok + Instagram via the logged-in browser       -> social.json
#   2) YouTube + Modrinth + Reddit + Trends, merged        -> feed.json
#   3) cross-platform content ideas                        -> ideas.md
# Keys come from the macOS Keychain (preferred, encrypted) or the git-ignored
# ../.env. Nothing is uploaded anywhere — results stay on this Mac.
set -u
cd "$(dirname "$0")/.." || exit 1          # repo root
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
# shellcheck disable=SC1091
source mac/.venv/bin/activate

LOG="mac/scrape.log"
echo "=== run $(date -u +%FT%TZ) ===" >> "$LOG"

# --- keys: prefer macOS Keychain (encrypted), only export when a value exists ---
# so an empty slot still lets scrape.py fall back to ../.env.
set_if() { local v; v="$(security find-generic-password -a "$USER" -s "$2" -w 2>/dev/null)"; [ -n "$v" ] && export "$1"="$v"; }
set_if YOUTUBE_API_KEY       social-radar-youtube
set_if REDDIT_CLIENT_ID      social-radar-reddit-id
set_if REDDIT_CLIENT_SECRET  social-radar-reddit-secret

python mac/mac_scraper.py >> "$LOG" 2>&1   # TikTok + IG -> social.json
python scrape.py          >> "$LOG" 2>&1   # merge everything -> feed.json
python ideas.py           >> "$LOG" 2>&1   # cross-platform content ideas -> ideas.md
echo "done — open ideas.md" >> "$LOG"
