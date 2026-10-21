# End-of-day LETF flow results — 2026-09-30

**All six preregistered cash-feasible variants lost money after costs.** The primary 1% daily-move / 2 bp-per-side case loses **$11.28 over 305 trades** in 2023–2026. It fails the owner’s profit-after-fees criterion and is not a funding or paper-promotion candidate on this evidence. No thresholds were changed after seeing the results.

This tests buying SPY/QQQ after positive daily moves. The cash account cannot implement the bearish short leg; those signals are counted, never traded. The complete long/short thesis remains unimplemented under the approved account constraints. The instruments traded here are unleveraged SPY/QQQ; leveraged-ETF rebalance flows are the proposed mechanism, not the assets purchased.

## All registered variants

| Variant | Trial | Closed trades | Net USD | Fees USD | Win rate | Marked drawdown USD | Rejected entries |
|---|---:|---:|---:|---:|---:|---:|---:|
| letf_1pct_2bp | 1546 | 305 | -11.28 | 6.00 | 21.3% | 11.34 | 0 |
| letf_05pct_2bp | 1547 | 585 | -18.22 | 10.05 | 23.8% | 18.37 | 2 |
| letf_15pct_2bp | 1710 | 139 | -4.17 | 3.06 | 26.6% | 4.23 | 0 |
| letf_1pct_5bp | 1753 | 305 | -15.83 | 6.00 | 13.4% | 15.87 | 0 |
| letf_1pct_10bp | 1754 | 305 | -23.41 | 6.00 | 7.5% | 23.43 | 0 |
| letf_1pct_close_2bp | 1760 | 305 | -10.68 | 6.00 | 20.7% | 10.82 | 0 |

All six trials are `complete`, including losses. All end flat, reconcile cash/unsettled proceeds with ledger P&L, and have no simulated risk halts. The two rejected 0.5% entries are SPY and QQQ on **2023-10-10 at 15:30 ET**, each rejected for insufficient settled cash in its assigned half. The simulation did not borrow from the other half to make them fill.

The daily-close case is an unattainable fractional closing-auction benchmark. The practical cases exit at the final minute’s opening-price proxy. Both use the same 15:30 opening-price signal and entry proxy.

## Chronological and instrument checks

| Variant | 2023–2024 net USD | 2025–2026 net USD | One-sided trade p | Day-aggregated p |
|---|---:|---:|---:|---:|
| letf_1pct_2bp | -6.76 | -4.51 | 1.000000 | 1.000000 |
| letf_05pct_2bp | -9.97 | -8.26 | 1.000000 | 1.000000 |
| letf_15pct_2bp | -3.13 | -1.04 | 1.000000 | 0.999995 |
| letf_1pct_5bp | -9.21 | -6.62 | 1.000000 | 1.000000 |
| letf_1pct_10bp | -13.29 | -10.12 | 1.000000 | 1.000000 |
| letf_1pct_close_2bp | -6.32 | -4.37 | 1.000000 | 1.000000 |

These p-values test positive mean net P&L against a zero-or-negative mean null. Values near one do not support a positive edge; they are not posterior probabilities that the result is luck. Day aggregation reduces same-day SPY/QQQ double-counting but does not remove all dependence. Neither statistic is used as an additional promotion gate. The two subdivisions are historical calendar periods, not unseen forward validation or an independently specified economic-regime classification.

Primary variant by exit year:

| Year | Trades | Net USD |
|---|---:|---:|
| 2023 | 89 | -3.39 |
| 2024 | 75 | -3.37 |
| 2025 | 79 | -3.04 |
| 2026 | 62 | -1.47 |

| Instrument | Trades | Net USD | Positive signals | Unavailable short signals |
|---|---:|---:|---:|---:|
| SPY | 108 | -5.10 | 108 | 86 |
| QQQ | 197 | -6.18 | 197 | 137 |

Account/day fee rounding is pooled across both ETFs. Equal-time events process SPY first; per-symbol fee attribution follows that order, so the symbol rows are not independent single-symbol backtests. The combined account result is authoritative.

The primary trade averages $-0.0370 net, with 200 active exit days and 147.42 instrument-position hours. Its return on the full $140 virtual cash is -8.05% over the entire sample; no compounding or interest is included.

## Data, causality and cost evidence

