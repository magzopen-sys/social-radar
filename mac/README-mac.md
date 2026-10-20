# Mac-side TikTok + Instagram scraper

GitHub Actions can't scrape TikTok or Instagram — their datacenter IPs are
blocked and both platforms require a login. Your Mac can, because it uses your
real logged-in session and your home IP. So this piece runs on your Mac once a
day, writes `../social.json`, and pushes it to the repo. The hourly GitHub
Action then merges that `social.json` with the (free, reliable) Reddit + YouTube
sources into `feed.json`.

```
  Your Mac (daily)                         GitHub Actions (hourly)
  mac_scraper.py --push ──> social.json ──> scrape.py merges it with
   (logged-in browser)      (pushed to       Reddit + YouTube ──> feed.json
                             the repo)
```

> ⚠️ Scraping TikTok/IG is against their Terms of Service. Keep it to once a day,
> and consider using a **secondary/throwaway login**, not your main creator
> account, which could be rate-limited or flagged. This is for personal trend
> monitoring of your own niche.

## One-time setup

```bash
cd mac
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-mac.txt
python -m playwright install chromium

# Log in once — a browser opens; sign into BOTH TikTok and Instagram, then press Enter.
python mac_scraper.py --login
```

Your session is saved in `mac/.mac-profile/` (git-ignored). You usually only
need to log in again if the session expires.

## Run it

```bash
source .venv/bin/activate
python mac_scraper.py            # scrape -> ../social.json
python mac_scraper.py --push     # scrape, then commit + push social.json
python mac_scraper.py --debug    # also save screenshots + raw JSON to mac/debug/
```

Tunables (env vars):

| Var | Default | Meaning |
|---|---|---|
| `TT_QUERIES` | `minecraft,minecraft build,minecraft shorts` | TikTok search terms |
| `IG_TAGS` | `minecraft,minecraftbuilds,minecraftmemes` | Instagram hashtags |
| `LIMIT` | `50` | max items per platform |
| `SCROLLS` | `8` | scroll passes per page (more = more items, slower) |
| `HEADLESS` | off | set `HEADLESS=1` to hide the window (more bot-detectable) |

## Schedule it daily (launchd)

1. Edit `com.magz.social-radar.plist` and replace the three `/ABSOLUTE/PATH/TO`
   paths with the real path to this repo (e.g. `/Users/you/social-radar`).
2. Install:
   ```bash
   cp com.magz.social-radar.plist ~/Library/LaunchAgents/
   launchctl load  ~/Library/LaunchAgents/com.magz.social-radar.plist
   launchctl start com.magz.social-radar     # run once now to test
   ```
3. Check `mac/scrape.log` and `mac/launchd.err.log` for output.

To stop:
```bash
launchctl unload ~/Library/LaunchAgents/com.magz.social-radar.plist
```

## If you get 0 items

- Re-run `python mac_scraper.py --login` — your session may have expired.
- Run with `--debug` and look in `mac/debug/`: the screenshots show what the page
  looked like, and the `.json` files show what data was captured. TikTok/IG change
  their internals periodically; if the structure moved, send me a debug capture
  and I'll update the extractor.
- Make sure `HEADLESS` is **off** for the first runs (some checks only pass with a
  visible window).

## How the data reaches the feed

`mac_scraper.py` writes `social.json` at the repo root in the exact shape
`scrape.py` already expects:

```json
{ "tiktok": [ {"id","title","url","author","views","tag"}, ... ],
  "instagram": [ {"id","title","url","author","views"}, ... ] }
```

`--push` commits and pushes it (with a rebase-retry so it doesn't clash with the
Action's hourly `feed.json` commits). The next hourly Action picks it up
automatically — no other wiring needed.
