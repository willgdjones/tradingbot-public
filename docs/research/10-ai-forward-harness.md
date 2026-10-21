# AI decision forward-paper harness

Implemented for `tradingbot-tph` on 2026-09-30 Pacific, following the owner's
2026-10-01 update to PRD §§3–4. This is infrastructure, not an AI strategy result.
No model provider, account, credentials, allocation, daemon or experiment was
activated by this change. The existing Alpaca paper adapter remains the only
order route.

## Evidence and admission

`tradingbot.forward.ai` accepts a registered local `AIForwardStrategy` subclass
whose `decide(Observation)` returns a `DecisionReply`. Preparation requires an
existing reviewed Alpaca strategy in `paper` status with a positive allocation,
an already initialized paper cash book, a flat starting portfolio, no active
orders or running paper experiment for that strategy, and a completed promotion
decision record containing the written **What could blow up this account?**
section. Preparation stores that record's path and SHA-256; it checks the section
exists, not whether a human has supplied an adequate analysis. Review the actual
record before invoking it. Preparation does not fund an account or promote a
strategy. Failed preparation attempts are retained in the trials ledger once
the existing strategy is identified.

The owner-approved AI exception in PRD §4 supersedes the historical-proof and
no-LLM wording still present in the older promotion-checklist template. Explain
that exception in the completed record; retain its other risk questions. An
equity position is limited by the strategy allocation under the revised §6.

The gate requires **all** of:

- At least seven elapsed calendar days between the first and latest fresh live
  regular-session observation. Preparation time and elapsed downtime alone do
  not advance this clock.
- At least 30 completed, flat-to-flat round trips across the reviewed universe.
  Partial fills, buy/sell order counts and model calls do not count as trades.
- Positive P&L after recorded broker fees, the frozen regulatory-fee scenario,
  and every reported provider-call cost, including rejected decisions.
- Flat positions, no pending orders, intact experiment identity and verifiable
  evidence; no strategy kill or active global halt.

Passing produces `eligible_for_review`, never a live order or status promotion.
There are no live credentials. Apply the owner's `ready-for-live` queue policy
after a completed review. No p-value cutoff is added to the owner's profit gate.
Observed drawdown, monthly P&L changes and a descriptive weekly-net-P&L luck
p-value are recorded. With fewer than two observed weeks that value is null;
serial dependence and a short observation window limit its meaning. Monthly
breakdowns are descriptive, not evidence of several market regimes.

## Trusted adapter and untrusted model

The reviewed subclass is trusted Python code. It must be stateless between
calls, put all decision settings in `params`, and use
`observation.messages(params['policy_prompt'])`. Those messages place policy in
the system message and quotes/news only inside the serialized `untrusted_data`
user payload. News carries both publication and first-observed timestamps;
ingestion code must supply truthful availability times. The CLI supplies no
news source; an explicitly reviewed caller may pass bounded `NewsItem` values.

Freeze the model revision, policy prompt, temperature, seed when supported,
provider settings and other decision parameters. Use a network timeout, no
tools, no browsing or account access, and no dynamic code execution. The model
receives immutable serialized observations, positions, paper cash and owned
order tags. It receives no database handle, broker session, keys or filesystem
path. This separation constrains model output; it is not a sandbox for arbitrary
Python provider code. Review adapter code and its dependencies before use.

`DecisionReply(body, model_id, cost_usd)` must contain a **trusted provider
receipt** for model identity and actual cost, not fields reported by the model.
Explicit `Decimal('0')` is required for a free/local call. Unknown costs or a
different provider model permanently flag the trial for review. No SDK, new
endpoint or paid subscription is supplied here; use only owner-authorized
existing access within the free-data policy. Never put credentials in params,
prompts, news or decision output: these are retained for audit.

