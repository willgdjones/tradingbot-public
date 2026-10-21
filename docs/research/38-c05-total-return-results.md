# C05 adjusted-total-return results — 2026-10-01

**Research profit criterion passed:** +$30.42 in training and +$47.13 in the single final, after 10 bp per side plus fees on separate $140 virtual allocations. The selected rule is monthly positive 126-session momentum.

Pre-registration: [plan](38-c05-total-return-plan.md). Owner-authorized model revision `total_return_d267cf7`; prior C05 final 3964 remains consumed. No fresh independent confirmation is claimed.

## Prices and coverage

Primary: unchanged Yahoo adjusted close and proportionally adjusted open, 4,716 sessions from 2008-01-02 through 2026-09-30. Secondary: Nasdaq split-adjusted closes, with DBA dividends incorporated using archived issuer/broker cash amounts and Nasdaq previous closes. No Yahoo prices or adjustment factors enter the secondary construction.

The reference spans 2016-09-30–2026-09-30: 2,512 consecutive daily-return comparisons per fund. The earlier 2,203 Yahoo sessions per fund are outside Nasdaq coverage. No reference sessions are missing inside the overlap. The original fixed cutoff remains 2021-02-14 14:24 UTC.

| Fund | Agreement within 5 bp | Disagreeing return dates |
|---|---:|---|
| DBA | 100.0000% | None |
| GLD | 99.9204% | 2026-04-20, 2026-04-21 |
| SLV | 99.9204% | 2026-04-20, 2026-04-21 |
| UNG | 100.0000% | None |
| USO | 99.9204% | 2017-03-20, 2017-03-21 |

Every discrepancy, both source returns and the difference in basis points are retained in `data/research/c05-total-return/nasdaq-total-return-source-check.json`. The six disagreeing observations remain in the unchanged Yahoo primary series. Original Alpaca SIP comparison and the cents-rounded ratio diagnostic remain archived; neither admitted the data. Stooq was unavailable. Nasdaq’s dividend endpoint was unavailable for these non-Nasdaq listings, so existing independently sourced cash amounts supplied the dividend adjustment.

Source receipt: `b4654006ee9cf0fbd3451c95300074556de3224d2901e558b73058cd3a0aa088`.

## Training and selection

All six training cases completed on 3,303 sessions, with flat terminal positions, zero rejected orders and no risk halts. Prices, signals, sizing and costs were unchanged after the first case started.

| Signal | bp/side | Trial | Net after costs | Fees | Round trips / fills | Max drawdown | Luck p |
|---|---:|---:|---:|---:|---:|---:|---:|
| 252-session momentum | 5 | 5371 | $-0.61 | $2.82 | 48 / 215 | $80.98 (41.31%) | 0.4921 |
| 252-session momentum | 10 | 5377 | $-2.04 | $2.82 | 48 / 215 | $81.84 (41.80%) | 0.5049 |
| 126-session momentum | 5 | 5381 | $+32.30 | $3.06 | 57 / 250 | $48.63 (26.33%) | 0.2513 |
| 126-session momentum | 10 | 5385 | $+30.42 | $3.09 | 57 / 251 | $49.33 (26.75%) | 0.2639 |
| Above 200-session SMA | 5 | 5393 | $+11.58 | $2.98 | 56 / 237 | $68.99 (34.56%) | 0.3844 |
| Above 200-session SMA | 10 | 5398 | $+9.65 | $2.99 | 56 / 235 | $69.88 (35.04%) | 0.3985 |

**Selected: 126-session positive momentum, 10 bp per side, training trial 5385.** Net +$30.421484, the highest profitable completed higher-cost result. This choice was committed in `79acf93` before final trial 5401. The 252-session variant failed the profit criterion; the SMA variant was profitable but ranked below 126-session momentum.

Selected strategy version: `cc23e1243ec9fd961e070e9ab83ecf5d7a5461a2eb3bdb9f114f3db73407d686`.

