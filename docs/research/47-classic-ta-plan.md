# Classic TA batch — preregistration (`tradingbot-ob1`)

2026-10-04, DarkMeadow. Research only; actual allocation $0. One batch plan
and one results file. Defaults are pinned to je-suis-tm/quant-trading commit
`611b73f2c3f577ac5b28aaa19ac8c43d3236c7a5`; original scripts, hashes and
Apache-2.0 license are in `classic-ta-sources/`. Adaptations below are ours.

## Fixed scope and source defaults

Daily panel: **SPY, QQQ, AAPL, MSFT**, in that order, chosen before prices or
outcomes: two broad equity ETFs and two established mega-caps from the existing
universe. This bounded panel is not the full 40-symbol Jev universe. No ticker
substitution, parameter search or outcome-dependent source repair.

| Rule | Frozen behavior / source limitation |
|---|---|
| Bollinger | 20-day sample standard deviation, ±2 deviations; exact upstream bottom-W search, 75-bar horizon, absolute alpha=beta=0.0001. Enter on W confirmation, exit on standard deviation < beta. Do not rescale those unusually small defaults. |
| MACD | Source uses simple moving averages and interactive `input()` periods; **no numeric defaults exist**. Record SPEC_BLOCKED; do not invent 12/26 or reuse Awesome's EMA parameters. |
| RSI | Executed upstream `main()` uses 14-period SMMA initialized by the first change, long below 30, flat otherwise (short above 70 clipped to flat). Optional head-and-shoulders code is not the executed default. No invented hold-until-70 rule. |
| Parabolic SAR | Preserve upstream recurrence: initial/step AF .02, cap .2; long when real SAR < close, flat otherwise. Require its two-bar initialization. |
| Heikin-Ashi | Preserve upstream contrarian entries on two bearish HA candles, increasing body and open=high; up to 3 equal tranches (`stls=3`), exit all on two bullish candles with open=low. Preserve this direction, despite momentum prose. |
| Awesome | 5/34 simple averages of (high+low)/2. Preserve source signal assignment order: MA comparisons overwrite saucer signals, leaving a long/flat crossover. |
| Shooting Star | Source is exclusively short-entry/short-cover, uses whole-sample mean and next-bar confirmation. Long/flat projection has **no entries**, so record NO_LONG_RULE; no inverted candle pattern or future-dependent return calculation. |
| Dual Thrust | 5-session range, param=.5; adapt FX session to US regular IEX session. Thresholds fixed from previous completed sessions, long above upper, exit below lower or by close; at most one entry per symbol/session. If archived IEX has insufficient complete sessions for warmup in both partitions, record DATA_FAIL (missing price history), log trial and do not manufacture history. |

## Data, execution and locked holdout

Daily interval **2016-01-01 inclusive through 2026-10-01 exclusive**. Use
`HoldoutSplit`'s 70/30 elapsed-UTC partition, independently initialized flat with
in-partition signal warmup. Yahoo split/dividend-adjusted OHLC (common
adj-close/close factor). Independently compare adjusted daily returns with free
Alpaca all-adjusted, Stooq, or Nasdaq closes multiplied by independently obtained
Alpaca all/split dividend factors. Require ≥99% of paired consecutive return days
within 5 bp, report coverage and every disagreement. All primary sessions must
match the archived exchange calendar. Source eligibility is decided before
strategy outcomes; failed symbols retain explicit failed ledger entries. Never
patch individual prices. OHLC inputs receive positivity/ordering checks.

Each rule/symbol is an independent **$140 virtual cash** research run, not four
concurrently funded slots. Only completed closes generate signals; execute at
the next regular open. Targets use min(95% of decision equity, $140), with 5%
cash reserve and $0.01 fee buffer; HA divides this budget into three tranches.
No shorting, borrowing or cash interest. Orders use settled cash, minimum $1,
quantity rounded down to 1e-9. Delayed entries are reconsidered only at a later
open against the latest completed-close target. Terminal open is exit-only.
Use the existing total-return equivalent runtime, ledger, unchanged risk vetoes,
conservative cash-release calendar and raw-share-equivalent `EquityFeeBook`.
Fixed **10 bp per side**, adverse cent rounding and fees; no alternate cost
scenario selection. This is a current-account cost scenario, not recovered
historical fees or proof of broker opening fills. Exact corporate-action ledger
mechanics and optional blackout are not research prerequisites.

Five executable daily rules × four symbols = 20 training configurations; record
all, including missing prices and zero trades. For each rule choose the highest
positive, complete, flat, rejection-free training net; fixed panel order breaks
ties. Commit source/code hashes and selection receipt before **one** final for
that rule's family (`classic_ta_<rule>`). Nonpositive/incomplete training has no
final. Failures after admission consume the final permanently. No sibling ticker,
cost case or renamed version may reopen it. No historical Jev decisions are run.

Report net/gross, costs, trades, marked maximum drawdown (dollars/peak/initial),
year and fixed regimes (2016–2019, 2020–2021, 2022, 2023–2026), exposure, turnover,
cash skips, risk rejections and ending holdings. Show buy/hold and cash as
nonselectable diagnostics. Use existing fixed-seed monthly block-bootstrap luck
estimate only with ≥30 months and ≥30 distinct exit-month clusters; otherwise
null with explanation. Prior research on these assets is known; do not call this
independent untouched evidence. Survivors are only possible J1 base-rule inputs,
subject to prospective adaptation and a separate paper admission.

## What could blow up this account? / promotion checklist

- **Edge/evidence:** behavioral trend/reversal heuristics permitted by the newer
  PRD §3, not established structural edges. Explicit source rules above; historical
  profitability, statistics and cross-regime evidence are pending. Older checklist
  wording does not override the owner's broader scope.
