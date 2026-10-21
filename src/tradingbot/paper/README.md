# Forward paper runtime

`PaperEngine` runs the existing `Strategy` / `StrategyContext` contract over the
PM US recorder's committed live rows. It uses the shared trade-through matcher,
ledger and unchanged §6 risk engine. It makes **no broker API calls**.
Alpaca paper execution remains in `connectors/alpaca_paper.py`; Kalshi is research-only.

Start only with an existing paper strategy, a positive recorded allocation and
an explicitly reviewed standard-fee, non-sports binary instrument universe.
Category checks catch missing/sports labels, but do not replace that review.
The runtime does not allocate capital, promote a strategy or claim proof of alpha.

```python
from tradingbot.db.session import SessionLocal
from tradingbot.paper import PaperEngine

# strategy is the same Strategy instance/class used by the backtester.
with SessionLocal() as session:
    engine = PaperEngine(session, strategy, strategy_id=strategy_id,
                         instrument_ids=reviewed_instrument_ids)
    trial_id = engine.start(git_commit=commit)
    engine.poll()  # call periodically; processes bounded recorder batches
```

The session must be dedicated to the engine: it owns commit and rollback.
Call `poll()` periodically even during quiet feeds; it refreshes P&L halts.
The foreground CLI imports a registered strategy and starts a new trial:

```sh
uv run python -m tradingbot.paper --help
# Supply --strategy-module, --strategy-key, --strategy-id, repeated
# --instrument-id and optional --params '{...}' with real reviewed values.
```

No strategy or paper run is enabled automatically. A current dated positive
USD/GBP observation in `fx_rates` is required for each fill. Every attempted
variant gets a trial before callbacks/validation, including failed attempts.
Rejections and fills stay in the shared ledger, tagged `mode=paper`.

## Execution evidence

- A maker BUY fills at its posted limit only on a strictly lower public trade;
  a maker SELL requires a strictly higher trade. Touches never count.
- The venue's `trade_time` must be strictly later than the order's submission
  clock and no later than receipt. Receipt must be within the existing 30-second
  limit. Unknown venue times and delayed pre-submission prints cannot fill.
- Only live `source=trade` rows are eligible. Historical observations, quote
  crossings, marks and recorder keepalives cannot manufacture maker fills.
- Known aggressor direction must oppose the resting side. Public trade size
  is shared across eligible orders and paper trials, with price/time priority
  inside a trial. Concurrent trials are serialized by the venue row; cross-trial
  priority follows polling order, not a claim about exchange queue position.
- Native trade IDs, or conservative timestamp/price/size fingerprints when
  IDs are absent, prevent reconnect duplicates from multiplying consumed volume.
  Identical prints without IDs may be collapsed; this undercounts possible fills.
- Strategy callbacks run **after** existing orders are matched. An order cannot
  fill on the print that caused its placement.
- Takers require a fresh executable opposite BBO, known displayed size and a
  limit permitting that price. They consume observed depth once per book/side;
  repeated identical books/keepalives cannot replenish it. There is no mid/last
  fallback. Unfilled taker quantity is explicitly immediate-or-cancel in paper.
  Maker orders that cross a known fresh BBO are rejected.

Current exact standard PM US fees/rebates use `pm-us-standard-2026-09-25`.
Order fee state is reconstructed from persisted fills on each execution so
rollback/restart cannot change cumulative rounding. Fills record the applicable
schedule, signed fee, USD/GBP rate and supporting recorder evidence.
This is a conservative simulator, not proof of queue priority, rewards income,
market eligibility, future fee terms or real exchange execution.

## Risk, durability and lifecycle

Risk is refreshed and its veto applied before placements and each fill, then
refreshed after fills. Pending orders across strategies/outcomes reserve the
same $25 per-market cap; opposite quotes cannot be presumed to offset first.
Binary short exposure uses the possible payout liability (`1 - price`), so a
low sale price cannot hide a large loss at resolution.
The separate BBO clock prevents a new trade from making an old quote executable.
API error counts follow the existing RiskEngine's process-local behavior; the
DB-fed runtime itself does not call venue APIs or inherit recorder error counts.

Each event commits orders, fills and its cursor atomically. Feed cursors assume
one ordered recorder writer per channel. Older arrivals are consumed without
rewinding context; late commits behind an advanced ID are conservatively skipped.
Keep a single strategy process per trial. Postgres locking protects accounting
and volume consumption, not arbitrary in-memory strategy state.

Stopping the CLI/process leaves the trial running and all maker orders intact.
There is no startup reconciliation, dead-man cancellation or maker expiry.
To resume, restore the strategy's own state, construct a new engine, and call
`resume(trial_id, strategy_state_restored=True)`. It validates the parameters,
universe, strategy key and fee schedule, restores local context/cursors/orders,
and does not call `on_start` again. The caller must actually restore any custom
strategy state; the boolean does not do that work. The CLI only starts new trials.

A callback/accounting failure rolls back the entire current event, finalizes
the trial as failed and logs an incident using the exception type. Previously
committed orders remain recorded and unmanaged; investigate before any explicit
manual continuation or cancellation. Starting another trial cannot take them
over. `finish()` succeeds only once orders and strategy positions are flat, and
records ledger P&L after fees, trade count and luck odds. Settlement is not
invented from a price; resolution handling belongs to explicit venue lifecycle
work. Open positions are not reported as a completed profitable experiment.

Verification: `uv run pytest tests/paper -q`. DB integration fixtures use an outer
transaction plus nested savepoints and assert that the outer rollback remains
active. No test submits a venue order or leaves strategy/trial/ledger fixtures.