Selection receipt SHA-256: `85c1a1ec5fba8efafeb6d4a88e9f239a1666773c8a3d89bb1b7357a519920852`. The immutable receipt is `data/research/c05-total-return/selection.json`; this committed paragraph binds the sole final to that receipt and version.

Training average invested exposure was 37.39%; 4 cash-delay skip records retained. Lowest marked equity was $117.32. The $49.33 maximum peak-to-trough decline equals 35.24% of starting virtual capital; the shared permanent kill is based on loss from allocation, not loss from a profitable peak, and did not trigger.

| Selected training regime | Marked net | Max drawdown |
|---|---:|---:|
| 2008-2009 (within training) | $-4.52 | $23.97 (16.97%) |
| 2010-2019 (within training) | $+15.24 | $49.33 (26.75%) |
| 2020-2021 (within training) | $+19.69 | $14.97 (9.77%) |

The selected portfolio lost $7.45 during January–April 26, 2020, then gained $21.02 over the remainder of 2020. Full calendar-year and USO-transition-period breakdowns are in the immutable trial artifact. These are whole-portfolio calendar slices, not a claim that USO caused all returns.

Monthly luck uses a one-sided centered circular block bootstrap (3-month blocks, 10,000 draws, seed 6062026); the selected training p-value is 0.2639 across 158 months and 38 exit-month clusters. It is descriptive and unadjusted for strategy selection, not an added acceptance threshold.

Cost-free descriptive benchmarks over the same training partition: SPY +253.35%; equal-weight commodity universe −14.53%; cash 0%. They use full hypothetical exposure, so their risk differs from the strategy’s partial exposure.

Validation: 33 shared holdout/admission tests and 25 C05 source/reactor/replay checks passed. The new synthetic adapter test verifies no duplicate dividend income, no blackout orders, unchanged risk/ledger reconciliation and flat terminal positions. Fees apply the current retail scenario to virtual adjusted units, so exact historical per-share fees still require broker evidence.

## Single final result

Trial **5401**, strategy row 10183, completed once on 1,413 final-partition sessions (2021-02-16–2026-09-30), using exactly the selected training version. Both partitions warmed up independently and started with $140 virtual cash.

| Measure | Final |
|---|---:|
| Net after costs | **+$47.13 (33.66%)** |
| Current retail fee scenario | $1.74 |
| Completed round trips / fills | 34 / 162 |
| Maximum marked drawdown | $30.31 (18.25% of peak) |
| Maximum daily-close drawdown | $29.63 (17.91%) |
| Average invested exposure | 51.03% |
| Rejected orders / risk halts | 0 / 0 |
| Terminal open positions | None |

| Final regime | Marked net | Maximum drawdown |
|---|---:|---:|
| 2021 after cutoff and warm-up | $+0.13 | $17.07 (11.10%) |
| 2022 | $+9.44 | $23.19 (13.97%) |
| 2023-2026 | $+37.56 | $28.88 (14.19%) |

Final lowest marked equity was $135.74; two cash-delay skip records occurred. Terminal equity was $187.13: $130.02 settled cash plus $57.11 unsettled sale proceeds. The latter are not yet spendable cash. No separate dividend income was credited; it is embedded in total-return prices.

The final luck p-value is **null**: 34 round trips fall in only 26 independent exit-month clusters, below the existing estimator’s 30-cluster sufficiency rule. That is a reporting limitation, not an added profit or promotion filter. Cost-free descriptive final benchmarks: SPY +109.93%, equal-weight commodity universe +102.73%, cash 0%; these have full hypothetical exposure and no transaction costs.

Exactly six new training trials and one new final exist for this revision. Final admission is durably spent under `c05:revision:total_return_d267cf7`. The selected training/final version matches; prior source-failure rows 3518/5311, selected training 3959 and consumed final 3964 have unchanged full-row fingerprints. No production replay was repeated to test the guard; synthetic tests cover refusal. Final artifact SHA-256: `cbae82cd064b7cea516e739ac3f03f8d911193a3442c6f4bda7191bcf3ea35cf`.

