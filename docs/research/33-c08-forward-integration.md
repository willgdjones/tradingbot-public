# C08 forward adapter integration and admission decision

2026-10-01 · NavyLantern · `tradingbot-5l3`

**Decision: hold before activating paper; not ready for live.** The durable
runner, source review, account evidence integration and explicit reconciliation
are implemented and tested. Current issuer notice coverage fails admission.
No C08 order, allocation, launchd job, account migration or historical replay
is authorized by a failed preparation. Committed implementation **88e4cae**
recorded failed preparation **trial 5195**, with null performance metrics and
zero orders/fills. The [machine-readable receipt](33-c08-forward-integration.json)
binds the exact committed code, source review and protected ledger comparison.

The [execution contract](33-c08-execution-contract.md) was frozen before any
new paper decision. The unchanged `InventoryScarcity` SHA-256 remains
`599442d4d877d32c5a1a82edd0abcc1036cc2ff8b10f62ae00201dddd69f87cc`.
The implementation uses the same reactor with −5% scarcity, 95% target,
$140 maximum slot, 5% reserve, $0.01 entry reserve and nine-decimal quantity.

## Implemented behavior

| Component | Verified behavior |
|---|---|
| `forward/c08_state.py` | Hash-bound finite official calendar; first-minute opens; after-close observations; terminal open; exact Decimal pending target, latest report, attempted tags and blackout state survive restart. |
| `forward/c08_sources.py` | First-observed dated EIA page/CSV/PDF, methodology and errata; issuer product/news/notices; exhausted bounded broker action/nontrade pages. Named review binds every raw file and notice link; unknown content, calendar drift and observed unhandled nontrade activity hold. |
| `forward/c08_runner.py` | Separate disabled preparation and activation; one durable phase/intent before POST; known-intent polling; no off-window catch-up or resend after interrupted claim; partial/unknown/rejected/risk-vetoed mandatory exits hold. Terminal success requires flat shares and resolved orders. |
| `connectors/alpaca_paper.py` | Optional locked evidence callback only tightens cash ceilings; offsets enter the original risk calculation before a trigger. Existing request idempotency and unknown reservations persist. Actual fills survive evidence failures; cancellation remains possible. |
| `forward/paper_evidence.py` | One fee accumulator across all account fills, including partial fills and other strategies; complete held/pending marks; documented completion followed by a later open; separate income receivable/model cash and actual broker cash. |
| Shared account migration | Explicit reviewed book/consumer identity and inactive runner locks are required. The SPY adapter supports this policy without changing trial 3298's parameters, sizing rule or schedule. Preparation does not perform the migration. |

Each source watch expires 24 hours after capture start. EIA availability remains
the later of publication's next New York midnight and actual validation/review,
and must precede the scheduled open. A capture during the first minute cannot
be used to reconstruct that open. Original first-release vintage remains
unverified; this limitation does not prohibit causal use of newly observed,
reviewed current information. The original 14-day report expiry remains in the
reactor.

Opening orders are marketable DAY limits. Remaining known quantities are
canceled after the first minute, with fill/cancel races reconciled from actual
activities. Every execution retains its decision quote, actual time/quantity,
broker fee, modeled fee comparison and IEX-relative adverse basis points. This
comparison is neither NBBO nor a primary opening-auction benchmark. Drawdown is
sampled at accepted complete portfolio quote batches, not continuously.

Ordinary income requires known issuer dates, USD rate and payable-session
coverage before ex-open. Ownership comes from actual prior fills; unresolved
pre-ex orders hold. The receivable enters modeled P&L once; modeled payable cash
cannot increase the connector's transport cash. A nonzero new nontrade response
requires explicit account reconciliation before admission, rather than an
assumed split/dividend/cash-in-lieu posting. Such reconciliation remains a
future evidence task when an actual event occurs.

`admit-completion` requires a reviewed raw broker document tied to the existing
account and exact sale fill. A nominal calendar label is rejected. Availability
cannot precede actual observation/review or the first regular open after the
documented completion date. The operation never funds the shared account.
`resolve-flat` can clear an explicitly reviewed hold only while flat, with no
active/unknown intents and after the current window; prior attempts and permanent
risk kills remain intact.

