#!/usr/bin/env python3
"""
Radar health check (runs in GitHub Actions on a schedule).

Reads feed.json and decides whether the radar has regressed. Writes a short
health_report.md and sets a GitHub Actions output `status=ok|regression`. The
workflow opens a single GitHub issue when status is regression.

Rules:
  - If a source's note says its key/credential isn't set, the owner just hasn't
    finished setup — that's NOT a regression, it's skipped.
  - Regression if: feed.json is missing/unparseable; or generated_at is older
    than STALE_HOURS; or a CONFIGURED api source (reddit/youtube) is failing or
    empty.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

STALE_HOURS = 48
NOT_CONFIGURED_HINTS = ("not set", "api key", "client_id", "client_secret", "credential")


def _set_output(status: str) -> None:
    out = os.getenv("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as fh:
            fh.write(f"status={status}\n")
    print(f"status={status}")


def _configured(src: dict | None) -> bool:
    note = ((src or {}).get("note") or "").lower()
    return not any(h in note for h in NOT_CONFIGURED_HINTS)


def main() -> None:
    problems: list[str] = []

    try:
        feed = json.load(open("feed.json"))
    except (FileNotFoundError, json.JSONDecodeError) as e:
        report = f"- **feed.json unreadable**: {type(e).__name__}: {e}"
        open("health_report.md", "w").write("### Radar health\n\n" + report + "\n")
        _set_output("regression")
        return

    sources = feed.get("sources", {}) or {}
    gen = feed.get("generated_at", "")

    # staleness
    try:
        ts = datetime.fromisoformat(gen.replace("Z", "+00:00"))
        age_h = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
        if age_h > STALE_HOURS:
            problems.append(f"- **feed is stale**: last updated `{gen}` "
                            f"(~{age_h:.0f}h ago, threshold {STALE_HOURS}h). "
                            "The scheduled run/push may have stopped.")
    except (ValueError, AttributeError):
        problems.append(f"- **feed has no valid `generated_at`** (`{gen!r}`).")

    # configured api sources that are failing/empty
    for name in ("reddit", "youtube"):
        src = sources.get(name)
        if src is None:
            continue
        if _configured(src) and (not src.get("ok") or src.get("count", 0) == 0):
            problems.append(f"- **{name} regressed**: "
                            f"`ok={src.get('ok')} count={src.get('count')}` — "
                            f"note: {src.get('note')!r}")

    if not problems:
        open("health_report.md", "w").write("### Radar health: OK\n")
        _set_output("ok")
        return

    lines = ["### Radar health: regression detected", "",
             f"Feed `generated_at`: `{gen}`", ""]
    lines += problems
    lines += ["", "**Likely causes:** expired Reddit/YouTube key; the Mac "
              "scraper or its browser login stopped (feed goes stale); or a "
              "TikTok/IG layout change needing an extractor update. Check the "
              "`sources` block in `feed.json` and `mac/scrape.log` on the Mac."]
    open("health_report.md", "w").write("\n".join(lines) + "\n")
    _set_output("regression")


if __name__ == "__main__":
    main()
