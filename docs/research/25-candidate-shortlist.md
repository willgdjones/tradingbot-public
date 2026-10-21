# Alpaca candidate batch 2: six frozen research specifications

2026-10-01, NavyLantern; parent `tradingbot-5n1`. Rules and source intervals
are fixed before fetching new candidate bars, option outcomes or running any
candidate replay. This is a desk review and research handoff, not a profitability
claim. [Source register](batch2-sources/2026-10-01-sources.md) preserves the
evidence, limitations and prior-inspection disclosures. The machine-readable
[candidate index](batch2-sources/2026-10-01-candidate-index.json) binds the rules
and exact `HoldoutSplit` boundaries.

## Ranking and intake decision

Use the [intake rubric](../strategy-intake/README.md) and current PRD §3–§6.
Scores 0–3 mean evidence / evaluability / low implementation cost / manageable
failure exposure; higher is better. They rank research work, not expected returns.

| Rank | ID | Candidate | Gates 1/2/3 | E/P/C/R | Verdict |
|---|---|---|---|---|---|
| 1 | C09 / `tradingbot-b8y` | IEF recovery after 10-year Treasury auctions | pass/pass/conditional | 3/2/2/2 | Pursue source admission, then bounded backtest |
| 2 | C10 / `tradingbot-eu4` | TLT month-end institutional demand | pass/pass/conditional | 3/2/2/1 | Pursue source admission, then bounded backtest |
| 3 | C11 / `tradingbot-e76` | SPY standard monthly option-expiration week | pass/pass/conditional | 2/2/3/2 | Pursue source admission, then bounded backtest |
| 4 | C12 / `tradingbot-lna` | SPY scheduled employment/inflation announcement risk | pass/pass/conditional | 3/2/1/1 | Pursue calendar audit first |
| 5 | C13 / `tradingbot-0cm` | Earnings-uncertainty long call + long put | pass/pass/failed historical execution gate | 2/0/1/1 | Park alpha replay; one source/capital-feasibility bead |
| 6 | C14 / `tradingbot-ddw` | Conditional cash-secured stock entry after a pullback | pass/testable/failed historical execution gate | 1/0/1/0 | Park alpha replay; one source/capital-feasibility bead |

There are **12 signal variants and 24 planned training configurations** (two
cost cases each), conditional on admission. Six candidate beads do not authorize
six funded slots. C09/C10 share duration risk; C11/C12 and existing #6 share SPY
beta/calendar exposure. C14 retains short-volatility tail risk: its inclusion is
the owner's explicit request for cash-secured cheap-stock puts in this bead and
PRD §3, not revival of generic short-vol/VIX strategies on the dead list.

## Common preregistration

### Source and account admission

