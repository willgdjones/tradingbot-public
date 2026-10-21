# #6 turn-of-month forward paper decision

2026-09-30, NavyLantern. User-directed preparation: `tradingbot-u6a`.
Historical evidence: [trials 849–853](05-turn-of-month-results.md).

## Promotion checklist

- Structural premise: periodic institutional/month-boundary flows; one fixed
  calendar rule. Buy SPY in the final minute of the fourth-last trading session;
  sell owned shares in the final minute of the third session next month.
- Primary 849: 128 completed trades, $9.221030 net after the fixed fee/slippage
  scenario, one-sided t-test p=0.0690. No new significance gate is imposed.
  Trials 850–852 are cost/timing sensitivity; 853 failed its dividend-control
  validation and is not evidence for promotion.
- Observed drawdown $4.5573 against $140 virtual allocation (3.26%), well below
  the unchanged 40% kill. Daily/execution marks do not bound intraday extremes.
- Chronological regimes: 2016–2022 net $6.27; 2023–2026 net $2.95. Both are
  positive, with negative individual years 2018, 2021, 2024 and 2025. This is
  a chronological breakdown, not a formal economic-regime classifier.
- The unchanged pure `TurnOfMonth` class supplies research and forward intents.
  Paper/live fidelity remains unproven; measuring it is the purpose of this
  paper trial. There is no live promotion or real capital allocation here.
- Existing Alpaca paper account and keys only; simulated cash budget $140,
  maximum intended SPY entry $24.90. No deposits, account reset, new venue,
  account, key, public post or §6 limit change.

## What could blow up this account?

**Tail/gap:** a funded long SPY position can lose its cost; each entry is below
$25. Overnight gaps can cross a loss threshold before an executable quote.
Partial or missed exits can leave shares beyond the intended holding window;
the runner logs an incident and requires explicit review, without inventing an
off-schedule liquidation rule. A finite calendar never adds extra entries.

**Adverse selection:** marketable fractional limits face spreads, latency and
price changes in the last minute. The historical 2 bp assumption is not a
guaranteed execution price. The runner retains the decision quote and broker
activities for comparison; a fresh second quote can cause a connector veto.
Rewards-specific passive fill/event guards are inapplicable to this taker rule.

**Counterparty/venue:** this experiment depends on Alpaca paper execution and
IEX quotes, not guaranteed live fills. Paper omits regulatory fees; the existing
fee scenario is recorded separately from broker receipts. The adapter exposes
paper orders/read-only data and has no live endpoint or withdrawal operation.
Existing key permissions are not changed. Accepted no-dead-man/no-startup-
reconciliation risks remain: orders can survive process exit. Resume polls
only explicitly owned durable order IDs. The job runs the checked-out code.

**Untrusted inputs:** calendar, quote, fill and ECB data are parsed values, not
instructions. No news, social text, LLM or discretionary price opinion produces
the signal. UTC FX availability and New York exchange sessions are explicit.

**Reproducibility:** trial 849's fixed rules and comparison parameters are
preserved. The paper trial stores its source commit, exact calendar, hash,
attempts, dated FX on every fill and broker execution IDs. Broker randomness,
future fee changes, feed differences and historical revisions limit inference.

**Correlation:** long SPY shares broad equity exposure with the LETF study.
The connector reserves holdings/pending buys and settled cash, including other
strategies, before submission. The mode-wide risk engine remains authoritative.
Review found `tradingbot-1oh`: overnight holdings currently escape daily loss
accounting. Activation waits for that repair; thresholds remain unchanged.

## Decision and schedule

Prepare primary #6 for paper with $140 simulated allocation and $24.90 entries.
Read-only official calendar verification on 2026-09-30 gives the first entry
**2026-10-27 15:59 America/New_York**, exit **2026-11-04 15:59**. The missed
September entry is not caught up. The prepared interval runs through the
2027-10-05 exit; it does not promise a year of uninterrupted operation.

Runner validation covers late/missed windows, early close, restarts, unknown
POST, partial fills/owned-share exits, residual incidents, dated FX and §6 vetoes.
Prepared **paper trial 2344**, source commit `eba9e77`, with $140 simulated cash
and the exact official future calendar. The broker account was not funded or
reset. The trial pointer is `data/forward/turn_of_month.trial` (gitignored local
state). Launchd is not loaded. The overnight-loss repair `tradingbot-1oh` is now
verified; the subsequent owner instruction in `tradingbot-gat` requires the new
locked-holdout/allocation study before continuing paper.
Validation: 52 focused tests pass after fixture isolation; the broader suite
passed 501 tests, skipped 6, and expected the three confirmed review defects.

Official sources: [Alpaca calendar](https://docs.alpaca.markets/us/v1.4.2/reference/getcalendar-1),
[Alpaca SDK](https://alpaca.markets/sdks/python/api_reference/trading/models.html),
[ECB reference rates](https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html).

## Subsequent policy update (2026-10-01)

The owner added the locked 70/30 holdout rule while this preparation was in
progress. Historical trials 849–853 predate that rule and used the whole sample;
they are **not** a passed locked-holdout result. Trial 2344 remains the explicitly
requested forward execution experiment, with no live/ready-for-live claim.
Keep its $24.90 entries fixed for comparability. Implementation of the separately
owner-approved asset-class caps is coordinator bead `tradingbot-h2i`; this task
does not enlarge the trial's entries or add funds. New strategies must follow
the updated proof requirements.

Final repair validation: 188 affected integration tests pass, with only the two
remaining PM paper/rewards review defects expected to fail; 13 dedicated daily
accounting/repro tests pass. No order was sent and no LaunchAgent was loaded.
