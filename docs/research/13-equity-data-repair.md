# Equity source repair: evidence checkpoint

**Partial repair; no strategy outcome calculated.** The
[SPY open/close amendment](13-equity-data-repair-spy-amendment.md) now passes its
source checks with explicit price/payment corrections and a frozen cash
convention. This is source validation only; XLF remains unadmitted and no
strategy is promoted or replayed.
The [source receipt](13-equity-data-repair.json) freezes request bodies, raw-file
hashes, failed fetches, exact sample bounds and the proposed correction. C04 and
C02 failed audit trials remain unchanged. Previously consumed C01/TOM finals
remain consumed. Bead `tradingbot-900` remains in progress.

## SPY distribution

The contemporaneous [2006 prospectus](https://www.sec.gov/Archives/edgar/data/884394/000095013606000650/file001.htm),
pages 1 and 61, schedules the June distribution for the last NYSE business day
of July: **2006-07-31**. This supports replacing the issuer workbook's impossible
June 16 payable date for the June 16 ex-date/June 20 record-date row. The amount
stays $0.555470. The raw workbook is preserved; the correction is applied only
to the derived source bundle, never a strategy replay. A scheduled issuer payment is not proof of an actual
broker account credit.

## Closing-price basis

Archived SIP trade windows cover exactly the first ten seconds from 16:00 New
York time on the three disputed dates. Primary exchange P (NYSE Arca), condition
6 (market-center closing trade), confirms the Yahoo closing prices:

| Date | Primary closing print | Disputed comparison |
|---|---:|---:|
| 2020-03-12 | 248.11 | SIP daily 255.24 |
| 2020-03-18 | 240.00 | SIP daily 235.69 |
| 2025-04-09 | 548.62 | IEX daily 542.955 |

The April 2025 Arca print also carries a separate official-close report (M).
IEX's last-minute bar equals its own daily close. The two March 2020 SIP daily
aggregates are unsuitable as primary-auction close proxies; their discrepancy
is not explained by simply assuming every after-hours print updates a daily
close. [Alpaca's condition rules](https://docs.alpaca.markets/us/docs/market-data-faq)
exclude condition T from daily prices. The source audit changes neither prices
nor tolerances. A future amendment must explicitly use matching price bases.
The new diagnostic rejects missing, conflicting, out-of-window, other-venue or
mixed extended-hours closing evidence. Forty-four source/calendar checks pass.
An additional opening-price discrepancy and its correction are documented in
the SPY amendment; it excludes unvalidated high/low fields from source scope.

## Corporate action still incomplete

The issuer's [2016 annual report, note 1](https://www.sec.gov/Archives/edgar/data/1064641/000119312516786454/d235287dncsr.htm)
confirms 0.139146 XLRE shares per XLF share, record September 21 and payable
September 22. [OCC notice 39575](https://infomemo.theocc.com/infomemos?number=39575)
sets September 19 as ex-date and identifies possible fractional cash. Its
option-deliverable allocation is explicitly unsuitable for customer accounts.
Fractional proceeds, their availability and incidental XLRE disposal remain
unresolved. Yahoo's 1.231 event cannot create extra XLF shares.

The independently archived Alpaca corporate-action response also misclassifies
the 0.139146 distribution ratio as a cash-dividend amount and gives a different
record date. It is unsuitable for those fields. It independently confirms the
five genuine 2:1 sector-fund splits on December 5, 2025. A generic broker article
about fractional shares does not establish this event's exact cash treatment.

## Reconciled settlement schedule

The [calendar evidence](13-equity-data-repair-calendar.json) now covers each
calendar year from 2006 through 2026, with finite coverage and a content hash.
FINRA annual schedules supply 2006–2023 dates; DTC/NSCC annual notices and
specific holiday notices supply 2024–2026 dates. All **291** in-coverage T+1
pairs in FINRA's current full filing workbook agree with the derived schedule.
The fixed research interval still contains 5,218 exchange sessions; it has
37 trading days without settlement and five settlement days without trading.
The schedule is derived from those primary notices, then compared with exchange
sessions; exchange dates are not the source of settlement eligibility.

The [NSCC rules](https://files.dtcc.com/download/assets/nscc_rules.pdf/85bda02a369211f0a3ae820bd5ac0897)
separate an operating day from a day when securities and money can settle.
Archived Nasdaq notices confirm valid settlement on the Ford, Bush and Carter
mourning days, despite exchange closures; SEC Sandy guidance provides further
exception evidence. Nasdaq's 2006 Good Friday schedule excludes that Friday
from regular-way settlement. Federal Reserve Saturday observance also differs
from a generic federal-office holiday calendar. Two reconciliations matter:

- FINRA's annual 2023 table excludes November 10. DTC's more specific
  [Veterans Day notice](https://files.dtcc.com/download/assets/19155-23/a4c71ae8369511f09a845e09fb65ecc7)
  explicitly provides normal T+1/T+2 settlement on that Friday. The correction
  retains both sources and their hashes.
- The [June 30, 2026 disruption notice](https://files.dtcc.com/download/assets/24518-26/2cfb5f4e957911f19784c258faf12821)
  confirms that June 29 balances rolled over and both days completed on June 30.
  The calendar distinguishes scheduled and completed settlement. Its proposed
  conservative cash convention waits until the next regular-session open after
  completion, so a June 26 sale cannot fund a June 29 or June 30 opening buy.

Neither scheduled settlement nor central completion proves actual broker credit.
The cash convention is **frozen for the SPY open/close source bundle**, with no
strategy replay or promotion. Source checks cover Good Friday, bank holidays,
Saturday observance, Juneteenth, exceptional exchange closures, regulatory
boundaries, finite coverage, changed evidence and the operational rollover.
Failed legacy DTCC URLs remain recorded as HTTP 404 responses, never accepted as
document evidence. The current receipt links to the preceding receipt's hash.
