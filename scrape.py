#!/usr/bin/env python3
"""
Social radar orchestrator (runs on the Mac, from mac/run.sh).

Merges every source into feed.json, which ideas.py turns into ideas.md:
  - TikTok + Instagram : mac/mac_scraper.py (logged-in browser, run BEFORE this) -> social.json
  - TikTok (optional)  : official Research API, if your app is approved
  - YouTube            : YouTube Data API v3
  - Modrinth           : public API (Minecraft mods)
  - Reddit             : official API, falling back to public .json pages
  - Google Trends      : pytrends (best-effort; often rate-limited)

Every source is best-effort and isolated, so one breaking doesn't sink the
others. Each item carries a stable `id`.
Each source also reports an honest status (count / ok / note) under `sources`,
so an empty feed no longer looks like a silent success.

Feed shape:
{
  "generated_at": "<ISO8601 Z>",
  "tiktok":        [...], "instagram": [...],
  "reddit":        [{"id","title","url","score","sub"}, ...],
  "google_trends": [{"id","query","value"}, ...],
  "sources": {
    "<name>": {"count": int, "ok": bool, "note": "..."}, ...
  }
}

Env:
  GEO                   default US
  REDDIT_SUBS           comma list (default is a Minecraft-niche set)
  REDDIT_CLIENT_ID      Reddit "script" app client id   (recommended)
  REDDIT_CLIENT_SECRET  Reddit "script" app secret      (recommended)
  REDDIT_USER_AGENT     descriptive UA Reddit requires   (has a default)
  REDDIT_MIN_SCORE      minimum post score to keep (default 100)
  REDDIT_LIMIT          max reddit items in feed (default 50)
  YOUTUBE_API_KEY       YouTube Data API v3 key (free; Google Cloud Console)
  YOUTUBE_QUERIES       comma list of search terms (default minecraft set)
  YOUTUBE_LIMIT         max youtube items in feed (default 50)
  YOUTUBE_DAYS          only videos newer than N days (default 7)
  TIKTOK_CLIENT_KEY     TikTok app key (official Research API; approval-gated)
  TIKTOK_CLIENT_SECRET  TikTok app secret
  TIKTOK_HASHTAGS       comma list of hashtags (default minecraft set)
  TIKTOK_LIMIT          max tiktok items from the API (default 50)
  MODRINTH_TOKEN        optional Modrinth token (reads are free without it)
  MODRINTH_LIMIT        max modrinth items (default 50)
  MODRINTH_QUERY        optional search text (default: all mods)
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone

import requests

# Make the vendored ./yars package importable regardless of cwd (anon fallback).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# Load keys from a local .env (git-ignored) if present, so credentials can live
# on the machine that runs this instead of in the repo or in CI secrets. Real
# environment variables always take precedence over .env values.
def _load_dotenv(path: str) -> None:
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except FileNotFoundError:
        pass


_load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

GEO = os.getenv("GEO", "US")
REDDIT_UA = os.getenv("REDDIT_USER_AGENT", "social-radar/1.0 (by /u/magzopen)")

# Honest per-source status, filled in by safe().
STATUS: dict[str, dict] = {}


def _sid(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]


def _subs() -> list[str]:
    return [s.strip() for s in os.getenv(
        "REDDIT_SUBS",
        "Minecraft,MinecraftMemes,youtubeshorts,Minecraftbuilds,redstone,technicalminecraft",
    ).split(",") if s.strip()]


# ── Reddit ──────────────────────────────────────────────────────────────────
def scrape_reddit() -> list[dict]:
    """Official API when creds are present (reliable), anonymous .json otherwise."""
    subs = _subs()
    min_score = int(os.getenv("REDDIT_MIN_SCORE", "100"))
    cid = os.getenv("REDDIT_CLIENT_ID")
    secret = os.getenv("REDDIT_CLIENT_SECRET")

    if cid and secret:
        try:
            return _reddit_api(cid, secret, subs, min_score)
        except Exception as api_err:
            # Reddit sometimes refuses new apps/accounts (403 at the token step).
            # Public .json pages usually still work from a home connection.
            print(f"[reddit] official API failed ({api_err}) — falling back to "
                  "public .json pages", file=sys.stderr)
            try:
                return _reddit_anon(subs, min_score)
            except Exception as anon_err:
                raise RuntimeError(f"API: {api_err} | public pages: {anon_err}") from anon_err

    print("[reddit] REDDIT_CLIENT_ID/SECRET not set — falling back to anonymous "
          ".json, which Reddit usually 403s from GitHub Actions. Set the secrets "
          "(see README) to make this reliable.", file=sys.stderr)
    return _reddit_anon(subs, min_score)


def _reddit_token(cid: str, secret: str) -> str:
    r = requests.post(
        "https://www.reddit.com/api/v1/access_token",
        auth=(cid, secret),
        data={"grant_type": "client_credentials"},
        headers={"User-Agent": REDDIT_UA},
        timeout=20,
    )
    r.raise_for_status()
    tok = r.json().get("access_token")
    if not tok:
        raise RuntimeError("no access_token in token response")
    return tok


def _get_with_retry(url: str, headers: dict, params: dict, attempts: int = 4):
    last = None
    for i in range(attempts):
        resp = requests.get(url, headers=headers, params=params, timeout=20)
        last = resp
        if resp.status_code == 429 or resp.status_code >= 500:
            wait = 2 ** i
            print(f"[http] HTTP {resp.status_code} on {url} — retry in {wait}s",
                  file=sys.stderr)
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp
    last.raise_for_status()
    return last


def _reddit_api(cid: str, secret: str, subs: list[str], min_score: int) -> list[dict]:
    token = _reddit_token(cid, secret)
    headers = {"Authorization": f"bearer {token}", "User-Agent": REDDIT_UA}
    out: list[dict] = []
    errors: list[str] = []
    for sub in subs:
        try:
            resp = _get_with_retry(
                f"https://oauth.reddit.com/r/{sub}/hot",
                headers=headers,
                params={"limit": 100, "raw_json": 1},
            )
            for ch in resp.json().get("data", {}).get("children", []):
                p = ch.get("data", {})
                score = int(p.get("score", 0) or 0)
                if score < min_score:
                    continue
                perma = p.get("permalink", "")
                out.append({
                    "id": _sid("rd", p.get("id") or perma),
                    "title": (p.get("title") or "")[:90],
                    "url": ("https://reddit.com" + perma) if perma else (p.get("url") or ""),
                    "score": score,
                    "sub": sub,
                })
        except Exception as e:
            errors.append(f"{sub}: {e}")
            print(f"[reddit] {sub}: {e}", file=sys.stderr)

    # If every subreddit failed, surface it as an error instead of a quiet [].
    if not out and errors:
        raise RuntimeError("all subreddits failed via API -> " + "; ".join(errors))

    out.sort(key=lambda x: x["score"], reverse=True)
    return out[:int(os.getenv("REDDIT_LIMIT", "50"))]


def _reddit_anon(subs: list[str], min_score: int) -> list[dict]:
    try:
        from yars.yars import YARS          # installed-package layout
    except Exception:
        from yars import YARS               # flat layout fallback
    miner = YARS()
    out: list[dict] = []
    errors: list[str] = []
    for sub in subs:
        try:
            # YARS prints HTTP failures instead of raising; capture and surface them.
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                posts = miner.fetch_subreddit_posts(sub, limit=50, category="hot")
            printed = buf.getvalue().strip()
            if not posts and "Failed" in printed:
                raise RuntimeError(printed)
            for p in posts:
                score = p.get("score", 0) or 0
                if score < min_score:
                    continue
                perma = p.get("permalink", "")
                out.append({
                    "id": _sid("rd", p.get("id") or perma),
                    "title": (p.get("title", "") or "")[:90],
                    "url": ("https://reddit.com" + perma) if perma else p.get("url", ""),
                    "score": score,
                    "sub": sub,
                })
        except Exception as e:
            errors.append(f"{sub}: {e}")
            print(f"[reddit] {sub}: {e}", file=sys.stderr)
    if not out and errors:
        raise RuntimeError("all subreddits failed (anonymous) -> " + "; ".join(errors))
    out.sort(key=lambda x: x["score"], reverse=True)
    return out[:int(os.getenv("REDDIT_LIMIT", "50"))]


# ── TikTok via the official Research API (needs an approved app) ──────────────
def scrape_tiktok_api() -> list[dict]:
    """Query public TikToks by hashtag via the official Research API.

    Only works if your TikTok developer app has Research API access (approval
    gated). A normal app will get an auth/scope error here — the caller then
    falls back to the Mac browser scraper's social.json.
    """
    ck = os.getenv("TIKTOK_CLIENT_KEY")
    cs = os.getenv("TIKTOK_CLIENT_SECRET")
    if not (ck and cs):
        raise RuntimeError("TIKTOK_CLIENT_KEY/SECRET not set")

    tr = requests.post(
        "https://open.tiktokapis.com/v2/oauth/token/",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={"client_key": ck, "client_secret": cs, "grant_type": "client_credentials"},
        timeout=20,
    )
    tr.raise_for_status()
    token = tr.json().get("access_token")
    if not token:
        raise RuntimeError("no access_token in token response")

    tags = [t.strip().lstrip("#") for t in os.getenv(
        "TIKTOK_HASHTAGS", "minecraft,minecraftbuilds").split(",") if t.strip()]
    limit = int(os.getenv("TIKTOK_LIMIT", "50"))
    days = int(os.getenv("TIKTOK_DAYS", "7"))
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)

    out: list[dict] = []
    errors: list[str] = []
    for tag in tags:
        try:
            resp = requests.post(
                "https://open.tiktokapis.com/v2/research/video/query/"
                "?fields=id,username,video_description,view_count,hashtag_names",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                data=json.dumps({
                    "query": {"and": [{"operation": "IN", "field_name": "hashtag_name",
                                       "field_values": [tag]}]},
                    "max_count": min(100, limit),
                    "start_date": start.strftime("%Y%m%d"),
                    "end_date": end.strftime("%Y%m%d"),
                }),
                timeout=25,
            )
            resp.raise_for_status()
            for v in resp.json().get("data", {}).get("videos", []):
                vid = str(v.get("id"))
                out.append({
                    "id": "tt" + vid,
                    "title": (v.get("video_description") or "(tiktok)")[:90],
                    "url": f"https://www.tiktok.com/@{v.get('username', '')}/video/{vid}",
                    "author": v.get("username", ""),
                    "views": v.get("view_count"),
                    "tag": tag,
                })
        except Exception as e:
            errors.append(f"{tag}: {e}")
            print(f"[tiktok-api] {tag}: {e}", file=sys.stderr)

    if not out and errors:
        raise RuntimeError("Research API returned nothing (likely not approved) -> "
                           + "; ".join(errors))
    seen, uniq = set(), []
    for i in out:
        if i["id"] not in seen:
            seen.add(i["id"]); uniq.append(i)
    uniq.sort(key=lambda x: (x.get("views") or 0), reverse=True)
    return uniq[:limit]


# ── YouTube via the official Data API v3 (free key, generous quota) ───────────
def scrape_youtube() -> list[dict]:
    key = os.getenv("YOUTUBE_API_KEY")
    if not key:
        raise RuntimeError(
            "YOUTUBE_API_KEY not set — create a free key in Google Cloud Console "
            "(enable 'YouTube Data API v3'). See README.")

    queries = [q.strip() for q in os.getenv(
        "YOUTUBE_QUERIES", "minecraft,minecraft shorts,minecraft build hacks").split(",") if q.strip()]
    limit = int(os.getenv("YOUTUBE_LIMIT", "50"))
    days = int(os.getenv("YOUTUBE_DAYS", "7"))
    after = (datetime.now(timezone.utc) - timedelta(days=days)) \
        .isoformat(timespec="seconds").replace("+00:00", "Z")
    per = min(50, max(1, (limit // max(1, len(queries))) + 5))  # search.list caps at 50

    out: list[dict] = []
    errors: list[str] = []
    for q in queries:
        try:
            # search.list costs 100 quota units and returns up to 50 items.
            resp = _get_with_retry(
                "https://www.googleapis.com/youtube/v3/search",
                headers={},
                params={
                    "key": key, "q": q, "part": "snippet", "type": "video",
                    "order": "viewCount", "maxResults": per,
                    "publishedAfter": after, "relevanceLanguage": "en",
                },
            )
            for it in resp.json().get("items", []):
                vid = (it.get("id") or {}).get("videoId")
                sn = it.get("snippet") or {}
                if not vid:
                    continue
                out.append({
                    "id": _sid("yt", vid),
                    "title": (sn.get("title") or "")[:90],
                    "url": f"https://www.youtube.com/watch?v={vid}",
                    "channel": sn.get("channelTitle", ""),
                    "published": sn.get("publishedAt", ""),
                    "query": q,
                })
        except Exception as e:
            errors.append(f"{q}: {e}")
            print(f"[youtube] {q}: {e}", file=sys.stderr)

    seen, uniq = set(), []
    for i in out:
        if i["id"] not in seen:
            seen.add(i["id"]); uniq.append(i)
    if not uniq and errors:
        raise RuntimeError("all queries failed -> " + "; ".join(errors))
    return uniq[:limit]


# ── Modrinth (Minecraft mods) — free public API, no auth needed for reads ─────
def scrape_modrinth() -> list[dict]:
    ua = os.getenv("MODRINTH_USER_AGENT",
                   "social-radar/1.0 (github.com/magzopen-sys/social-radar)")
    limit = int(os.getenv("MODRINTH_LIMIT", "50"))
    query = os.getenv("MODRINTH_QUERY", "")
    headers = {"User-Agent": ua}
    tok = os.getenv("MODRINTH_TOKEN")          # optional: only raises rate limits
    if tok:
        headers["Authorization"] = tok
    out: list[dict] = []
    seen: set[str] = set()
    errors: list[str] = []
    # "follows" = what's trending; "updated" = freshly active projects.
    for index in ("follows", "updated"):
        try:
            resp = _get_with_retry(
                "https://api.modrinth.com/v2/search",
                headers=headers,
                params={"query": query, "index": index,
                        "facets": json.dumps([["project_type:mod"]]),
                        "limit": min(100, limit)},
            )
            for h in resp.json().get("hits", []):
                slug = h.get("slug") or h.get("project_id")
                if not slug or slug in seen:
                    continue
                seen.add(slug)
                out.append({
                    "id": _sid("mr", str(slug)),
                    "title": (h.get("title") or "")[:90],
                    "url": f"https://modrinth.com/mod/{slug}",
                    "downloads": h.get("downloads"),
                    "follows": h.get("follows"),
                    "author": h.get("author", ""),
                    "index": index,
                })
        except Exception as e:
            errors.append(f"{index}: {e}")
            print(f"[modrinth] {index}: {e}", file=sys.stderr)
    if not out and errors:
        raise RuntimeError("Modrinth search failed -> " + "; ".join(errors))
    out.sort(key=lambda x: (x.get("downloads") or 0), reverse=True)
    return out[:limit]


# ── Google Trends via pytrends ────────────────────────────────────────────────
def scrape_google_trends() -> list[dict]:
    from pytrends.request import TrendReq
    out: list[dict] = []
    p = TrendReq(hl="en-US", tz=0)
    for seed in ("minecraft", "minecraft shorts"):
        try:
            p.build_payload([seed], timeframe="now 7-d", geo=GEO)
            rising = (p.related_queries().get(seed) or {}).get("rising")
            if rising is None:
                continue
            for _, row in rising.head(50).iterrows():
                q = str(row["query"])
                out.append({"id": _sid("gt", q), "query": q, "value": f"+{row['value']}%"})
        except Exception as e:
            print(f"[gtrends] {seed}: {e}", file=sys.stderr)
    seen, uniq = set(), []
    for i in out:
        if i["id"] not in seen:
            seen.add(i["id"]); uniq.append(i)
    return uniq[:50]


def safe(name: str, fn) -> list[dict]:
    """Run a source, record an honest status, never let it sink the others."""
    try:
        items = fn() or []
        STATUS[name] = {
            "count": len(items),
            "ok": True,
            "note": "ok" if items else "ran but returned no items",
        }
        return items
    except Exception as e:
        STATUS[name] = {"count": 0, "ok": False, "note": f"{type(e).__name__}: {e}"}
        print(f"[{name}] FAILED:\n{traceback.format_exc()}", file=sys.stderr)
        return []


def main() -> None:
    social = {"tiktok": [], "instagram": []}
    if os.path.exists("social.json"):
        try:
            social = json.load(open("social.json"))
        except Exception as e:
            print(f"[social.json] {e}", file=sys.stderr)

    tiktok_browser = social.get("tiktok", []) or []
    instagram = social.get("instagram", []) or []

    # TikTok: try the official Research API first (stable, if your app is
    # approved); otherwise fall back to the Mac browser scraper's social.json.
    tiktok = tiktok_browser
    tt_note = "from Mac browser scraper" if tiktok_browser else "no items yet (run the Mac scraper)"
    try:
        api_tt = scrape_tiktok_api()
        if api_tt:
            tiktok, tt_note = api_tt, "from official TikTok Research API"
    except Exception as e:
        msg = str(e)[:120]
        print(f"[tiktok] official API unavailable: {msg}", file=sys.stderr)
        tt_note = (f"official API unavailable; using Mac browser scraper ({msg})"
                   if tiktok_browser else
                   f"official API unavailable ({msg}); Mac scraper has no items yet")

    feed = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "tiktok":        tiktok,
        "instagram":     instagram,
        "reddit":        safe("reddit", scrape_reddit),
        "youtube":       safe("youtube", scrape_youtube),
        "modrinth":      safe("modrinth", scrape_modrinth),
        "google_trends": safe("google_trends", scrape_google_trends),
    }

    # TikTok / IG are produced by the Node step; report their status honestly too.
    STATUS["tiktok"] = {
        "count": len(tiktok), "ok": bool(tiktok), "note": tt_note,
    }
    STATUS["instagram"] = {
        "count": len(instagram), "ok": bool(instagram),
        "note": "ok" if instagram else
                "no items yet (run mac/mac_scraper.py --login once, then mac/mac_scraper.py)",
    }
    feed["sources"] = STATUS

    with open("feed.json", "w") as f:
        json.dump(feed, f, indent=2, ensure_ascii=False)

    total = (len(tiktok) + len(instagram) + len(feed["reddit"])
             + len(feed["youtube"]) + len(feed["modrinth"]) + len(feed["google_trends"]))
    print(f"feed.json: tiktok={len(tiktok)} instagram={len(instagram)} "
          f"reddit={len(feed['reddit'])} youtube={len(feed['youtube'])} "
          f"modrinth={len(feed['modrinth'])} gtrends={len(feed['google_trends'])} total={total}")
    for name, st in STATUS.items():
        flag = "OK " if st["ok"] else "ERR"
        print(f"  [{flag}] {name}: {st['count']} — {st['note']}")


if __name__ == "__main__":
    main()
