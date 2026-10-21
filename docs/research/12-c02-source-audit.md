# C02 sector momentum: data failure before replay

**DATA_FAIL.** Bead `tradingbot-7l3` stops at the common preregistered data
gate. No strategy return, ranking, training configuration or final holdout was
calculated. No P&L, fees, drawdown, regime result or p-value is available.

The fixed nine-fund universe remains XLB/XLE/XLF/XLI/XLK/XLP/XLU/XLV/XLY.
All nine free Yahoo chart responses were archived with exact query, bytes,
retrieval time and SHA-256. Each has 5,218 daily sessions, no null rows and no
missing/extra sessions against the archived official calendar. The source
interval remains 2006-01-01 00:00 UTC to 2026-10-01 00:00 UTC, end exclusive;
the `HoldoutSplit` boundary remains 2020-07-10 14:24 UTC. The
[machine-readable audit](12-c02-source-audit.json) binds these source hashes,
the issuer workbook, calendar evidence and fixed bounds to a dataset identity.

## Failed prerequisites

1. **Settlement calendar inconsistency.** The official Alpaca calendar says a
   2017-07-05 trade settles on 2017-07-07. That two-calendar-day interval cannot
   contain the three settlement days required by the then-standard T+3 cycle.
   The SEC records the actual T+2 transition on
   [2017-09-05](https://www.sec.gov/newsroom/press-releases/2017-163), followed by
   T+1 on [2024-05-28](https://www.sec.gov/exams/educationhelpguidesfaqs/t1-faq).
   Changing the regulatory cutoff to fit a provider response would not resolve
   the discrepancy. Native T+3/T+2 history is also not itself the required T+1
   current-account counterfactual.
2. **XLF's non-cash corporate action.** Yahoo labels 2016-09-19 as a 1.231 split.
   The issuer's contemporaneous [SEC-filed notice](https://www.sec.gov/Archives/edgar/data/1064641/000119312516699787/d246445d497.htm)
   describes an in-kind distribution of XLRE shares. It cannot be replayed as
   additional XLF shares or immediately spendable cash. The issuer workbook has
   that additional distribution ex-date, which Yahoo's cash-dividend events
   omit. Actual entitlement, delivery, fractional cash, valuation and any sale
   of the received asset need a documented action policy and evidence before
   outcome inspection. The fixed ranking universe is unchanged; no new sector
   is retroactively added to rescue the result.

The archived sources also contain ordinary 2-for-1 splits on 2025-12-05 for
XLB/XLE/XLK/XLU/XLY. Their split-adjusted quote prices and dividend histories
require conversion to actual share units before execution simulation. This
audit inventories the events; it does not claim that all corporate actions
have been reconciled. Zero-valued issuer declaration rows and out-of-sample
issuer errors are retained as source facts, not fabricated cash payments or
additional in-sample data failures.

## Calendar validation method

The new `settlement_calendar.reconstruct_t1` only admits a unique next eligible
date forced by the archived native settlement constraints. Each observed T+N
settlement is an eligible day, and exactly N eligible dates must lie in
`(trade_date, settlement_date]`. Constraint propagation rejects contradiction
or ambiguity. It neither equates a trading day with a settlement day nor
invents weekday holidays. Six focused tests cover the actual regulatory
boundaries, derivation from consistent T+3 examples, a bank holiday, ambiguity
and both direct and joint inconsistencies. The real source fails admission.
No inferred calendar has been used in a backtest.

## Decision and next evidence

Record one failed **data-audit** trial. The three planned score variants
(12-month, 6-month, mean of 1/3/6/9/12-month returns) and both training cost
cases (5/10 bp) remain unattempted. The $140 allocation, 95% target ceiling,
fees, risk limits, sample bounds and single final-holdout rule remain intact.

A shared data-repair follow-up must establish a consistent historical banking
calendar for the T+1 counterfactual and reconcile real corporate actions before
this source bundle is eligible for a new preregistered attempt. Preserve the
failed trial; do not mark any previously consumed strategy holdout reusable.
SPY benchmark overlap with earlier inspected research remains disclosed.
Momentum crashes, sector concentration and trading costs remain the candidate's
predeclared failure mechanisms, not measured C02 outcomes. Promotion is absent.
