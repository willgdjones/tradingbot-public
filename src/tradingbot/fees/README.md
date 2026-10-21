# Fee models

All public monetary amounts are USD `Decimal`. Positive `net_fee` is an expense;
negative is a credited maker rebate. Inputs accept decimal strings or integers
as well, but reject floats, booleans, nonfinite values and invalid fills.
Arithmetic and rounding do not depend on the ambient Decimal context.

Create **one model instance per venue order**, and feed executions once, in
execution order. A new instance resets the rounding accumulator. These objects
calculate fees; they do not submit trades, persist records or reconcile accounts.
The ledger must retain the actual exchange-reported fee and the model's schedule
ID. Never overwrite a reported charge with an estimate.

```python
from datetime import datetime, timezone
from decimal import Decimal
from tradingbot.fees import (
    FeeFill, Liquidity, Side, PolymarketUSOrderFees, PM_US_STANDARD_2026_09_25,
)

fees = PolymarketUSOrderFees(PM_US_STANDARD_2026_09_25)
execution = FeeFill(
    price=Decimal("0.50"), quantity=Decimal("100"),
    liquidity=Liquidity.TAKER, side=Side.BUY,
    executed_at=datetime(2026, 9, 30, tzinfo=timezone.utc),
)
assert fees.charge(execution).net_fee == Decimal("1.74")
```

## Scope and selection

- `PolymarketUSOrderFees`: standard US CLOB schedule, with a dated preset effective
  September 25, 2026. The caller must verify the instrument uses that policy.
  Combos, sports-specific exceptions, block trades, negotiated fees and the
  international venue are not supported by this preset. Fee policy eligibility
  does not authorize a strategy or market under the PRD.
- `KalshiOrderFees`: research-only quadratic fees. Require an explicit
  `KalshiSchedule(schedule_id, effective_from, taker_multiplier, maker_multiplier)`
  and `balance_precision=Decimal("0.0001")` (direct) or `Decimal("0.01")` (FCM).
  General multipliers are taker 1 / maker 0; maker fees and exceptions require
  separately verified inputs. Resolve series changes and event overrides at each
  execution time upstream. Do not assume all makers are free or reuse the taker
  multiplier for makers. Non-quadratic products require another model.
- Schedules reject fills outside their effective interval (`effective_until` is
  exclusive). An open-ended schedule means no end has been supplied, not that
  the published terms can never change. Refresh source evidence before use.
- Kalshi's current rounding engine is documented without a historical activation
  date. Its applicability to older fills is an explicit research assumption until
  supported by dated evidence. Public history lacks enough account/order details
  to reconstruct every actual charge; state the chosen clearing/fill assumptions
  in the trial ledger. No fabricated automatic historical policy lookup is used.

`FeeBreakdown` exposes the exact model fee, rounded trade fee, balance-rounding
fee and rounding refund/cap adjustment. `net_fee` combines those components.
PM US weekly volume rebates and liquidity incentives are separate account
credits: no presumed reward is included in `net_fee`. Canceled unfilled orders
have no execution and must not be sent to `charge`.

For `FeeFill`, price and side refer to the contract actually traded, so Kalshi's
signed cash revenue is `-price * quantity` for a purchase and positive for a sale.
Adapters must normalize YES/NO conventions and fixed-point quantities first.
`decode_commission` handles US execution-report fee scales with explicit scale
inputs. It is not a general purpose API parser.

Source links, publication discrepancy and operational implications:
[open-item research](../../../docs/research/04-open-items.md).
Run `uv run pytest tests/fees -q` for the venue examples and rounding regressions.
