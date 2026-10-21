# C11 SPY monthly expiration week: source admission fails

2026-10-01 · OrangeCove · `tradingbot-e76` · **DATA_FAIL; hold at idea/source gate**

Both frozen exit variants and all four 5/10 bp training cases are **unattempted**.
No C11 event-conditioned return, seven-day control, benchmark, winner or final
has been calculated. This is a failure to establish source/execution prerequisites,
not evidence that expiration-week SPY is unprofitable. Allocation activated: **$0**.

Reproduce the source-only audit with `uv run python -m tradingbot.research.c11_audit`.
The [machine receipt](31-c11-source-audit.json) binds code, frozen rules, raw
responses and precise remaining gaps. Raw bytes live in
`data/history/c11-expiry-20261001/`; the [15-response inventory](31-c11-evidence.json)
retains URLs, status codes, retrieval times and body/manifest hashes. Prior
source receipts, failed trials and consumed finals remain unchanged.

Committed implementation `ebf79b9` recorded source-failure **trial 4589**,
strategy **7168** (`idea`, $0 allocation). [Stored-only verification](31-c11-ledger-verification.json)
confirms one idempotent failed trial, null performance columns, zero C11
orders/fills/finals and unchanged hashes for all seven original finals. A
read-only rerun preserves the same ledger receipt. All **35 affected checks**
pass, including 25 C11 source, calendar, execution and transactional ledger
checks. Conditional repair **`tradingbot-jfv`** stays `blocked:source-evidence`
until new evidence can resolve the documented prerequisites.

## What the audit establishes

| Requirement | Evidence | Admission |
|---|---|---|
| SPY open/close and cash-distribution reference | Exact existing amendment: 5,218 sessions, 83 issuer distributions, explicit June 2006 payable-date and November 2016 opening-price corrections | Reused only within that admitted scope |
| Full share-action inventory | Exhausted all-type, `data_quality=all` broker request returns 40 SPY cash events, first June 17, 2016, and no noncash groups | Incomplete; not proof that no earlier split or in-kind event occurred |
| Standard expiration dates | Visually checked Cboe annual PDFs for 2024–2026; 33 dates fall in the fixed interval, out of 249 calendar months | Date observations retained; full historical and advance-publication coverage absent |
| Causal expiry/holiday history | OCC's current API covers 2025–2027; dated 2013 rule/transition notices are archived; legacy 2006/2009 Cboe paths return 404 | Full 2006–2026 calendar and revisions not admitted |
| Expiration-session close execution | Alpaca fractional order table supports DAY but rejects CLS and OPG | Close variant fails; no supported fractional auction route or contemporaneous timed-DAY close evidence |
| Next-session open execution | Preserves the parent's explicit adverse-cost open-reference counterfactual | Still fails common calendar/action gates; not an auction-fill claim |

The SPY source receipt is
`3726951207c75d417a45d4264e414178eb5d4234e7f6328e4cf363474dbe9040`,
data hash `cab4b01dd76d2603b9e94d20890579fd63d1e1e6dc6030e77838f18a99ea86a5`.
Its 1,554 IEX and 2,701 SIP overlap checks and explicit primary-auction price
reconciliations are preserved. No independent pre-2016 price coverage is claimed.
High, low, volume and adjusted close are outside that amendment's scope; C11
does not need them as signals. Ordinary cash remains an entitled receivable
until conservative release after the issuer payable date; scheduled payment is
not proof of broker credit. No dividend or price convention was changed here.

