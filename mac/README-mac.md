# Run social-radar on your Mac (all sources, keys stay local)

This runs the **whole** radar on your Mac, with your keys in a git-ignored
`.env` that never leaves the machine. Nothing is stored in the repo or in CI.

- **TikTok + Instagram** — scraped from your logged-in browser (only way that works).
- **YouTube + Modrinth + Reddit + Google Trends** — APIs, keys read from `../.env`.
- Results stay on the Mac: open `ideas.md` for the day's content ideas.

```
  Your Mac (scheduled by launchd)
  mac/run.sh:
    1) mac_scraper.py  -> social.json   (TikTok + IG, logged-in browser)
    2) scrape.py       -> feed.json     (YouTube + Modrinth + Reddit + Trends + social.json)
    3) ideas.py        -> ideas.md      (cross-platform content ideas)
  Keys come from ../.env (git-ignored) or the Keychain.
```

> ⚠️ Scraping TikTok/IG is against their ToS. Keep it to once a day, and use a
> secondary/throwaway login, not your main creator account.

## One-time setup

```bash
cd social-radar

# 1) Your keys -> local .env (never pushed)
cp .env.example .env
#    then open .env and paste in REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET,
#    YOUTUBE_API_KEY (and REDDIT_USER_AGENT with your reddit username).

# 2) Python env + browser
cd mac
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-mac.txt
python -m playwright install chromium

# 3) Log into TikTok + Instagram once (a browser opens; sign in, press Enter)
python mac_scraper.py --login
```

## Test it by hand

```bash
cd social-radar/mac
source .venv/bin/activate

python mac_scraper.py --debug     # just TikTok + IG -> ../social.json (+ debug/)
cd .. && python scrape.py         # merge everything -> feed.json (reads .env)
cat feed.json                     # check the "sources" block: ok/count per source
```

`feed.json`'s `sources` block tells you exactly what worked, e.g.:
```
"reddit":  {"count": 50, "ok": true,  "note": "ok"},
"youtube": {"count": 50, "ok": true,  "note": "ok"},
"tiktok":  {"count": 0,  "ok": false, "note": "no items ..."}
```

## Choosing what it scrapes

Add any of these to `../.env` (comma-separated):

| Var | Default | What it opens |
|---|---|---|
| `TT_TAGS` | `minecraft,minecraftbuilds,minecraftmemes` | `tiktok.com/tag/<tag>` (works logged out) |
| `TT_QUERIES` | `minecraft,minecraft build,minecraft shorts` | TikTok search (needs a TikTok login) |
| `IG_ACCOUNTS` | `minecraft,kingfox.yt,bweeyt,askplayz.gg` | `instagram.com/<handle>/reels/` |
| `IG_LIMIT` | 30 per account | max Instagram posts kept |
| `IG_TAGS` | *(none)* | Instagram hashtag pages (often show "Something went wrong", so off by default) |
| `SCROLLS` | `8` | max scrolls per page (stops early once a page stops growing) |

Adding a few big Minecraft creators to `IG_ACCOUNTS` is the easiest way to get
more Instagram results.

## Schedule it (launchd)

`mac/run.sh` runs all three steps and leaves the results on the Mac. To run it daily:

1. Edit `com.magz.social-radar.plist` — replace the three `/ABSOLUTE/PATH/TO`
   paths with your real repo path (e.g. `/Users/you/social-radar`).
2. Install:
   ```bash
   cp com.magz.social-radar.plist ~/Library/LaunchAgents/
   launchctl load  ~/Library/LaunchAgents/com.magz.social-radar.plist
   launchctl start com.magz.social-radar     # run once now to test
   ```
3. Watch `mac/scrape.log` for the per-source counts.

To change the time, edit `StartCalendarInterval` in the plist (default 09:00).
To run more often than daily, you can add more `StartCalendarInterval` entries.

To stop:
```bash
launchctl unload ~/Library/LaunchAgents/com.magz.social-radar.plist
```

## If TikTok/IG return 0

- Re-run `python mac_scraper.py --login` — the session may have expired.
- Run with `--debug` and look in `mac/debug/`: screenshots show the page, the
  `.json` files show what was captured. TikTok/IG change their internals
  periodically; send me a debug capture and I'll update the extractor.
- Keep `HEADLESS` off for the first runs (some checks only pass with a window).

Reddit/YouTube returning 0 instead means a key problem — check `.env` and the
`note` field in `feed.json`'s `sources` block.

## Security — making a breach harmless

The goal: even if someone got onto your Mac, the keys are hard to read and
useless if they do leak. Layers, strongest first:

### 1. Store keys in the macOS Keychain (recommended, instead of .env)

The Keychain encrypts secrets at rest and unlocks them with your login, so there
is no plaintext file sitting around. `run.sh` reads from the Keychain first.

```bash
security add-generic-password -a "$USER" -s social-radar-youtube        -w 'YOUR_YOUTUBE_KEY'
security add-generic-password -a "$USER" -s social-radar-reddit-id      -w 'YOUR_REDDIT_ID'
security add-generic-password -a "$USER" -s social-radar-reddit-secret  -w 'YOUR_REDDIT_SECRET'
```

To update one, delete then re-add:
`security delete-generic-password -s social-radar-youtube`.

If you use the Keychain for all three, you can delete `.env` entirely.

### 2. If you keep a .env, lock it down

```bash
chmod 600 .env        # only your user can read it
```
It's already git-ignored, and `run.sh` aborts if `.env` is ever tracked and only
ever stages `feed.json` / `social.json` — so it can't be committed by accident.

### 3. Restrict the keys at the source (limits the blast radius)

- **YouTube key** → Google Cloud Console → Credentials → your key →
  **API restrictions → Restrict key → YouTube Data API v3 only**. A leaked key
  then can't touch anything else, and it's already capped at 10k units/day.
- **Reddit app** → it's a *script* app with app-only (read-only) access to public
  data — it can't post, delete, or read private messages even if leaked.

### 4. Rotate anything that was ever exposed

If a key was pasted somewhere it shouldn't be (chat, screenshot, a commit):
- YouTube: **Regenerate key** in Google Cloud, update Keychain/.env.
- Reddit: click **edit** on the app at reddit.com/prefs/apps and regenerate the
  secret, update Keychain/.env.

Rotation takes ~30 seconds and instantly invalidates the old value.
