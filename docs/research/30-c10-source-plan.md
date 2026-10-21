# C10 TLT month-end source admission plan

2026-10-01, NavyLantern. Bead `tradingbot-eu4`.

This freezes source checks before fetching TLT bars or calculating any C10
signal, outcome or selection. The parent [batch 2 rules](25-candidate-shortlist.md)
remain binding: TLT only, 2006-01-01 through 2026-10-01 exclusive; elapsed-time
70/30 cutoff 2020-07-10 14:24 UTC; two entry variants, third-to-last then
fifth-to-last announced regular session open; exit first announced regular open
next month. Decisions occur at the preceding close. Unexpected closures delay
execution while preserving original planned dates; never re-rank a past month
from its realized session list. All event endpoints/warm-up stay in partition.

Capture immutable Yahoo daily OHLC/adjusted close and action bytes, a Stooq
request, the primary iShares TLT distribution page, and existing-key free Alpaca
IEX raw open/close overlap from 2016 plus all-type corporate actions. No premium
feed, source splice or changed interval. Full coverage and positive/valid fields
must reconcile to the existing hashed exchange calendar. Compare every available
independent raw open and close at the existing 1% discrepancy bound; any breach
needs primary exchange evidence without changing the threshold or Yahoo price.
No independent coverage is claimed before the reference's start.

Require complete ordinary cash amounts/components, ex/record/payable dates and
all share-action notices. Reuse the tested iShares parser only if its two typed
embedded distribution views agree exactly, then reconcile every Yahoo event
against the issuer inventory. Vendor event omission is not proof of no action.
Document TLT's benchmark chronology separately from share conversions. Ordinary
cash is a receivable based on pre-ex-open ownership, becoming spendable only at
the first regular opening after documented payable date. Apply Amendment 21 to
any split/in-kind action, using advance primary notices; blackouts cancel an
event rather than restarting it late.

Audit announced exchange calendar availability separately from actual exchange
sessions and settlement eligibility. In particular, October 2012's pre-Sandy
planned entries are October 25/29, not the dates obtained by deleting closures
before ranking; December 2006's planned January 2 exit encounters the late Ford
closure. Dated exchange notices and their decision-time availability govern.
The shared settlement repair supplies dated T+3/T+2/T+1 and operational-delay
evidence, not an as-of exchange calendar or actual broker credit.

If admitted, implement the pure reactor and shared risk/ledger replay before
the four frozen training cases (two variants × 5/10 bp per side). Clip fractional
quantity at the rounded adverse limit, frozen target, $140 cap and settled cash,
with 95% equity target/reserves. Preserve delayed targets and fixed exit; skip
an entry that cannot precede it. Select only a complete profitable 10 bp training
case by net dollars, preregistered order for ties. Freeze before the sole final,
guarded by the canonical `c10` family; failures/interruption consume a final.
Do not compute returns while any source prerequisite is unresolved.

Source exposure: no TLT strategy outcomes have been inspected. Searching issuer
benchmark/action documents exposed annual fund-return/NAV figures in previews;
these are disclosed and cannot select parameters. C09/C06 and existing SPY
calendar work share duration/calendar hypotheses. Monid discovery offered paid
or unrelated endpoints; none were run. All sources remain free.

The complete parent promotion/account-risk review still applies. No promotion,
real allocation, account/key/venue, public post or order occurs during source
admission. PRD §6 and accepted §9 risks remain unchanged. A source-failure
receipt with null return metrics is a valid conclusion, not permission to
discard problematic dates or fabricate prices, notices or cash credits.
