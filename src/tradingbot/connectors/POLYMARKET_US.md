# Polymarket US live connector

`PolymarketUSConnector` records explicit live limit orders and their actual
executions in the shared Ledger, with the unchanged RiskEngine as the pre-trade
veto. Construction performs no network requests or startup reconciliation.
Nothing in this module promotes a strategy, allocates capital, launches a trading
loop, creates keys or submits an order without an explicit call.

## Verification status

Implemented against the official retail SDK 2.1.0 and current retail API schemas,
with exact-decimal transport and real Postgres integration tests. The existing
`.env` credentials returned HTTP 401 on two read-only balance probes on
2026-09-30 (local date); server and host clocks agreed. No live order, cancel,
account setting, funding or key change was attempted. Authenticated behavior is
therefore **unverified**. Repair existing access before an operational trial.

The retail authentication documentation does not expose a key-permissions
inspection endpoint. A `TradingKeyPolicy` must record actual owner/venue evidence
that this specific key permits trading and cannot withdraw. A successful balance
GET would not prove that. Do not fill the evidence field with an invented claim.
Changing accounts/keys still requires the owner's approval. The adapter exposes
no funding or key-management methods.

## Contract and prerequisites

Use a dedicated SQLAlchemy Session; the connector owns commits and rollbacks.
Serialize all calls and stream callbacks on that Session. Use the same connector
instance for its process-local API-error window. A venue-row lock serializes local
order reservations/fills across processes and clears stale ORM views. The
foundation API-error counter is process-local, not aggregated across workers.

Before `submit_limit`, a strategy must already be live with a positive allocation,
its live Trial must be running, and the supplied `proof_trial_id` must identify a
completed, profitable-after-fees historical backtest with identical parameters.
This is an eligibility check against the trials ledger, not an audit of research
quality or an automatic promotion. The operator must separately complete
`docs/promotion-checklist.md`, including the written failure-case analysis,
drawdown and regime evidence, before a promotion. Strategy/parameter variants must already be
recorded there, including failures.

`reviewed_instrument_ids` is an explicit universe of **standard, non-sports USD
binary YES contracts** whose fee applicability and structural strategy have been
reviewed. The local instrument ID must map to `<market-slug>:yes`. A sell is a
signed YES sale/short (NO exposure); this adapter does not translate separately
stored NO instrument rows. It verifies active market status, tick size, minimum
quantity and BBO from the venue before sending. Categorization alone is not a
complete sports or fee-policy review. No combos or international markets.

All orders are GTC limits. Maker-only is the default and uses the venue's
`participateDontInitiate` flag. Explicit `maker_only=False` permits a taker or
resting limit; actual execution liquidity always comes from the venue. There is
no short expiry, automatic cancellation, dead-man behavior or startup position
reconciliation (the deliberate PRD §9 choices).

The gate includes existing positions and independently executable pending sides
across strategies and market outcomes in the unchanged $25 cap. Binary shorts
reserve payout liability at `1 - price`. Strategy allocation and USD buying power
also bound collateral, with global pending-order reservations and a conservative
fee reserve from the standard cumulative taker cap. Expected maker rebates never
finance orders. Venue ledger state is tied to a key fingerprint; key rotation
requires explicit accounting review/migration.

## Explicit execution calls

Import the modules directly; no background job is installed:

```python
from tradingbot.connectors.polymarket_us import PolymarketUSConnector
from tradingbot.connectors.polymarket_us_api import PolymarketUSAPI, TradingKeyPolicy

# session, verified_policy, reviewed_ids, and the approved live/trial/proof IDs
# must come from the operator's existing setup; no defaults create authority.
api = PolymarketUSAPI.from_env(key_policy=verified_policy)
connector = PolymarketUSConnector(session, api, reviewed_instrument_ids=reviewed_ids)

# Calls which place/cancel orders are intentionally not run by this example.
# submit_limit(request_id=..., instrument_id=..., strategy_id=..., trial_id=...,
#              proof_trial_id=..., side="buy", quantity=Decimal(...),
#              limit_price=Decimal(...), maker_only=True)
# refresh(local_order_id) and cancel(local_order_id) are explicit operations.
```

