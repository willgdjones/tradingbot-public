# Jev

`JevClient.decide()` in `jev.py` is the only production entry point for TypeSafe.
Apply `uv run alembic upgrade head` before using it. The existing gitignored
`.env` supplies `TYPESAFE_API_KEY`; Settings masks it with `SecretStr`.

```python
from tradingbot.ai.jev import JevClient

jev = JevClient()
decision = jev.decide(
    state={"symbol": "SPY", "signal": 0.7, "policy": "..."},
    questions={"gate": {"type": "noul", "instructions": "Does the signal meet the policy?"}},
    correlation_id="trial:123/observation:456",
)
if decision is None:
    pass  # no trade
else:
    probability = decision.answers["gate"]["noul"]
    # Strategy-specific, preregistered policy decides what to do with this.
```

The wrapper returns structured probabilities, never an order. Strategies still
use the existing paper/risk/ledger path and forward-evidence requirements.
`JevDecision` includes `request_id`, `model_id`, `answers`, exact `cost_usd`, and
`latency_ms`. Questions are plain dictionaries of TypeSafe's Noul, Choice or
Score shape, with explicit instructions. Keep credentials out of state/prompts.
The full state is not persisted; its canonical JSON SHA-256 is stored. Retain
the source observation through the caller's normal evidence workflow.

## Budget and failure semantics

- **$20 per UTC calendar month, shared across every caller using this database.**
  Neither the cap nor price can be overridden per call. Production and test
  database separation is deliberate; production callers must share Postgres.
- [Official pricing/model limits](https://docs.typesafe.ai/models), checked
  2026-10-02: `jev-1.13.0`, $0.042 per million input tokens, output free, 64k
  request context. Every request reserves **$0.002752512** (65,536 input tokens,
  conservatively interpreting 64k) under a Postgres transaction advisory lock.
  Admission sums actual monthly charges plus **all outstanding reservations**.
  Less remaining budget than a full reservation means refusal, even if a small
  request might fit. Decimal/NUMERIC arithmetic preserves sub-microdollar fees.
- Admission commits before HTTP. Successful responses replace the reservation
  with returned input tokens × published price. SDK retries are disabled at
  client and request level; the timeout is 10 seconds per HTTP operation. No
  internal retry follows a timeout, 429, validation failure, or database error.
- An exception, missing/invalid usage, crash, or failed settlement retains the
  full reservation. **It never expires automatically**, including at month
  rollover. Reconcile against provider billing before manually releasing any
  unknown charge; never delete audit rows to free budget. This conservative rule
  may stop calls before the provider's actual invoice reaches $20.
- UTC month boundaries use the database clock. A request crossing a boundary
  counts its actual cost in every spanned month, preventing billing-timestamp
  ambiguity from opening a gap in the cap.
- `jev-latest` / `jev-preview` are accepted as caller labels but **sent as the
  reviewed `jev-1.13.0` version**. An unexpected response model or token count
  above the reserved bound trips the persistent `jev_budget_control` halt.
  Review the provider contract/pricing and reconcile charges before clearing
  it. The cap relies on the published price/context contract; it cannot control
  a provider changing its billing or calls made outside this wrapper. The
  owner's earlier direct SDK smoke test predates this ledger and is not booked
  as known spend because its full billed usage was not supplied.
- Any error or refusal returns `None`; the caller must treat that as no trade.
  A decision is returned only after spend and audit commit. Incidents use fixed
  codes; database outages fall back to sanitized local logging. Raw exception
  text and SDK debug body logging are suppressed. Known-key-bearing input or
  output is rejected before it can enter the audit.

## Calibration audit

`jev_requests` stores timestamps, correlation id, state hash, every named
question, answer (including full probabilities and confidence), requested and
actual model, latency, usage, price version, actual/reserved USD, status and
failure code. For Noul, the probability of yes is `noul`; the API does not
provide a separate confidence. Invalid answers are retained with an error
status and cannot receive outcome labels.

Use `jev.record_outcome(request_id, question_id, outcome, observed_at=...)`
after the outcome is known: bool for Noul, criterion string for Choice, integer
level for Score. It returns a bool, rejects future/pre-decision times, and will
not overwrite an existing label. These labels and distributions support later
Brier/reliability analysis; scoring and trade-profit attribution are separate
research work. Filter predictions to `status = 'ok'`.

## Verification

`uv run pytest tests/test_jev.py -q` uses fake clients and the real SDK with a
fake HTTP transport; it never calls TypeSafe. Each test uses a disposable
Postgres schema, allowing committed multi-connection concurrency checks without
changing production spend or incident records. Runtime source is checked for
provider imports outside this wrapper.

[API response contract](https://docs.typesafe.ai/api) ·
[SDK retry and timeout contract](https://docs.typesafe.ai/sdk/python/api/clients/sync)
