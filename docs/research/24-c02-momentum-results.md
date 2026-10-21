# C02 monthly sector momentum under Amendment 21: results

Bead: `tradingbot-0qk` (C02 re-attempt under [Amendment 21](21-corporate-action-blackout.md)).
Admissibility: [22-c02-amendment21-admissibility.md](22-c02-amendment21-admissibility.md)
(**ADMITTED** — all six blackout actions causally handleable with archived evidence).
Engine: `strategy/c02_sector_momentum.py` + `research/c02_sector_momentum.py`.
Selection receipt: `24-c02-momentum-selection.json`; final receipt: `24-c02-momentum-final.json`.
Trials ledger: training `5402–5407`, holdout `5408` (DB, local Postgres).

## What was run
Nine Select Sector SPDRs (XLB, XLE, XLF, XLI, XLK, XLP, XLU, XLV, XLY), free Yahoo
daily bars 2006-01-03 → 2026-09-30, on the **admitted nine-ETF Amendment 21 frozen
source** (`data/research/c07-blackout/frozen-source-v1`, receipt
`6c89c1cd…c4b214e7` — the same C02-lineage source audit, 12-c02 → 22-c02; actual-share
opens with primary-auction corrections, issuer-reconciled cash dividends on a
conservative documented-payable release, economic in-kind value for the XLF 2016
spin, Amendment 21 blackout plans). Locked 70/30 split by elapsed UTC time, holdout
boundary **2020-07-10T14:24:00Z** (identical window to C06/C07).

**Rule (unchanged from [07-candidate-shortlist](07-candidate-shortlist.md)):** at each
month-end rank the nine by a trailing economic total-return momentum score; hold the
**top three equally** inside the 95% total weight (alphabetical ties); rebalance
monthly — sell the names that left the top three, hold the names that stay (only
positive target gaps topped up, never trimmed), buy entrants pro-rata across positive
gaps with a 5% cash reserve and sub-$1 skip. Blacked-out names are excluded from
selection and any held position is force-exited at the blackout exit open and
re-entered only after reentry. Score variants (order): **12-month total return; 6-month;
mean of 1/3/6/9/12-month**. Next-month first-open raw execution, 5/10 bp adverse
slippage per side + Alpaca retail fee counterfactual, conservative T+1 settled cash,
terminal-open liquidation. Shared `RiskEngine`/`Ledger` (one code path), $140 virtual slot.

## Training (first 70%, 2006-01-03 → 2020-07-09) — all six complete, all positive
Selection cost 10 bp; net is after fees + slippage, dividends included.

| Variant | 5 bp net | 10 bp net | 10 bp max marked DD² | 10 bp 1-sided p¹ |
|---|---|---|---|---|
| ret12 | +$113.26 | +$107.98 | $70.87 (45.3%) | 0.068 |
| ret6  | +$127.20 | +$119.65 | $82.56 (48.8%) | 0.073 |
| **mean5** (selected) | +$135.25 | **+$127.92** | **$66.69 (42.5%)** | 0.070 |

Rule: highest positive complete 10 bp training net; variant order breaks ties →
**mean5** (strategy version `fc96077107e5f997…`). mean5 also had the lowest training
drawdown. ¹ One-sided centered 3-month circular-block bootstrap (descriptive, not
selection-adjusted). ² Drawdown fractions are peak-to-trough; none reached the §6
−40%-of-allocation kill (the trough never fell below $84 because peaks were elevated by
the 2010s run-up).

## Holdout (last 30%, 2020-07-10 → 2026-09-30) — single run, mean5 / 10 bp (trial 5408)

| Metric | Value |
|---|---|
| **Net P&L** | **+$91.03** (+65.0% on the $140 virtual slot) |
| Execution net / dividends | +$76.62 / +$14.41 |
| Round-trips / fills / rejections | 49 / 132 / **0** |
| Complete execution (flat ending) | **yes** |
| Fees / turnover | $1.62 / $4,518 |
| **Max marked drawdown** | **$30.79 (14.9%)**; daily-close 14.5% |
| Average exposure | 69.5% |
| p-value (1-sided, descriptive) | **0.013** |
| Blackout symbol-sessions (processed) | 10 / 10 (the 2025-12-05 splits) |
| Blackout forced-exit / reentry cost | 2+2 fills, $0.04 fees, ~$0.19 adverse |
| Halt / kill events | none |

### Per-regime (holdout, marked net / execution-trip net)
- **2020-2021:** +$2.55 marked (4 trips) — post-COVID recovery, low exposure ramp.
- **2022** (bear): +$19.94 marked, but −$13.65 trip net over 8 trips — momentum defended
  via reduced exposure; marked gain is held-position recovery into year end.
- **2023-2026:** +$68.53 marked, +$90.21 trip net (37 trips) — the bulk of the result.

## Verdict
**PASS PRD §4 both-partitions-positive** (training +$127.92, holdout +$91.03), complete
execution with zero rejections in both partitions, drawdowns well inside the §6 kill,
holdout p = 0.013. The locked single-use holdout is now consumed (family `c02`,
`family_holdout_spends` trial 5408); re-running requires a new strategy version.

**But not alpha and not promotion-eligible.** Diagnostic (non-executable, cost-free,
fully-invested) benchmarks over the same observations beat the strategy in both
partitions:

| Partition | mean5 net return | SPY buy&hold | Equal-weight 9-ETF |
|---|---|---|---|
| Training | +91.4% (DD 42.5%) | +232.9% (DD 55.2%) | +228.3% (DD 51.7%) |
| Holdout | +65.0% (DD 14.9%) | +161.5% (DD 24.5%) | +145.6% (DD 16.7%) |

Monthly rotation among sectors delivered a positive, lower-drawdown, ~70%-exposed
long-only equity line, but passive buy-and-hold would have earned far more in these two
strong-trend decades — the rotation's timing drag and partial exposure cost more than
its defensive drawdown benefit was worth. Benchmarks are diagnostic, not the alpha bar.

**Promotion gate: none passed here.** The result is an Amendment 21 source/cash/execution
*counterfactual* on free Yahoo bars, over a previously inspected SPY reference window;
`promotion_eligible` is `false`. Live promotion would require the
[promotion checklist](promotion-checklist.md) including the written "what could blow up
this account?" section, and — because the whole history was inspectable — a forward paper
run (7+ days, 30+ trades) before any `ready-for-live` queue. No §6 change; no live keys.

## Reproduction
`uv run python -m tradingbot.research.c02_sector_momentum train` then `… final`
(final refuses once the family holdout is consumed; read the stored trials/receipts
instead). Durable receipts under `data/research/c02-momentum/runs/` (gitignored).
