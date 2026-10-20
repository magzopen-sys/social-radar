#!/bin/bash
# Daily driver, run by launchd. Runs the WHOLE pipeline locally, then pushes
# feed.json. Keys come from the macOS Keychain (preferred, encrypted at rest)
# or, if not in the Keychain, from the git-ignored ../.env.
#   1) TikTok + Instagram via the logged-in browser   -> social.json
#   2) Reddit + YouTube + Trends, merged with social.json -> feed.json
#   3) push feed.json (+ social.json)
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

# --- safety: never let secrets get committed ---
if git ls-files --error-unmatch .env >/dev/null 2>&1; then
  echo "ABORT: .env is tracked by git. Run: git rm --cached .env" >> "$LOG"; exit 1
fi

python mac/mac_scraper.py >> "$LOG" 2>&1   # TikTok + IG -> social.json (no push)
python scrape.py          >> "$LOG" 2>&1   # merge everything -> feed.json
python ideas.py           >> "$LOG" 2>&1   # cross-platform content ideas -> ideas.md

# Only ever stage these generated files — never a blanket 'git add .'
git add feed.json social.json ideas.md 2>/dev/null
if git diff --quiet --staged; then
  echo "no changes to push" >> "$LOG"; exit 0
fi
git commit -m "feed: $(date -u +%FT%TZ)" >> "$LOG" 2>&1
for i in 1 2 3 4; do
  if git pull --rebase origin main >> "$LOG" 2>&1 && git push origin HEAD >> "$LOG" 2>&1; then
    echo "pushed" >> "$LOG"; exit 0
  fi
  sleep $((2 ** i))
done
echo "ERROR: push failed after retries" >> "$LOG"
exit 1
