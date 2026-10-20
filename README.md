# Social Radar — Minecraft trend radar that runs on your Mac

Once a day, your Mac checks what's trending in the Minecraft niche across
TikTok, Instagram, YouTube, Modrinth (mods), Reddit and Google Trends, and
writes a ranked list of content ideas to `ideas.md`. Everything runs and stays
on your Mac.

```
mac/run.sh (daily, via launchd)
  1) mac/mac_scraper.py -> social.json   TikTok + Instagram, from your logged-in browser
  2) scrape.py          -> feed.json     YouTube + Modrinth + Reddit + Trends, merged
  3) ideas.py           -> ideas.md      themes trending on 2+ platforms, hottest examples
```

**Setup, the daily schedule and troubleshooting:** see
[`mac/README-mac.md`](mac/README-mac.md).

## Sources

| Source | How | Needs |
|---|---|---|
| TikTok | your logged-in browser (`mac_scraper.py`) | a TikTok login (hashtag pages also work logged out) |
| Instagram | your logged-in browser | an Instagram login |
| YouTube | YouTube Data API v3 | free `YOUTUBE_API_KEY` |
| Modrinth | public API | nothing |
| Reddit | official API, falls back to public pages | `REDDIT_CLIENT_ID` / `SECRET` (Reddit currently refuses new apps) |
| Google Trends | pytrends | nothing; often rate-limited |
| TikTok Research API | optional, tried before the browser | an *approved* Research API app |

Keys go in a git-ignored `.env` (copy `.env.example`) or the macOS Keychain.

## Reading the results

- `ideas.md` — open it any time: `open ideas.md`.
- `feed.json` — every item, plus a `sources` block saying how many items each
  source returned and, if it failed, why.

## Content ideas (`ideas.py`)

Finds themes that show up on **more than one** platform (the strongest signal),
each with the hottest real example to riff on, plus the top individual posts.
It's keyword/co-occurrence analysis, no API key. Filler hashtags (`#fyp`,
`#minecraftmemes`…) and promo spam are filtered out.