The JSON body permits one action per interval (minimum 60 seconds): hold; buy or
sell a reviewed instrument with decimal-string quantity and limit price; or
cancel one of this trial's owned tags. Extra fields, duplicate keys, nonfinite
money, invalid instruments and foreign cancellations are rejected. Responses
are limited to 4 KiB; at most 16 instruments and 16 bounded news items are
accepted. The bounded archive stops at 10,000 decisions for explicit review.
The inherited `on_event` cannot be overridden. Historical backtest contexts are
rejected before calling the provider.

## Execution, costs and recovery

The shared Alpaca paper connector and ledger enforce settled cash, T+1 proceeds,
owned shares, regular sessions, current IEX data and the unchanged §6 risk
checks. Orders are marketable DAY limits only. Maker decisions are unsupported;
quotes never manufacture fills. Only actual paper activity fills enter the
ledger. IEX and paper executions do not establish consolidated-market or live
fill quality; that remains a promotion-review limitation.

The strategy/execution source files, prompt/model parameters, allocation,
universe, interval, fee policy and decision-record hash form a frozen identity.
Changes stop decisions for review and require a new trial after the original
position/order lifecycle is resolved. Existing fills remain accounted for.
Provider costs and the explicit `EquityFeeBook` September-2026 fee scenario are
subtracted from paper cash and P&L; paper activity fees are recorded separately.
The scenario uses daily cumulative fee rounding per trial and may conservatively
overstate shared-account fees across trials. Its frozen policy is not a claim
that Alpaca's simulated account charged those amounts. Execution prices already
include the paper fill outcome; no extra hypothetical slippage is credited.
Additional costs also feed the existing −40% strategy kill and −$50 UTC daily
halt thresholds. Those thresholds are unchanged.

A PostgreSQL advisory lock serializes each trial across connector commits. The
decision interval and input are committed before calling the provider, and the
response/cost receipt before submitting an order. A restart never repeats a
consumed interval. An interrupted provider call with unknown cost requires
review. A crash after receipt but before submission consumes that decision;
there is no later catch-up order. Broker timeout recovery polls the connector's
durable order/client ID rather than sending another POST. Model decisions older
than 30 seconds are discarded even if a subsequent quote is fresh.

Continue reconciliation until orders and positions are resolved before
`finish`. A failed gate can be finished and retained as a completed negative
experiment. Integrity errors are intentionally not cleared automatically;
investigate the audit evidence and record the disposition. Existing connector
risk procedures govern intervention if an experiment stops while holding
shares. The harness does not silently liquidate positions on review failures.

## Running an explicitly reviewed variant

The module must register its subclass with the existing strategy registry. Its
key must match the already reviewed DB strategy. Instrument IDs must already
refer to registered Alpaca USD equities/ETFs. A recent dated USD/GBP reference
rate is required before model decisions, as in the existing paper connector.
Keep that reference current using the established dated FX import workflow;
the harness does not fetch or invent exchange rates.

```sh
uv run python -m tradingbot.forward.ai prepare \
  --strategy-module tradingbot.strategies.REVIEWED_MODULE \
  --strategy-key REVIEWED_KEY --params-file REVIEWED_PARAMS.json \
  --instrument-id REGISTERED_ID --decision-record COMPLETED_REVIEW.md \
  --interval-seconds 60
uv run python -m tradingbot.forward.ai run \
  --strategy-module tradingbot.strategies.REVIEWED_MODULE --trial-id TRIAL_ID --once
uv run python -m tradingbot.forward.ai status --trial-id TRIAL_ID
uv run python -m tradingbot.forward.ai finish \
  --strategy-module tradingbot.strategies.REVIEWED_MODULE --trial-id TRIAL_ID
```

Omit `--once` for a foreground process polling every ten seconds. This does not
install a launchd job. `status` is read-only and prints compact evidence, not raw
model/news content. Use the trials ledger for the full private audit. The CLI
applies the existing global free-disk guard before writing.

Verification uses isolated rollback-only Postgres fixtures, a fake broker and
a deterministic fake provider. It exercises the shared paper connector without
sending venue orders or spending provider money. Synthetic test timestamps do
not count as a real seven-day run or prove an AI edge.
