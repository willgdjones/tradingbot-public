# C01 — SPY monthly trend: archived results, failed evidence audit

Original bead: `tradingbot-8yz` (parent `tradingbot-cfe`). Preregistration:
[`07-candidate-shortlist.md`](07-candidate-shortlist.md). Machine-readable:
[`09-c01-spy-monthly-trend-results.json`](09-c01-spy-monthly-trend-results.json).
Audit and repair: [`11-c01-holdout-audit.md`](11-c01-holdout-audit.md), `tradingbot-bbw`.

## Verdict: FAILED_AUDIT — original PRD §4 pass withdrawn

The final replay preceded durable admission, the simulator bypassed the shared
risk/ledger path, and cash dates and risk metrics deviated from preregistration.
Stored trades also exceed the $140 allocation: selected training buys reach
$414.96 and final buys reach $186.07. Positive arithmetic from that model is not
a PRD §4 pass. **Hold in research; no paper/live promotion.**

The numbers below are **unchanged legacy outputs**, retained for audit. They
were not recalculated and do not estimate performance from a compliant model.
The benchmark drawdown includes future dividend cash, so the former “same
drawdown/no alpha” quantitative comparison is unvalidated. There is no
demonstrated edge from this evidence.

## Recorded source and partition

Yahoo capture SHA-256
`782593bb64e78f69ef8f4a0f625e23c0201bf68fa26299b7dedcfec3dd32d8b2`, retrieved
2026-10-01T05:45Z, archived under `data/equities/raw/free/SPY/` (gitignored).
Recorded coverage: 5,218 sessions, 2006-01-03 through 2026-09-30; 83 dividends
and no split events. The original coverage function returned diagnostics; the
runner did not enforce them as a fail-closed data gate.

Execution used quote open/close, signals used adjusted closes, and dividends
used an ex-date-plus-30-day payment proxy. The report proposed an Alpaca IEX
cross-check after a Stooq access failure, but C01 never called the comparison
function. Subsequent C04/C02 audits found unresolved source and calendar issues.

Dataset `sweep-c01-v1`: 2006-01-01Z through 2026-10-01Z, end exclusive;
`holdout_start=2020-07-10T14:24:00Z` (70% of elapsed UTC time). These recorded
boundaries do not prove single-use consumption. Each partition started flat
with its own warm-up; terminal open liquidation was applied after the final
close had already entered the equity curve, leaving inconsistent risk metrics.

## Legacy training outputs

The old runner selected by highest 10 bp training net P&L, with lookback ties
in preregistered order 10, 8, 12. It selected L=8.

| L | 5 bp net $ | 10 bp net $ | return | round trips | exposure | max DD |
|---|---|---|---|---|---|---|
| 10 | 175.23 | 171.97 | +122.8% | 11 | 0.69 | 21.9% |
| 8 (selected) | 319.72 | 315.82 | +225.6% | 9 | 0.69 | 17.6% |
| 12 | 143.18 | 140.25 | +100.2% | 11 | 0.68 | 21.9% |

All three were recorded positive by the old simulator. This does not establish
compliant profitability, risk control or alpha.

## Legacy final outputs: L=8 at 10 bp

| metric | strategy | SPY buy-and-hold | cash |
|---|---|---|---|
| net return | +48.6% | +155.8% | 0% |
| end equity ($140 start) | $208.07 | $358.19 | $140 |
| max drawdown | 25.0% | 23.3% | 0% |
| round trips | 7 | — | — |
| average exposure | 0.69 | 1.0 | 0 |
| monthly luck p | 0.049 | — | — |

Recorded by year: 2021 +23.3%, 2022 −21.5%, 2023 +8.7%, 2024 +24.2%,
2025 +11.1%, 2026 YTD +1.7%. These statistics came from the unreconciled
legacy path and are preserved without endorsement as validated evidence.

Recorded final fees $0.28, slippage $2.14 and dividends $10.31 used the
September-2026 EquityFeeBook counterfactual plus adverse slippage. The reported
zero cash delays is not evidence of T+1 compliance: the banking calendar was
not consulted and the delay-counting condition was unreachable. Dividend
entitlement/payment and terminal settlement/marking also fail the audit.

## Preserved history and decision

SPY history overlaps earlier #5/#6 research and was already inspected. The
original report also stated that a JSON serialization failure preceded the
surviving run and prior trials were cleared. Deterministic code does not make
failed or deleted consumption disappear. The audit cannot reconstruct every
deleted attempt and does not claim the surviving final was the first look.

Strategy `sweep_c01_spy_monthly_trend` (5080), training trials 3313–3318 and
consumed final 3319 retain their original rows and numbers. Final admission
occurred after simulation in the original runner. It remains consumed forever;
no code fix, new version hash or dataset rename authorizes replaying it.

The original JSON verdict is retained as `original_verdict`; the current verdict
is failed audit. The original “mechanically correct” and “PRD §4 pass” claims
are withdrawn. Keep the strategy in research, with no paper/live allocation.

## Read stored evidence

`uv run python -m tradingbot.research.c01_spy_monthly_trend --stored-trial-id 3319`
reads the ledger only. Optional `--out NEW_FILE.json` writes a new export without
replacing an existing file. Historical replay flags are disabled while the audit
is failed. A future compliant study needs the shared execution path, reconciled
data and a preregistered unseen evaluation period; see the full audit.