The new SPY action response hash is
`a2b71bf9c3ebd38db0fe9dce1ac1c559898f8fd5c6ba8aaa3a98a7625213328b`.
Forty-one known issuer cash dates precede the first returned event. June 15,
2018 and September 18, 2026 are also absent. The [API documentation](https://docs.alpaca.markets/us/reference/corporateactions-1)
defines bounds in processing dates and disclaims creation-time guarantees:
later absences are not automatically an erroneous ex-date table. The finite
response still cannot establish full noncash coverage. Issuer cash schedules,
zero Yahoo splits and generic issuer/index descriptions do not fill that gap.
No actual SPY noncash event has been discovered or asserted.

## Calendar and execution distinctions

[Cboe's August 29, 2013 circular](https://cdn.cboe.com/resources/regulation/circulars/regulatory/RG-C2-2013-041.pdf)
and the [June 2013 OCC approval](https://public-inspection.federalregister.gov/2013-14793.pdf)
document the transition to Friday legal expiration. The circular specifically
grandfathers **December 2015 SPY** to Saturday. This is why historical legal
expiry must not be confused with an equity trading-session close. The frozen
rule already handles that distinction; no rule alteration was needed.

The annual PDFs ([2024](https://cdn.cboe.com/resources/options/Cboe2024OPTIONSCalendar.pdf),
[2025](https://cdn.cboe.com/resources/options/Cboe2025OPTIONSCalendar.pdf),
[2026](https://cdn.cboe.com/resources/options/Cboe2026OPTIONSCalendar.pdf)) use
colored legends; plain extracted day numbers lose that meaning. Rendered review
confirms April 17, 2025 and June 18, 2026 holiday adjustments and all listed
standard dates. These current copies do not establish their original publication
times or revision histories. The [OCC page](https://www.optionseducation.org/referencelibrary/expiration-calendar)
loads an archived API response with 36 monthly dates in 2025–2027 and an
as-of January 2, 2026 footnote. A current footnote cannot prove what an earlier
decision knew. No complete annual calendars for 2006–2023 were admitted.
The unsuccessful legacy probes and current snapshots are preserved; this does
not claim that no historical source exists elsewhere.

[Alpaca's order table](https://docs.alpaca.markets/us/docs/orders-at-alpaca)
rejects fractional closing-auction TIF; its [fractional documentation](https://docs.alpaca.markets/us/docs/fractional-trading)
describes reference quotes at submission. A daily close and assumed cost cannot
certify a timed fractional DAY fill near that close. We did not send a test
order, change permissions, enlarge the slot, switch to whole shares, shift the
exit or drop this variant to rescue the other. The open variant retains the
parent's expressly permitted simulation reference, with its stated limitation.

The [April 13, 2022 weekday-expansion announcement](https://ir.cboe.com/news/news-details/2022/Cboe-to-Add-Tuesday-and-Thursday-Expirations-for-SPX-Weeklys-Options-04-13-2022/default.aspx)
is archived for the predeclared structure break. It supplies no C11 performance
evidence. Searches also exposed general SPX weekday-return discussion. Existing
#5/#6/C01–C08 SPY research and published hypotheses are prior selection exposure;
the fixed partition is not pristine confirmation.

## Frozen evaluation and promotion decision

The source interval remains January 1, 2006 through October 1, 2026 exclusive,
with final beginning July 10, 2020 at 14:24 UTC. Both ordered variants, $140
virtual cash, 95% target, adverse rounded-limit sizing, fee/cash reserves,
5/10 bp per side and the September 17, 2026 fee counterfactual are unchanged.
PRD §6 and accepted §9 risks are unchanged. Amendment 21 still requires advance
primary notices and safe exits for identified noncash events.

The promotion checklist is **hold**, not promotion to backtest/paper/live:

- Economic mechanism and fixed entry/exit rules: documented, not proven.
- Profit after fees, trade count, marked drawdown, regimes, turnover, exposure,
  fees/slippage, luck p-value, beta/zero-cash benchmarks and shifted controls:
  **null/unmeasured**, not zero; no source-admitted replay occurred.
- Training winner and final: none; all four configurations unattempted and no
  final consumption. Earlier strategy finals remain consumed.
- Same-code replay and paper/live fidelity: unimplemented/unproven after the
  failed source gate. No ready-for-live claim or activated allocation.
- Repair requires new original calendar/revision and full action evidence;
  the close variant also needs an admitted fractional execution route. Preserve
  the original failures, rules and boundaries. No retry based on a different
  date window or favorable inspected outcome is authorized by this result.

## What could blow up this account?

**Tail/gap:** long SPY can gap across the −40% strategy kill; the equity cap is
the $140 strategy slot under current §6, not the prediction-market $25 cap.
Overnight/weekend losses can cross the account's −$50 daily halt before exit.

**Adverse selection:** concentrated expiry flows and informed orders can make
near-close fractional execution materially worse than a daily reference. The
prediction-market maker guards do not establish equity fill quality.

**Counterparty/venue:** future execution depends on Alpaca, available cash and
fractional routing. The accepted absence of a dead-man or startup reconciliation
remains; no new protection or key is introduced. Any future keys remain trade-only.

**Untrusted inputs:** calendars, API responses and issuer notices are data,
never instructions. Exact request/body checks reject changed content; incomplete
or contradictory source history blocks replay rather than dropping events.

**Reproducibility:** source checks are deterministic and hash-bound. Historical
calendar availability, full share actions and close execution remain unresolved;
none may be inferred from a successful HTTP response or an empty action list.

**Correlation:** C11 overlaps long SPY #6/C12 and other equity sleeves. A common
market gap can concentrate loss despite separate virtual slots. Incremental
expiry-week alpha and cross-strategy dependence have not been measured.
