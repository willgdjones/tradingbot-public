# C05 commodity ETF trend: source audit stops before replay

**DATA_FAIL — unresolved fractional split treatment.** The fixed five-fund
candidate has complete vendor session coverage, but no admitted policy for
fractional entitlements versus cash-in-lieu and cash availability. No signal,
strategy return, training case or final holdout was evaluated. This says nothing
about the candidate's profitability. P&L, fees, trades, marked drawdown, regime
results and luck p-value remain **unmeasured**, not zero.

The [machine-readable receipt](15-c05-commodity-trend.json) binds exact raw
responses, request URLs, retrieval times, hashes, calendar evidence, code
dependencies and the unchanged [C05 preregistration](07-candidate-shortlist.md).
Archives remain under `data/research/c05/`; every load verifies their hashes.

Failed source-audit trial **3518** belongs to strategy **6032**, bound to
committed audit code `5c6f253`. Independent database readback confirms one
failed trial, null performance, zero orders/fills and zero final attempts.
The strategy remains `idea` with zero allocation.

| ETF | Sessions | Vendor cash distributions | Vendor split events |
|---|---:|---:|---|
| GLD | 4,716 | 0 | None |
| SLV | 4,716 | 0 | 2008-07-24, 10 new shares per old |
| USO | 4,716 | 0 | 2020-04-29, 1 per 8 |
| UNG | 4,716 | 0 | 2011-03-09, 1 per 2; 2012-02-22, 2018-01-05 and 2024-01-24, 1 per 4 |
| DBA | 4,716 | 7 | None |

All five series match official regular sessions from 2008-01-02 through
2026-09-30, with no missing/extra/null/invalid rows, duplicate dates or orphaned
actions. Yahoo's numeric and textual split ratios agree after numeric
normalization; `10.0:1.0` and `10:1` represent the same ratio. A development
validator initially compared their formatting and was corrected before any
ledger result. This was not a vendor-data failure.

Coverage and internal consistency do not establish executable prices or a
complete corporate-action inventory. Yahoo's dividend events contain `amount`
and `date`, not pay dates. Its split-adjusted OHLC cannot be used as historical
actual-share prices while also applying the splits to positions.

## Concrete failed gate

