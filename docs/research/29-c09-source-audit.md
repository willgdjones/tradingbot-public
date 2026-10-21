# C09: source gate failed; hypothesis remains untested

2026-10-01, OrangeCove; `tradingbot-b8y`. **Hold before backtesting.** The frozen
IEF auction-cycle hypothesis has no measured return. All 242 Treasury events
reconcile, but full-interval IEF share-action completeness is unresolved.
The [machine receipt](29-c09-source-audit.json) binds source hashes, dates,
parser versions and the failed prerequisite. Implementation `780b2c2`, present
at recorded HEAD `5f0a104`, produced failed source trial **4585**, strategy
**7164**. The
[stored-only verification](29-c09-ledger-verification.json) confirms idempotence,
null performance columns, no C09 final and all seven prior final rows unchanged.

## Evidence and decision

| Required evidence | Result |
|---|---|
| Dated auction offerings and original-10-year CUSIP lineage | 242/242 in-interval events reconcile; eight 2005 records provide lineage only |
| Dated auction occurrence | 241 PDFs plus one official XML alternative; all dates/CUSIPs agree |
| Linked amendments/special announcements | All 23 distinct documents reviewed and hash-bound |
| IEF session/field coverage | 5,218/5,218 expected sessions, 2006-01-03 through 2026-09-30; no missing/null/invalid rows |
| Issuer cash distribution inventory | All 248 Yahoo ex-dates reconcile to complete issuer components, record and payable dates within the fixed $0.0005 rounding bound |
| Independent raw open/close overlap | 2,701 existing SIP sessions from 2016-01-04 and 1,553 IEX sessions from 2020-07-27; no fixed 1% breaches |
| Complete share-action admission | **Failed:** independent action inventory omits known history; no complete full-period noncash inventory established |
| Strategy training/final/diagnostics | None attempted; both hold variants and all four cost cases remain unattempted |

The independent broker action request explicitly spans 2006–2026 and is an
exhausted, hash-verified response. It contains 127 IEF cash events beginning
2016-02-01 and no noncash events. It omits **121 known earlier issuer cash dates
plus 2016-08-01**. This demonstrates incomplete action coverage; the absence of
noncash rows is not evidence of a complete noncash history. The issuer's complete
cash-distribution table repairs cash amounts/dates, but does not enumerate splits,
reverse splits, in-kind distributions or spin-offs.

