# C04: cash-capped inverse-variance SPY — source audit

2026-09-30 America/Los_Angeles / 2026-10-01 UTC. Bead `tradingbot-wri`.
The binding candidate and execution rules remain in
[the sweep preregistration](07-candidate-shortlist.md). No strategy outcomes
have been computed, and no final holdout has been admitted.

The fixed source interval is 2006-01-01 00:00 UTC through 2026-10-01 00:00 UTC,
end exclusive. `HoldoutSplit` places the 70% boundary at
2020-07-10 14:24 UTC. The contemplated variants remain c = 0.15², 0.10², 0.20²,
in that order, with 5/10 bp training cases and one selected 10 bp final case.
They have **not** been attempted. The $140 allocation, 95% target ceiling,
completed-full-month sample variance, next-open execution, actual dividend
payments, T+1 cash and unchanged §6 risk vetoes remain binding.

## Source policy, before any return analysis

The existing byte-archived Yahoo SPY response supplies prices/actions. All
5,218 daily rows match the official Alpaca regular-session calendar in the
fixed interval; there are no missing sessions or source splits. The issuer
SSGA workbook supplies 83 matching distribution ex-dates and actual record and
pay dates. Yahoo rounds most amounts to three decimals; December 2021 also
differs beyond rounding (1.633 versus issuer 1.636431). A future valid dataset
would use reconciled issuer amounts, raw executable prices, and causal daily
total returns `(close + ex-date distribution) / previous close - 1`; cash is
spendable only on the actual pay date. No adjusted-price dividend is credited
twice. This clarification precedes performance inspection, and is not an
authorization to overlook a failed source check.

The workbook is read without alteration. The parser rejects changed headers,
formulas, duplicate ex-dates, invalid values and payment dates before the record
date. One issuer row fails that last check; see the result. Raw bytes and hashes
are retained under `data/equities/c04/sources/`.

A free, GET-only IEX overlap request was also archived. It returned 1,554 daily
bars: one in 2018 and continuous ordinary coverage from July 2020 onward,
rather than the requested full 2016+ interval. This is partial independent
validation, never replacement price history. One close differs from Yahoo by
1.0434%. The existing, separately archived SIP data matches that particular
Yahoo close but has two other >1% disagreements in March 2020. A regular-session
versus extended-session explanation is plausible but is **not verified** here.
No tolerance was widened or source substituted to pass the audit.

Alpaca's full calendar includes actual historical settlement conventions:
2006-01-03 maps to 2006-01-06. It cannot be labeled a T+1 counterfactual.
The set of observed settlement dates is not proof of a complete hypothetical
T+1 banking calendar; taking the next weekday/session would silently assume
unverified holidays. That derivation is therefore not implemented.

Sources: [issuer distribution page](https://www.ssga.com/us/en/intermediary/resources/documents/etf-dividend-distributions),
[issuer workbook](https://www.ssga.com/library-content/products/fund-data/etfs/us/spdr-etf-historical-distributions.xlsx),
[Alpaca calendar reference](https://docs.alpaca.markets/us/v1.4.2/reference/getcalendar-1).
Provider archives contain exact query parameters, response bytes, retrieval
timestamps and hashes. No new account, key, paid endpoint or order was used.

## Admission and contamination

The dataset identity binds all archived source hashes, these adjustment/cash
requirements, and the unchanged time bounds. The attempted data validation is
recorded as a failed trial, without fabricated P&L, trade count or p-value.
The six proposed training configurations remain unattempted. A later source
repair must be documented before any outcome inspection; it must not move the
time bounds. Existing #5/#6 and C01 inspection makes overlapping SPY history
diagnostic rather than fresh unseen evidence. No promotion is justified by
this audit or by relabeling that history.