- **Tail/gap:** overnight equity gaps can lose much of a $140 slot and jump the
  −40% kill; the $25 prediction-market cap is inapplicable to these equities.
- **Adverse selection:** next-open taker execution faces spreads, news and weak
  liquidity; 10 bp is a scenario, not guaranteed execution. Prediction-market
  maker-event guards do not describe these fills.
- **Venue:** Alpaca, feed and Mac outages remain, including the accepted absence
  of dead-man protection and startup reconciliation. Any future keys trade only,
  never withdraw. No new venue, key, account, capital or orders here.
- **Untrusted inputs:** upstream code is reviewed reference data, never imported
  or executed as a downloader; feed/headline contents cannot issue instructions.
- **Reproducibility:** pin source bytes and executable dependencies, test causal
  prefixes and hand-computed paths; shared strategy interface and ledger. Future
  paper/live require actual fills/actions and separately verified fidelity.
- **Correlation:** SPY/QQQ/AAPL/MSFT overlap strongly and can lose simultaneously
  with existing equity sleeves, concentrating the −$50 global daily halt.
- **Limits:** −40% strategy kill, −$50 daily halt, slot cap, 30-second stale-data
  halt and five API errors/minute remain unchanged. No new luck threshold.

**Decision:** idea → backtest only after source and implementation checks; virtual
$140/run, actual $0. No paper/live promotion or readiness claim in this batch.

## Frozen source and implementation admission — 2026-10-04

Source archive: `data/research/classic-ta/source.json`, SHA-256
`0c87c2622ff9399067c38a744302fabd7c886a24982d5a1f0f9d423d6dddc9a8`.
All four primary histories have 2,701 sessions. SPY passes independent Nasdaq
close × Alpaca dividend factors (99.88053% over 2,511 paired returns; earlier
unpaired dates retained), QQQ passes Alpaca (99.77778% / 2,700) and MSFT passes
Alpaca (99.29630% / 2,700). AAPL fails Alpaca (98.70370% / 2,700); Stooq returned
no price CSV. All disagreeing/unpaired dates and original bytes are retained.
No AAPL outcomes are admitted. Its five training configurations are DATA_FAIL.
SPY's direct Alpaca failure and unsuccessful Stooq attempt are also retained.

IEX snapshot cutoff: 2026-10-04 00:00 UTC. Each panel symbol has only the regular
session of 2026-10-02, insufficient for five prior sessions plus any replay.
Four Dual Thrust configurations receive DATA_FAIL without strategy outcomes.
MACD and Shooting Star each have four explicit specification dispositions.

Implementation uses a distinct stable reactor/family key per daily rule, shared
across symbols. Tests use synthetic data and rollback transactions; an early
fixture attempt generated a synthetic admission-refusal incident before its
transaction isolation was corrected. No real holdout was consumed by tests.
Admit 15 daily training runs after the committed synthetic checks; all 32
rule/symbol configurations remain in the batch ledger.

## Training selection frozen before final — 2026-10-04

Implementation `8b49eab`; training/disposition trials **6366–6397**. All 15
admitted runs completed flat, without rejected orders or risk halts. Seventeen
configurations have explicit unattempted dispositions (nine DATA_FAIL, four
SPEC_BLOCKED and four NO_LONG_RULE). No parameter or ticker was added.

Selection receipt `data/research/classic-ta/selection.json`, SHA-256
`0a37b0081f7ef69b2dc18be5d9f12de30f688d38230a82033b61f381b661f50b`.
It binds the source, exact code dependencies, all training metrics and artifact
hashes. Holdout starts **2023-07-11T04:48:00Z**; no final has run at this freeze.

| Family | Selected symbol / training trial | Net USD | Frozen strategy version |
|---|---|---:|---|
| classic_ta_bollinger | None (zero trades in all admitted symbols) | 0 | No final |
| classic_ta_rsi | QQQ / 6371 | 16.24932947 | `1d295b4a0ab7f134b1d73306166d45b91ad7cb1ff337b6f6eafea8821968dbc6` |
| classic_ta_sar | QQQ / 6375 | 61.56479990 | `70d7d07936d994c0462bdab974caff4c59fe0fcb37133658821281e76bad7e4e` |
| classic_ta_heikin_ashi | MSFT / 6381 | 108.72826643 | `7844f44e69b3e2e9fd32fb4896456775b911b8e8c21cd1f2728e460e948add44` |
| classic_ta_awesome | QQQ / 6383 | 100.43796755 | `3b98ab4f853b5b1717621683ad842adfdc612456cff552cbed9e21438d694cda` |

Execute one final at the existing 10 bp cost scenario for each of those four
families. The large training drawdowns and 2022 losses are retained in the one
results file; this selection does not authorize deployment or redesign.

## Completed final disposition — 2026-10-04

Selection commit `9d8ab07` preceded four single-use finals: Awesome QQQ 6398
**+$64.80**, Heikin-Ashi MSFT 6399 **−$2.75**, RSI QQQ 6400 **+$19.95**, SAR QQQ
6401 **+$3.09**, all after costs. All finished flat with no rejected orders or
risk halts. No second symbol/version or final was run. Read-only verification
matched all 36 trials, frozen identities and one family receipt per final.

**Decision:** keep Awesome/RSI/SAR as research candidates for a separate J1
base-rule study; reject Heikin-Ashi MSFT v1's profit criterion. No paper/live
promotion. Full drawdowns, trade counts, costs, regimes, source limitations and
luck estimates are in [the single batch results file](47-classic-ta-results.md).
