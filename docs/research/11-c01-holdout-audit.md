# C01 evidence audit: original PRD §4 pass withdrawn

Bead `tradingbot-bbw`, 2026-09-30 Pacific / 2026-10-01 UTC.
**FAILED_AUDIT. C01 remains in research; no paper/live promotion.**
This is a code and stored-evidence audit, not another strategy replay.

The original runner and report were committed at
`f43aacb0833710322585692d25454d4317f15746`. The original results JSON SHA-256 was
`e9fff236b7ea9a3194af18143bb1d9d0b52c39860db08f51913aa4daaf3f9241`.
Its six training results and final numerical result are preserved. The prior
verdict is retained as `original_verdict`; the current verdict is failed audit.
The [original-results report](09-c01-spy-monthly-trend.md) now labels its tables
as legacy outputs rather than validated performance.

## Confirmed failures

| Requirement | Original implementation / stored evidence | Consequence |
|---|---|---|
| Durable admission before final consumption | `main` called `C01Backtester(...).run(hold_bars)` before `claim_final`; the `HoldoutViolation` handler reused a trial ID with the newly computed result | Repeat invocations could consume the final sample again; the original single-use claim is not valid |
| Shared Strategy, RiskEngine and execution Ledger | `SpyMonthlyTrend` is a standalone dataclass; `C01Backtester` maintains local cash/shares and writes only summary Trial rows | No shared order/fill risk vetoes, execution receipts or dated FX records; hashing risk source files does not execute their checks |
| Position cap at the recorded allocation | Strategy 5080 has allocation $140; entry uses 95% of compounded equity without applying the slot cap | Stored selected training trades contain eight buys above $140, largest $414.95602942128295; final trades contain three, largest $186.07004040625 |
| Actual dividend entitlement and payment dates | Each daily walk credits whichever shares remain after that month's opening trade; payment is ex-date +30 calendar days, with all outstanding amounts paid at terminal | A buy on the ex-date can receive an unearned dividend; an exit on the ex-date can lose an earned one; cash availability is invented |
| Validated T+1 banking calendar | Sales become pending for `trade_date + timedelta(days=1)`; no banking-calendar lookup | Calendar-day arithmetic does not establish the required settlement date. The cash-delay counter also compares `spendable` to its own defining expression minus one cent, an impossible condition |
| Causal and reconciled terminal/risk metrics | The daily equity curve includes the final session's close, then a sale is applied retrospectively at that session's open; the curve is not reconciled to final cash and fees | Terminal drawdown, exposure, yearly/monthly statistics and final realized value describe different paths |
| Causal benchmark drawdown | `_benchmarks` adds the sum of **all** sample dividends to cash at **every** historical mark | Future dividend cash distorts the benchmark drawdown comparison; the old “same drawdown/no alpha” quantitative claim is not validated |
| Fail-closed source validation and identity | Coverage returns diagnostics but the runner does not reject them; the available cross-check function is never called; the frozen code list omits `free_history.py` and `research/equity_fees.py`; dataset key does not bind archive SHA | Stated independent validation and complete executable/data provenance were not established |
| Honest consumption history | The original report states that a serialization failure preceded the canonical run and earlier trials were cleared | Determinism does not erase prior consumption. This audit cannot reconstruct every deleted attempt and does not claim the surviving final is the first observation |

The slot examples above are read from the saved trade arrays, not recomputed
orders. These failures are enough to withdraw the pass claim regardless of the
stored profit. Their exact effect on a compliant model's profit, drawdown or
ranking is unknown; none has been estimated by rerunning the consumed sample.

The shared [C04 audit](11-c04-inverse-variance-results.md) separately found an
issuer dividend-date inconsistency and unreconciled IEX/SIP closing-price
bases. The [C02 audit](12-c02-source-audit.md) found contradictory historical
settlement data. Neither investigation authorizes a payment-date proxy,
weekday-only banking calendar, tolerance change or hidden source substitution
for C01.

`tradingbot-900` is separately repairing those source problems. Its later
auction-trade and primary dividend-date evidence may resolve parts of the data
audit, but does not retroactively validate C01's simulator or reopen its final.

## Repair and containment

The final-admission primitive now uses a lazy feed factory: it commits
`claim_final` **before** invoking the loader or simulator. A prior consumed
candidate/dataset is rendered from the ledger before any new source hash or
feed is evaluated, so this repair's changed code hash cannot recycle C01's
sample. Failed and interrupted admissions remain consumed, including a process
lost while its trial is still `running`. Exceptions retain their type without
storing private exception text. New synthetic test receipts retain JSON-safe
trade details; missing details in old trials are explicitly marked unavailable.

The real C01 CLI is now an **archive reader**. It never loads market prices,
trains, selects or replays. Legacy `--capture`, `--no-ledger` and `--no-holdout`
replay flags fail before database access. The standalone legacy simulator is
retained for forensic/synthetic tests; it is not a compliant execution adapter.
Its real-data route stays disabled while these findings remain unresolved.
The lower-level admission primitive is tested with synthetic data, not used to
run another real experiment.

```sh
uv run python -m tradingbot.research.c01_spy_monthly_trend --stored-trial-id 3319
# Optional: write stored facts to a NEW file; existing files are never replaced.
uv run python -m tradingbot.research.c01_spy_monthly_trend \
  --stored-trial-id 3319 --out /tmp/c01-stored-evidence.json
```

Original trials **3313–3319**, including consumed final **3319**, retain their
status, parameters, code versions, timestamps and numerical fields. No trial is
deleted or relabelled unused. An audit annotation in the strategy's research
configuration and a separate incident link the failed evidence to this report;
the original trial rows remain unchanged. A canonical full-row snapshot was
taken before edits and compared after the metadata annotation.
The [audit receipt](11-c01-holdout-audit.json) records matching SHA-256 hashes
`6379a6d18f5bf2437ff1bab44229a86cc9d9e96db8665a15d6b36278327646db`
and incident **920**. Strategy 5080 remains `backtest` with allocation $140;
only its evidence-audit configuration was added. The repair is `0f08a9b`.

No risk constant, allocation, account, key, order or strategy activation changes.
All tests use synthetic data; committed admission fixtures have unique test
IDs and are cleaned up without touching research trials.
Validation: 17 C01 tests and nine shared holdout tests pass. The real CLI was
checked against stored final 3319 and reported `replayed: false` / failed audit.

## Remaining evidence needed for any future study

Any later implementation must use the common Strategy/RiskEngine/Ledger path,
validated settlement and corporate-action data, correct ex-date entitlement,
slot-limited orders and reconciled causal marking. That is a separate study,
with a new preregistered **unseen** evaluation period. Fixing code or renaming
the dataset does not make 2006–September 2026 unseen again. Retain the original
failed evidence and the consumed final permanently.

The written account-risk decision remains **hold in research**: equity gaps,
trend reversals and common SPY exposure still threaten the allocation, and this
model did not enforce the hard limits that would constrain those losses.
The evidence does not justify paper/live promotion or a claim of alpha.
