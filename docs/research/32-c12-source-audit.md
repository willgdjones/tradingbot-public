# C12 scheduled macro risk: failed calendar admission

2026-10-01, NavyLantern; `tradingbot-lna`.

**Decision: hold at idea/source admission.** Complete decision-time BLS
announcement and revision evidence is not established for the frozen
2006-01-01–2026-10-01 interval. This is an evidence failure, not a negative
strategy result. Both Employment Situation/CPI variants and all four 5/10 bp
training cases remain unattempted. P&L, fees, trade count, marked drawdown,
regimes and luck p-value are **null/unmeasured**, not zero. No selection,
final-holdout use, promotion, order or allocation occurred.

The [source plan](32-c12-source-plan.md), [frozen batch rules](25-candidate-shortlist.md)
and [Amendment 21](21-corporate-action-blackout.md) govern. The
[capture inventory](32-c12-evidence.json) binds 74 public responses, including
HTTP failures and connection failures. The [machine receipt](32-c12-source-audit.json)
checks raw bytes, manifests, issue identities, sampled original release
announcements and the unchanged **2020-07-10 14:24 UTC** split. Sources are
free and retained under `data/history/c12-macro-20261001/`.

## What the archives establish

The [FRASER Employment](https://fraser.stlouisfed.org/title/employment-situation-144)
and [CPI](https://fraser.stlouisfed.org/title/consumer-price-index-6838) indexes
cover 247 and 248 of 249 reference months, December 2005–August 2026.
Both omit canceled October 2025. Employment also omits June 2024, whose
[original July 5 BLS PDF](https://www.bls.gov/news.release/archives/empsit_07052024.pdf)
was captured separately. That omission is repairable and is not itself the
reason for failing admission. An issue's existence or archive ingestion date
does not establish advance schedule knowledge. Non-monthly notices remain
separate from the monthly denominator.

Fourteen original BLS PDFs were sampled across ordinary months and exceptional
periods. Thirteen explicitly announce a subsequent release; the
[October 24, 2025 CPI release](https://www.bls.gov/news.release/archives/cpi_10242025.pdf)
does not. The parser checks the embargo/publication date against the archived
URL, weekday, Eastern daylight-saving convention, family, reference month and
future date. It extracts no macro value, surprise, forecast or trading signal.
Access-denied HTML is retained but never parsed as an announcement.

The original OMB [2025](https://statspolicy.gov/assets/fcsm/files/docs/OMB_pfei_schedule_of_release_dates_2025.pdf)
and [2026](https://statspolicy.gov/assets/fcsm/files/docs/OMB_pfei_schedule_release_dates_cy2026.pdf)
calendars preserve planned dates, including later-canceled releases.
Page 4 of each PDF was rendered and visually checked. Official publication
history dates them [September 27, 2024](https://statspolicy.gov/fiscal-year-2024-news/)
and [September 26, 2025](https://statspolicy.gov/resources), respectively.
They establish dates/reference months; the PDFs do not independently establish
08:30 BLS release times. No first-Friday or realized-date substitution is used.

## Revision chronology that cannot be silently repaired

| Reference event | Preserved original / later schedule | Decision-time consequence |
|---|---|---|
| September 2013 Employment | Sep 6 release announces Oct 4; DOL Oct 3 withdraws it; Oct 17 notice gives Oct 22 | Original decision is Oct 2 close. The Oct 3 notice is later; it cannot erase the original Oct 3–7 holding window or extend its exit. Earlier suspension completeness still needs reconciliation. |
| October 2013 Employment | Oct 22 release explicitly replaces Nov 1 with Nov 8 | This is a dated prior-release replacement before the original Oct 30 decision. |
| September 2013 CPI | Sep 17 release announces Oct 16; later replacement is Oct 30 | Original decision is Oct 14 close. Earlier suspension availability is unresolved; the Oct 17 replacement notice alone is too late. |
| October 2013 CPI | Oct 30 release explicitly replaces Nov 15 with Nov 20 | The replacement is before the original Nov 13 decision. |
| September 2025 Employment | Sep 5 release announces Oct 3; eventual release is Nov 20 | Preserved primary suspension chronology by Oct 1 close is incomplete. Do not drop or delay the original window from retrospective knowledge. |
| September 2025 CPI | Sep 11 release announces Oct 15; BLS Oct 10 notice gives Oct 24 | The dated revision precedes Oct 13 close. Its proposed revised window is Oct 23–27, subject to all other gates. |
| October 2025 Employment / CPI | OMB plans Nov 7 / Nov 13; both eventually canceled | Preserve original identities and planned denominator. The revised table does not date each cancellation announcement. |
| November 2025 Employment | OMB plans Dec 5; Nov 20 release gives Dec 16 | A dated prior release establishes the replacement before the original Dec 3 decision. |
| November 2025 CPI | OMB plans Dec 10; eventual release Dec 18 | The current December calendar is modified Dec 11, later than original Dec 8 decision. Earlier revision provenance remains unresolved. |
| January 2026 Employment | Jan 9 release announces Feb 6; eventual release Feb 11 | February calendar is dated Feb 4 without a time. This cannot establish availability before that same day's original decision close. |
| January 2026 CPI | Jan 13 release announces Feb 11; later date Feb 13 | February calendar's Feb 4 date precedes original Feb 9 decision, but the exact prior version still needs admission. |

Original release PDF hashes and parsed sentences are in the machine receipt.
Additional primary references: [DOL Oct 3, 2013](https://www.dol.gov/newsroom/releases/opa/opa20132030),
[DOL Oct 17, 2013](https://www.dol.gov/newsroom/releases/opa/opa20132044),
[BLS Oct 10, 2025 CPI notice](https://www.bls.gov/bls/092025-cpi-reschedule-notice.htm),
[December 2025 calendar](https://www.bls.gov/schedule/2025/12_sched_list.htm),
[February 2026 calendar](https://www.bls.gov/schedule/2026/02_sched_list.htm).
Browser-extracted primary text/search discovery and raw 403 responses are
preserved separately; extracted browser text is not relabeled original HTML.

The [current revised-date table](https://www.bls.gov/bls/2025-lapse-revised-release-dates.htm),
modified February 12, 2026, is retrospective. The accessible
[FRASER PDF snapshot](https://fraser.stlouisfed.org/files/docs/releases/bls/bls_lapse_2025.pdf)
instead records January 23, 2026 (PDF created January 29). Neither proves the
first announcement time of 2025 revisions. A date-only notice is conservatively
available from the next local midnight; it cannot prove same-day pre-close
availability. This is a known-provenance limit, not a claim that no earlier
notice ever existed.

The [March 6, 2026 Employment PDF](https://www.bls.gov/news.release/archives/empsit_03062026.pdf)
announces April 3, Good Friday. C12 excludes this non-equity-session date;
it does not roll it to Monday. Calendar diagnostics use only the frozen
session dates/open/close timestamps; no event-conditioned prices are computed.

## Remaining admission scope

Twenty-seven Fed documents were archived, locating annual advance schedules
for 2006–2026 and specific changes in 2005/06, 2008/09, 2011/12 and March 2020.
Examples include the [2006 baseline](https://www.federalreserve.gov/boarddocs/press/monetary/2005/20050629/default.htm),
[2009 revisions](https://www.federalreserve.gov/newsevents/pressreleases/monetary20090213a.htm),
[2012 revisions](https://www.federalreserve.gov/newsevents/pressreleases/monetary20120516b.htm)
and [March 15, 2020 conference](https://www.federalreserve.gov/mediacenter/files/FOMCpresconf20200315.pdf).
For the latter, do not assign the statement's 17:00 timestamp to later conference
wording. Annual schedules, revisions and unexpected emergency meetings remain
distinct. Full event-by-event FOMC exclusion reconciliation stopped at the failed
BLS gate; it is not claimed complete.

The exact [SPY source amendment](13-equity-data-repair-spy-amendment.json) is
rechecked by hash: 5,218 open/close sessions and 83 issuer distributions.
Its excluded high/low/volume/adjusted-close fields and source-exposure disclosures
remain intact. It is not a complete primary noncash-action inventory or proof
of fractional opening-auction fills. Full C12 action admission, cash/settlement
replay and same-code strategy implementation remain unfinished prerequisites.
Existing source access failures are not used to dismiss the working free archives.

## Promotion checklist and account-risk decision

- **Edge/rules:** scheduled aggregate-news risk compensation is testable;
  Employment and CPI remain separate adaptations of published research. Fixed
  entry/exit, predecision revisions, FOMC exclusions and training-only shifted
  controls are specified. Historical profitability is not established.
- **Statistics:** trades, P&L, fees, marked drawdown, regimes, month-cluster luck,
  buy-and-hold/cash diagnostics and #6 overlap are unmeasured. Null values do not
  signify flat performance. No winner or final is eligible.
- **Fidelity:** no admitted C12 shared replay, paper reproduction or live fills.
  No assertion that daily opens guarantee fractional execution within 5/10 bp.
- **Limits/decision:** hold at idea, allocation **$0**; $140 is only proposed
  virtual cash. PRD §6 and accepted §9 risks remain unchanged. No capital,
  account, venue, key, public post or order is created.

**What could blow up this account?**

**Tail/gap:** the rule deliberately holds SPY across overnight and macro-news
risk. Gaps can exceed planned costs and the stop/−40% strategy kill cannot
guarantee its exit price. The ETF cap is the strategy slot, not the prediction
market's $25 cap.

**Adverse selection:** informed flows around scheduled releases can overwhelm
an average risk premium. Market opens and fractional execution need actual
fill evidence. Prediction-market maker quote guards are inapplicable to this
long-only ETF rule; they are not claimed as protection.

**Counterparty/venue:** eventual execution relies on the accepted single
Alpaca venue, data and settlement services. No live key is used; trading-only,
never-withdrawal permissions remain required. Accepted dead-man/venue risks
are restated, not changed.

**Untrusted inputs:** agency pages, archives and metadata are data only.
Validate identity, timezone, date, reference month, hashes and response status.
A 403 body, missing issue, current calendar or late publication cannot become
invented advance knowledge.

**Reproducibility:** source diagnostics are deterministic and retain failed
retrievals. The missing revision chronology prevents a reproducible causal
strategy result. Changing dates after seeing returns would invalidate the test.

**Correlation:** SPY exposure overlaps C11, C06 and existing #6/calendar research.
Joint equity gaps could hit the shared −$50 daily halt. Published macro-risk
results and earlier SPY inspections are dependent prior evidence; this source
audit creates no fresh independent confirmation.

## Validation and continuation

Focused checks cover immutable raw/source identity, bounded response and error
budgets, original event denominators, explicit next-release extraction, missing
announcements, timezone/weekday contradictions, Good Friday, same-day notice
ambiguity, unchanged cutoff and idempotent null-metric ledger recording. Ledger
tests use port 5433 and roll back synthetic rows.

Reproduce with `uv run python -m tradingbot.research.c12_source_audit`.
`--record-ledger` requires committed code/evidence and can only append the
failed source admission. It cannot run a final or promote. Any future source
repair must preserve the frozen universe/interval/rules and resolve chronology
before replay; unchanged current calendars cannot reopen admission.

Implementation `07c02e7`, recorded under HEAD `d2e5018`, produced
failed source trial **4591** (strategy **7170**, retained at `idea`).
[Stored-ledger verification](32-c12-ledger-verification.json) confirms one
idempotent source row, null performance metrics, zero C12 finals and unchanged
hashes for all seven existing final rows. All **28 focused checks pass**.
Conditional repair **`tradingbot-qb5`** is `blocked:source-evidence`; unchanged
inputs cannot reopen this result. Research bead `tradingbot-lna` closes under
its explicit source-failure acceptance criteria.