- Sample: 2023-01-03 through 2026-09-30, 939 regular trading sessions per ETF. The first session is warm-up only; eight early-close sessions are excluded, leaving 930 signal sessions and 1,860 instrument/day decisions. Primary signals: 305 positive, 223 negative/unavailable, 1,332 below threshold.
- Complete capture: 935 hashed pages / 62,454 source records, including 946 calendar records (with future settlement coverage), 1,878 raw daily bars, 1,878 adjusted daily bars, 57,722 minute bars and 30 corporate-action reference rows. All 55,860 required 15:30-to-final-minute bars are present; the capture also includes 15:29. No execution is forward-filled.
- Entry uses only the 15:30 minute OPEN divided by the previous observed daily CLOSE. Same-bar high/low/close and the later day return are not decision inputs. Synthetic tests deliberately make those future values disagree. The current opening print is still only a proxy for a fresh executable quote: its first-print latency and historical revisions are unknown.
- Two fixed $70 virtual cash buckets alternate by trading-session index, including skipped sessions. Both ETF entries target $24.90, remain within the unchanged cap, and include fees in cash availability. The archived calendar correctly shows T+2 on 2023-01-03 (settles January 5), May 24, 2024 settling May 29, and T+1 on May 28, 2024 (also settles May 29). Settlement holidays remain effective.
- Costs use the September 17, 2026 retail Alpaca schedule uniformly as a current-cost counterfactual: zero default commission, SEC/TAF on sells, CAT on both sides, separate daily type rounding up to cents. This is not reconstructed historical billing. Bid/ask spread and market impact are represented by the registered adverse bp scenarios, not observed BBO.
- Raw price changes include ex-dividend effects and do not equal exact leveraged-fund NAV changes. The primary has three positive signals on reported ex-dividend dates. Vendor corporate-action coverage is partial (SPY reference ex-dates include December 2022 through June 2026, QQQ March 2023 through June 2026); daily adjustment factors show no >2% discontinuity and the reference returns no noncash action. No overnight position is held, so no dividend credits are assumed.
- Drawdown uses chronological minute-opening and daily-close marks plus fills/fees; it does not measure every intraminute extreme. Source identity, archived decimal prices, FX references and per-fill settlement/bucket evidence are retained.
- The capture encountered one transient ENOSPC write failure. The atomic page writer retained prior pages; resumption completed the same request identities. Final checksum, pagination and full-session coverage checks passed. No unrelated files were deleted.

## Decision record: no promotion

Date/reviewer: 2026-09-30, NavyLantern. Decision: hold #5 at research, no funding. Funded allocation: $0; virtual allocation: $140 per isolated trial. The six trials above are complete and negative after costs. The fixed rule and shared `EodLetf` reactor exist, but profitable historical evidence and paper/live fidelity are absent. Parent strategy `letf_eod` remains `idea` with zero allocation. No live venue flag, account, capital, secret, §6 limit or accepted-risk choice was changed.

### What could blow up this account?

**Tail/gap risk:** each unleveraged long position can lose its purchase cost plus fees; the model limits each entry to $24.90. Two correlated ETFs can lose together. A late-day halt, outage or unfilled exit could create unintended overnight exposure; bar simulations do not prove the exit always succeeds. Repeated losses can consume the allocation even with small positions.

**Adverse selection:** marketable fractional orders pay spread/impact and can meet adverse late-session flow. This is not passive maker selection, and the hypothesis lacks direct fund-assets/holdings evidence tying returns to forced flows. The tested prices show no positive after-cost continuation edge for the feasible subset.

**Counterparty/venue:** both execution and input prices depend on Alpaca/SIP. Vendor corrections and broker outages can invalidate the fill approximation. Accepted no-dead-man/no-startup-reconciliation behavior is unchanged: orders can remain active after a process failure. Trading-only, nonwithdrawal permissions require evidence from the execution connector; read-only history retrieval does not establish them.

**Untrusted inputs:** external prices, calendars and corporate-action responses are parsed as data and never followed as instructions. Fixed deterministic code produces signals; no model, headline or tweet selects trades.

**Reproducibility:** source and FX checksums, committed code, complete parameters, persisted orders/fills and local per-trade/equity artifacts make the scenarios repeatable. That does not reconstruct the unrevised real-time feed or actual fills.

**Correlation:** SPY and QQQ share substantial market exposure, and SPY also overlaps #6. The standalone trials cannot be added into a portfolio forecast; concurrent strategies must share the same SPY market cap, cash book and $50 daily halt. The daily grouped statistic is supplementary, not a joint portfolio test.

## Reproduce and inspect

- Code commit: `5eaef1cfd7f6de8ac607bf333c93410cc84a5ded`. Runs used an isolated committed checkout to avoid unrelated in-progress shared ledger changes.
- Data run: `letf-20260930`; SHA-256 `ad70b5fb85a03b02010f349c544c95907b198659f233be00fa7668df8a34c58e`.
- ECB FX SHA-256: `684f22325b80a05da42ca1de044e07ca5515c00a35386335f573c7cc08d6ab0f`; each fill uses the strictly previous reference date, maximum seven days old.
- Full fills/orders/results: local Postgres port 5433, trial IDs listed above. Full parameters, decision records, per-trade returns and equity curves: gitignored `data/equities/results/letf-20260930-v1/`. [Compact results](06-letf-results.json) omit the reconstructible per-session parameter maps and full daily series, which remain in the ledger/artifacts.
- With the recorded code checked out and archived inputs available: `uv run python -m tradingbot.research.eod_letf --run-id YOUR_NEW_ID`. Existing run IDs cannot be reused. Changed code/parameters require new recorded trials.
- Validation: 23 focused downloader/strategy/research tests pass against the exact committed checkout, including pooled fees, fractional sizing, alternating halves, settlement restrictions, missing-data rejection, signal causality, risk-veto behavior, failed-attempt retention and cash/ledger reconciliation. No test broker orders are sent. After the real rows were persisted, 13 dashboard/longshot-runner compatibility tests also passed.

Assumptions and official sources are linked in [the preregistration](06-letf-plan.md). The cost and execution decisions match the [SPY study](05-turn-of-month-results.md). Further variants require a new explicit plan and ledger entry; do not rescue this result with an unlogged threshold search.
