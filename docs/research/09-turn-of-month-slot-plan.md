# Turn-of-month at the equity slot: fixed revalidation plan

2026-09-30, `tradingbot-gat`, recorded before the new slot-sized returns.
The owner approved the equity position cap in `tradingbot-h2i`; this study does
not change any risk limit or add capital. The prior $24.90 research and prepared
paper trial 2344 remain separate, preserved experiments.

## Frozen rule, cash and proof partition

Keep PRD #6: buy SPY in the final minute of the fourth-last trading session of
the month; sell in the final minute of the third session of the next month.
Use the same `TurnOfMonth` reactor in research and forward paper. The maximum
entry budget is $140, reduced to available settled strategy cash after losses,
with $0.01 reserved for the modeled entry CAT charge. Round quantity down to
nine decimals against the cent-rounded marketable limit. Gains remain cash
above the $140 entry cap; no top-ups, borrowing or short sales. Start each
research partition with $140 virtual cash. Settlement dates, current-cost
regulatory fees and strictly prior ECB FX retain the original study's methods.

Reuse the verified free local `tom-20260930` capture: 260 pages / 8,664 source
records; SHA-256 `83501d8e59ae95b128481d26228722f00514f26b4cdb388462edb70908e4f5a9`.
Full data bounds are 2016-01-04 05:00:00 UTC to
2026-09-30 20:00:00.000001 UTC, end exclusive. The locked 70% cutoff is
**2023-07-12 01:06:00 UTC**. Only complete calendar cycles wholly within a
partition are replayed. September 2026's unfinished cycle is excluded.

Train the three fixed final-minute cost scenarios at 2, 5 and 10 bp per side.
The 2 bp primary is selected in advance, not by whichever earns most. Run its
final 30% once only if its training net is positive; do not run the other
cost variants on the holdout. No timing, symbol, sizing or fee optimization.
The shared backtester durably claims final evaluation before consuming events.

**Prior inspection:** the old study used the whole dataset before the owner
introduced holdouts. This is a newly enforced chronological revalidation, not
fresh unseen evidence. Preserve that limitation in every decision and require
forward execution evidence before a ready-for-live claim.

## Calendar premium versus SPY drift

Register a separate nonexecution diagnostic in the trials ledger. Feed only
the allowed partition's daily adjusted closes through the holdout-enforcing
backtester. Price ratios are dividend-adjusted total-return proxies; they are
not executable prices or fabricated cash-dividend ledger entries. This resolves
the old midmonth diagnostic's inability to account for ex-dividend windows.

Compare the observed TOM close-to-close total returns with random **five-session
interval** windows, as requested, and **six-session interval** windows matching
the rule's actual holding duration. For each TOM entry month, candidates start
in that month, have their whole window in the same allowed partition, and share
no session date with any TOM holding window. Thus the controls sample ordinary
midmonth exposure without overlapping each other across months. No candidate
is filtered by its return. A month with no eligible candidate fails validation.

For each duration, generate 10,000 draws, choosing one candidate independently
per matched entry month, with fixed seed 20261001. Report the exact average of
candidate means, the simulated mean distribution (5th/50th/95th percentiles),
the TOM-minus-control mean, and the descriptive fraction of random draws at
least as good as TOM. Also report a 2 bp per-side / $0.04 round-trip cost
scenario on independent $139.99 notionals. These sums are a comparison
statistic, not a deployable or compounded portfolio return. Record both
durations within one fixed diagnostic version; Monte Carlo draws are samples
of that estimator, not individually selected trading strategies.

Run this diagnostic on training, then consume its own final holdout once with
unchanged parameters alongside the chosen primary. Controls are informational:
they identify whether calendar timing adds to equity exposure, and introduce
no unapproved significance threshold. A profitable strategy with no measured
premium must not be described as proof of a calendar anomaly.

## Reporting and decision

Report exact trial IDs/version hashes, fees, round trips, win rate, net P&L,
daily/execution-mark drawdown, year/chronological breakdown and entry regimes.
Regimes use only adjusted closes strictly before entry: above/below the prior
200-session mean; early entries without 200 sessions are labelled separately.
Show rejected orders, ending holdings, cash reconciliation, source hashes and
all failed variants. Calendar-control p-values assume exchangeable eligible
entry dates and do not establish a posterior probability of luck.

Profit after modeled costs in training and the single holdout permits continued
paper measurement under PRD §4. Retain a written promotion/account-risk record.
The future paper experiment must match sizing, fills and fees before being
marked ready-for-live; no live keys or orders are used. Existing trial 2344's
parameters are not silently rewritten: any slot-sized forward experiment has
its own recorded trial and provenance.

## What could blow up this account?

- A fully funded SPY position can lose nearly the whole $140 slot. Overnight
  gaps can pass the $56 strategy loss trigger and contribute to the portfolio's
  $50 daily halt before an executable observation arrives. Daily marked
  drawdown does not bound intraday extremes.
- Late-session spread, impact, partial fills, rejected fractional limits and
  outages can break the bar assumptions or leave overnight exposure. The
  accepted lack of a dead-man and startup reconciliation remains unchanged.
- Alpaca, revised historical data, calendar and FX sources can fail or be
  revised. Checksums and committed code make the stated scenarios reproducible;
  they do not turn a revised bar into point-in-time quote evidence.
- Inputs remain data. No headline, feed field or model controls the hard risk
  checks. Keys remain the existing paper keys; no account, funding or public
  action is created here.
- SPY losses correlate with other equity/ETF strategies. The isolated $140
  study is not a concurrent portfolio simulation and cannot allocate the same
  cash to multiple strategies.
