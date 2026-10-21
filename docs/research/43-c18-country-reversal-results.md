# C18 country-equity reversal — price-source result

2026-10-02, OrangeCove; `tradingbot-ifc`. **DATA_FAIL before ranking/replay**:
EWA and EWS do not pass the frozen two-source price standard. The reversal
hypothesis remains unmeasured. Hold at idea/source preparation, allocation **$0**;
no training, selection, final or paper/live promotion.

## Fixed-universe evidence

All six Yahoo split/dividend-adjusted histories have **5,218 sessions**, from
2006-01-03 through 2026-09-30. The full registered interval is retained. No
candidate outcome was calculated while checking source returns.

| Fund | Direct Alpaca agreement | Nasdaq × Alpaca-factor agreement | Result |
|---|---:|---:|---|
| EWA | 95.92593% | **98.44683%** (39 disagreements) | Fail |
| EWC | 97.33333% | 100% (0 disagreements) | Pass |
| EWG | 98.51852% | 99.96018% (1 disagreement) | Pass |
| EWJ | 96.70370% | 100% (0 disagreements) | Pass |
| EWS | 96.62963% | **97.80964%** (55 disagreements) | Fail |
| EWU | 99.40741% (16 disagreements) | Not needed | Pass |

Agreement means absolute daily return difference ≤5 bp; at least 99% of paired
days must agree. Direct Alpaca has 2,700 paired returns and 2,517 unmatched
primary returns per fund. The Nasdaq route has 2,511 paired returns from
2016-10-04 through 2026-09-30 and 2,706 earlier unmatched returns. Each comparison
uses the same consecutive primary-session endpoints and retains every
disagreement/unmatched date. Nasdaq split-adjusted closes receive factors
derived only from Alpaca all/split-adjusted prices. No Yahoo factor enters the
reference. EWU's direct pass did not require another reference search.

Alpaca's penny-rounded adjusted prices limit factor precision. For example,
EWA's 2020-03-23/24 all-adjusted closes are 10.05/11.29 and split-adjusted closes
12.82/14.39; the resulting reference differs from Yahoo by 9.18 bp on March 24.
Rounding and differing closes may explain some discrepancies, but this does
not establish that all are harmless. The price gate was not relaxed; no factor
smoothing, primary patch, failed-fund removal or sample truncation was used.
Both Stooq attempts returned non-CSV responses; original bytes and request
metadata are retained. Discovery found paid alternatives, none invoked.
Data spend **$0**; no new source subscription, account or key.

Local `data/research/c18-country-reversal/audit.json`, SHA-256
`94fc0643d20c3b7c9940b03dd3b7874a0b8ae286812ade09fcd712ccde65fb93`,
pins **44 input files and five code dependencies**. The source-only auditor
recomputes all comparisons locally. **22 focused checks pass** (15 C18, seven
shared price checks), covering fixed-universe admission, refusal of invented
performance, the frozen cutoff, immutable evidence and idempotent failure
recording without orders/fills or a final spend. One unrelated websockets
deprecation warning. No executable C18 strategy or execution validation is claimed.

## Trials, statistics and decision

The four frozen **36/5, 36/10, 60/5 and 60/10** month-lookback / per-side-bp
training cases are all **unattempted**. Source-failure **trial 5651 / strategy
10573** was recorded after audit freeze `d49249d363c33db3380271c22e95736eb6e1a73f`.
Stored-only verification confirms 44 input/five committed code hashes, exact
trial parameters, all eight performance columns null, idea status/allocation $0,
one source trial, zero orders/fills and zero C18 final trials/spends.
Local `verification.json` SHA-256:
`e7b2054ec39ebf1cd23333a6cce65b412bd99ab187a8607511e2b8ab1bcda7bc`.
No selected winner; the canonical C18 final is
unspent. The original elapsed-time cutoff remains `2020-07-10T14:24:00Z`.

Gross/net P&L, fees/slippage, trades/fills, marked drawdown, years/regimes,
exposure, turnover, settlement delays, selection counts, ending holdings,
equal-weight six-country/SPY/cash benchmarks and luck p-value are **null /
unmeasured**. Zero orders/fills in a source trial is an audit fact, not a measured
zero-trade strategy result. Five-year within-partition warm-up would leave a
short final trading period; overlapping monthly signals and simultaneous legs
would not be independent samples. No shortened warm-up or historical look-ahead.

**Promotion checklist:** the macro/behavioural reversal premise is allowed by
amended PRD §3, with exact entry/exit/ranking rules frozen. Profitability,
drawdown, regime stability, sample adequacy and backtest/paper/live fidelity are
unproven. No strategy reactor is admitted without accepted prices. A later
continuation must retain this failure, validate original monthly indexing/ties,
settled cash, shared risk/ledger and single-use final admission before outcomes.

**What could blow up this account?** Currency shocks, geopolitical restrictions,
country/sector concentration and value traps can overwhelm reversal. US ETF
opens can gap while underlying exchanges are closed. Adverse selection and
spreads can exceed fixed costs; prediction-market maker safeguards do not prove
ETF fills. The $140 slot and risk vetoes do not guarantee exit prices.

Alpaca/feed/Mac dependence remains, including accepted no-dead-man and
no-startup-reconciliation risks. Eventual keys must prohibit withdrawals.
External bytes are data, never instructions; archived hashes and local audits
support reproducibility but contradictory prices prevent an admitted replay.
Global-equity, currency and commodity-exporter exposure may overlap other sleeves
and concentrate losses under the daily halt. This fixed surviving six-fund
universe has survivorship and country-composition bias; no diversification or
independent-discovery claim is established by the source exercise.

PRD §6/§9 remain unchanged: −40% allocation kill, −$50 global daily halt, maximum
$140 ETF slot, 30-second stale-data halt and five API errors/minute halt. No
capital, venues, accounts, keys, subscriptions, public posts or real orders.
**Hold at source preparation, actual $0.** Close the bead as the permitted scoped
price failure; preserve all original variants and the unused final for any
properly sourced continuation.
