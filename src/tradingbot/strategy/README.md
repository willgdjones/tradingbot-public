# Strategy interface + backtester (`tradingbot-ltj`)

One contract, one code path for backtest, paper and live (PRD §4, §7). A strategy
is written **once** and the runtime (backtester now; paper/live later) drives it
through the identical `StrategyContext`.

## Writing a strategy

One file per strategy. Subclass `Strategy`, set a unique `key`, implement
`on_event`, and register it:

```python
from tradingbot.db import enums
from tradingbot.strategy import PlaceOrder, Strategy
from tradingbot.strategy.registry import register

@register
class MyStrategy(Strategy):
    key = "my_strategy"

    def on_event(self, ctx, event):
        snap = ctx.snapshot(event.instrument_id)
        if ctx.position(event.instrument_id) == 0 and snap and snap.reference_price:
            return [PlaceOrder(
                instrument_id=event.instrument_id, side=enums.Side.BUY,
                size=Decimal("10"), limit_price=snap.reference_price * Decimal("0.95"),
                intended_liquidity=enums.Liquidity.MAKER, tag="entry",
            )]
        return []
```

Rules that keep the three modes identical:

- The strategy is a **pure reactor**: given a context and a `MarketEvent`, return
  `Intent`s. No I/O, no clock, no venue or mode knowledge. Any state it keeps is
  derived from what it has been shown.
- All prices are `Decimal`; tolerate `None` book fields (historical display /
  sampled prices carry no executable BBO — see `../data/LOADING.md`).
- Sizing and pricing are only *requests*. The risk engine (§6) has an absolute
  veto the runtime applies before anything reaches a book, in every mode.

The context exposes `now`, `mode`, `params`, `position(iid)`, `snapshot(iid)` and
`resting_tags(iid)`. Cancel a resting order with `CancelOrder(tag)`.

## Running a backtest

The backtester (`tradingbot.backtest`) replays a time-ordered `MarketEvent`
stream and routes every intent through the **same** risk gate and ledger the live
path uses, so fees, positions, P&L and the luck p-value come from the one source
of truth, and every run — including losers — is written to the `trials` ledger.

```python
from tradingbot.backtest import Backtester, market_events
from tradingbot.backtest.holdout import HoldoutSplit

split = HoldoutSplit("source-content-sha256", full_source_start, full_source_end)
bt = Backtester(session, strategy=MyStrategy(), strategy_id=sid)
result = bt.run(
    market_events(session, instrument_ids, start=split.data_start, end=split.holdout_start),
    split=split,
)
print(result.report)          # pnl_after_fees, trade_count, luck_p_value, ...
```

Every replay requires the full dataset's locked 70/30 time split. Ordinary runs
refuse events **and settlements** at or after `holdout_start`; a caller must
choose the training slice explicitly. The [holdout workflow](../backtest/README.md)
describes the durable, single-use `final_holdout=True` run and its incident log.

### Fill model (PRD §7)

A resting **maker** order fills only when a later public trade goes *strictly
through* its price (buy fills below the limit, sell above), at the resting limit
price, capped by the trade's size. A **taker/market** order crosses to the far
touch. Display/sampled price observations are marks, never executable trades, so
they never fill a maker (`maker_fill_eligible` gates this in the feed).

Scope note: `positions` is keyed by (strategy, mode, instrument), not by trial, so
a backtest run assumes it starts flat for that scope — run backtests in isolation
(a fresh/rolled-back DB, or distinct strategies). The paper/live runtimes share
one real book, which is correct there.