Apply [07's common rules](07-candidate-shortlist.md#common-preregistration-binding-on-all-eight-beads)
except the explicit candidate/option-specific rules below. Use a **$140 virtual
cash allocation**, no borrowing, no short stock, no cash interest, and the
unchanged shared risk engine. ETF entries target `min(0.95 * decision equity,
$140)` including the common fee/cash reserves, rounded down to allowed fractional
precision and limited by settled cash. Do not spend sale proceeds before their
documented settlement completion; execute a delayed purchase at the first
eligible session open after release, without recomputing the frozen dollar
target. Any planned event exit remains fixed; skip if the delayed entry cannot
precede it. No purchase below $1. No price/feed/interval substitution to rescue
a source failure or result.

Clip share additions at the **rounded adverse buy limit**, not the reference
mid/open: total owned plus added quantity valued at that limit must fit $140,
the frozen target and settled cash after fees/reserves. This incorporates the
existing [C04 capacity repair](24-c03-c04-c04-sizing-amendment.md) without
changing the risk limit. Quantities round
down; an exhausted capacity skips the addition and is reported. For every
`S+H` rule below, S is the **originally scheduled** entry session. Cash or
closure delays cannot reset S or extend the planned exit.

ETF source evidence requires raw Yahoo opens/closes, adjusted signal series,
independent price reconciliation (Stooq/Alpaca IEX or primary exchange evidence),
issuer cash-distribution entitlement and payable dates, exchange/settlement
calendars and complete share-action admission. A previous admitted bundle may
be reused by hash only when its full coverage, policy and instruments match.
Present fractionability/tradability is not historical evidence. Archive dated
primary event notices, corrections and retrieval hashes before strategy P&L.
Missing or conflicting source evidence is a recorded failed admission, not
permission to discard inconvenient events. Planned calendars use notices known
at decision time; unexpected closures delay execution, never redefine the
original signal using hindsight.

**Amendment 21 applies by default.** Exit at the last regular open before an
identified split/reverse split/in-kind action, decided at the preceding close;
stay flat through the payable date. Require a primary announcement available by
that decision. Unknown or edge-of-record actions still fail admission. Ordinary
dividends remain receivables until proven payable. For these event strategies,
blackout cancels a pending entry or truncates a holding; re-entry requires a
new normal event, never a late restart of the cancelled event. For C13/C14 this
also covers OCC deliverable adjustments: close all affected contracts and any
assigned shares, and fail admission if causal notice or safe exit evidence is
missing. Do not assume that adjusted contracts are standard contracts.
[Amendment 21](21-corporate-action-blackout.md).

No paid source, subscription, new key/account/venue, capital movement, public
post or trading permission change is part of this work. Source admission and
simulation remain separate from real paper/live orders.

### Partition, trials and selection

| Families | Complete UTC source interval (end exclusive) | Final 30% begins |
|---|---|---|
| C09–C12 | 2006-01-01 00:00:00Z to 2026-10-01 00:00:00Z | 2020-07-10 14:24:00Z |
| C13–C14 | 2024-02-01 00:00:00Z to 2026-10-01 00:00:00Z | 2025-12-13 02:24:00Z |

Use the shipped elapsed-UTC-time `HoldoutSplit`, not a row/trade-count split.
Keep price warm-up, required event-announcement observations and complete round
trips inside each partition. Start flat. Calendar/rules metadata may describe
the exchange clock, but an event-specific forecast/announcement used as a
signal must itself be available within the partition. Skip the initial warm-up
events consistently; do not use pre-boundary returns or earnings announcements.
Do not enter a trade whose scheduled exit lies outside the partition. The final
eligible reference open is liquidation-only for residual positions, with costs;
no forced close may bypass a risk veto. A killed/interrupted/partially executed
run is failed, with remaining marked inventory reported, not an eligible winner.

For ETFs use fixed **5 bp / 10 bp adverse costs per side**, plus the dated
September 17, 2026 `EquityFeeBook` as a current-fee historical counterfactual.
Expenses already in ETF prices are not deducted twice. Options use the two
separate cost cases below. Each source failure, attempted variant, parameter
change and extra diagnostic belongs in the trials ledger, including failures.
This preregistration itself has no executed trials.

Choose one completed, eligible variant per family by highest **positive net
dollar training P&L at the higher cost case**; ties use listed variant order.
The lower cost is diagnostic only. No positive eligible winner means no final.
Commit sources, code, training evidence and frozen choice before consuming the
last 30% **once at the higher cost**, including failed/interrupted attempts.
No second cost run, sibling variant, cosmetic version or renamed dataset
recycles the final. Source-gate failure does not consume an outcome holdout.

These are deterministic strategies. The special ≥7 days/≥30 trades replacement
proof rule applies only to AI-decided strategies, not to these six. Existing
source probes and SPY/IEF/TLT history used in previous work are disclosed; this
mechanical partition does not make familiar history untouched confirmation.

### Required evaluation

Report gross/net dollars, all fees/slippage, marked max drawdown in dollars and
as percentage of peak and initial allocation, exposure, turnover, completed
round trips, partial legs/assignments, rejected orders, settlement delays,
missed/calendar events, blackout sessions and forced-exit costs. Show calendar
years and 2006–2009, 2010–2019, 2020–2021, 2022, 2023–2026 where covered; option
history only spans 2024–2026 and cannot establish earlier regimes. Report the
final boundary's partial year explicitly. No regime tuning or new luck gate.

Compute benchmarks from the same admitted observations: zero-yield cash and
buy-and-hold of the traded ETF; options also compare the same underlying event
windows using fractional stock with common equity costs. Benchmarks are
diagnostics, not extra promoted strategies. Report shared exposure with #6 and
C01–C08. Raw positive beta/insurance compensation is not incremental alpha.
Use month clusters for calendar strategies and issuer/earnings-event dependence
for options; disclose insufficient clusters with a null/unreliable p-value.
Roughly 250 monthly events over 20 years, or only about 10 months in the options
final, cannot guarantee significance. The illustrative independent-sample count
`(1.96 / 0.10)^2 ≈ 384` is not a power guarantee or promotion criterion.

## Candidate rules

### C09 — IEF recovery after nominal 10-year auctions

**Reason:** intermediary inventory constraints can create auction-cycle price
pressure/reversal. Lou–Yan–Zhang studies Treasury securities and hedged portfolios;
recent NY Fed work finds intraday effects that might dissipate before our entry.
IEF is a basket with unhedged duration exposure, not the auctioned bond.
[Author paper](https://ifr.hkust.edu.hk/uploads/upload/files/20250212/f5cba4b7e2aa3ada8477ad2fc38fab02.pdf),
[NY Fed SR1188](https://www.newyorkfed.org/research/staff_reports/sr1188.html).

**Universe/event:** IEF only. Every nominal **original-10-year** note auction,
including reopenings mapped by original issue/CUSIP. Exclude TIPS, FRNs and
other original maturities. Use archived Treasury offering notices and dated
amendments; current auction-search rows enumerate events but do not alone prove
past availability. No tail, bid-to-cover, yield or subsequent-price condition.

**Timing/variants:** decide at the first regular ETF close on/after auction date
A, using schedule information then known. Schedule entry for the next regular
session open S; any actual delay follows the common fixed-exit rule.
Exit at S+**5**, then S+**10** exchange-session opens (five/ten full open-to-open
intervals). Ignore overlapping events while invested; never extend an exit.
Common ETF sizing and interval apply. Advance cancellation removes the event;
unknown occurrence or contradictory notice provenance fails admission.

**Failure/falsification:** duration losses, an effect gone before next morning,
fees and IEF tracking can dominate. Compare with IEF buy-and-hold and, as a
training-only diagnostic, the equal-length window from S−H open to S open for
holding length H, excluding controls intersecting another auction holding
window. Skip controls missing an endpoint or crossing a partition; do not search
for replacements. The shared endpoint is not an overlapping holding interval.
No diagnostic chooses parameters or creates a second final run.

### C10 — TLT month-end institutional demand

**Reason:** scheduled institutional purchases and benchmark additions can
concentrate Treasury demand at month-end. Hartley–Schwarz uses individual/
synthetic bonds and financing, not TLT. NY Fed closing-flow evidence supports
the mechanism, not this ETF rule's profitability.
[Author paper](https://www.kristaschwarz.com/EOM.pdf),
[NY Fed closing flows](https://libertystreeteconomics.newyorkfed.org/2026/09/treasury-trading-at-the-close/).

**Rule/variants:** TLT only. Buy at the **third-to-last**, then **fifth-to-last**
regular session open of each month, deciding at the preceding session close
using the announced session calendar. Exit at the first regular open next
month. No price/yield/volatility/quarter-end filter, no daily resizing. Common
ETF sizing and interval apply. Keep the originally planned dates if an
unexpected closure changes the realized calendar; execute at the next eligible
open, and skip an entry if it can no longer precede its fixed exit.

**Failure/falsification:** long-duration losses overwhelm the flow; an
open-to-open ETF adaptation may miss a close-based bond effect. Dividend cash
timing matters around month boundaries. Report TLT beta and overlap with
auctions, C06 and #6. Duration/calendar dependence precludes a claim of new
independent diversification.

### C11 — SPY standard monthly option-expiration week

**Reason:** dealer hedge changes and option-linked risk perceptions may affect
option-active equities during expiration week. The published stock-portfolio
finding is not proof of a broad SPY calendar trade.
[Stivers–Sun](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1571786).

**Rule/variants:** SPY only, no option position. Identify the standard monthly
third-Friday expiration, with holiday adjustments from archived OCC/Cboe
calendars. The expiration **session** means the last regular equity trading
session associated with standard monthly expiry, including historically
Saturday-dated legal expirations; never seek a Saturday close. Use that
session's Monday–Sunday New York week. Decide at the preceding week's
last session close; buy at expiration week's first regular open. Exit at
**the standard expiration session close**, then **the next regular session
open**. Both exits are scheduled without observing their prices. Missing
execution-price/close-order evidence fails admission of the affected variant;
do not silently replace a close by an open. Common ETF sizing/interval apply.

**Failure/falsification:** monthly activity may be diluted by weekly/daily
expirations; 2022's expansion to weekday SPX expirations is a predeclared
structure break. Quarterly dividend entitlement must be correct. As a
training-only diagnostic, shift both planned endpoints exactly seven calendar
days earlier and seven days later into non-expiration weeks, preserving the
open/close endpoint type. Skip a control unless both shifted endpoints are
regular sessions, it has the same number of session intervals as the trade,
and its complete window is inside the partition. Never roll dates or search
for replacements. Cluster by month; never use the result to move the trading
week. Positive SPY drift alone is insufficient.

### C12 — SPY scheduled macro-announcement risk

**Reason:** bearing scheduled aggregate-news risk may command compensation.
Savor–Wilson studies broader daily market returns and several release classes;
its historical inflation series principally uses PPI after 1971. Our CPI-only
variant is an adaptation, not exact replication or a pre-FOMC revival.
[Author paper, §3.1](https://rodneywhitecenter.wharton.upenn.edu/wp-content/uploads/2014/04/0906.pdf).

**Rule/variants:** SPY only; **BLS Employment Situation only**, then **BLS CPI
only**. Each forthcoming event must be announced in a dated prior BLS release
or official notice available by the decision. Require announced date D to be
an equity session. Decide at the close two sessions before D; enter at the
preceding session's open; exit at the first session open after D. No actual
release value, surprise, consensus, directional filter or revised actual-date
calendar. This adds prior-day/post-release exposure to the paper's daily rule.

Use only schedule revisions published before the decision: cancellation
removes the event and an announced replacement supersedes it. After decision,
keep the original exit despite postponement; never extend the holding period.
At most one entry per release type/reference month; skip overlaps while held.
Missing/contradictory advance provenance fails source admission. Exclude a
window that intersects a scheduled FOMC decision session **or its preceding
session**, based on Fed notices available before the decision. Unknown Fed
calendar provenance fails the gate. No retrospective removal of losing events.
Common ETF sizing and interval apply.

**Failure/falsification:** announcement gaps, ordinary SPY beta, fees and event
date errors. Report overlap with #6. Training-only comparison uses the same
weekday and duration shifted exactly seven calendar days earlier, skipping
control windows that intersect either BLS family or the same FOMC exclusion.
Shift both planned open endpoints; skip unless both are regular sessions, the
session-interval count matches and the complete window is inside the partition.
Never roll a closed date or search for replacement controls.
Keep family results separate; the published pooled result proves neither one.

## Options: additional binding admission and execution rules

[Harness 10](10-options-data-harness.md) demonstrates today's contract catalogs,
modified indicative quotes and historical bars/trades, **not historical BBO,
point-in-time chain membership or executable fills**. Free option history is
documented only from February 2024. Current inactive contracts cannot establish
past listing dates, and provider-unspecified trade/bar feeds cannot be relabelled
as OPRA. C13/C14 fail the current historical execution gate: their beads first
test source/capital/model feasibility; no historical strategy P&L is authorized
until every required input is admitted. A recorded failure is a valid completion.

Require timestamped historical tradability/listings including expired/delisted
series, contemporaneous bid/ask with sizes, point-in-time standard deliverables,
underlying raw/adjusted prices and actions, event/assignment chronology and
exact fee/settlement rules. Only standard American USD equity contracts on
**100 shares**, with no cash/other deliverables. Check real account capability
read-only; do not request an upgrade. One position at a time per candidate,
whole contracts only. Do not use today's open interest, Greeks or chain to
screen historical trades. No fitted theoretical price or invented spread can
fill a missing BBO. Indicative/synthetic/forward captures may validate plumbing,
but do not satisfy historical alpha or automatically activate a strategy.

After source admission, entries/exits use the first valid regular-session BBO
at/after 09:30 New York, observed by 09:35, with quote age ≤30 seconds and size
at least the intended contracts. No entry if absent; a missing required exit
quote fails the run rather than supplying a future/zero mark. Normal marks
must include an executable liquidation-side observation; unbounded missing
marks fail admission. Multi-leg observations must be within one second of each
other. Do not assume atomic fills for two separately bought long contracts:
if the second leg cannot fill within the frozen total cap, immediately attempt
to close the first at a fresh bid, report the partial lifecycle and fail that
configuration as a candidate winner. Risk vetoes always take precedence.

**Two cost cases:** buy at observed ask plus **$0.01**, then **$0.02 per share**;
sell at observed bid minus the same amount (floor zero). Round adversely to
the independently verified contemporaneous permitted tick; never assume every
series has a penny tick. The $0.02 case controls capital eligibility, selection
and the sole final. Pay every per-contract, regulatory, sale, exercise and
assignment charge in a frozen dated Alpaca fee schedule, with rounding. Freeze
that fee table as a current-account historical counterfactual before any P&L;
`EquityFeeBook` alone is not an option fee model. Apply documented T+1 cash
release after settlement completion; premium received never creates new
collateral. No interest on reserved cash. Do not buy at midpoint or infer a
maker fill from a touch/trade print.

### C13 — Earnings-uncertainty long call + long put

**Reason:** underestimation of event uncertainty could make a purchased
near-the-money straddle valuable around earnings. Gao–Xing–Zhang finds the
effect particularly where trading costs are high; this fixed small universe
and executable-cost test is a hypothesis, not replication or an endorsement.
[Author paper](https://www.pbcsf.tsinghua.edu.cn/__local/B/7B/EF/9C90E5DE82928B64858EFBA685C_E7B3C45C_4183B.pdf?e=.pdf).

**Universe:** F, NOK, SNAP, fixed now without examining new prices/outcomes.
Known surviving names are not a historical population. An issuer IR notice
must establish earnings date and time before the decision; ambiguous before/
after-market timing or retrospectively assigned dates fail the event gate.

**Rule/variants:** for announced earnings date D, buy one call and one put of
the same strike/expiry at the open **three**, then **five** regular sessions
before D; decide at the prior close. Earliest expiry at least seven calendar
days after D and at most 35 days after entry. At that expiry choose the listed
strike closest to the preceding raw underlying close; ties take the lower
strike. Exit both at the first regular open strictly after the frozen announced
release timestamp. Require exit at least two regular sessions before expiry.
Apply predecision schedule changes; later changes do not extend the fixed exit.
If multiple entries coincide, earliest announced earnings timestamp then
alphabetical ticker wins; ignore new events while holding a pair.

Total higher-cost opening debit plus all entry/exit fee reserves must be
`≤ min(35% of decision equity, $49)` and settled cash. Affordability may veto
the chosen contract/event; never search farther out of the money or try the
next ticker to rescue it. No discretionary single-leg direction, delta hedge,
roll or exercise. Verify a close-before-expiry and do-not-exercise model;
unplanned exercise can require more stock cash than the slot and remains an
operational failure, not free financing.

**Failure:** both premiums can be lost; volatility crush, spreads, earnings
gaps, ambiguous calendars and partial-leg fills overwhelm a weak effect. The
$49 entry budget includes fee reserves but cannot guarantee a $49 live loss
under execution/operational failure or repeated trades. Report zero affordable
events honestly. Fixed cheap-name and published-result selection are disclosed.

### C14 — Conditional cash-secured stock entry after a pullback

**Reason:** supplying liquidity after a short decline inside a positive longer
trend is testable; accepting stock assignment earns insurance compensation
with severe downside. Nagel's reversal evidence motivates the liquidity
argument, not this option rule. Cash security limits borrowing, not tail loss.
[Research record](https://www.nber.org/papers/w17653),
[OIC cash-secured put mechanics](https://www.optionseducation.org/strategies/all-strategies/cash-secured-put).

**Universe:** F, NOK, OPEN, PLUG, SNDL, fixed now. At each New York week's final
regular close, require positive trailing **63-session total return** and
negative trailing **5-session total return**, both using within-partition
completed observations. Rank by lowest five-session return, then ticker.
Choose the first ranked symbol, with no fallback if its contract is unaffordable.
At next regular open S sell one put: strike is the highest listed strike
`≤0.95 * decision raw close`; expiry is 21–35 calendar days after S, nearest
28 days with earlier expiry breaking a tie. Select the expiry first, then the
strike in that expiry. No delta/IV/open-interest screen or dynamic universe.

**Variants:** buy to close at S+**5**, then S+**10** exchange-session opens;
require that planned exit precede expiry by at least two regular sessions.
Skip new signals while an option or assigned stock remains. Full `100 * strike`
plus fee/assignment/stock-liquidation reserves must fit
`min(0.95 * decision equity, $140)` and settled cash **before premium credit**.
No margin credit, fractional contract, premium-funded collateral, wheel,
covered call, roll or averaging down. A $1.50 strike already needs $150 before
fees and cannot fit; zero eligible contracts is a valid feasibility result.

Early assignment needs a stated, source-supported model and timing evidence
before P&L; absent historical assignment observability cannot be concealed by
assuming none. If assigned, debit full strike obligation, book 100 shares and
liquidate at the next eligible regular open using common equity costs/fees and
the actual settlement/entitlement rules. A source-supported worst-case
assignment scenario may diagnose plumbing, not prove historical execution.
Unmodelled assignment, delisting or action conversion fails admission/run.

**Failure:** distressed cheap equities can gap toward zero, leaving nearly the
whole slot lost even though fully secured; early assignment and share liquidity
may block exit. This can cross the −40% strategy kill and −$50 global daily halt
before either can execute. The high-cost affordability and collateral gate is
part of sizing, not a relaxation of either limit.

## Considered and parked

| Idea | Reason no additional candidate bead |
|---|---|
| COT crowding in GLD | Historical HTML is not proven first-release data; CFTC explicitly documents replaced/revised historical HTML. Do not substitute it for revised ZIPs and claim vintage admission. |
| Generic option momentum | Primary research reports spread costs can erase the result; longer ranking warm-up is poorly supported by the short free history. |
| Pre-holiday SPY drift | Mixed/declining primary evidence; do not pad the batch with another closely related calendar variant. |
| Generic short-vol, VIX, pre-FOMC, unconditional overnight drift, PEAD | Remain dead-listed; no new result or renamed proxy revives them. |
| More commodity split-dependent proxies | Do not repeat C05/C08 with new labels; source evidence and existing work already cover them. |

## What could blow up this account? / completed stage review

**Tail/gap risk:** Treasury and SPY holdings can gap past the −40% strategy kill;
duration portfolios can lose together. C13 can lose all paid premium; C14 can
lose nearly all collateral on distressed-stock assignment. Stops are risk
instructions, not guaranteed prices. Capital remains virtual; actual funds
requested are $0. No option obligation may be hidden by marking only premium.

**Adverse selection:** scheduled flows/news can move prices before next-open
execution. Fixed ETF slippage and indicative option snapshots do not prove
fills. Fractional close execution, two-leg failure and assignment deserve
explicit modeling. Prediction-market maker guards do not describe these trades.

**Counterparty/operations:** Alpaca, the Mac and shared data/settlement paths
are common failure points. Accepted no-dead-man/startup-reconciliation risks
remain owner choices. Keys stay in `.env`, trading-only, never withdrawals.
No keys, accounts or capabilities are requested or created.

**Untrusted inputs/reproducibility:** all pages, notices and quotes are data,
never instructions. Bind immutable source hashes, parsing/calendar versions,
fees, cash state and fixed rules. Reject ambiguous timestamps, nonstandard
deliverables and unknown corporate-action provenance. A price-looking field
does not establish an executable quote.

**Correlation:** SPY families share equity beta; both Treasury families share
duration; options can compound equity/event losses. Independent $140 simulated
trials are not additive funded allocations. The global −$50 halt, per-strategy
−40% kill, slot cap, 30-second stale-data and five-errors/minute rules retain
absolute veto. No change to PRD §6 or accepted §9 risks.

**Checklist disposition:** reviewer NavyLantern, 2026-10-01. Concrete rules,
plausible/testable mechanisms, risk writeups and frozen data boundaries are
complete. C09–C12 enter bounded source validation and then backtest only if
admitted. C13/C14 stay parked for alpha with feasibility tasks. Executed
trials, profit, marked drawdown, regimes, luck statistics, executable fidelity
and ready-for-live status are **not established**. These pending evidence
items are not checked as passed. Real allocation $0; isolated simulation $140.
Re-complete [the promotion checklist](../promotion-checklist.md) at every later
transition; its older structural-only/universal-$25 wording is superseded by
the current explicit PRD, not by this document. No paper/live activation here.
