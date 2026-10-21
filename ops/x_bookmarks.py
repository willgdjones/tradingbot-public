#!/usr/bin/env python3
"""Pull the owner's X bookmarks (via browser-harness + their logged-in Chrome)
and append unseen ones to docs/strategy-intake/bookmarks.jsonl as status "new".

The owner bookmarks strategies and ideas on X for us to investigate; each new
entry is then evaluated through docs/strategy-intake/README.md and marked done.
Read-only: never likes, reposts, replies or un-bookmarks anything.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LEDGER = REPO / "docs" / "strategy-intake" / "bookmarks.jsonl"

SCRAPE = r'''
import json
tabs = [t for t in list_tabs() if "x.com/i/bookmarks" in t.get("url", "") or "x.com/i/history" in t.get("url", "")]
if tabs:
    switch_tab(tabs[0]["targetId"] if "targetId" in tabs[0] else tabs[0].get("id"))
    goto_url("https://x.com/i/bookmarks")
else:
    new_tab("https://x.com/i/bookmarks")
wait_for_load(); wait(4)
seen = {}
cdp("Emulation.setFocusEmulationEnabled", enabled=True)
try:
  for _ in range(SCROLLS):
      rows = js("""(() => Array.from(document.querySelectorAll('article')).map(a => {
        const u = a.querySelector('a[href*="/status/"] time')?.closest('a');
        const t = a.querySelector('[data-testid="tweetText"]');
        const n = a.querySelector('[data-testid="User-Name"]');
        return {url: u ? u.href : null, author: n ? (n.innerText.split('\\n').find(s => s.startsWith('@')) || null) : null,
                text: t ? t.innerText : ''};
      }))()""") or []
      for r in rows:
          if r.get("url"):
              seen.setdefault(r["url"], r)
      scroll(0, 2500); wait(2)
finally:
  cdp("Emulation.setFocusEmulationEnabled", enabled=False)
print("BOOKMARKS_JSON=" + json.dumps(list(seen.values())))
'''


def main(scrolls: int = 6) -> None:
    out = subprocess.run(["browser-harness"], input=SCRAPE.replace("SCROLLS", str(scrolls)),
                         capture_output=True, text=True, timeout=300)
    line = next((l for l in out.stdout.splitlines() if l.startswith("BOOKMARKS_JSON=")), None)
    if line is None:
        sys.exit(f"bookmark scrape failed: {out.stderr[-500:]}")
    rows = json.loads(line.split("=", 1)[1])

    known = set()
    if LEDGER.exists():
        known = {json.loads(l)["url"] for l in LEDGER.read_text().splitlines() if l.strip()}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    new = [r for r in rows if r["url"] not in known]
    with LEDGER.open("a") as f:
        for r in new:
            f.write(json.dumps({"url": r["url"], "author": r.get("author"), "text": r.get("text", "")[:2000],
                                "fetched_at": now, "status": "new"}) + "\n")
    print(json.dumps({"scraped": len(rows), "new": len(new)}))


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 6)
