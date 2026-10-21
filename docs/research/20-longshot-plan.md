# Strategy #1 — full-history replay preregistration

Recorded 2026-10-01 for `tradingbot-yg2`, before computing any strategy returns
on the expanded cohort. The [capture audit](08-history-capture.md) and its JSON
are the source contract. This is research while prediction venues await owner
verification; international history and a PM US fee counterfactual cannot prove
PM US execution quality.

## Fixed data and partitions

- Keep the exact 37,384-contract cohort with SHA-256
  `35c64518ea06b437e6c4a614d43f1650333ac5e9c66da7800825e7b7700be0d9`.
  Do not substitute dates, strikes, series or venues after seeing returns.
- Evaluate the five captured venue/category pairs separately. Each category is
  an alternative deployment of a virtual $140 slot, not five funded portfolios
  whose profits can be added together.
- Pin one common elapsed-time 70/30 split to the full cohort's observed tape and
  terminal timestamps, before exclusions: start `2025-08-29T15:15:47Z`, exclusive
  end `2026-09-30T23:01:46.460587Z`. The end is one microsecond after the last
  observed terminal timestamp. The cutoff is `2026-06-03T18:17:58.622410Z`.
  These include pre-close August observations; the scheduled-close cohort still
  spans September 2025 through September 2026.
- A contract belongs to a partition only when both its scheduled close and
  actual resolution are in that partition. Exclude boundary-crossing contracts
  from both partitions and enumerate them; never shorten the full dataset to
  change the cutoff. No held-out prices may be read by a replay before durable
  final admission. Source completeness/schema audits are separate from returns.
- Use per-instrument Kalshi catalog times, not its event-level market row's
  aggregate dates. For PM, use its condition's catalog times and observed
  lifecycle resolution timestamp. Bind the chosen reference fields and source
  receipts into a frozen manifest before execution.

## Source exclusions and trading windows

- Exclude the one PM condition with two uncertified payout labels, the eleven
  PM weather conditions with reversed opening/closing times, and all thirty
  contracts of the documented off-session `KXINX-26JAN19H1600` event. Exclude
  missing/invalid opening, close or terminal timestamps and incomplete binary
  payout pairs, with explicit reasons. Preserve every original source record.
- The five positive-volume empty Kalshi tapes and the 16,098 exact zero-volume
  skips remain coverage observations. They cannot generate hypothetical fills.
  Other documented catalog gaps remain gaps; no replacement selection.
- Entry eligibility uses the public scheduled close: from the later of opening,
  scheduled close minus seven days, and partition start, until five minutes
  before scheduled close. Actual terminal resolution closes positions when it
  occurs. It never moves the entry window backwards using future knowledge.
  Keep and report delayed settlements and any actual holding period over seven
  days; the evidence cannot pass the seven-day mandate if such a breach occurs.
- A binary contract is the pair of yes/no outcomes, not all strikes in a Kalshi
  event. The strategy's one-side commitment and fill cap apply to that pair.
  Sibling strikes and common event/date outcomes remain correlated for reporting.
- Replay only the audited matched Kalshi and PM taker-history prints. Display
  prices and mixed maker/taker feeds cannot fill makers. Use exact source prices;
  round available execution quantity down to the ledger's supported quantity
  precision, never up. State and reconcile any accounting-column rounding.

## Frozen strategy and execution

- Run the existing `FavouriteLongshotBias` reactor with the six combinations of
  `buy_favourite` / `sell_longshot` and offsets 0.01 / 0.02 / 0.05. Fixed settings:
  size 10, threshold 0.5, reference band 0.03–0.97, tick 0.01, maximum three fills
  per binary contract, 300-second scheduled-event blackout. No extra grid.
- Maker orders require a strictly later timestamp and a strictly through-price
  trade. Equal-time database ordering cannot establish a fill. Cap fills at
  observed trade volume. Blackout callbacks cancel orders even on quiet tapes;
  terminal settlement cancels remaining orders and applies at its actual time.
- Use the existing current PM US fee coefficients and exact per-order fee model,
  explicitly counterfactual on both source venues. Settlement is fee-free.
  Report gross P&L, fees/rebates and net P&L separately. No rewards are invented.
- Require fully funded binary collateral for held and pending exposure, bounded
  by the $140 virtual book. Fully collateralize a short's possible liability;
  do not treat its sale proceeds as free capital. Enforce the existing $25
  prediction-market limit across a contract's held and pending outcomes. The
  shared risk engine remains an absolute veto; no PRD §6 constants change.
- Mark only from observations already processed. Track UTC-day equity changes,
  including carried positions, and permanent per-strategy loss in the simulated
  run. Apply the unchanged −$50 daily halt and −40% slot kill, record their
  timestamps, and cancel resting orders on a simulated halt. Terminal settlement
  remains accounting, including after a halt. Never write a live kill/halt.
- Start every variant and final flat with $140 virtual collateral. Retain every
  variant, including failures and zero-fill runs, in the trials ledger. Preserve
  the six earlier one-market trials and their provenance. Orders/fills can be
  isolated with rollback, but save compact execution/metric receipts first.

## Selection, statistics and decision

- Tune only on training. Per category, choose the positive-net variant with the
  largest after-fee training P&L; require at least one completed trade. Ties use
  the declared side order above, then ascending offset. If none is profitable,
  record failure and do not consume a final. Commit the frozen selection and
  training evidence before its single final evaluation.
- The final uses exactly that category's frozen code, parameters, reference
  mapping and execution scenario. Admission commits before price-feed access;
  failures/interruption remain consumed. A repeated invocation must report stored
  facts or refuse, never recompute the holdout or change identity to rescue it.
- Report trade/fill counts, unique traded contracts/events/calendar dates, gross
  and net P&L, fees, marked peak-to-trough drawdown and its fraction of $140,
  realized drawdown, open/terminal positions, rejected orders and risk halts.
- Report calendar-month and quarter performance, plus fixed entry-price bands
  0.03–0.30 / 0.30–0.50 / 0.50–0.70 / 0.70–0.90 / 0.90–0.97. Call calendar
  buckets calendar regimes, not independently verified economic regimes.
- Show the existing per-round-trip one-sided zero-edge p-value and a second
  p-value on UTC-date-aggregated net outcomes, with sample counts and explicit
  serial-dependence/selection caveats. Do not count sibling strikes, Kalshi
  yes/no projections, or cross-venue duplicates as independent evidence. Neither
  p-value is the probability a hypothesis is true or an extra promotion gate.
- Profit must be positive in training and the once-only final, with valid risk,
  fill and accounting evidence, before any historical pass. Calendar fragility,
  delayed holds, absent point-in-time catalog history and venue/fee transfer
  remain practical limitations. Complete the promotion checklist and written
  account-risk review with the results. No funding, keys, live orders or public
  publication belongs to this bead.

## Preparation checks

The generic runner previously loaded final prices before admission, allowed
same-timestamp maker fills and deferred all settlements until after the tape.
Repair and validate these with synthetic data before real returns. Also test
binary collateral/pending reservations, quiet-tape blackouts, overnight/day loss
accounting, permanent kills, exact source selection, partition boundaries,
interruption/reuse handling and ledger/result reconciliation. Keep capture's
20 GB `data/` ceiling and 30 GB free-space abort floor for derived artifacts.
