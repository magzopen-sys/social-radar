#!/usr/bin/env python3
"""
Social radar orchestrator (runs on GitHub Actions).

Merges four sources into feed.json that the Odysseus bot ingests:
  - TikTok + Instagram : produced by scrape_social.js (Node, run BEFORE this) -> social.json
  - Reddit            : official Reddit API (OAuth app-only) — reliable on CI IPs
  - Google Trends     : pytrends (best-effort; Google rate-limits CI IPs)

Every source is best-effort and isolated, so one breaking doesn't sink the
others. Each item carries a stable `id` so the bot only pings new trends.
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
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone

import requests

# Make the vendored ./yars package importable regardless of cwd (anon fallback).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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
        return _reddit_api(cid, secret, subs, min_score)

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
            print(f"[reddit] HTTP {resp.status_code} on {url} — retry in {wait}s",
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
            for p in miner.fetch_subreddit_posts(sub, limit=50, category="hot"):
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

    tiktok = social.get("tiktok", []) or []
    instagram = social.get("instagram", []) or []

    feed = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "tiktok":        tiktok,
        "instagram":     instagram,
        "reddit":        safe("reddit", scrape_reddit),
        "google_trends": safe("google_trends", scrape_google_trends),
    }

    # TikTok / IG are produced by the Node step; report their status honestly too.
    STATUS["tiktok"] = {
        "count": len(tiktok), "ok": bool(tiktok),
        "note": "ok" if tiktok else "no items (needs TIKTOK_SESSION; library is unmaintained)",
    }
    STATUS["instagram"] = {
        "count": len(instagram), "ok": bool(instagram),
        "note": "ok" if instagram else "no items (needs IG_SESSION; library is unmaintained)",
    }
    feed["sources"] = STATUS

    with open("feed.json", "w") as f:
        json.dump(feed, f, indent=2, ensure_ascii=False)

    total = len(tiktok) + len(instagram) + len(feed["reddit"]) + len(feed["google_trends"])
    print(f"feed.json: tiktok={len(tiktok)} instagram={len(instagram)} "
          f"reddit={len(feed['reddit'])} gtrends={len(feed['google_trends'])} total={total}")
    for name, st in STATUS.items():
        flag = "OK " if st["ok"] else "ERR"
        print(f"  [{flag}] {name}: {st['count']} — {st['note']}")


if __name__ == "__main__":
    main()
