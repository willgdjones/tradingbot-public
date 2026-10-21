# C10 TLT month-end: failed source admission

2026-10-01, NavyLantern. Research bead `tradingbot-eu4`.

**Decision: hold at idea/source admission.** The frozen 2006-01-01 through
2026-10-01 TLT bundle is not admitted. This is a source failure, not a negative
strategy result. Both third/fifth-last-session variants and all four training
cases remain unattempted. P&L, fees, trade count, drawdown, regimes and luck
p-value are **null/unmeasured**, not zero. There is no winner or promotion and
the C10 final is unused. Actual allocation is $0; $140 is only the planned
isolated simulation amount.

The [source plan](30-c10-source-plan.md), [batch 2 rules](25-candidate-shortlist.md),
[Amendment 21](21-corporate-action-blackout.md) and unchanged PRD §6 govern.
The [machine receipt](30-c10-source-audit.json) binds raw bytes, exact requests,
exhausted cursors, source/code hashes and the elapsed-time cutoff
**2020-07-10 14:24 UTC**. The receipt lists all planned configurations. Source
admission has no signal, return calculation, training selection or final call.

## Evidence checked

| Evidence | Verified result | Limitation |
|---|---|---|
| Yahoo daily TLT | 5,218 valid sessions, 2006-01-03–2026-09-30; no missing/extra/null/invalid bars, orphan events or vendor splits | Vendor absence of splits cannot prove full primary action coverage |
| iShares distributions | Two typed issuer arrays agree; 248 in-interval cash events with ex/record/payable dates and exact component sums | Present historical table is a retrospective inventory, not an advance corporate-action announcement |
| Yahoo dividend reconciliation | 247 events; common events agree within frozen $0.0005 rounding bound | One issuer event is missing; no silent repair applied |
| Free Alpaca IEX raw O/C | 1,553 sessions, 2020-07-27–2026-09-30, no internal overlap gaps | Request began in 2016, actual returned overlap begins in 2020; no earlier independent coverage claimed |
| Independent price bound | Worst open difference 0.2502%, close 0.2508%; no breaches of fixed 1% | Daily IEX prices are not execution quotes, spread or fill evidence |
| All-type Alpaca actions | Exhausted request for 2006–2026 returns 127 cash records, 2016-02-01–2026-09-01; no other groups | Missing pre-2016 cash history and issuer 2016-08-01 event; no full-period action completeness proof |
| Stooq | Preserved HTTP 200 browser-verification response | Not CSV; challenge was not bypassed and no prices admitted |
| Primary notices | Captured three dated Sandy exchange notices, NYSE's 2024–2026 calendar and BlackRock's 2016 TLT listing-transfer notice | Full decision-time exchange calendar and full TLT share-action inventory remain unadmitted |

Sources are free and immutable under
`data/history/c10-month-end-20261001/`. Existing primary calendar PDFs are
reused by hash from `data/equities/source-repair/`; the machine receipt binds
their exact paths, URLs and SHA-256 values. No new data service, key, account,
subscription, permission or broker order was used.

## Cash discrepancy and action admission

