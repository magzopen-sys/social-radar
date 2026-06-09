# Social Radar — off-machine TikTok / Instagram / Google Trends scraper

Your home PC's IP is blocked/rate-limited by TikTok, Instagram, Reddit (public),
and Google Trends, and it's RAM-limited (it freezes). So the heavy scraping runs
**for free on GitHub Actions** instead. It publishes a small `feed.json`; the
Odysseus Discord bot reads it and pings you on new cross-platform trends.

```
GitHub Actions (free, clean IP)        Your PC (light)
  scrape.py every 2h  ──> feed.json ──> bot reads SOCIAL_FEED_URL ──> #cross-platform ping
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

That's it — Google Trends works out of the box. TikTok and IG are best-effort and
get more reliable with the optional secrets below.

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
- **Free tier:** every 2h ≈ 360 runs/mo × ~3–8 min each — well within the free
  2,000 min/month for private repos, and unlimited for public repos.
- **Private repo:** raw URLs need a token. Easiest is a public repo containing
  *only* feed.json, or switch the bot to fetch via the GitHub API with a token.
- **It will break sometimes** — these endpoints change. `scrape.py` degrades
  gracefully (one source failing doesn't stop the others), and the Action logs
  show what failed.
