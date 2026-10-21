# XLF 2016 action: unresolved evidence, fixed disposal policy

**UNRESOLVED_DATA_FAILURE. No nine-sector dataset or strategy is admitted.**
Bead `tradingbot-vx0` completes its explicit unresolved-data acceptance route.
The [hashed receipt](17-xlf-action-amendment.json) records the primary evidence,
vendor contradictions, failed retrievals, remaining proof and policy. This does
not replace the original C02 failed trial 3491 or any consumed final.

Research bounds remain **2006-01-01 to 2026-10-01, end exclusive**, with the
unchanged **2020-07-10 14:24 UTC** holdout boundary. No ranks, candidate returns
or historical execution were computed. No strategy parameter, risk limit,
allocation, cash balance or original source file changed.

## What the evidence supports

| Field | Accepted evidence | Consequence |
|---|---|---|
| Event type | Issuer prospectus supplement and annual report | Distribution of a different asset, XLRE; original XLF share count stays unchanged. |
| Ratio | Annual report, Note 1 | Nominal entitlement is exactly 0.139146 XLRE units per eligible actual XLF share. |
| Ex-date | OCC memo 39575 background; issuer Form 8937, page 3 | September 19, 2016. |
| Record date | Annual report and Form 8937 | September 21, 2016. |
| Issuer payment | Annual report and Form 8937 | September 22, 2016; no account-level delivery or spendable-cash timestamp established. |
| Fractional allocation | No sufficient account-level primary evidence located | Actual delivered fraction, rounding and cash-in-lieu remain unknown. |

The [issuer annual report](https://www.sec.gov/Archives/edgar/data/1064641/000119312516786454/d235287dncsr.htm)
and [prospectus supplement](https://www.sec.gov/Archives/edgar/data/1064641/000119312516699787/d246445d497.htm)
were already archived by the shared repair. Their original bytes and hashes
were verified again. For example, 100 eligible XLF shares give a nominal
13.914600-unit XLRE claim. This arithmetic does not establish that a broker
delivered 13 shares, retained 0.914600 shares, or paid any particular amount.

New evidence is the issuer's [signed Form 8937](https://www.ssga.com/library-content/products/fund-docs/etfs/us/tax-documents/US-Form-8937-XLF-Signed-New.pdf),
archived successfully with SHA-256
`7533175812afe7d5924513b3cd6144bc6d5216aae76c01fe6070bd7db22ad551`.
All three scanned pages were rendered and visually read. It was signed on
November 15, 2016, after the event. Page 3 reports $4.5292 total distribution,
$2.9588 return of capital and $1.5704 taxable distribution per XLF share. These
are tax-characterization amounts, not executable cash or a fractional-payment
rate. Its page-3 heading says September 31, while page 1 says September 30;
that source typo is preserved. The tax form supplies no broker delivery proof.

[OCC memo 39575](https://infomemo.theocc.com/infomemos?number=39575) describes
options/futures deliverables, conditional cash in lieu, and delayed settlement
while final amounts are determined. It does not specify a final cash rate or
customer-account availability. Its settlement allocation is expressly scoped
to OCC/NSCC. Applying it as a retail cash-credit rule would exceed its scope.

## Exact conflicts retained

- Yahoo's archived `1231:1000` event is rejected as an XLF share split. It
  neither creates 23.1 extra XLF shares per 100 shares nor determines cash.
- Alpaca's archived action puts `0.139146` in `cash_dividends.rate` and gives
  September 19 as the record date. The issuer establishes XLRE units and a
  September 21 record date. Its ex-date and scheduled payable date corroborate
  the primary documents; its processing date does not prove an account credit.
- The September 19 issuer press-release URL at Business Wire timed out without
  an HTTP body. The MarketScreener reprint returned HTTP 403; its exact response
  is retained and not admitted as financial evidence. The previously archived
  OCC search failure also remains untouched. Search snippets and secondary
  commentary did not fill the missing primary proof.

## Disposal and cash policy, declared before outcomes

`xlf-incidental-disposal-v1` treats XLRE solely as incidental inventory. It
never enters the candidate ranking universe. Keep the nominal claim pending
until documented delivery; sell delivered tradable units at the first regular
session open strictly after documented availability, using the candidate's
existing cost case and ledger/risk checks. This is a declared research rule,
not an enabled execution amendment.

Release sale proceeds only at the first regular-session open strictly after
completed settlement under the frozen source calendar. Independently supported
cash in lieu releases strictly after its documented availability date. Preserve
any income entitlement earned before disposal. A scheduled issuer pay date
alone does not satisfy any broker-availability requirement.

An unresolved fraction stays unresolved. Do not value it at zero, substitute
the tax value, fabricate a sale, assume fractional retention, or invent a
payment delay. Do not remove XLF, the event or adjacent dates from the sample.

## What must be supplied to reopen admission

1. Primary account-level treatment of whole and fractional XLRE entitlements,
   including aggregation, rounding or fractional retention for this action.
2. If cashed out, the fractional-payment basis and amount plus evidence of
   availability; if retained, evidence of delivered tradable fractional units.
3. Supported XLRE availability and independently validated actual-share
   execution prices for the declared disposal, plus any intervening income.

Current generic broker policies do not establish this historical event's
account treatment. No new account, key, payment or trade is requested. A later
source amendment must remain explicit; C02/C07 still require their own source
admission and preregistered ledger replay before inspecting outcomes.

## Reproduction

`uv run python -m tradingbot.data.xlf_action_amendment` verifies the exact
archived bytes and provider response, parses the issuer terms and emits the
failure receipt without network or database access. The code deliberately
contains no price transformation, cash posting, trading or return calculation.
Thirteen focused tests cover missing/ambiguous/changed primary fields,
tampering, contradictory vendor semantics and exact fractional arithmetic.
Two offline builds reproduced the same receipt digest.