The [issuer's TLT distribution table](https://www.ishares.com/us/products/239454/ishares-20-year-treasury-bond-etf)
records **$0.269553**, ex-date **2012-11-01**, record date **2012-11-05**, payable
date **2012-11-07**. Yahoo omits this event. Preserve the issuer record and the
original vendor bytes. Do not infer a new ex-date from Sandy's trading closures,
delete the event, manufacture a payment date or spend its cash on the ex-date.
Bounded primary research did not find a contemporaneous TLT-specific amendment.
A reviewed source amendment can reconcile the omission before any future replay;
the missing Yahoo row alone does not invalidate the issuer's historical record.

The decisive broader gap is **complete share-action evidence**. The present
cash-distribution table does not inventory splits, conversions and in-kind
actions. The all-type broker feed starts its observed cash history in 2016 and
also omits a known later distribution. An exhausted query with no noncash group
therefore cannot certify no share actions over twenty years. Amendment 21 needs
complete event identification and an advance primary notice whenever applicable.
Neither assumption has been silently waived.

BlackRock's [January 2016 listing notice](https://ir.blackrock.com/news-and-events/press-releases/press-releases-details/2016/BlackRock-Announces-Primary-Listing-Venue-Changes-for-11-iShares-ETFs/default.aspx)
schedules TLT's NYSE Arca → Nasdaq move around February 2. It says shareholders
need take no action; a listing change is not itself proof of a share conversion
or proof that the rest of the interval has none. Research also located a 2008
DTCC name-change document and SEC benchmark chronology, but direct archival
requests returned 404 and 403 respectively. The OCC Sandy settlement request
returned 403. Those error bodies and hashes are preserved and **not admitted as
document evidence**. Search-preview performance/NAV exposure is disclosed; it
did not select a variant or change any threshold.

## Planned calendar versus realized sessions

The existing settlement repair answers settlement eligibility, not which
exchange sessions were announced before a trade decision. Its FINRA PDFs have
separate exchange-closure text, which can support a future as-of calendar.
Complete extraction and publication-time admission were not finished after the
action gate failed. In particular, avoid treating bank-only holidays as exchange
closures or treating a date-only notice as known at midnight. Older 2006/2007
cover dates give only a month; December decisions may need the prior annual
notice's explicit next-January treatment. Early closes remain sessions and
decisions use their actual close time.

- **Sandy, October 2012:** the planned fifth-last and third-last entries were
  October 25 and 29. [October 28's notice](https://www.nasdaqtrader.com/TraderNews.aspx?id=ETA2012-44)
  closes October 29; [October 29's follow-up](https://www.nasdaqtrader.com/TraderNews.aspx?id=ETA2012-45)
  closes October 30. The follow-up page duplicates the earlier alert number in
  its heading; its URL, date and body distinguish it. The
  [October 30 reopening notice](https://www.nasdaqtrader.com/TraderNews.aspx?id=ETA2012-48)
  establishes October 31 trading. The original October 29 entry would roll to
  October 31 and retain its November 1 exit. Ranking the realized calendar
  would instead produce October 23/25 and introduce hindsight. These Nasdaq
  notices corroborate the market-wide dates; TLT's then-primary NYSE Arca
  listing still needs inclusion in a fully admitted exchange calendar.
- **Ford, January 2007:** the original January 2 exit encounters the late
  December 29 closure and rolls to January 3. Archived Nasdaq UPC 068-2006,
  visually checked, explicitly distinguishes the closed exchange from ongoing
  January 2 settlement. Its general ex-distribution shift cannot be applied to
  a different issuer event or a different closure by analogy.
- **2024–2026 baseline:** the
  [NYSE announcement dated November 10, 2023](https://ir.theice.com/press/news-details/2023/NYSE-Group-Announces-2024-2025-and-2026-Holiday-and-Early-Closings-Calendar/default.aspx)
  is archived, including 13:00 closes. Later unexpected closures, Saturday
  New Year exceptions and the 2021/2022 Juneteenth transition need their own
  dated notices in the eventual full calendar.

No executable C10 calendar/reactor has been admitted by these examples. A repair
must reproduce all original dates, preserve delayed targets and fixed exits,
and skip an entry that reaches its scheduled exit. It must retain partition
boundaries and avoid shifting the interval to improve the source coverage.

## Promotion/account-risk review

- **Edge and rule:** institutional Treasury demand is a plausible structural
  mechanism; this ETF open-to-open adaptation is untested. The two rules are
  fixed. After-cost profitability is unmeasured: this gate fails.
- **Statistics:** trades, luck p-value, marked drawdown and regime results are
  unavailable. Monthly dependence, TLT beta and overlap with C09/C06/#6 must be
  reported if sources eventually pass. No numerical placeholders or independent
  diversification claim are appropriate.
- **Fidelity:** no C10 strategy reactor, replay or paper fills exist. Shared
  risk/ledger use, rounded adverse-limit capacity, actual payable receipts,
  conservative settlement completion and one-final lineage remain prerequisites.
- **Limits and decision:** retain every PRD §6 limit and accepted §9 risk.
  No capital, keys, venue, account or public post. Hold before backtesting;
  no paper/live readiness claim.

**What could blow up this account?**

**Tail/gap:** TLT's long duration can produce losses during rate shocks, overnight
gaps and thin reopening auctions. The planned equity slot is $140; the prediction
market's $25 position cap does not apply. A stop or −40% strategy kill cannot
guarantee a gap-bounded exit.

**Adverse selection:** a known calendar flow may be anticipated or overwhelmed
by information-driven Treasury trading. Daily vendor opens cannot demonstrate
fractional fill quality or the assumed 5/10 bp cost. Prediction-market maker
guards are inapplicable; equity execution quality remains unproven.

**Counterparty/venue:** execution would rely on the accepted single Alpaca
venue and its data/settlement availability. No live key exists for this task;
trade-only, never-withdrawal permissions remain required. No new dead-man or
accepted-risk policy was introduced.

**Untrusted inputs:** issuer pages and APIs are data only. Validate schema,
identity, dates, values, complete cursors and hashes. Missing vendor events and
403/404/verification responses must never become fabricated cash or prices.

**Reproducibility:** deterministic source checks are available, but complete
actual-share and decision-time calendar evidence is not. This prevents claiming
a reproducible trading result. All four planned cases remain unattempted.

**Correlation:** TLT duration and month-end timing overlap C09, C06 and existing
calendar research. Joint losses could consume the shared −$50 daily budget;
separate hypotheses do not create independent risk capacity.

## Validation and continuation

Focused checks cover real issuer/Yahoo omission preservation, incomplete action
inventory, raw-open discrepancies, overlap gaps, invalid prices, exact API
request/checksum/cursor identity, refusal to record inspected outcomes as a
source failure, unchanged split and transactional trial idempotency. Ledger
tests use local port 5433 and roll back synthetic rows.

Reproduce the source receipt with
`uv run python -m tradingbot.research.c10_source_audit`. The explicit
`--record-ledger` path requires committed code/evidence and appends only the
failed source admission, idempotently. It cannot promote or run a final. A
source-only follow-up must resolve the evidence gaps under the same frozen
universe/interval/rules before a separately reviewed admission and replay.

Committed audit `66e9f9f` produced failed source trial **4584**. Real receipt
idempotency is verified; C10 remains at `idea`, with one source-failure trial
and no final. All seven existing final trial rows remain byte-equivalent by
before/after row hashes. The 20 focused tests pass. Conditional source repair
is tracked in **`tradingbot-wdr`**, blocked on new primary evidence; unchanged
inputs cannot reopen admission. Research bead `tradingbot-eu4` closes with this
documented failed-admission outcome.