## Promotion and account risk

The deterministic research criterion is **passed**: positive net after fees in both the frozen training winner and its single final. This is a diagnostic model re-evaluation over a previously inspected historical period, not independent confirmation of a newly discovered edge. P-values did not gate selection or acceptance.

The checklist records explicit entry/exit rules, trade counts, costs, drawdown and regime results above. Trend risk premia are allowed by amended PRD §3; the pure `CommodityTrend` reactor is unchanged. Historical drawdown is material, especially the training $49.33 decline; live gaps can exceed the modeled execution costs. Actual paper/broker execution fidelity remains unverified. This research slice takes no paper/live action and certifies no live readiness; no exact corporate-action mechanics were required to obtain these backtest results.

Funded allocation stays $0; $140 is virtual research capital. The existing shared cash book and forward experiments are unchanged. PRD §6 limits and accepted risks remain unchanged. No account, venue, key, capital, subscription or public post was added.

**What could blow up this account?** Overnight commodity gaps, fund structural changes, futures roll losses and whipsaw can overwhelm monthly trend exits. Five $28 sleeve caps bound each opening exposure but cannot guarantee timely liquidation. Gold/silver and oil/gas can become correlated, especially alongside other equity/commodity strategies. Market-at-open fills face spread and slippage; these are taker scenarios, so prediction-market maker adverse-selection controls are inapplicable. Venue outages or stale feeds can leave exposure open; unchanged shared halts and trade-only/no-withdrawal key policy remain required. Feeds are numeric data, never instructions. Adjusted total-return accounting is deterministic research, while actual broker fills, fractional units, dividends and share events still require paper evidence before promotion. Replaying a historically inspected period does not provide independent confirmation.

## Backtest → prospective paper review — 2026-10-05

Decision: **admit to paper**, $35 strategy ceiling within the existing shared $140 book, reviewer DarkMeadow under s47. The daily session authorizes this next stage. The rule remains the selected 126-session monthly trend; historical trials 5385/5401 and their consumed holdout are preserved. No live promotion is made.

Promotion checklist:

- Edge/rule: trend risk premium is allowed under amended PRD §3; explicit monthly entry/reduction and finite terminal exit are frozen in the plan. No model generates the signal.
- Profit/statistics: +$30.421484 training and +$47.127360 final after costs, 57/34 round trips. Training luck p=0.2639; final p=null because 26 exit-month clusters fall below the estimator's 30-cluster rule. This is weak statistical evidence, suitable for prospective paper observation. Drawdown and all regime results remain above. Training peak drawdown $49.33 (35.24% of starting $140) is material, although the lowest equity was $117.32 (16.20% below allocation), distinct from the unchanged 40% loss-from-allocation kill. A smaller paper slot does not improve the percentage risk.
- Fidelity: the same pure reactor runs in research and paper; actual broker shares/fills replace research total-return-equivalent units. Opening slippage, fees, cash delays and corporate actions are to be measured prospectively. Backtest-to-paper fidelity and live gap are **pending**, not certified by admission. No automatic live qualification.
- Limits/capital: all §6 limits unchanged; $35 is below currently available shared cash after costs. Other J/AI/TOM allocations and initial funding remain unchanged. Every submission rechecks shared settled cash and complete portfolio risk under the venue lock. No borrowing, new venue/account/key, capital addition, subscription or public post.