A stable `request_id` names exactly one local intent. Its pending order and
reservation commit **before** the POST. Repeating the same intent returns the
same local order without another POST. Reusing its ID for different economics,
trial or key is rejected. The documented retail API has no client order ID or
idempotency key; a timeout or malformed response leaves an uncertain reservation
and blocks further orders. HTTP POSTs are never automatically retried.

A successful response stores the venue ID and synchronous execution evidence
before processing fills. Unknown submissions need explicit operator investigation:
`bind_order(local_id, venue_id)` checks the full venue order identity through GET,
but the operator must establish that it is the actual order. Identical price and
size alone are not enough. There is no heuristic matching or automatic restart
repair. A 404 does not authorize resubmission or release a reservation.

## Executions, stream and repair

`ingest_execution(raw)` accepts a documented individual retail Execution.
`refresh` fetches order state only: cumulative quantity and average price can
never create fills. A terminal state releases an order's reservation only when
all reported quantity has individual ledger fills. Cancel acknowledgments alone
do not release it. Older snapshots cannot reopen a terminal order.

Each fill stores the reported price, quantity, fee, maker/taker classification,
execution/trade identifiers, venue timestamp, dated positive USD/GBP rate and
raw evidence. The retail commission is a USD Amount, **not** the institutional
scaled integer. Reported commission is authoritative; differences from the exact
standard fee model generate incidents. Actual executions are recorded even
under a risk halt or when price/liquidity differs from intent, with incidents for
those discrepancies. Risk is refreshed after accounting.

Missing commission/FX, conflicting duplicates or inconsistent identity retain
execution evidence and block new submissions. After resolving the source issue,
`retry_pending(local_id)` explicitly replays preserved evidence. Missing fills can
also be supplied explicitly with `ingest_execution`. Unbound executions are
stored in venue metadata and an incident; bind their actual local intent, then
replay the original execution. Do not guess a strategy assignment. Corrections
that change previously recorded economics require a separate audited ledger
correction; this connector does not silently overwrite tax records.

For an explicit foreground private stream, call
`api.private_socket(connector.handle_private_message)`, then await the returned
SDK socket's `connect()` and `subscribe_orders(...)`. Close it explicitly when
stopping. The wrapper passes raw JSON to preserve fractional numbers. Attach
`socket.on("error", lambda *_: connector.stream_error())` and a corresponding
`close` handler to record sanitized connectivity incidents. Intentional closure
should suppress that handler in the calling loop. Errors never print SDK
requests or credentials. Do not concurrently use the connector's Session.

The initial order snapshot is deliberately ignored, including on an explicitly
requested reconnect. No automatic reconnect/reconciliation is installed. Resting
orders continue at the venue during disconnects. There is no demonstrated durable
replay cursor for the order stream. Operational gaps require explicit
investigation; order GETs cannot recover missing individual executions.

Call `tick()` in an active loop to refresh halts from the latest ledger/market
marks even in quiet periods. Callers remain responsible for fresh market capture,
strategy state and scheduled-event/adverse-selection guards. This module does
not supply strategy alpha, a live Strategy runner, settlement/corporate-action
accounting, reward accrual, deposit/withdrawal accounting or historical backfill
of missed private executions. Those lifecycle events must not be inferred from
an order's average price or from balance changes.

## Sources and checks

Primary retail references checked 2026-09-30:

- [Authentication](https://docs.polymarket.us/api-reference/authentication)
- [Create order](https://docs.polymarket.us/api-reference/orders/create-order)
- [Get order](https://docs.polymarket.us/api-reference/orders/get-order)
- [Private WebSocket](https://docs.polymarket.us/api-reference/websocket/private)
- [Market BBO](https://docs.polymarket.us/api-reference/markets/get-market-bbo)
- [Collateral and margin](https://docs.polymarket.us/market-structure/collateral-and-margin)
- [Fees](https://docs.polymarket.us/fees)

Run `uv run pytest tests/connectors/test_polymarket_us*.py -q`. Integration fixtures
use savepoints inside an outer rollback transaction; they never call a venue or
leave test orders/capital in the live ledger. The SDK emits one existing
`websockets.legacy` deprecation warning.
