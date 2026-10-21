# Locked historical evaluation

PRD §4 reserves the last 30% of each dataset, by elapsed UTC time, for one final
evaluation per strategy version. The split uses full source coverage, with an
exclusive end. It is not a 70/30 row count and must not be recomputed from the
selected training slice. `HoldoutSplit` derives the cutoff with integer
microseconds; `backtest_datasets` pins those bounds to the dataset key. An
attempt to change an existing key's bounds is refused.

```python
from tradingbot.backtest import Backtester, market_events
from tradingbot.backtest.holdout import HoldoutSplit

split = HoldoutSplit(source_fingerprint, full_source_start, full_source_end)
training = market_events(session, instrument_ids,
                         start=split.data_start, end=split.holdout_start)
result = Backtester(session, strategy=frozen_strategy, strategy_id=sid).run(
    training, split=split, version_params={"slippage_bp": 2},
)
session.commit()
```

All events and settlement labels must lie in the selected partition. The engine
validates them before calling the strategy. A normal run refuses timestamps
equal to or later than the cutoff; an explicit final run refuses timestamps
before the cutoff or at/after the source end. Input order must be chronological.
Every new replay trial records `dataset_key`, `holdout_start`, `strategy_version`,
`final_holdout` and full split/code/parameter provenance in `params._holdout`.
Older trials are retained as legacy results; they do not become holdout proof.

Once tuning is complete, commit the research strategy and training result, start
with a fresh flat book and fresh strategy instance, and explicitly evaluate the
frozen version:

```python
held_out = market_events(session, instrument_ids,
                        start=split.holdout_start, end=split.data_end)
result = Backtester(session, strategy=fresh_frozen_strategy, strategy_id=sid).run(
    held_out, split=split, final_holdout=True, version_params={"slippage_bp": 2},
)
session.commit()
```

The version hashes the actual strategy/runtime source files, shared execution,
fee, ledger and risk code, `Strategy.params`, and the execution `version_params`.
Put every decision setting in `Strategy.params`; `ctx.params` exposes that same
configuration. The `run(params=...)` argument stores audit metadata only, so a
new report/run ID cannot grant another final attempt. Runtime wrappers preserve
the underlying strategy identity. Frozen calendar schedules and cash-bucket
assignments stay the same between training and holdout. Do not change parameters
after looking at held-out results and describe them as an untouched test.

Final admission commits a trial in a separate transaction **before the replay
consumes its event iterable**. A transaction advisory lock and a unique partial
index permit only one final trial per version, across processes, dataset/run
names and research strategy row IDs. Reusing a version is refused before the
feed is consumed and writes an `incidents` row (`category=other`,
`details.kind=holdout_reuse`) in its own committed transaction. Rolling back the
caller cannot erase that incident or restore the allowance. An interrupted or
rolled-back attempt remains consumed; its durable trial may remain `running`
without completed metrics. Resolve such incidents as failed evidence, not a
reason to delete the trial and rerun. Source validation failures before calling
the replay are not performance evaluations.

Normal trial/result transactions remain caller-owned. Commit a failed normal
trial when handling a replay error, or log a replacement failure as the existing
equity drivers do. Final evaluation needs an already committed strategy row and
dataset/training transaction; uncommitted fixtures cannot be claimed from the
independent audit connection.

The TOM and LETF drivers derive the split from full archived daily-bar coverage,
filter to complete cycles/sessions in the requested partition, and leave cycles
crossing the boundary out. Their normal CLI runs evaluate training only. Final
runs require both `--final-holdout` and one `--variant`; the parameter sweep is
never run implicitly on the final slice. The longshot CLI requires
`--dataset-key`, `--data-start` and `--data-end`; a final run also requires one
`--side-rule` and `--offset`. It scores only markets with observed resolution
times inside the partition, never a scheduled close used as a payout timestamp.

Profit after fees must be positive in both partitions before promotion, with
drawdown and regime reporting under the promotion checklist. These guards do
not grant promotion or make a previously inspected holdout unseen. Existing
full-period research already viewed the old data; its last 30% is contaminated
for claims of a fresh holdout. AI-decided strategies require the separate
7-calendar-day/30-trade forward-paper proof specified by PRD §4.

Validation uses synthetic datasets only:

```sh
uv run alembic upgrade head
uv run pytest tests/backtest tests/research/test_equity_runtime.py -q
```

## Family holdout reuse (u1h)

A new code hash or parameter choice does **not** restore the test allowance.
`family_holdout_spends` records each final admission with its canonical research
family and the full declared source interval. Before consuming a final feed,
admission rejects overlap between the proposed holdout and any source interval
already consumed by that family. It also rejects overlap with the family's
committed training trials that have locked dataset bounds. Comparison uses UTC
half-open intervals, independent of dataset names, vendors, symbols and selected
trade dates. A holdout starting exactly at an earlier source's exclusive end is
eligible for a **new version**, subject to all other evidence checks.

Candidate amendments/versions retain the root family: `C04-readmission` and
`sweep_c04_inverse_variance_readmission_v2` both mean `c04`. TOM's random-window
control belongs to `turn_of_month`, so its diagnostic cannot supply a second
independent test allowance. Existing longshot, LETF and rewards keys also map
explicitly. For a new family, declare a stable identifier on the committed
strategy row before final admission:

```python
row.config = {**(row.config or {}), "research_family": "my_preregistered_family"}
session.commit()
```

Every successor and renamed implementation must retain this declaration.
Missing/conflicting declarations fail closed. `holdout_family_aliases` pins
strategy row IDs and reactor names to their family; reuse of either under a
new family is refused, and database triggers prohibit updating bindings or
receipts. These declarations encode research lineage; they cannot infer that
an arbitrarily rewritten and renamed algorithm is secretly the same idea.
Inventing a new family label to reuse evidence violates the research protocol.

A short shared transaction lock covers final version admission, family aliases,
and date checks across processes. The final trial and family receipt commit
together before loading the iterable. Refusal incidents also commit separately
from the caller: `holdout_reuse`, `holdout_family_reuse`,
`holdout_family_training_overlap`, or `holdout_admission_refused`. A failed,
empty, partial or interrupted final consumes the full declared coverage.

Migration `bcf10a202601` backfills all existing finals from immutable dataset
bounds, without changing old trial rows or their hashes. Unknown/conflicting
legacy identities stop migration for review. A final inserted by older code
without a family receipt blocks further admissions pending an audit; it is
never silently treated as fresh. The migration cannot be downgraded while any
family spend exists. Do not rerun an old final because shared infrastructure
hashes changed.

Training still follows the existing caller-owned ledger transaction: commit
all attempted variants, including failures, before final admission. Unlogged,
rolled-back, concurrent or externally inspected training cannot be certified
unseen by a database lookup. Legacy full-period results likewise remain
contaminated; passing this guard alone is not a claim of untouched evidence or
promotion. Successors can instead use newly collected forward-paper data under
the existing forward protocol; AI-decided strategies retain the separate
7-day/30-trade requirement. No risk limits or promotion thresholds changed.
