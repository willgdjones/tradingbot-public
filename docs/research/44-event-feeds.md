# J1–J4 event feeds

2026-10-02; `tradingbot-96t`; NavyLantern. Read-only infrastructure, not a
strategy trial or an alpha result. No model calls, orders, new keys or data fees.

## Source contract

| Feed | Free source | Captured meaning |
|---|---|---|
| News | [Alpaca news API](https://docs.alpaca.markets/us/v1.1/reference/news-3), existing paper credentials | Last 24 hours for the shared 40-symbol universe; headline only, creation/update timestamps and article ID. No article links followed. |
| CPI and jobs | [BLS monthly release lists](https://www.bls.gov/schedule/2026/10_sched_list.htm) | Current and next month, explicitly published Eastern times. The ICS URL returned 403 in the source probe; monthly lists were accessible. |
| GDP | [BEA machine-readable schedule](https://apps.bea.gov/API/signup/release_dates.json), linked from [BEA's calendar page](https://www.bea.gov/news/schedule/icalendar) | Explicit timezone-aware GDP dates. Its ICS feed omitted current GDP dates in the probe; the JSON includes them. |
| FOMC | [Fed calendar](https://www.federalreserve.gov/newsevents/calendar.htm) and its [public JSON](https://www.federalreserve.gov/json/calendar.json) | Explicit decision, minutes and press-conference times; no assumed 14:00 fallback. |
| Earnings | [Nasdaq earnings calendar](https://www.nasdaq.com/market-activity/earnings) public dated API | Today through 45 days ahead, restricted to the universe's stocks. Dates are estimates. Before-open/after-close/unknown is retained; no exact time is invented. ETFs are not applicable. |

Alpaca entitlement errors remain unavailable; no subscription upgrade or paid
fallback. Monid discovery returned paid alternatives, which were not used.
Calendar parsing is strict: wrong dates, missing target releases, unexpected
formats or incomplete pagination fail the capture.

## Point-in-time and consumer API

`tradingbot.data.event_feeds.events_asof(session, symbol, at)` returns:

- `news`: status, `untrusted: true`, at most five headlines of 400 characters,
  article IDs, symbols, source creation/update times and `known_at`.
- `macro`: status, the next known event and minutes until it. The numeric field
  is null if any required calendar snapshot is unavailable or stale.
- `earnings`: scheduled estimate, unknown, unavailable or not applicable;
  a known candidate date and numeric days only with complete fresh coverage.
- `receipts`: exact source/scope/observation/digest references for reproducing
  the decision input. Unknown never means no upcoming event risk.
- `collection_halted`: durable rolling error status using the unchanged PRD
  five-errors/60-seconds constants. While active, collection stops and all
  applicable feature statuses are unavailable.

Every fetch produces an append-only PostgreSQL `event_feed_snapshots` row,
including failures. Source response bytes are SHA-256 addressed under
`data/forward/events/raw/`; URLs, nonsecret request parameters and receipt times
are in the database snapshot. DB triggers refuse updates/deletes. A query sees
only snapshots observed **strictly before** its decision time. Unchanged news
retains its first observation time; an edit gets a new time. Later corrections,
removals and outages cannot rewrite what an earlier decision saw. A failed
latest fetch supersedes the last healthy fetch; there is no stale-good fallback.

News is untrusted quoted input, never instructions. The state builder must keep
it separate from system instructions and numeric state; code still owns all
actions, symbols, sizing and risk vetoes. Calendar collection times describe
when *this system* knew a schedule, not its original public announcement date.

## Operation and validation

`uv run python -m tradingbot.data.event_feeds --once` captures due feeds once;
omit `--once` for the recorder. `--once --refresh` explicitly refreshes all
scopes after a source fix, preserving earlier failures. A PostgreSQL advisory lock prevents duplicate
recorders. News polls at 60 seconds (120-second collection-health TTL), calendars
at six hours (26-hour TTL); failed calendars retry hourly. These are feed
coverage checks, not a relaxation of the unchanged 30-second execution quote
limit. At most 20 news pages and 4 MB per response; five failed sources stop a
cycle, and the rolling halt survives process restarts. News is also refreshed
during a slow calendar sweep. Archive plus database storage uses the existing combined disk budget.
Transport permits read-only GETs, has finite timeouts and no automatic retry.

Validation: 28 focused tests against isolated PostgreSQL schemas,
including the actual migration and immutability trigger, timestamp boundaries,
edits/removals, DST, missing dates, stale/failed feeds, bounded untrusted text,
pagination, secret-safe incident handling, archive tampering and GET-only
transport, slow calendar sweeps and the durable rolling error halt. Another
43 IEX and shared paper-cost checks pass (71 unique focused checks total).

Migration `eventfeed01` applied with a clean Alembic schema check. Initial
read-only capture verified 110 headlines, two BLS releases in each of October
and November, three GDP releases, seven FOMC events and all 46 earnings dates
through November 16 (16 dated stock events). Nasdaq required the same
browser-compatible header as the repo's existing research client; five earlier
failed captures remain in history and were superseded by successful captures.
The recorder uses the existing tmux services window via `ops/event_feeds.sh`.
Running-service verification found **51/51 latest source scopes healthy** and
verified all 53 referenced raw-body hashes. All 40 symbols had healthy news and
macro context; earnings were 20 ETFs not applicable, 16 stock estimates and
four unknown dates. The existing $140 paper book and TOM strategy remained the
only active paper allocation. No event-feed operation submitted an order.