**What could blow up this account?** Tail/gap risk: overnight commodity gaps, roll losses and fund restructuring can outrun a monthly exit. A $7 sleeve ceiling bounds planned opening exposure, not gap loss or timely liquidation. Adverse selection: opening taker fills can suffer widening spreads, partial fills and informed flow; compare actual execution to the frozen reference and hold unresolved intentions. Prediction-market maker controls are inapplicable. Counterparty/venue: one Alpaca account, IEX execution quotes and Yahoo signal history can fail; accepted lack of account-wide startup reconciliation and dead-man protection remains unchanged. Existing trade-only credentials are reused. Untrusted inputs: external numeric prices and broker records are data only, with bounded parsing, timestamp/identity checks and immutable receipts. Reproducibility: coherent vintages and durable reactor state make the rule deterministic; historical final consumption is preserved. Correlation: gold/silver, oil/gas and concurrent equity positions may fall together; shared settled cash, model costs and the account daily halt constrain combined activity. Broker distributions/share events require attribution when encountered; no fabricated income is permitted, and unresolved fidelity prevents live readiness.

Admission/runtime receipts and validation will be recorded below after implementation checks; this review does not claim orders or future evidence already exist.

Implementation validation: **15 new profile tests and 94 related C05/state/source/cost regressions passed**. Tests cover the $35 slot, shared outstanding model charges, coherent monthly targets, five real-connector opening intents/fills, fee-adjusted equity, restart deduplication, unknown POST reservation/no resubmission, unavailable prices/activities, actual share-event holds without invented fills, admission failure accounting, current-session startup, and flat/held terminal liquidation. Tests use disposable database schemas and fake brokers; no production trade was created by them. Shell syntax and whitespace checks pass.

The bound-account read-only preflight passed on 2026-10-05. All five current completed closes (October 2) agreed between Yahoo and raw IEX within 1–5 bp, inside the preregistered 1% operational bound. Source receipt: `data/forward/c05-total-return/20261005T152755-prices-c6505bfb56/prices.json`, SHA-256 `6b8faa501c2c5d41630bb8ad803c8b48e337bb803f450082ec59708092d7fd06`. The initial probe retained an incomplete current-day bar and correctly refused it; the final query ends at midnight after the selected completed session. Paginated broker-activity capture returned zero records and exhausted normally (`20261005T152817-activities-6ec0efb0d4/activities.json`, SHA-256 `a47b4719da1fbc5d2036d68f3b3b32ec1a7839a517c1be6906fe0a1de664e737`). Zero records is not a claim that no economic entitlement exists.

Alpaca's [activity documentation](https://docs.alpaca.markets/us/docs/account-activities) describes actual nontrade records and pagination. Its [paper specification](https://docs.alpaca.markets/us/docs/paper-trading) excludes regulatory fees and dividends from the simulation. Thus modeled fees are retained explicitly, dividend/share-credit fidelity remains unresolved, and the runner cannot certify live readiness from paper P&L alone. No issuer website review blocks starting the prospective experiment.

**Admitted and running:** paper trial **7852**, strategy **18288**, selected research version `cc23e124…`, executable commit `74895ae`, $35 ceiling. Initial paper close-source receipt is `20261005T153536-prices-76b2f03807/prices.json` (SHA-256 `e74a2724a3af8ab22a3042e6490beb7dc62d19f526d85cb15b9fe8820fd168bc`). The full before/after audit lives in `data/forward/c05-total-return/20261005T153531-admission-1fa9316360/`; checks receipt SHA-256 `05e60f4cc9697ad5fb0d7b568756e348a836ee85b06be626f2cc39959eb0efe7`. Initial $140 cash, account guard, every existing allocation and frozen paper identity, and full rows for prior trials 3518/5311/3959/3964/5385/5401 were unchanged.

The registered `ops/c05_paper.sh` service owns the trial singleton in tmux `tradingbot:services` pane `%116` (launcher PID 59723). Re-running `ops/services.sh` added no duplicate and left every existing launcher intact. Health checks through 15:41 UTC report `observing`, enabled, no hold, current source/plan/code bindings valid, exactly one running C05 profile and zero C05 orders/fills/positions. Today's already elapsed opening is recorded as missed; today's future close is eligible for observation. The first prospective monthly decision is **2026-10-30 close**, with any purchases at **2026-11-02 open**; terminal liquidation remains **2027-01-04 open**. Forward outcomes and live readiness are pending.