## Current source evidence

The immutable watch is
`data/forward/c08-integration/watch-20261001-2042/watch.json`, SHA-256
`6cac900fc0ca093bd529cd50266d653adce226f64ece8f8553eda043ed67f7e9`.
Its dated hold review is `review-hold.json`, SHA-256
`7e3f73971b5201dae34fd0c993955e05d4625cd785103b58b349c49571afc819`.

- The September 30 EIA release identifies the September 25 observation and
  comparable September 26, 2025 denominator. CSV values 427.320 / 416.546 million
  barrels agree with PDF rounding, units and commercial crude excluding SPR.
  This capture validated at **20:43:00 UTC on October 1**; earlier immutable
  readiness receipts, including first validation at 18:29:21, remain preserved.
  No strategy signal or outcome was computed during admission.
- Current Appendix B and Appendix E are byte-identical to the previously
  reviewed C08 research captures. Appendix E concerns 2023 propane/propylene
  corrections; it is not a correction to these commercial crude fields.
  The dated page exposes no new notice link. [EIA archive](https://www.eia.gov/petroleum/supply/weekly/archive/),
  [methodology](https://www.eia.gov/petroleum/supply/weekly/pdf/appendixb.pdf),
  [errata](https://www.eia.gov/petroleum/supply/weekly/pdf/appendix_e.pdf).
- The existing account matched its cash book. All-type USO actions and bounded
  nontrade activities exhausted with **zero records**. This does not establish
  advance issuer coverage, future fractional treatment, entitlement, or
  settlement completion.
- The [USO product page](https://www.uscfinvestments.com/uso),
  [news page](https://www.uscfinvestments.com/news) and
  [qualified notices](https://www.uscfinvestments.com/qualified-notices) return
  dynamic templates. The product HTML retains the historical 2020 split note;
  that note cannot establish current share/cash treatment. Three exact linked
  loader scripts returned **HTTP 500**. Their 774-byte responses and metadata
  are preserved under `issuer-diagnostics-20261001-2049`. No repeated failure
  was used to invent clearance. Current issuer content coverage remains
  unresolved.

## Promotion checklist and account risk decision

**Edge and rule:** The deterministic commercial-inventory scarcity thesis and
cash/blackout exits are unchanged. No LLM supplies alpha. Historical training
3907 and consumed final 3910 remain the only evaluated version; no final is
replayed and no new threshold, cost case, or sample is selected.

**Statistics and regimes:** Existing training net is +$102.29 over 3 trips,
with $54.80 / 26.61% peak-to-trough drawdown. Final net is +$7.67 over 4 trips,
with $28.68 / 16.41% drawdown. Both luck p-values remain null. Training profit
is concentrated in a 2021–2022 trip and final 2026 net is −$12.04. Those small,
concentrated samples and material drawdown remain disclosed. No extra luck
threshold or AI 7-day/30-trade gate is imposed on this deterministic rule.
See the unchanged [historical report](22-c08-blackout.md).

**Fidelity:** Synthetic and transactional checks establish adapter behavior.
They do not establish actual fractional opening fills, attainable 10 bp costs,
live regulatory charges, settlement completion, forced-exit success or actual
income/share credits. The earlier regular-session USO IEX spread observation
was approximately 236 bp; freshness alone cannot validate a 10 bp assumption.
Actual future qualifying execution receipts are still required before a live
readiness decision. There is no automatic ready-for-live promotion on terminal
paper completion.

**What could blow up this account?**

- **Tail and gap risk:** USO can gap through stale marks or an intended exit.
  Overnight commodity risk, fund mechanics and a missed split/distribution can
  strand exposure. The approved equity/ETF cap is the slot, up to $140 here;
  it is not the prediction-market $25 cap. A $50 daily halt or $56 strategy
  loss trigger is an order veto, not a guaranteed loss bound. Risk vetoes can
  also prevent a mandatory sell; that produces an incident and explicit hold.
- **Adverse execution:** These are taker limits. IEX is a single venue, and
  reported freshness does not prove NBBO depth, opening-auction access or
  fillable fractional liquidity. Rounded limits, partial fills, late receipts
  and paper simulation can differ from the historical cost case.
- **Venue and operations:** One Alpaca account/feed and the existing local
  ledger remain dependencies. The accepted lack of account-wide startup
  reconciliation and dead-man cancellation remains unchanged. The new runner
  reconciles only its durable known intents. It creates no keys and preserves
  trade-only/no-withdrawal policy; no live transport is invoked.
- **Untrusted inputs:** External HTML, PDFs and API bodies are data. Explicit
  hashes, field/units checks and notice review govern admission. Unknown or
  late actions hold; page text never instructs the bot or changes the rule.
- **Reproducibility:** The reactor and runtime dependencies, calendar, source
  review and durable attempts are bound to a trial. A crash cannot justify
  replaying a POST or a consumed historical final. Corrections require a new
  reviewed receipt; an interrupted claim is retained for resolution.
- **Correlation and funding:** SPY, C05 and C08 share one $140 paper book.
  C05's USO exposure can overlap C08 directly, and macro shocks can hit SPY
  and commodities together. Venue reservations, cross-strategy ticker exposure,
  complete marks and account-wide fees prevent duplicated spending; they do
  not diversify the common $50 daily loss risk.

**Limits and decision:** PRD §6 remains unchanged: −40% strategy kill, −$50
daily halt, current asset-class cap, 30-second freshness and five API errors
per minute. No capital, venue, account, key or public post is added. C08 stays
at its existing allocation/status and the shared account remains unconverted.
The completed decision is **hold**, pending usable issuer coverage, a fresh
review, explicit account migration and a paper activation decision.

## Operating entry points

Run modules with `uv run python -m tradingbot.forward.c08_sources` or
`tradingbot.forward.c08_runner`; each supports `--help`.

1. Capture a new bounded watch, inspect the exact issuer/EIA/broker bytes and
   append a dated review. A negative review is preserved and cannot activate.
2. `prepare --through <terminal trading date> --review <review.json>` records
   a failed or disabled experiment. It never increases the existing cash book.
3. Once evidence supports activation, coordinate every existing account
   consumer using `paper_evidence.migration_identity` / `enable_account_guard`,
   retaining the same trial IDs, funding and schedules. Active runner locks
   prevent this migration.
4. A complete source/promotion/account-risk receipt may then authorize
   `activate --trial-id <id> --receipt <decision.json>`. Run explicitly with
   `run --trial-id <id>`; no C08 job is installed by this change.
5. Renew sources through `bind-review`; use `admit-completion` for documented
   actual completion, and `resolve-flat` for a specific reviewed flat hold.
   These commands do not infer payments or permit an off-window catch-up.

## Verification

All **235 affected checks pass**, including **52 C08 checks / 23 full runner
integration cases**, the connector/default-SPY regressions, guard-enabled SPY
cases and shared-account fee/income/cash/migration tests. Database fixtures are
isolated in rollback transactions on port 5433. The protected ledger comparison
confirms all ten protected rows are unchanged: the seven historical finals
3281, 3282, 3319, 3910, 3964, 3969 and 4066, plus C08 training 3907,
preparation 4176 and SPY paper trial 3298. The original shared book hash is
unchanged, with $140 initial virtual cash and no evidence-policy opt-in.
C08 strategy 6446 remains `backtest`, allocation $140; preparation did not
change either field. There are zero actual C08 paper orders/fills.

Trial **5195** is `failed` at `source_admission`, with every return, fee,
trade-count, drawdown and luck metric null. Its dependency bytes exactly match
implementation commit **88e4caeb221a688520736ee6fc7eec717b08d4e6**. The immutable
verification is `data/forward/c08-integration/verification-20261001-2059/after.json`,
SHA-256 `70f5dd507757099e006b203df6e2b9f825e1d9c36a25270407979f29977257e8`.

The implementation bead is complete under its explicit readiness/conditional
activation acceptance. Follow-up **`tradingbot-ndl`** is labelled
`blocked:source-evidence` for usable issuer coverage, fresh admission, coordinated
account migration and actual future execution/action/cash receipts. It must not
manufacture trades, replay final 3910, or treat these fixture results as live
fidelity.
