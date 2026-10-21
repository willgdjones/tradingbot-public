# Alpaca paper connector

`tradingbot.connectors.alpaca_paper.AlpacaPaperConnector` implements bead
`tradingbot-7mr` on the existing `Ledger` and `RiskEngine`. Its transport uses
official `alpaca-py`, always with the paper trading URL. `.env` credentials are
`ALPACA_PAPER_KEY` and `ALPACA_PAPER_SECRET`, loaded by python-dotenv. A live URL
environment override cannot change the transport's endpoint. No account setup,
configuration, funding, withdrawal, reset or live trading methods are exposed.

## Cash and risk contract

Alpaca paper accounts simulate margin. This adapter applies a **local cash-only
book**; it does not change the broker account type. A once-only explicit virtual
budget is required. It is never inferred from the paper account's default balance
or multiplier. Initialization must use an intended, already-settled paper budget
on an otherwise unused account. Unmanaged broker activity is outside this book.
No real capital is added by initializing it.

- Each buy must fit local settled cash after open-order reservations, broker
  `cash`, and current `buying_power`. Removed PDT/day-trading fields are unused.
- Buys debit cash immediately. Sale proceeds become available on the API's
  explicit `settlement_date`, using New York dates. Missing settlement metadata
  fails closed; the next trading day is not a safe substitute. For example,
  2026-10-09 settles on 2026-10-13, despite trading on October 12.
- Pending and uncertain buys reserve their full unfilled limit notional. A
  cancellation acknowledgment alone releases nothing. Pending sells reserve
  owned shares; the connector never opens shorts.
- Submission requires a positive strategy allocation and a running paper trial
  belonging to that strategy. Available strategy allocation includes realized
  P&L after fees and subtracts open cost basis and pending buys. Every parameter
  variant still belongs in the trials ledger.
- Every submission refreshes the existing P&L halt logic and obeys
  `RiskEngine.evaluate_order`. Pending buys and holdings across strategies share
  the unchanged $25 instrument cap. API failures feed the existing five/minute
  gate. §6 constants and the risk engine were not modified.

The connector captures an IEX quote with its original timestamp, including a
freshness check against the unchanged 30-second limit. The trading loop remains
responsible for periodically supplying marks for **all** its open positions to
the shared risk engine; the connector's submission refresh supplies the traded
instrument's current mark. Keep one connector/risk-engine instance per process
so its rolling API-error window spans calls. Cash and orders persist across
processes; the foundation's rolling API-error counter is process-local.

## Order and fill lifecycle

Supported orders are fractional or whole-share **marketable DAY limits**, USD US
equities, during the regular session. Quantity is explicit, at most nine decimal
places. Limit prices follow Alpaca's cent/sub-dollar increments. Decimal-string
payloads bypass the SDK request model's float coercion while retaining its
official HTTP transport. Request timeouts are bounded and automatic retries are
disabled, including POST retries.

Use a stable `request_id` for each intent. The adapter commits a pending ledger
order and its reservation before sending it. Repeating the same intent returns
that order without another submission; reusing its ID with different parameters
is rejected. Timeouts and unverified outcomes retain reservations and log an
incident. `refresh(order_id)` explicitly looks up that client ID and polls
paginated fill activities. A missing/failed lookup does not prove an order was
never accepted; resolve an unresolved submission explicitly before releasing
its reservation. There is no automatic resubmission.

Actual activity IDs make fill ingestion idempotent. The adapter validates the
order identity, limits, cumulative quantities, timestamps and precision before
calling `Ledger.record_fill`. A dated positive USD/GBP rate must already exist in
`fx_rates`. The broker's cumulative quantity/average price never creates a
synthetic fill. Terminal statuses release remaining reservations only after
individual executions catch up. Explicit `cancel(order_id)` operates only on
connector-owned orders, including when new submissions are halted.

The cash baseline and account fingerprint live in `Venue.metadata[alpaca_paper_v1]`;
order/fill provenance and settlement dates live in ledger metadata. No migration
or separate cash database is needed. The Alpaca venue row is locked while checking
cash and reserving/recording orders, so cooperating processes cannot spend the
same cash. Always give the connector a **dedicated Session**: its public methods
own commit/rollback. Do not mix unrelated pending writes into that Session.

Construction does no network work. There is no startup reconciliation, automatic
order cancellation, heartbeat or dead-man behavior. DAY is Alpaca's supported
TIF for fractional limits, not a custom short expiry. Accepted PRD §9 risks remain.

## Usage

Read-only connectivity and calendar check; no DB or account mutation:

```sh
uv run python -m tradingbot.connectors check --symbol SPY --date 2026-10-09
```

Strategy integration (IDs, allocation, budget and dated FX already established
by the paper experiment):

