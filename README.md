# Social Radar — off-machine TikTok / Instagram / Google Trends scraper

Your home PC's IP is blocked/rate-limited by TikTok, Instagram, Reddit (public),
and Google Trends, and it's RAM-limited (it freezes). So the heavy scraping runs
**for free on GitHub Actions** instead. It publishes a small `feed.json`; the
Odysseus Discord bot reads it and pings you on new cross-platform trends.

```
GitHub Actions (free, clean IP)        Your PC (light)
  scrape.py hourly   ──> feed.json ──> bot reads SOCIAL_FEED_URL ──> #cross-platform ping
```

## One-time setup (~10 min)

1. **Create a new GitHub repo** (e.g. `magz-social-radar`). Public is simplest
   (then the feed has a public raw URL). Private works too — see note at bottom.

2. **Copy these files to the repo root** and push:
   ```
   scrape.py
   requirements.txt
   .github/workflows/social-radar.yml
   ```

3. **Enable Actions** in the repo: Settings → Actions → General → allow, and under
   "Workflow permissions" pick **Read and write** (so it can commit `feed.json`).

4. **Run it once**: Actions tab → *social-radar* → *Run workflow*. After it finishes
   you'll have a `feed.json` in the repo. Its raw URL is:
   ```
   https://raw.githubusercontent.com/<your-username>/magz-social-radar/main/feed.json
   ```

5. **Point the bot at it** — add to `~/odysseus/.env`:
   ```
   SOCIAL_FEED_URL=https://raw.githubusercontent.com/<your-username>/magz-social-radar/main/feed.json
   ```
   then `systemctl --user restart odysseus.service`.

That's it — but see the Reddit setup below: Reddit now blocks anonymous requests
from GitHub's IPs, so the two Reddit secrets are what make the feed actually fill.
TikTok and IG are best-effort and get more reliable with the optional secrets below.

## Reddit setup (2 min — makes Reddit reliable)

Reddit returns **403** to anonymous `.json` requests from GitHub Actions IPs, so
the scraper now uses the official Reddit API (app-only OAuth). You need a free
Reddit "script" app:

1. Go to <https://www.reddit.com/prefs/apps> → **create another app...**
2. Pick type **script**. Name it anything (e.g. `social-radar`). For the
   redirect URI put `http://localhost:8080` (unused, but required).
3. After creating it you'll see:
   - the **client id** — the string just under the app name (near "personal use script")
   - the **secret** — labelled `secret`
4. Add them as repo Secrets (Settings → Secrets and variables → Actions → New
   repository secret):
   - `REDDIT_CLIENT_ID`
   - `REDDIT_CLIENT_SECRET`
5. (Optional) Set a repo **Variable** `REDDIT_USER_AGENT`, e.g.
   `social-radar/1.0 (by /u/yourname)`. There's a sensible default if you skip it.

Without these secrets the scraper falls back to anonymous scraping, which will
keep getting 403'd on CI — you'll see that clearly in the logs and in the new
`sources` section of `feed.json`.

Other tunables (optional repo Variables / env): `REDDIT_SUBS` (comma list),
`REDDIT_MIN_SCORE` (default 100), `REDDIT_LIMIT` (default 50). To actually fill
50 items/hour you need enough supply — keep several busy subreddits in
`REDDIT_SUBS` and don't set `REDDIT_MIN_SCORE` too high.

## YouTube setup (free, high volume — recommended)

The YouTube Data API v3 gives you a free key and 10,000 quota units/day. One
search returns up to 50 videos and costs 100 units, so hourly runs use a tiny
fraction of the daily quota. This is the most reliable way to hit ~50/hour.

1. Go to <https://console.cloud.google.com/> → create a project (any name).
2. **APIs & Services → Library** → search **"YouTube Data API v3"** → **Enable**.
3. **APIs & Services → Credentials → Create credentials → API key**. Copy it.
4. Add it as a repo Secret: `YOUTUBE_API_KEY`.
5. (Optional) repo Variable `YOUTUBE_QUERIES`, e.g.
   `minecraft,minecraft shorts,minecraft build hacks`. Has a default.

Tunables: `YOUTUBE_LIMIT` (default 50), `YOUTUBE_DAYS` (default 7, only recent videos).

## Optional secrets (make TikTok / IG solid)

Set these in the repo: Settings → Secrets and variables → Actions.

- **`TIKTOK_MS_TOKEN`** (secret) — hugely improves TikTok reliability.
  Get it: log into tiktok.com in a browser → DevTools → Application → Cookies →
  copy the value of `msToken`. Paste as the secret. (It rotates every few weeks;
  refresh when TikTok results dry up.)
- **`IG_ACCOUNTS`** (variable, not secret) — comma-separated public handles to watch,
  e.g. `minecraft,somemcytcreator,anotherone`. Defaults to a generic set.
- **`IG_USERNAME` + `IG_SESSIONFILE`** (secrets) — only if IG starts requiring login.
  Generate a session locally with `instaloader --login <user>` and paste the
  session file contents. Skip unless anonymous scraping stops working.

## Notes
- **Free tier:** hourly ≈ 720 runs/mo × ~1 min each — well within the free
  2,000 min/month for private repos, and unlimited for public repos.
- **Private repo:** raw URLs need a token. Easiest is a public repo containing
  *only* feed.json, or switch the bot to fetch via the GitHub API with a token.
- **It will break sometimes** — these endpoints change. `scrape.py` degrades
  gracefully (one source failing doesn't stop the others), and the Action logs
  show what failed.
