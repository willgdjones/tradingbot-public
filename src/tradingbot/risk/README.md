# `tradingbot.risk` — hard risk limits with absolute veto (PRD §6)

The risk engine is the final say on every order. Its limits are **hard-coded
constants** in `limits.py` and **must never be changed without explicit owner
approval** (AGENTS.md). PRD §9 accepts that the only guardrail on the limits
themselves is process — do not add config, env, or model control over them.

## The five limits (PRD §6)

| Limit | Constant | Value |
|---|---|---|
| Per-strategy kill (permanent) | `PER_STRATEGY_KILL_FRACTION` | −40% of allocation |
| Global daily halt | `GLOBAL_DAILY_HALT_USD` | −$50 in one day |
| Per-market position cap | `PER_MARKET_POSITION_MAX_USD` | $25 |
| Stale data | `STALE_DATA_MAX_SECONDS` | 30s |
| API errors | `API_ERROR_MAX_PER_MINUTE` | 5 / minute |

## Usage

```python
from tradingbot.risk import RiskEngine

eng = RiskEngine(session)

# 1. Pre-trade gate — the execution layer MUST obey this before every order.
decision = eng.evaluate_order(
    instrument_id=iid, mode="live", side="buy", size=Decimal("10"),
    price=Decimal("0.40"), strategy_id=sid,
)
if not decision.allowed:
    ...  # do NOT place the order; decision.reasons explains why

# 2. Periodic re-evaluation — trips the daily halt and per-strategy kills.
tripped = eng.refresh_halts("live", marks={iid: last_price})  # marks optional

# 3. Connectors report API errors so the 5/min halt can fire.
eng.record_api_error()
```

`evaluate_order` checks (in order): strategy killed → global daily halt active →
API-error halt → stale data → $25 position cap. `refresh_halts` recomputes P&L
(realized-after-fees from the ledger, plus open unrealized when `marks` are
given) and persists any halt to `risk_halts` while logging an `incidents` row, so
a permanent kill and the daily halt survive a restart. Days are bounded in UTC.

The `test_limits_match_prd_section_6` canary fails loudly if any §6 value is
edited — a tripwire, not a substitute for owner approval.
