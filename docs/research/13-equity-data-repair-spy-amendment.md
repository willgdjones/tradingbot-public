# SPY source amendment, before strategy outcomes

**Open/close source validation passed; no strategy admitted or replayed.** The
[frozen receipt](13-equity-data-repair-spy-amendment.json) binds 5,218 sessions,
83 issuer distributions, exact raw hashes, the settlement calendar, corrections,
cash convention and build-code hashes. The derived file is
`data/equities/source-repair/frozen-spy-source-v1/data.json`; its adjacent
`build.py` reproduces the source checks without signals, ranks or returns.

The research bounds stay **2006-01-01 00:00 UTC to 2026-10-01 00:00 UTC**,
end exclusive, with the same **2020-07-10 14:24 UTC** 70/30 boundary. Original
C04 failed trial 3377 and every previously consumed final remain unchanged.
The source amendment does not make previously inspected SPY history unseen.

## Explicit corrections

1. The June 16, 2006 SPY distribution retains its $0.555470 amount and June 20
   record date. Its derived scheduled payment date becomes July 31, following
   the contemporaneous prospectus. The opt-in `PaymentDateAmendment` requires
   exact original workbook and primary-document hashes plus an exact row match.
   The raw workbook is unchanged; the default parser still rejects it.
2. December 17, 2021 uses the issuer's $1.636431, rather than Yahoo's $1.633.
   The independently archived Alpaca action corroborates that amount, December
   20 record date and January 31, 2022 payment. Other Yahoo differences are
   recorded, mostly three-decimal rounding; issuer amounts govern all 83 rows.
3. The November 7, 2016 opening price becomes **$211.47**, the NYSE Arca
   opening trade at 14:30:00.243 UTC, also disseminated at .2474. Yahoo's
   $208.5500030517578 equals the prior session's close. SIP's $211.45 opening
   is the earlier Nasdaq print, not Arca's opening auction. All 1,215 raw trades
   in the fixed first-ten-second window are preserved with condition codes.

Yahoo's disputed closes on March 12/18, 2020 and April 9, 2025 agree with the
primary closing prints to within half a cent, so those values are unchanged.
All available IEX and SIP daily opens/closes were checked at the existing 1%
bound: 1,554 IEX sessions and 2,701 SIP sessions. Each breach is documented and
reconciled; no tolerance was widened. Independent price coverage before 2016
is not claimed.

## Source scope and cash

Only **open and close** prices are admitted by this source bundle. Yahoo's
high, low, volume and adjusted close remain archived and are excluded from this
artifact. In particular, the November 7 low also equals $208.55 and has not been
validated as a regular-session low. This bundle cannot support an intraday-stop
or high/low strategy without additional source work.

Dividend entitlement is a receivable from the ex-date, not spendable cash. A
future replay using this exact source policy releases dividends at the first
regular-session open strictly after the issuer's scheduled pay date. Sales
release at the first regular-session open strictly after completed settlement;
the June 29, 2026 rollover completes June 30 and releases no earlier than July 1.
This is a conservative counterfactual, not evidence of an actual broker credit.
Live/paper accounting must continue to use actual ledger availability.

No allocation, sizing, cost case, variant, risk limit or final-admission rule
changes. A strategy still needs a separate preregistered execution/ledger run.
The current amendment neither consumes a final nor permits replay of C01 or TOM
finals. Forty-four focused source checks passed.

XLF's in-kind distribution remains unresolved for the nine-sector universe.
This SPY result does not admit C02 or complete the other funds' C03 source audit.
