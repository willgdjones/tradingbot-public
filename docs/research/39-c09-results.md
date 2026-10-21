# C09: post-auction IEF total-return results

**Profit test failed; hold at actual $0.** The selected ten-session hold at
10 bp earned **$13.222513 in training** (5492) but lost **$38.435118 in its
single final** (5495). The final completed 74 round trips, ended flat at
$101.564882 and had no rejected orders or risk halts. Maximum marked drawdown
was **$39.219920 / 27.86%**. The final is consumed; no promotion or retuning.

The [plan](39-c09-plan.md) preserves both holding periods, four main cost cases,
original interval and 2020-07-10T14:24Z cutoff. Implementation `c425f8b` preceded
all outcomes; selection `3b3342d` preceded final 5495. Failed source trial 4585
remains failed with all eight performance fields null. The owner's new research
standard supersedes its historical share-action prerequisite.

## Data and execution

Yahoo supplies 5,218 IEF adjusted sessions, 2006-01-03–2026-09-30. Nasdaq
split-adjusted closes multiplied by independent Alpaca-only `all/split`
dividend factors agree within 5 bp on **2,512/2,512 paired daily returns**,
2016-10-03–2026-09-30. There are no disagreeing paired days; **2,705 older
returns remain unmatched**, retained without price patches. Adjusted opens use
the same-day adjusted-close/raw-close ratio. This is a total-return equivalent,
with no separate dividend credit or optional blackout.

Revalidated original Treasury captures preserve all 242 dated offering and
occurrence records, 23 special notices and eight earlier CUSIP-lineage records.
Emergency and contingency auctions remain included. Announcement clocks precede
the post-auction decisions; realized yields, tails and bid-to-cover never select
trades. Decide at the first ETF close on/after the auction, enter next open S,
exit S+5 or S+10 opens. Decisions and both endpoints must fit one partition.
Additional auctions while invested or pending are ignored, never used to extend
an exit. Same-date CUSIP order labels the one position.

Each partition starts with $140 virtual cash. Freeze min(95% decision equity,
$140), retain a 5% reserve, buy only with settled cash after fees, and preserve
the original exit when cash delays entry. Adverse raw-cent-rounded prices at
5/10 bp per side are converted into adjusted units; September 17, 2026 fees
are assessed on raw-share equivalents. These daily scenarios do not establish
actual fractional/open fills. Previous IEF work and published-event selection
mean the partition is not claimed as pristine unseen evidence.

## Measurements

| Case | Trial | Round trips | Net after fees | Marked maximum drawdown |
|---|---:|---:|---:|---:|
| Five sessions, 5 bp | 5489 | 164 | −$6.28 | $23.75 / 15.23% |
| Five sessions, 10 bp | 5490 | 164 | −$25.92 | $36.95 / 24.61% |
| Ten sessions, 5 bp | 5491 | 163 | $35.82 | $16.19 / 9.17% |
| **Ten sessions, 10 bp training** | **5492** | **163** | **$13.22** | **$20.08 / 12.42%** |
| Pre-auction five-session control, 10 bp | 5493 | 164 | −$45.33 | $46.05 / 32.86% |
| Pre-auction ten-session control, 10 bp | 5494 | 112 | −$12.82 | $26.92 / 17.57% |
| **Ten sessions, 10 bp final** | **5495** | **74** | **−$38.44** | **$39.22 / 27.86%** |

All seven cases completed flat, without rejections or halts. Selected training
and final fees were $6.52/$2.96; adverse reference costs $47.68/$17.35; gross
after execution costs before fees $19.74/−$35.48; turnover $45,319.06/$16,509.18.
Average daily exposure was 40.78%/44.94%. Of 167/74 admitted windows, 4/0 were
skipped for overlap. No cash delays, late entries or terminal liquidations
occurred; those paths were tested synthetically.

Controls use S−H to S, matching session length, and exclude missing endpoints,
partition crossings and overlap with other planned post-auction holds. They
retain 239/165 full-source windows, admit 165/112 training windows and execute
164/112 after overlap handling. They are retrospective calendar diagnostics,
not alternative strategies chosen after results. Their negative returns do not
rescue the failed final or establish causal auction alpha.

Descriptive monthly three-month-block bootstrap p-values are **0.250675** in
selected training and **0.999300** in the final, with 162/74 exit-month clusters
and 10,000 fixed-seed draws. These are one-sided zero-mean tests, not posterior
probabilities that an edge is false; they are not selection-adjusted. No new
p-value gate was added to the owner's profit criterion.

| Regime | Selected training marked net / drawdown | Final marked net / drawdown |
|---|---:|---:|
| 2006–2009 | $12.17 / 5.87% | — |
| 2010–2019 | −$5.71 / 12.42% | — |
| 2020–2021 within partition | $6.76 / 3.54% | −$6.42 / 5.27% |
| 2022 | — | −$14.07 / 11.04% |
| 2023–2026 | — | −$17.95 / 15.79% |

Final annual marked net: 2020 −$0.25, 2021 −$6.17, 2022 −$14.07,
2023 −$8.97, 2024 −$7.29, 2025 +$1.03, 2026 −$2.72. Exact annual results and
drawdowns for every case are retained in `marked_calendar_years`. Use that and
`calendar_regimes` for dated attribution: the inherited legacy `2016_2022`
metric groups all exits through 2022, despite its label; `tradingbot-luy` tracks
that metadata defect without changing these frozen receipts.

No-cost IEF buy/hold returned **114.18%/−14.01%** in training/final, with
10.40%/23.92% drawdown, versus the strategy's **9.44%/−27.45%** returns.
Cash returned zero. The strategy underperformed buy/hold in both partitions;
its final lost more with less average exposure. The 2010–2019 loss and broad
final losses weaken the proposed recovery effect.

## Promotion checklist and what could blow up this account?

- **Edge/statistics/decision:** the auction-flow hypothesis, fixed entries/exits,
  complete fee-bearing trades, luck statistic, drawdown and several regimes are
  measured. Historical after-fee profit fails in the final. **Hold; actual $0**,
  OrangeCove, 2026-10-01. No paper/live activation or ready-for-live status.
- **Tail/gap risk:** unhedged duration and rate gaps can overwhelm the effect
  before entry or exit; IEF also has tracking risk. The ETF slot permits up to
  $140, not the prediction-market $25 cap. The unchanged −40% allocation kill
  and −$50 daily halt can veto an exit and cannot guarantee bounded losses.
- **Adverse selection:** open/taker slippage is assumed, not observed; auctions
  attract informed rate flow. Prediction-market maker guards are inapplicable.
- **Venue/operations:** eventual Alpaca, feed and Mac dependence and accepted
  no-dead-man exposure remain. No accounts, venues, keys, withdrawal powers,
  funded allocation or paid data were added; spend was $0.
- **Inputs/reproduction:** external data are never instructions. Immutable
  source hashes, 14 focused tests, deterministic reactor and shared ledger/risk
  receipts support inspection. No repeat final is permitted.
- **Correlation/fidelity:** bond exposure overlaps duration and trend sleeves
  and can concentrate daily losses. Paper has not reproduced actual broker
  fills, costs, settled cash or corporate actions. The same pure strategy
  interface is available; no mode fork or PRD6/PRD9 change was made.

Source, selection and exact version hashes are pinned in the plan. Run artifacts
are in `data/research/c09-total-return/`; final artifact SHA-256:
`6eab87fdc80341dc6e5c67d2593ce93cf7495ea53f015ca3f86cb7c562c52a24`.
Stored-only verification matched all seven trial metrics/versions/dependencies,
all source-input hashes and exactly one permanent family receipt, trial 5495.
