#!/usr/bin/env python3
"""
Social radar orchestrator (runs on GitHub Actions).

Merges four sources into feed.json that the Odysseus bot ingests:
  - TikTok + Instagram : produced by scrape_social.js (Node, run BEFORE this) -> social.json
  - Reddit            : YARS (datavorous/yars) — scrapes Reddit .json, no creds
  - Google Trends     : pytrends

Every source is best-effort and isolated in try/except, so one breaking doesn't
sink the others. Each item carries a stable `id` so the bot only pings new trends.

Feed shape:
{
  "generated_at": "<ISO8601 Z>",
  "tiktok":        [...], "instagram": [...],
  "reddit":        [{"id","title","url","score","sub"}, ...],
  "google_trends": [{"id","query","value"}, ...]
}

Env: GEO (default US), REDDIT_SUBS (comma list).
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import traceback
from datetime import datetime, timezone

# Make the vendored ./yars package importable regardless of cwd.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

GEO = os.getenv("GEO", "US")


def _sid(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]


# ── Reddit via YARS ───────────────────────────────────────────────────────────
def scrape_reddit() -> list[dict]:
    try:
        from yars.yars import YARS          # installed-package layout
    except Exception:
        from yars import YARS               # flat layout fallback
    miner = YARS()
    subs = [s.strip() for s in os.getenv(
        "REDDIT_SUBS", "Minecraft,MinecraftMemes,youtubeshorts").split(",") if s.strip()]
    out: list[dict] = []
    for sub in subs:
        try:
            for p in miner.fetch_subreddit_posts(sub, limit=12, category="hot"):
                score = p.get("score", 0) or 0
                if score < 500:
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
            print(f"[reddit] {sub}: {e}", file=sys.stderr)
    out.sort(key=lambda x: x["score"], reverse=True)
    return out[:10]


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
            for _, row in rising.head(10).iterrows():
                q = str(row["query"])
                out.append({"id": _sid("gt", q), "query": q, "value": f"+{row['value']}%"})
        except Exception as e:
            print(f"[gtrends] {seed}: {e}", file=sys.stderr)
    seen, uniq = set(), []
    for i in out:
        if i["id"] not in seen:
            seen.add(i["id"]); uniq.append(i)
    return uniq[:12]


def safe(fn) -> list[dict]:
    try:
        return fn() or []
    except Exception:
        print(f"[{fn.__name__}] FAILED:\n{traceback.format_exc()}", file=sys.stderr)
        return []


def main() -> None:
    social = {"tiktok": [], "instagram": []}
    if os.path.exists("social.json"):
        try:
            social = json.load(open("social.json"))
        except Exception as e:
            print(f"[social.json] {e}", file=sys.stderr)

    feed = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "tiktok":        social.get("tiktok", []),
        "instagram":     social.get("instagram", []),
        "reddit":        safe(scrape_reddit),
        "google_trends": safe(scrape_google_trends),
    }
    with open("feed.json", "w") as f:
        json.dump(feed, f, indent=2, ensure_ascii=False)
    print(f"feed.json: tiktok={len(feed['tiktok'])} instagram={len(feed['instagram'])} "
          f"reddit={len(feed['reddit'])} gtrends={len(feed['google_trends'])}")


if __name__ == "__main__":
    main()
