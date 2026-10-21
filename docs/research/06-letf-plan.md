# End-of-day LETF flow: fixed research plan

Recorded 2026-09-30 before computing any SPY/QQQ intraday strategy returns;
`tradingbot-8v6`. Binding PRD rule: SPY/QQQ, enter at 15:30 ET in the direction
of a large daily move, exit at the close, study 2023–2026 only, alternate two
halves of the cash allocation. No dates or thresholds are selected by results.

## Cash-account implementation

The approved account cannot short. Evaluate **positive-move long entries only**
and report negative threshold crossings as unimplemented short signals. Do not
add inverse ETFs, margin, options or new instruments to imitate the bearish leg.
This is the feasible subset of #5, not a test of its complete long/short version.

Virtual cash $140, split into two $70 buckets alternating by trading-session
index, including skipped/early-close sessions. Each SPY or QQQ entry targets
$24.90, rounded down to nine decimal shares using a cent-rounded marketable
limit, within the unchanged $25 cap. Both ETFs may trigger on the same day.
Cash is debited with fees; proceeds become reusable on Alpaca's supplied
settlement date (historical T+2 or T+1 and settlement holidays). If settled
funds in the assigned half are insufficient, retain the rejected order and
skip that entry. No borrowing from the other half or cash compounding.

## Data and signal

Capture SPY and QQQ SIP daily raw/adjusted bars, official sessions/settlement
calendar and all regular-session minutes from 15:29 through the final minute,
2023-01-01 through 2026-09-30. Archives preserve exact responses and hashes.
Require both ETFs' scheduled entry/exit bars. Do not forward-fill execution.
Skip sessions closing at or before 15:30. Skip the first sample session because
its previous close would fall outside the specified sample; no 2022 backtest.

The signal is **raw price return** from the previous regular daily close to the
15:30 minute OPEN. That opening print is an explicitly assumed fresh execution
reference at 15:30; the same bar's high, low, close and the later daily return
are never used to decide entry. Live/paper can use a current quote at that time.
This is a bar proxy with unknown first-print latency and revisions, not proof
of a timestamp-perfect executable quote. Corporate actions are audited; a split
between sessions must be handled or fail validation. Cash dividends can affect
the raw daily move but not the held intraday return: report flagged ex-dates,
and do not call this raw price change an exact fund NAV/forced-flow estimate.

## Six variants, each retained in the trials ledger

| Variant | Positive daily-move threshold | Adverse bp per side | Exit proxy |
|---|---:|---:|---|
| `letf_1pct_2bp` (primary) | 1.0% | 2 | Final minute open |
| `letf_05pct_2bp` | 0.5% | 2 | Final minute open |
| `letf_15pct_2bp` | 1.5% | 2 | Final minute open |
| `letf_1pct_5bp` | 1.0% | 5 | Final minute open |
| `letf_1pct_10bp` | 1.0% | 10 | Final minute open |
| `letf_1pct_close_2bp` | 1.0% | 2 | Daily close, nonexecutable fractional-auction benchmark |

All use the same entry minute and both ETFs; no symbol/date/threshold search.
Fee policy is the already implemented September 17, 2026 Alpaca retail schedule
as a current-cost counterfactual, aggregating each fee type across SPY and QQQ
by account/day and rounding up to cents. It is not actual historical billing.
FX uses the strictly previous ECB reference date with provenance on each fill.

## Outputs and interpretation

Retain all trials including zero-trade, losing or failed variants, source/code
hashes, params, orders/fills/fees, calendar/data exclusions, negative signals,
cash-bucket rejection counts, per-symbol counts/net, yearly net, 2023–2024 and
2025–2026 subdivisions, mean net per trade, win rate, one-sided t-test p-value,
minute-marked drawdown and exposure. Correlated SPY/QQQ trades mean the ordinary
per-trade p-value is descriptive; also report a day-aggregated p-value. Neither
is an additional promotion gate or a posterior probability of luck.

Profit after costs is the owner's criterion. No profitable unseen period is
claimed from these historical subdivisions. Price continuation after large moves
is only a proxy test for the proposed forced-flow mechanism; this sample lacks
LETF assets/holdings and does not identify flows causally. Exact fills, fees and
slippage require forward observation. No broker orders or capital changes.

Sources: PRD §5; [existing structural-edge research](03-structural-edges.md);
[Alpaca bars](https://docs.alpaca.markets/us/reference/stockbars),
[data aggregation](https://docs.alpaca.markets/us/docs/market-data-faq),
[fee schedule](https://files.alpaca.markets/disclosures/library/BrokFeeSched.pdf),
[orders](https://docs.alpaca.markets/us/docs/orders-at-alpaca), and
[corporate actions](https://docs.alpaca.markets/us/reference/corporateactions-1).