USCF's primary announcements specify cash for fractional entitlements in
[USO's 2020 split](https://www.prnewswire.com/news-releases/uscf-announces-one-for-eight-reverse-share-split-for-the-united-states-oil-fund-nyse-arca-uso-301045001.html)
and UNG's [2011](https://www.prnewswire.com/news-releases/notice-of-reverse-unit-split-116350854.html),
[2012](https://www.prnewswire.com/news-releases/notice-of-reverse-unit-split-138526579.html),
[2018](https://www.prnewswire.com/news-releases/notice-of-reverse-share-split-300574185.html)
and [2024](https://www.prnewswire.com/news-releases/notice-of-reverse-share-split-302026652.html)
splits. These five issuer releases are archived as successful HTTP responses.
Their first post-split trading dates and ratios agree with Yahoo. The 2024
release has stray 2023 dates in later FAQ answers; its opening announcement and
the [subsequent 8-K](https://www.sec.gov/Archives/edgar/data/1376227/000117120024000010/i24014_ung-8k.htm)
identify January 24, 2024.

Two successful, checksum-bound Alpaca captures leave the applicable account
treatment unresolved:

- Its [August 2021 announcement](https://alpaca.markets/blog/updated-terms-for-payments-in-fractional-shares/)
  says splits will deliver fractional shares, replacing cash-in-lieu effective
  August 2, 2021.
- Its [daily-process documentation](https://docs.alpaca.markets/us/docs/daily-processes-and-reconcilations),
  whose captured Markdown reports a November 2025 update, still describes
  possible reverse-split cash-in-lieu, delayed until receipt from DTC.

The issuer's treatment of registered shares and Alpaca's handling of beneficial
fractional holdings are different questions. These sources do not establish
which treatment applies to each C05 event in the intended current-account
counterfactual. Neither fractional continuation nor immediate cash is silently
assumed. The initial target is only $26.60 per active sleeve; rounding away an
entitlement can materially change its holdings and spendable cash.

[OCC memo 46961](https://infomemo.theocc.com/infomemos?number=46961), dated
May 8, 2020, provides a USO cash-in-lieu rate of $16.35028 per whole share
($8.18 for a half share in its adjusted contract) and confirms delayed cash
settlement after the April 29 split. This is useful source evidence, **not** an
Alpaca share-account credit timestamp. UNG's
[2024 OCC adjustment](https://infomemo.theocc.com/infomemos?number=53931)
delivers 25 whole shares per standard adjusted contract; it does not resolve a
retail fractional holding. No option contract or option strategy was traded.

The [SLV issuer announcement](https://www.sec.gov/Archives/edgar/data/1330568/000119312508149627/dex991.htm)
supports its July 24, 2008 trading adjustment and separately describes later
account delivery. This distinction is retained rather than interpreting a split
date as proof of broker availability.

## Other evidence and unfinished checks

DBA's [2008 annual report](https://www.sec.gov/Archives/edgar/data/1383082/000119312509035862/d10k.htm)
identifies a $0.45 payment on December 30 to December 17 holders. Invesco's
[2024 qualified notice](https://www.invesco.com/us-rest/contentdetail?contentId=083ba7fa-a1de-4f70-9b8e-e77ff1228dac&dnsName=us)
lists ex/record date December 23, pay date December 27 and $1.08408 per share,
versus Yahoo's rounded $1.084. These facts came from accessible web text; direct
SEC/OCC requests returned 403 and Invesco returned 406. Those failed HTTP
responses remain archived, explicitly marked failed, not relabelled source
documents. The PDF table was text-extracted; no successful local PDF download
or visual verification is claimed. Full seven-payment reconciliation is pending.

The [shared settlement schedule](13-equity-data-repair-calendar.json) is already
reconciled. C05 does not assert the earlier missing-calendar problem or SPY/XLF
source defects as commodity-universe failures. A nominal settlement schedule
cannot resolve the separate split-entitlement/cash question.

Under the preregistered stop rule, the attempt ends at this failed action gate.
Complete issuer inventory validation, actual-share conversions, independent
same-basis execution-price checks for all five funds, and a frozen cash policy
remain explicitly incomplete. No source/date/ticker substitution, spot-price
proxy or new variant was used to rescue the attempt.

## Preserved experiment and account risks

Bounds stay **2008-01-01 00:00 UTC to 2026-10-01 00:00 UTC**, end exclusive;
the fixed elapsed-time cutoff is **2021-02-14 14:24 UTC**. The three planned
monthly variants remain 252-session total return positive, 126-session total
return positive, and adjusted close above its 200-session SMA. Equality means
cash. Five 19% sleeves retain inactive allocations in cash. Warm-up stays within
each partition. Both 5/10 bp training cases for each variant and the single
10 bp final remain unattempted. The $140 allocation assumption, current fee
book, risk limits, settlement rule and promotion criteria remain unchanged.

**What could blow up the account?** Commodity gaps, prolonged roll losses,
correlated commodity declines, monthly exit delays, fund exposure changes and
mistimed corporate-action cash can produce losses or rejected replacements.
A kill threshold does not guarantee its execution price. USO's 2020 dislocation
and September 2023–January 2024 transition require separate reporting in any
future replay; see [USCF's disclosures](https://www.uscfinvestments.com/disclosures).
GLD/SLV are metal exposures, not a broad commodity basket. C01/C03/C05 share
trend risk, so this family does not establish independent alpha.

GLD source history overlaps C03. Published fund performance was incidentally
visible in issuer/search pages; it did not select rules, dates or variants. No
claim of pristine unseen evidence is made. A later attempt must document and
validate the action/cash amendment and remaining data checks before inspecting
outcomes. Preserve this failure and the unused final. The strategy stays at
`idea`, with no allocation, promotion or orders.

## Reproduce

```sh
uv run python -m tradingbot.research.c05_commodity_trend --capture --capture-evidence
uv run pytest tests/research/test_c05_commodity_trend.py -q
# Commit audit code and dependencies before its durable failure receipt:
uv run python -m tradingbot.research.c05_commodity_trend --record-ledger
```

Eight focused tests pass: fixed bounds, coverage/field integrity, identity,
split normalization and invalid actions, byte/URL provenance, missing action
evidence, and transactional failed-trial idempotence without holdout consumption.
This module has no strategy replay or final-admission path.