```python
from decimal import Decimal
from tradingbot.db.session import SessionLocal
from tradingbot.connectors.alpaca_api import AlpacaPaperAPI
from tradingbot.connectors.alpaca_paper import AlpacaPaperConnector

api = AlpacaPaperAPI.from_env()
try:
    with SessionLocal() as session:
        connector = AlpacaPaperConnector(session, api)
        # Run initialize_cash(paper_budget) once when creating the paper book.
        instrument_id = connector.register_equity("SPY")
        result = connector.submit_limit(
            request_id=stable_signal_id,
            instrument_id=instrument_id, strategy_id=strategy_id, trial_id=trial_id,
            side="buy", quantity=Decimal(quantity_string),
            limit_price=Decimal(marketable_limit_string),
        )
        # The runtime calls refresh explicitly; this is not startup reconciliation.
        result = connector.refresh(result.order_id)
finally:
    api.close()
```

## Scope and evidence

This is broker-execution integration, not the PRD's conservative paper engine.
Alpaca simulates fills from quotes and omits regulatory fees; it does not model
queue position, market impact or dividends. Recorded liquidity is `unknown` and
the zero paper fee has explicit provenance. These results cannot by themselves
prove profitability after live fees or the maker trade-through condition.
Resting maker support belongs to `tradingbot-pef`; the connector rejects limits
that would already rest at submission. Market movements after submission can
still leave an order resting under Alpaca's own simulation.

Fractional orders do not support `CLS`/market-on-close TIF. Strategies #5/#6 must
account for that execution constraint rather than assume an auction fill.
Scheduling, #5's alternate-half allocation, strategy direction decisions and
backtests remain their own beads. A bearish signal cannot turn into a short in
this cash adapter.

Sources checked 2026-09-30:

- [Orders and fractional TIF matrix](https://docs.alpaca.markets/us/docs/orders-at-alpaca)
- [Paper simulation assumptions](https://docs.alpaca.markets/us/docs/paper-trading)
- [Fill activities and pagination](https://docs.alpaca.markets/us/docs/account-activities)
- [Trading/settlement calendar](https://docs.alpaca.markets/us/reference/legacycalendar)
- [PDT implementation evidence](../../../docs/research/04-open-items.md)

The paper account/asset/quote/calendar read probe confirms `buying_power`, SPY
fractional eligibility, raw quote fields and the October settlement holiday.
No real or simulated broker orders were sent during development. Integration
tests use a fake broker and real Postgres on port 5433, with nested savepoints
inside a rolled-back outer transaction. Run `uv run pytest tests/connectors -q`.

# Alpaca live connector (cash account)

`tradingbot.connectors.alpaca_live.AlpacaLiveConnector` (`tradingbot-l3r`) has
the same public methods as the paper connector. It uses `mode='live'` and keeps
its own cash book in `Venue.metadata[alpaca_live_v1]`. It is a separate file on
purpose: `alpaca_paper.py` and `alpaca_api.py` are hashed into running paper
cohorts' identities, so the two connectors are unified only after the
execution-code freeze.

What differs from paper:

- **Keys and endpoint.** `AlpacaLiveAPI.from_env()` reads `ALPACA_LIVE_KEY` and
  `ALPACA_LIVE_SECRET`. It refuses to construct if either is missing, or if the
  key is a paper (`PK…`) key. The transport is pinned to
  `https://api.alpaca.markets`, and there are no transfer, withdrawal or account
  configuration methods. Keys must be trading-only. Only the owner adds them.
- **Cash account only.** The broker account must report `multiplier` 1 and no
  shorting. A paper account number (`PA…`) is refused.
- **Risk.** Every order needs a running *live* trial and passes the unchanged
  §6 `RiskEngine` in mode `live`.
- **Kill switch.** It persists across processes and restarts:
  `uv run python -m tradingbot.connectors.alpaca_live kill --reason "..."`.
  This refuses all new live orders, cancels this connector's open orders and
  logs a critical `kill_switch` incident. `clear-kill --note "who, why"` turns
  it off, and `status` shows it. Refresh and cancel always remain available.
- **Dry run.** `AlpacaLiveConnector(..., dry_run=True)` runs every gate and
  stores the would-be payload in `last_dry_run`. It reserves nothing and sends
  nothing.
- **Fees.** Alpaca books SEC/TAF/CAT as separate FEE activities. Each live fill
  records a per-fill cent ceiling from the dated schedule (`EquityFeeBook`), so
  local P&L is never better than the broker's. Actual FEE reconciliation is a
  follow-up.

`uv run python -m tradingbot.connectors.alpaca_live check --symbol SPY` is a
read-only live check. Without keys it exits with the missing-key message. Tests
use a fake broker: `uv run pytest tests/connectors/test_alpaca_live.py -q`. No
live request was made during development: no live keys exist.
