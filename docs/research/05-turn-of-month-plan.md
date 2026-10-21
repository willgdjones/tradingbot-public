# SPY turn-of-month: fixed research plan

Recorded 2026-09-30 before calculating strategy returns; `tradingbot-c1s`.
Binding rule: buy on the fourth-to-last trading day of a month, sell on the
third trading day of the next month. Calendar dates come from Alpaca, including
early closes. No entry/exit-day optimization. Initial connectivity probes
inspected a few January 2023 daily bars; no return analysis informed this plan.

## Data and sample

Use the existing Alpaca paper credentials for read-only SIP history through
2026-09-30: SPY raw and adjusted daily bars from 2016, plus final-session-minute
bars for scheduled entries/exits. Retain exact responses in hashed/resumable
Parquet, separate from prediction-market archives. Validate each required
session and endpoint; never fill missing data forward into an execution.
Only completed calendar-defined cycles enter the closed-trade study; record the
unfinished September 2026 cycle explicitly. Report 2016–2022 and 2023–2026
chronological subsets without choosing parameters on either. These historical
subsets are not a newly observed forward test.

## Four variants, all recorded in the trials ledger

1. `tom_minute_2bp`: use the open of the final regular-session minute as a
   fractional marketable-order execution proxy, with 2 bp adverse movement per
   side. This is a disclosed approximation, not an observed broker fill.
2. `tom_minute_5bp`: identical schedule and sizing, 5 bp per-side stress.
3. `tom_minute_10bp`: identical schedule and sizing, 10 bp per-side stress.
4. `tom_close_2bp`: daily close prices, 2 bp per side, a rule-level benchmark
   only. Fractional CLS/closing-auction execution is unavailable; do not promote
   this variant on that fill assumption.

Virtual allocation $140, fixed target entry notional $24.90 (subject to the
unchanged $25 cap, settled cash and fees), fractional quantity rounded down to
nine decimal places. Long-only, no margin or shorts. No leverage, compounding
or cash interest. Track unsettled sale proceeds using Alpaca's settlement date.
Research allocation is simulated capital, not a funded account allocation.

Use the current September 17, 2026 Alpaca equity fee schedule as a **current-cost
counterfactual applied uniformly to the historical sample**, not reconstructed
historically charged fees. Retail/default routing commission is zero. SEC on
sales: 0.0000206 × dollars; TAF on sales: 0.000195 × shares, capped at $9.79 per
trade; CAT both sides: 0.000003 × shares. Aggregate each fee type separately by
account/date, then round up to cents; incrementally attribute the resulting
charge to fills. Stress slippage separately. This is conservative relative to
zero-SEC periods; avoid claiming exact historical fees from this model.

Preserve actual raw execution prices. Compare adjusted/raw daily ratios across
holding windows to detect corporate actions; any affected cycle needs explicit
handling before reporting complete net performance. FX snapshots use a dated
public reference rate, never an invented rate presented as history.

## Required outputs

Ledger rows for all variants, including failures; source hashes, code commit,
parameters, exact modeled fees, completed-trade count, net P&L, per-trade mean,
win rate, informational p-value, marked-equity drawdown, year and chronological
subset results, exposure days and missing/excluded cycle counts. Compare the
calendar schedule with equal-duration non-overlapping mid-month windows as a
separately logged diagnostic if sufficient data exist; any additional tested
variant must be registered before evaluating it.

No luck/significance filter changes the owner's profit-after-fees criterion.
A profitable benchmark with unattainable fills is not executable proof. Preserve
the §6 limits and all accepted risks. Publish no posts and send no broker orders.

### Diagnostic registered before returns (2026-09-30)

`tom_midmonth_close_2bp`: buy the fourth trading day's close and sell the tenth
trading day's close of each complete month, January 2016–August 2026. This gives
the same six close-to-close session intervals as the month-end rule and avoids
overlapping its holding windows. Use identical sizing, current fees and 2 bp
per-side slippage. This fifth variant is a daily-close diagnostic, with the same
fractional auction limitation. No optimization or return inspection selected it.

Sources checked 2026-09-30:

- [Alpaca historical bars](https://docs.alpaca.markets/us/reference/stockbars):
  symbol-first pagination, SIP feed and adjustment flags.
- [Alpaca data FAQ](https://docs.alpaca.markets/us/docs/market-data-faq):
  bar timestamps label interval starts; daily and minute aggregation differ.
- [Alpaca fee schedule, September 17](https://files.alpaca.markets/disclosures/library/BrokFeeSched.pdf):
  equity rates and separate daily fee-type rounding.
- [Order support](https://docs.alpaca.markets/us/docs/orders-at-alpaca) and
  `src/tradingbot/connectors/README.md`: fractional DAY limits, no fractional CLS.
