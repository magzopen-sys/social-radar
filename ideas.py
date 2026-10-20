#!/usr/bin/env python3
"""
Turn feed.json into content ideas.

Reads the radar's feed.json and surfaces themes that are trending across MORE
THAN ONE platform (the strongest signal for a creator), ranked, each with the
hottest real example to riff on. Writes ideas.md and prints a summary.

    python ideas.py                 # uses ./feed.json
    python ideas.py path/to/feed.json

No API key needed — it's a keyword/co-occurrence analysis, not an LLM call.
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict

# Words that are the niche itself or filler — kept out of "themes".
BASE = {"minecraft", "mc", "mcyt", "shorts", "short", "video", "videos",
        "youtube", "yt", "reddit", "tiktok", "instagram", "reel", "reels",
        "gameplay", "gaming", "game"}
STOP = {"the", "and", "for", "you", "your", "with", "this", "that", "but",
        "are", "was", "how", "why", "what", "when", "all", "new", "get", "got",
        "out", "not", "they", "his", "her", "its", "has", "had", "can", "will",
        "just", "like", "from", "have", "who", "one", "two", "best", "every",
        "ever", "guys", "about", "into", "made", "make", "making", "day", "part"}

PLATFORMS = ["youtube", "tiktok", "instagram", "reddit", "modrinth", "google_trends"]


def _text(item: dict) -> str:
    return " ".join(str(item.get(k, "")) for k in ("title", "query"))


def _words(text: str) -> set[str]:
    toks = re.findall(r"[a-z0-9']+", text.lower())
    return {t for t in toks if len(t) >= 3 and t not in STOP and t not in BASE}


def _engagement(item: dict) -> int:
    return int(item.get("views") or item.get("score")
               or item.get("downloads") or item.get("follows") or 0)


def _title(item: dict) -> str:
    return item.get("title") or item.get("query") or "(untitled)"


def _link(item: dict) -> str:
    """Markdown link if there's a url, else just the title text."""
    t = _title(item)
    url = item.get("url")
    return f"[{t}]({url})" if url else t


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else "feed.json"
    try:
        feed = json.load(open(path))
    except FileNotFoundError:
        sys.exit(f"{path} not found — run the scraper first.")

    # keyword -> {platform -> [items]}
    themes: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for plat in PLATFORMS:
        for item in feed.get(plat, []) or []:
            for w in _words(_text(item)):
                themes[w][plat].append(item)

    ranked = sorted(
        themes.items(),
        key=lambda kv: (len(kv[1]), sum(len(v) for v in kv[1].values())),
        reverse=True,
    )
    cross = [(w, plats) for w, plats in ranked if len(plats) >= 2][:15]

    lines: list[str] = ["# Content ideas from the radar",
                        f"_source: {path} · generated {feed.get('generated_at', '?')}_", ""]

    if not cross:
        lines += ["No cross-platform themes yet — the feed may be empty or thin. "
                  "Run the scraper with keys set, then re-run `python ideas.py`."]
    else:
        lines.append("## Trending across multiple platforms (strongest signals)\n")
        for w, plats in cross:
            where = ", ".join(f"{p}×{len(items)}" for p, items in plats.items())
            lines.append(f"### {w}  \n_on {len(plats)} platforms: {where}_\n")
            # hottest example across the platforms it appears on
            best = max((i for items in plats.values() for i in items),
                       key=_engagement, default=None)
            if best:
                eng = _engagement(best)
                tag = f" ({eng:,} views/score)" if eng else ""
                lines.append(f"- hottest: {_link(best)}{tag}")
            lines.append(f"- angle starters: "
                         f"\"{w} but it gets harder every minute\" · "
                         f"\"I survived 100 days of {w}\" · "
                         f"\"the {w} trend everyone's copying\"")
            lines.append("")

    # Hottest individual items overall, any platform.
    allitems = [(p, i) for p in PLATFORMS for i in (feed.get(p, []) or [])]
    allitems.sort(key=lambda pi: _engagement(pi[1]), reverse=True)
    if allitems:
        lines.append("## Hottest individual posts right now\n")
        for p, i in allitems[:10]:
            eng = _engagement(i)
            tag = f" — {eng:,}" if eng else ""
            lines.append(f"- **{p}**: {_link(i)}{tag}")

    out = "ideas.md"
    open(out, "w").write("\n".join(lines) + "\n")
    print(f"Wrote {out}: {len(cross)} cross-platform themes, "
          f"{len(allitems)} items total.")
    for w, plats in cross[:8]:
        print(f"  • {w} — {len(plats)} platforms")


if __name__ == "__main__":
    main()