Yahoo reports no IEF splits. Public primary searches did not establish a complete
older share-action inventory. Current issuer product material and prospectus
split provisions do not certify historical absence; secondary assertions of no
splits do not establish full noncash coverage or causal notices. We are **not
claiming that IEF had an undiscovered action**. The evidence falls short of the
explicit [batch-2 source gate](25-candidate-shortlist.md#source-and-account-admission).
No date, ticker, tolerance or holding length was changed to get around it.

C06's prior IEF use was a close-only signal, with no IEF ownership. Its source
admission cannot establish C09's execution and share entitlement. Existing
calendar/settlement receipts are preserved as references, not relabelled as a
complete C09 execution contract. No independent pre-2016 price overlap is claimed.
Maximum relative differences were 0.226972%/0.045636% for SIP open/close and
0.161051%/0.259631% for IEX. No prices were spliced or replaced.

## Treasury findings retained for a future source repair

The [official press archive](https://www.treasurydirect.gov/auctions/announcements-data-results/announcement-results-press-releases/)
and its JavaScript supply annual index and document links. Annual responses are
not capped at 500: the 2020 response contains 503 auctions across all securities.
All nominal original-10-year notes are retained, even when their remaining
maturity is far shorter. Old notices may contain several securities; the parser
selects the target CUSIP column and independently checks its dates and maturity.

The source set preserves four emergency reopenings on October 8–9, 2008 and the
June 21, 2019 live small-value contingency auction. Neither size nor unusual
purpose becomes a new selection filter. Multiple auctions on the same date
remain distinct source events; any future strategy must apply the frozen
overlap rule rather than create multiple concurrent IEF positions.

[Special-notice review](29-c09-special-notice-review.json) records all 23 hashes
and dispositions. January 2025's Carter mourning notice moves the ten-year
reopening to January 7; the dated offering and occurrence agree. February 2026's
notice describes a conditional conversion into an original-30-year bond. The
actual occurrence document retains new-note CUSIP `91282CPZ8`, matching the
offering; no yield threshold is used by this strategy. Other notices address
intraday closing times, Treasury settlement, maturing amounts or tax treatment.

The December 9, 2020 occurrence PDF returns 404. The same official index links
[its XML release](https://www.treasurydirect.gov/xml/R_20201209_3.xml), which
confirms the CUSIP, announcement/auction dates and 13:02 release clock. Both the
failed PDF and successful XML are retained. An initial wrong-directory XML probe
also returned 404 and remains archived; it is not counted as an unresolved event.
The parser accepts only this reviewed alternative and rejects wrong identities,
missing/duplicate fields and a release at or after the regular close.

The source audit does not prove historical broker observation latency or model
execution. Treasury results contain financial metrics, but the occurrence parser
reads only identity/date metadata; no yield, tail or bid-to-cover affects a
signal. Generic IEF performance was visible on issuer/search pages and history
was familiar from C03/C06. No auction-conditioned IEF outcome was calculated.

## Promotion checklist and account risk

**Decision: hold at the source gate; real allocation $0.** The mechanism and
fixed rule are specified, and §6 limits remain unchanged. Profitability after
fees, trade count, marked drawdown, regimes, dependence-aware luck, exposure,
turnover and buy-and-hold/cash comparisons are **unmeasured**, not zero. No
training winner or final selection exists. Backtest/paper/live fidelity is
unestablished; there is no promotion or ready-for-live claim.

**What could blow up this account?** IEF retains duration and overnight gap risk;
five or ten days of unhedged bond exposure can lose money regardless of auction
flows. A missing share action can corrupt the price basis, quantity and cash
ledger; a missed amendment or wrong CUSIP can create a false event. The required
action blackout cannot repair an action that has not been identified causally.
The equity slot remains at most $140; the prediction-market $25 cap is not the
applicable limit. Gaps and a failed exit can still cross the unchanged −40% kill
or contribute to the shared −$50 daily halt.

**Adverse selection and execution:** professionals can price auction pressure
before the next ETF open; spreads, gaps and fees can erase it. The 5/10 bp cases
are fixed research assumptions, with no demonstrated live fill quality. No maker
fill or intraday speed advantage is assumed. Stale quotes and API failures remain
subject to the existing 30-second and five-errors/minute halts.

**Venue and inputs:** accepted Alpaca/feed/counterparty concentration remains.
Every downloaded page, PDF and XML is data only. Requests are public GETs or
reuse existing source bytes; no key, account, permission or order changes occur.
No new capital or service subscription is needed for this audit. Downloaded
bytes are bounded and hashed, failed requests retained, and parsers fail on
conflicting identities. Archive hashes make this source conclusion reproducible;
there is no once-only outcome to rerun.

**Correlation:** C09 and C10 share duration exposure; broader rate shocks also
affect the existing allocation. A calendar rule alone does not establish
independent diversification. No portfolio allocation is justified by these
source checks.

Conditional repair **`tradingbot-5hl`** is labelled `blocked:source-evidence` and
requires materially new evidence before another attempt. It cross-links the
shared action-inventory question with TLT repair `tradingbot-wdr` and C03 repair
`tradingbot-2wh`; unchanged-source retries are not ready work.

To reopen admission, establish independently supported full-interval noncash
action coverage, archive causal notices for any events, and complete the planned
calendar/cash/execution contract under Amendment 21. Preserve this failed receipt,
the frozen interval and variants. Source failure has consumed no final; familiar
history still cannot be presented as untouched confirmation.

Validation: **61 affected tests pass**, including 40 C09 checks, existing IEF
source parsers, wrong-CUSIP/date and multi-column cases, XML conversion/clock
rejection, receipt tampering, null-metric enforcement and transactional source
ledger idempotence. No historical strategy was replayed.
