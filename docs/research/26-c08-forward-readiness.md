# C08 forward execution preparation

Date: 2026-10-01. Bead: `tradingbot-gx2`.

**Decision: hold before ordering paper; not ready for live.** The historical
profit gate remains passed. This preparation establishes usable free source and
account access, preserves the frozen reactor, and supplies tested publication
and cash-availability helpers. It does not establish opening fills, a working
action-notice watch, or actual settlement completion. Those facts cannot be
inferred from a daily bar, an empty action response, or paper buying power.

The [machine-readable receipt](26-c08-forward-readiness.json) records the
committed capture, exact source hashes, unchanged historical rows and failed
preparation **trial 4176** (zero trades; return/drawdown/luck metrics null). No C08 order, launchd job, allocation change, live key or
new historical evaluation is part of this decision.

## Evidence preserved

Use the unchanged `InventoryScarcity` reactor in
`src/tradingbot/strategy/c08_inventory.py`, SHA-256
`599442d4d877d32c5a1a82edd0abcc1036cc2ff8b10f62ae00201dddd69f87cc`.
Training **3907** and the permanently consumed final **3910** use version
`739e205972e6208c07c0fc0618946a1813a877e7c775d4d737237f54c9183376`.
The [historical report](22-c08-blackout.md) remains authoritative:

| Existing evidence | Net after costs | Trips | Maximum marked drawdown |
|---|---:|---:|---:|
| Training, −5%, 10 bp per side | +$102.29 | 3 | $54.80 / 26.61% |
| Single final, same rule and costs | +$7.67 | 4 | $28.68 / 16.41% |

The frozen signal is commercial crude stocks excluding SPR divided by the
same release's comparable year-ago stocks, minus one, strictly below **−5%**.
Cash-to-long targets 95% of current equity, capped at $140, retaining the
5% reserve and $0.01 entry-fee reserve. Long-to-cash sells owned shares; an
unchanged long signal retains shares. A cash-delayed entry retains its original
target. Inventory evidence expires after 14 calendar days under the original
reactor. No threshold, cost case, source interval or historical version changes.

Training profit is concentrated in one 2021–2022 trip; final 2026 net is
−$12.04. Both dependence-aware luck p-values remain null. Neither a Sharpe or
p-value threshold nor the separate AI 7-day/30-trade requirement is added.
Prior source/benchmark inspection and the original archive-vintage uncertainty
remain disclosed. This check reads stored evidence; it never invokes a replay.

## What the operational probes establish

The authenticated probes use only the existing paper credentials and GET
operations. The account fingerprint matches the existing local cash book;
connector account checks pass. The account reports active/USD/unblocked, and USO reports active,
tradable and fractionable on ARCA. A regular-session IEX bid/ask passed the
unchanged 30-second freshness test. This is a point-in-time availability check,
not an opening quote, a fill, or evidence that 10 bp execution is achievable.
The final capture at 18:42:41 UTC showed $149.75 / $153.32, approximately
236 bp of full spread. This single-venue IEX observation is not an NBBO fill
benchmark; its freshness cannot validate the 10 bp historical assumption.

The existing venue-wide paper cash book contains **$140**, with no paper
orders, fills or open positions at the initial capture. SPY trial **3298** is
already running against that book. C08 cannot treat the same $140 as a second
independent cash balance. A future runner must use the shared reservation gate
and its own allocation/fee/position accounting; it must preserve SPY's trial
and schedule. No broker reset or virtual-book increase was performed.

