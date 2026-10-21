# C15 low-volatility sectors — source result

2026-10-02, OrangeCove; `tradingbot-xwy`.

**DATA_FAIL: XLE and XLU fail the frozen adjusted-price comparison.** This is
unmeasured strategy performance. All four planned training cases (63/126 daily
returns × 5/10 bp per side) remain unattempted, and no final was consumed.
Actual allocation **$0**; decision **hold at idea/source preparation**.
Rules remain in the [one preregistration](43-c15-low-volatility-plan.md).

## Price evidence

All nine original Yahoo captures have **5,218 sessions**, 2006-01-03 through
2026-09-30, matching the common calendar with no missing or extra session.
The source interval and elapsed-time cutoff remain 2006-01-01 to 2026-10-01
exclusive, final starting **2020-07-10T14:24:00Z**. Prices were inspected solely
for source agreement; no candidate rankings or strategy returns were computed.

| Fund | Direct Alpaca agreement | Nasdaq × Alpaca factors agreement | Nasdaq-route disagreements |
|---|---:|---:|---:|
| XLB | 95.74074% | 99.32298% | 17 |
| XLE | 91.22222% | **97.57069%** | **61** |
| XLF | 88.66667% | 99.88053% | 3 |
| XLI | 96.81481% | 100% | 0 |
| XLK | 97.37037% | 99.64158% | 9 |
| XLP | 97.11111% | 100% | 0 |
| XLU | 97.18519% | **98.80526%** | **30** |
| XLV | 96.07407% | 100% | 0 |
| XLY | 98.92593% | 100% | 0 |

Agreement means daily returns differ by at most **5 bp**, required on at least
**99%** of paired consecutive primary sessions. Direct comparisons cover 2,700
returns per fund and leave 2,517 unpaired; the Nasdaq route covers **2,511**
returns (2016-10-04 through 2026-09-30) and leaves **2,706** unpaired. Every
disagreement and unmatched date is retained, including those from passing funds.
Stooq XLE/XLU responses returned no CSV price series; their raw responses and
parse failures are archived. No paid endpoint, subscription or new key was used.

The Nasdaq reference uses **only Alpaca all-adjusted/split-adjusted ratios** for
dividend factors. Penny precision can add noise: XLE's recorded factor changes
from 24.23/36.38 on 2016-11-25 to 23.89/35.85 on 2016-11-28. That comparison differs
by 5.36 bp. XLU's 2016-10-14 comparison differs by 6.03 bp. These examples suggest
a precision/convention problem; they do not establish that every discrepancy is
harmless. No rounding allowance, factor smoothing, primary patch, date removal
or universe substitution was introduced to make the source pass.

## Reproducibility and ledger

The immutable audit is `data/research/c15-low-volatility/audit.json`, SHA-256
`0499a65e57590343189b63fd6a617a09ff52d05b90c43535f0f3414a790613a4`.
It binds **64 input files**, archived HTTP request/response identities, raw-byte
hashes, primary coverage, recomputed comparisons, the unchanged split and audit
code. Local audit replay performs no new network request and no strategy replay.
Source-failure **trial 5589 / strategy 10469** follows audit commit `c361b9b`;
the ledger recorded current HEAD `c94f6f9`, which also contains the independently
completed C17 report. All four planned configurations are explicitly unattempted.
Stored-only verification confirms **one source trial, zero orders, zero fills,
zero C15 final spends**, an idea-stage strategy with $0 allocation, and null P&L,
fees, trade count, drawdown and luck fields. It rechecks all 64 inputs and five
code files. Verification: `data/research/c15-low-volatility/verification.json`,
SHA-256 `52f3a5caf58d19701e8ddd5e992f0db1e5bdb4a44970e89ffa801aef01dfb5ab`.

**22 focused checks pass**, covering the source comparison boundaries, missing
endpoints, fixed universe, altered evidence, immutable receipts and idempotent
failure logging with null performance and no orders/fills/final spend. No
candidate P&L, fees, trade count, turnover, exposure, drawdown, regime returns,
benchmark performance or p-value is reported because none was measured.

## Promotion checklist and account risk

- **Evidence/statistics:** a specified risk-premium hypothesis is permitted by
  the owner's updated PRD §3, but this sector adaptation has no measured edge.
  Profitability, drawdown and regime gates are unassessed; no idea → backtest,
  paper or live promotion is made.
- **Tail/gap and correlation:** three sectors can lose together during equity
  shocks; utilities/staples can add duration exposure and overlap C02/C03/#6.
  Opening gaps can pass the −40% allocation kill before execution; the kill is
  a veto, not a guaranteed exit price. No present positions exist.
- **Execution/adverse selection:** the proposed next-open taker scenario still
  needs fractional fill, spread, partial-fill and conservative settlement
  validation. Prediction-market maker guards do not establish equity fidelity.
  The $140 virtual slot and all PRD §6 limits remain unchanged.
- **Venue/operations:** future use depends on Alpaca, its feed and the Mac.
  Accepted no-dead-man/no-startup-reconciliation risks remain; no connector,
  capital, account, key or real order was activated by this work.
- **Untrusted inputs/reproducibility:** external bytes are data only; the audit
  verifies checksums and request identities. Source review can be repeated
  without evaluating signals or spending a final. An admissible source and a
  tested common-mode reactor are required before any later replay.

This closes the current scoped research attempt as a price-data failure. Any
future source reconciliation must retain this receipt and freeze its evidence
before strategy outcomes; this result neither rejects nor validates the edge.
