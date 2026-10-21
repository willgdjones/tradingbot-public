# C09 auction-cycle source audit

2026-10-01, OrangeCove; `tradingbot-b8y`. This work implements the source gate in
[the frozen batch-2 specification](25-candidate-shortlist.md), without changing
the interval, universe, variants, costs or risk limits. No C09 strategy return,
signal, benchmark, training case or final has been computed.

## Binding scope

- IEF only; nominal original-10-year Treasury note auctions, including every
  reopening. The two holding lengths remain five and ten full session intervals
  from the originally planned next-session entry open. No auction yield, tail,
  bid-to-cover, size or realized price determines event inclusion.
- Sources span 2006-01-01 through 2026-10-01 exclusive; the elapsed-time split is
  2020-07-10 14:24 UTC. The additional 2005 Treasury documents establish CUSIP
  lineage only. They cannot supply an out-of-partition strategy observation.
- $140 virtual cash, frozen 95% target and adverse rounded-limit sizing; 5/10 bp
  per side plus the dated fee book. Amendment 21 and all PRD §6 limits remain
  binding. A source failure must be logged before outcomes and leaves both
  variants unattempted, with no final consumed.

## Source procedure

The official [Treasury press archive](https://www.treasurydirect.gov/auctions/announcements-data-results/announcement-results-press-releases/)
and its downloaded JavaScript identify the annual search and PDF paths. Archive
every annual response, offering PDF, linked special announcement and occurrence
release with request identity, HTTP status, retrieval time, length and SHA-256.
Captures are bounded, immutable and subject to the existing disk budget. A
non-200 response remains evidence of failure. Annual rows enumerate events;
dated offering documents establish the schedule independently.

The parser binds the correct CUSIP column in old multi-maturity notices, release
date, auction date, original issue lineage and maturity. It retains the 2008
emergency reopenings and June 2019 small-value contingency operation. Review
special announcements separately, including January 2025's schedule change and
February 2026's conditional possible original-30-year reopening. Occurrence
verification uses only the release date and CUSIP, never a result-based signal.
Representative old and modern PDFs were rendered and visually checked.

Recheck the existing IEF Yahoo bytes, full exchange-session coverage, issuer
distribution components/ex/record/pay dates, and existing raw IEX/SIP open/close
overlaps at the fixed 1% bound. No independent price coverage before 2016 is
claimed. Reuse the reviewed cash/calendar receipts only within their documented
scope; C06's IEF close-only signal evidence cannot authorize owning IEF.

## Current unresolved evidence

The broker action request starts in 2006, but its IEF results begin February
2016. It omits 121 known earlier cash-distribution dates and August 1, 2016.
The issuer table reconciles all 248 cash distributions, but is not a complete
noncash-action inventory. Yahoo's empty split list and an incomplete independent
action feed do not, by themselves, establish the full share-action admission
required by the frozen specification. This is a coverage limitation, not a claim
that an undiscovered split actually occurred.

The initial full Treasury occurrence capture also retained one HTTP 404,
`R_20201209_3.pdf`. Its official linked XML alternative reconciles the same CUSIP,
announcement/auction dates and a 13:02 release clock. Both responses are retained.
All 242 events and 23 special notices reconcile. Final source findings and ledger
receipts follow in a separate report; strategy replay remains barred by IEF's
unresolved share-action inventory.

Public fund pages and search snippets exposed general IEF performance already
familiar from previous work. No C09 event-conditioned outcome was calculated.
Treasury result files necessarily contain auction metrics; none is parsed for
event selection or used as alpha.

Validation at this preparation boundary: 18 focused integrity/parser checks pass,
covering wrong CUSIPs/dates, multiple notice columns, emergency reopening
classification, duplicate fields, changed bytes, path traversal and fixed bounds.
The completed source/recorder slice passes 61 affected checks, including XML
identity and release-clock validation, immutable receipt checks, outcome-claim
refusal and transactional ledger idempotence without spending a final.