The current corporate-action query uses **all types**, `data_quality=all`,
USO, a bounded 30-day lookback/45-day lookahead, and exhausts pagination.
The observed response is empty. Alpaca explicitly gives **no guarantee of
action-data creation time**; a successfully exhausted query is not advance
notice clearance. An issuer announcement record is still needed for a causal
blackout plan. [Alpaca corporate-action API](https://docs.alpaca.markets/us/reference/corporateactions-1).

The EIA collector discovers the newest recent dated page from actual archive
links, then independently checks page publication/observation dates, the CSV's
current/previous/year-ago dates and crude-stock components, PDF units and
rounded stock values, and the unchanged commercial-stock definition. It
archives each original response before accepting the schema. No synthetic
Wednesday, current bulk-series revision, or URL-derived publication date is
used. New methodology/errata notices still require review before signal
admission. [EIA dated archive](https://www.eia.gov/petroleum/supply/weekly/archive/).

The first capture validated the **September 30 release / September 25
observation** at **18:29:21 UTC on October 1**. It was observed after that day's
open. `first_eligible_open` uses the later of next New York midnight after
publication and actual validation time, followed by the next regular open:
**October 2, 09:30 New York**. It must never manufacture an October 1 opening
decision. This date is evidence of source eligibility, not an activated order
schedule. First-release vintage is still unverified; later recaptures do not
erase the earliest immutable receipt or certify a first vintage.

## Settlement and broker fidelity

The historical C08 adapter releases sale proceeds at the first regular open
**after documented settlement completion**. The current shared Alpaca paper
connector releases them at New York midnight on its calendar settlement date.
These differ. The new `release_after_completion` and `conservative_cash`
helpers preserve the evaluated C08 rule, debit fees immediately, subtract
reservations, and refuse missing/future/invalid sale-release evidence. They do
not change the shared connector, another strategy, or the risk engine.

For a hypothetical Friday October 9 sale, the returned calendar labels
settlement Tuesday October 13; Monday October 12 is a trading session. **If**
documented completion is October 13, C08 may spend that sale's proceeds only
from Wednesday October 14's open. The shared connector would release at the
start of October 13. The nominal label is not proof of actual completion.
A future C08 adapter must cap spendability at the minimum of this conservative
book, the existing shared book, broker cash/buying power and remaining strategy
cash after modeled fees; it cannot use a larger broker margin balance.

The existing transport reads only `FILL` account activities. It does not ingest
nontrade split, distribution or cash-in-lieu activity. Alpaca's corporate-action
documentation describes separate share and cash events and their settlement
dates; it is not account-specific proof that a current USO fractional position
will receive a particular treatment or credit time.
[Mandatory actions](https://docs.alpaca.markets/us/docs/mandatory-corporate-actions).

Paper trading omits regulatory fees and dividends, does not check order size
against displayed NBBO quantity, and simulates partial fills. Therefore the
fee scenario must remain separate from broker-reported zero fees, and paper
cash/fills cannot certify live action treatment or market impact. USO's absence
of ordinary distributions in the historical interval is not a promise about
future distributions. [Paper specification](https://docs.alpaca.markets/us/docs/paper-trading).

## Concrete forward contract

These requirements follow from the evaluated reactor and Amendment 21. They
are implementation/evidence work, not new statistical selection gates.

1. Bind preparation to trials 3907/3910, the reactor hash, −5%, the frozen
   sizing and fee policy, and an explicit future exchange calendar. Start flat;
   retain original failed/source/historical rows. No final replay or retuning.
2. Persist first-observed raw EIA bytes, validation/notice review and the
   resulting `available_at`. Supply only causally available releases at an
   opening event; newest observation wins. A missing/unusable report produces
   no new signal, and the original 14-day expiry still governs.
3. Obtain a fresh regular-session quote for each opening intent and again at
   connector submission. Preserve the pure reactor; persist `latest`, pending
   dollar target, attempted tags, blackout decisions and forced-exit state.
   Commit each attempt before POST, restore it on restart, and never resend an
   uncertain POST. Explicitly freeze the opening execution window and missed
   window behavior before activating a runner; an afternoon quote cannot be
   relabeled an opening reference.
4. Archive issuer announcement and broker action records with first-seen
   times. Establish ex/pay dates and announcement availability before the
   prior-close exit decision. Sell at the last regular open before ex-date;
   stay flat through payable; normal sizing resumes after payable with
   documented spendable cash. Empty vendor data is not an issuer review.
   Missing/late/conflicting evidence, partial exit, or risk-vetoed liquidation
   is an incident requiring explicit review, never permission to carry an
   unresolved conversion or bypass the risk engine. Unknown ordinary cash
   distributions also stop admission until entitlement/payment handling exists.
5. Integrate the C08 conservative cash bridge and dated completion evidence.
   Record actual fractional fills and fees plus the fixed modeled regulatory
   fee scenario. Compare decision quote, submission quote, fill price and
   timestamp with the frozen 10 bp assumption. Do not equate an IEX quote with
   an NBBO execution guarantee or a daily opening bar with a tradable quote.
6. Before any live queue entry, reconcile owned share/cash movements and
   action handling, inspect achieved costs and drawdowns/regimes, and complete
   the promotion review. An uneventful empty-action period does not demonstrate
   forced-exit handling. Deterministic C08 has no arbitrary elapsed-day or
   trade-count quota; sparse evidence is reported honestly.

## Promotion review and account-risk record

**Edge/evidence:** the published inventory-scarcity hypothesis, explicit pure
entry/exit and profitable training/final gate are established by the historical
report. **Statistics:** seven trips, null luck odds, the drawdowns above and
the concentration in 2021–2022 / negative 2026 remain visible. Historical
profit alone is insufficient execution evidence. **Fidelity:** incomplete;
cash timing differs and no C08 forward fills/action handling exist. Decision
is **hold**, $0 activated, up to $140 virtual sizing in any later prepared
experiment. The historical strategy remains in backtest status.

**What could blow up this account?**

- **Tail/gap risk:** USO futures exposure, roll changes and overnight gaps can
  lose much of the $140 slot before an opening sale. The $25 prediction cap
  does not apply. A −40% kill may veto a liquidation and leave inventory; it
  is not a guaranteed exit price or loss ceiling.
- **Adverse selection:** these are taker-style marketable fractional limits.
  Opening spreads, delayed quotes and post-release repricing can overwhelm
  the small final profit. Prediction-market maker fill/event guards are not
  this strategy's mechanism; quote freshness and connector/risk vetoes remain.
- **Counterparty/venue:** the strategy depends on Alpaca, IEX, EIA and issuer
  publication. The Mac can sleep or disconnect, and accepted lack of a
  dead-man/startup account reconciliation remains unchanged. Keys remain the
  existing paper keys; this probe neither creates keys nor proves live
  withdrawal-permission settings.
- **Untrusted inputs:** pages, JSON and tables are parsed as data. Responses
  never supply executable instructions or a model decision. Changed schema,
  dates, units, hosts or action evidence fail admission. Account identifiers
  and remote exception bodies are excluded from capture output.
- **Reproducibility:** the same hashed reactor must run forward. Durable raw
  source, first-seen times, cash evidence and attempt state are needed to
  reconstruct each decision. Storing today's publication retrospectively is
  not an earlier observable signal.
- **Correlation:** C08 overlaps C05's USO sleeve and can share commodity or
  risk-on losses with other Alpaca strategies. The shared cash book and
  aggregate held/pending exposure matter, as does the unchanged −$50 daily
  halt. No portfolio independence or live loss estimate is claimed.

PRD §6 stays unchanged: −40% strategy kill, −$50 daily halt, 30-second data
limit, five API errors/minute and the owner-approved asset-class allocation
caps. No capital, account, venue, credentials or public communication is added.

## Handoff

Implementation and subsequent execution evidence are tracked in
**`tradingbot-5l3`**, using the concrete contract above. This readiness assessment
is complete; the strategy remains on hold until that evidence supports a
separate promotion decision.

## Reproduce the preparation

```sh
uv run python -m tradingbot.forward.c08_readiness \
  --output data/forward/c08-readiness/UNUSED-CAPTURE-NAME
uv run python -m tradingbot.forward.c08_readiness \
  --record-failed-preparation data/forward/c08-readiness/UNUSED-CAPTURE-NAME/readiness.json
```

Capture is read-only against the broker and database, with immutable local
files and disk-budget checks. The separate explicit record command appends an
idempotent **failed paper preparation**, with zero trades and null return,
drawdown and luck metrics. It cannot promote a strategy or reuse a historical
holdout. The readiness flag deliberately remains false; a source-access probe
does not qualify an execution experiment.

Validation: **91 focused checks pass**, including source timing, missing cash
evidence, settlement holidays, fresh/stale quotes, response redaction, action
pagination, immutable historical/ledger semantics, the existing reactor,
blackout/risk veto and paper connector. A C08 family-guard test previously
assumed an empty real database; its expectation now includes the existing
earliest consumed final without editing or replaying that evidence. The
existing SDK deprecation warning remains.
