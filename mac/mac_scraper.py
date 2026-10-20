#!/usr/bin/env python3
"""
Mac-side TikTok + Instagram scraper for social-radar.

Runs on YOUR Mac, in YOUR logged-in browser (real session + home IP) — the only
reliable way to get TikTok/IG data, since GitHub's datacenter IPs are blocked.
Writes ../social.json in the shape scrape.py expects, and (with --push) commits
and pushes it so the hourly GitHub Action merges it with Reddit + YouTube.

It uses a PERSISTENT browser profile (mac/.mac-profile, git-ignored), so you log
in once and the session sticks. Data is captured by watching the JSON the pages
themselves load (network interception), then walked heuristically — more robust
to layout changes than scraping the DOM.

One-time setup:
    cd mac
    python3 -m venv .venv && source .venv/bin/activate
    pip install -r requirements-mac.txt
    python -m playwright install chromium
    python mac_scraper.py --login      # browser opens: log into TikTok & IG, then press Enter

Daily run:
    python mac_scraper.py              # scrape -> ../social.json
    python mac_scraper.py --push       # also git add/commit/push social.json
    python mac_scraper.py --debug      # save screenshots + raw JSON to mac/debug/

Config (env):
    TT_QUERIES   comma list for TikTok search (default minecraft set)
    IG_TAGS      comma list of Instagram hashtags (default minecraft set)
    LIMIT        max items per platform (default 50)
    HEADLESS=1   run with no visible window (more bot-detectable; default off)
    SCROLLS      scroll passes per page (default 8)

NOTE: scraping TikTok/IG is against their ToS. Keep it low-frequency (daily) and
consider using a secondary/throwaway login rather than your main creator account.
This script is for personal trend monitoring of your own niche.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.exit("Playwright not installed. Run: pip install -r requirements-mac.txt "
             "&& python -m playwright install chromium")

ROOT = Path(__file__).resolve().parent.parent          # repo root
HERE = Path(__file__).resolve().parent                 # mac/
PROFILE = HERE / ".mac-profile"
DEBUG_DIR = HERE / "debug"
SOCIAL_JSON = ROOT / "social.json"

LIMIT = int(os.getenv("LIMIT", "50"))
SCROLLS = int(os.getenv("SCROLLS", "8"))
HEADLESS = os.getenv("HEADLESS", "") not in ("", "0", "false", "False")
# Real Google Chrome passes TikTok/IG login checks far better than Playwright's
# bundled Chromium. Set BROWSER_CHANNEL="" to force the bundled one.
CHANNEL = os.getenv("BROWSER_CHANNEL", "chrome")

def _env_list(name: str, default: str, strip: str = "") -> list[str]:
    return [x.strip().lstrip(strip) for x in os.getenv(name, default).split(",") if x.strip()]


# TikTok hashtag pages usually load logged-out; search pages require a login.
TT_TAGS = _env_list("TT_TAGS", "minecraft,minecraftbuilds,minecraftmemes", "#")
TT_QUERIES = _env_list("TT_QUERIES", "minecraft,minecraft build,minecraft shorts")
# Instagram account Reels tabs load reliably; hashtag pages sometimes show
# "Something went wrong" but often still return a few posts, so both are on.
IG_ACCOUNTS = _env_list("IG_ACCOUNTS", "minecraft", "@")
IG_TAGS = _env_list("IG_TAGS", "minecraft,minecraftbuilds,minecraftmemes", "#")


# ── heuristic extractors: walk any JSON and pick out video/post objects ───────
def _walk_tiktok(node, out: dict):
    if isinstance(node, dict):
        if "id" in node and "desc" in node and ("author" in node or "authorId" in node):
            vid = str(node.get("id"))
            a = node.get("author")
            author = (a.get("uniqueId") or a.get("nickname") or "") if isinstance(a, dict) \
                else (a if isinstance(a, str) else "")
            stats = node.get("stats") or node.get("statsV2") or {}
            views = stats.get("playCount") or stats.get("playCountStr") or node.get("playCount")
            if vid and vid.isdigit():
                out[vid] = {
                    "id": "tt" + vid,
                    "title": (node.get("desc") or "(tiktok)")[:90],
                    "url": f"https://www.tiktok.com/@{author}/video/{vid}" if author
                           else f"https://www.tiktok.com/video/{vid}",
                    "author": author,
                    "views": _as_int(views),
                    "tag": "",
                }
        for v in node.values():
            _walk_tiktok(v, out)
    elif isinstance(node, list):
        for v in node:
            _walk_tiktok(v, out)


def _walk_instagram(node, out: dict):
    if isinstance(node, dict):
        sc = node.get("shortcode") or node.get("code")
        # Error objects also carry a "code" (e.g. 400); only accept real shortcodes.
        if isinstance(sc, str) and re.fullmatch(r"[A-Za-z0-9_-]{6,20}", sc):
            cap = ""
            edges = (node.get("edge_media_to_caption") or {}).get("edges") or []
            if edges:
                cap = ((edges[0] or {}).get("node") or {}).get("text", "")
            if not cap and isinstance(node.get("caption"), dict):
                cap = node["caption"].get("text", "")
            if not cap:
                cap = node.get("accessibility_caption") or ""
            owner = node.get("owner") or node.get("user") or {}
            views = (node.get("video_view_count") or node.get("play_count")
                     or node.get("view_count")
                     or (node.get("edge_media_preview_like") or {}).get("count"))
            out[str(sc)] = {
                "id": "ig" + str(sc),
                "title": (cap or "(reel)")[:90],
                "url": f"https://www.instagram.com/p/{sc}/",
                "author": owner.get("username", "") if isinstance(owner, dict) else "",
                "views": _as_int(views),
            }
        for v in node.values():
            _walk_instagram(v, out)
    elif isinstance(node, list):
        for v in node:
            _walk_instagram(v, out)


def _as_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# ── scraping ──────────────────────────────────────────────────────────────────
def _collect(page, walker, found: dict, debug_name: str | None):
    """Attach a response listener that feeds JSON bodies into `walker`."""
    captures = []

    def on_response(resp):
        try:
            ct = (resp.headers or {}).get("content-type", "")
            if "json" not in ct:
                return
            data = resp.json()
        except Exception:
            return
        try:
            walker(data, found)
            if debug_name:
                captures.append({"url": resp.url, "data": data})
        except Exception:
            pass

    page.on("response", on_response)
    return captures


def _scroll(page, found: dict, label: str):
    stalled = 0
    for i in range(SCROLLS):
        if len(found) >= LIMIT:
            break
        before = len(found)
        try:
            page.keyboard.press("Escape")          # dismiss login/cookie popups
            page.mouse.move(640, 450)              # wheel only scrolls under the mouse
            page.mouse.wheel(0, 3000)
            page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
        except Exception:
            pass
        page.wait_for_timeout(1500)
        print(f"    [{label}] scroll {i + 1}/{SCROLLS}: {len(found)} items so far", file=sys.stderr)
        stalled = stalled + 1 if len(found) == before else 0
        if stalled >= 3:                           # page stopped loading more; move on
            break


def _visit_all(ctx, targets: list[tuple[str, str]], walker, platform: str,
               debug: bool) -> list[dict]:
    """Open each (label, url), capture page JSON with `walker`, rank by views."""
    found: dict = {}
    for label, url in targets:
        page = ctx.new_page()
        name = f"{platform}_{label}".replace(" ", "_").replace("/", "_")
        caps = _collect(page, walker, found, name if debug else None)
        print(f"  [{platform}] {url}", file=sys.stderr)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(3000)
            _scroll(page, found, f"{platform}:{label}")
        except Exception as e:
            print(f"  [{platform}] {label}: {e}", file=sys.stderr)
        if debug:
            _dump(page, caps, name)
        page.close()
        if len(found) >= LIMIT:
            break
    items = list(found.values())
    items.sort(key=lambda x: (x.get("views") or 0), reverse=True)
    return items[:LIMIT]


def scrape_tiktok(ctx, debug: bool) -> list[dict]:
    targets = [(f"tag_{t}", f"https://www.tiktok.com/tag/{t}") for t in TT_TAGS]
    targets += [(f"search_{q}", f"https://www.tiktok.com/search/video?q={q.replace(' ', '%20')}")
                for q in TT_QUERIES]
    return _visit_all(ctx, targets, _walk_tiktok, "tiktok", debug)


def scrape_instagram(ctx, debug: bool) -> list[dict]:
    targets = [(f"acct_{a}", f"https://www.instagram.com/{a}/reels/") for a in IG_ACCOUNTS]
    targets += [(f"tag_{t}", f"https://www.instagram.com/explore/tags/{t}/") for t in IG_TAGS]
    return _visit_all(ctx, targets, _walk_instagram, "instagram", debug)


def _dump(page, caps, name: str):
    DEBUG_DIR.mkdir(exist_ok=True)
    try:
        page.screenshot(path=str(DEBUG_DIR / f"{name}.png"), full_page=False)
    except Exception:
        pass
    try:
        (DEBUG_DIR / f"{name}.json").write_text(
            json.dumps(caps, ensure_ascii=False)[:5_000_000])
    except Exception:
        pass


# ── browser launch ─────────────────────────────────────────────────────────────
def _launch(pw, headless: bool):
    """Open the persistent profile in a browser that sites don't flag as a bot.

    Drops Playwright's --enable-automation flag and the AutomationControlled
    blink feature (both make TikTok/IG refuse logins), and prefers real Chrome.
    """
    kwargs = dict(
        headless=headless,
        no_viewport=True,
        ignore_default_args=["--enable-automation"],
        args=["--disable-blink-features=AutomationControlled"],
    )
    try:
        ctx = pw.chromium.launch_persistent_context(
            str(PROFILE), channel=CHANNEL or None, **kwargs)
    except Exception as e:
        print(f"Couldn't start '{CHANNEL}' ({str(e)[:120]}); "
              "using Playwright's bundled Chromium instead.", file=sys.stderr)
        ctx = pw.chromium.launch_persistent_context(str(PROFILE), **kwargs)
    ctx.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return ctx


# ── modes ──────────────────────────────────────────────────────────────────────
def do_login():
    print("Opening a browser. Log into TikTok and Instagram in the tabs, then "
          "come back here and press Enter.", file=sys.stderr)
    with sync_playwright() as pw:
        ctx = _launch(pw, headless=False)
        ctx.new_page().goto("https://www.tiktok.com/login")
        ctx.new_page().goto("https://www.instagram.com/accounts/login/")
        input("Press Enter when you have logged into BOTH...")
        ctx.close()
    print("Login profile saved to mac/.mac-profile — you can now run the scraper.",
          file=sys.stderr)


def do_scrape(debug: bool) -> dict:
    with sync_playwright() as pw:
        ctx = _launch(pw, headless=HEADLESS)
        try:
            tt = scrape_tiktok(ctx, debug)
            ig = scrape_instagram(ctx, debug)
        finally:
            ctx.close()
    data = {"tiktok": tt, "instagram": ig}
    SOCIAL_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"social.json: tiktok={len(tt)} instagram={len(ig)} -> {SOCIAL_JSON}",
          file=sys.stderr)
    if not tt and not ig:
        print("WARNING: got 0 items. You may not be logged in, or the pages "
              "changed. Re-run with --login, or --debug to inspect mac/debug/.",
              file=sys.stderr)
    return data


def do_push():
    def git(*args):
        return subprocess.run(["git", *args], cwd=str(ROOT),
                              check=True, capture_output=True, text=True)
    git("add", "social.json")
    # Nothing staged? then nothing changed; skip.
    if subprocess.run(["git", "diff", "--quiet", "--staged"], cwd=str(ROOT)).returncode == 0:
        print("social.json unchanged — nothing to push.", file=sys.stderr)
        return
    git("commit", "-m", f"social.json: {time.strftime('%FT%TZ', time.gmtime())}")
    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    for attempt in range(4):
        try:
            git("pull", "--rebase", "origin", branch)
            git("push", "origin", branch)
            print(f"Pushed social.json to {branch}.", file=sys.stderr)
            return
        except subprocess.CalledProcessError as e:
            wait = 2 ** attempt
            print(f"push attempt {attempt + 1} failed ({e.stderr.strip()[:200]}); "
                  f"retry in {wait}s", file=sys.stderr)
            time.sleep(wait)
    print("ERROR: could not push after retries.", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description="TikTok + Instagram scraper (Mac-side).")
    ap.add_argument("--login", action="store_true", help="open a browser to log in once")
    ap.add_argument("--push", action="store_true", help="git add/commit/push social.json after scraping")
    ap.add_argument("--debug", action="store_true", help="save screenshots + raw JSON to mac/debug/")
    args = ap.parse_args()

    if args.login:
        do_login()
        return
    do_scrape(args.debug)
    if args.push:
        do_push()


if __name__ == "__main__":
    main()
