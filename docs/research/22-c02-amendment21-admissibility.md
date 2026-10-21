# C02 sector momentum under Amendment 21: corporate-action admissibility

Bead: `tradingbot-0qk` (re-attempt of C02 / `tradingbot-7l3` under
[Amendment 21](21-corporate-action-blackout.md)). Supersedes the data-gate stop in
[12-c02-source-audit](12-c02-source-audit.md) and the fractional-treatment dead end
in [17-xlf-action-amendment](17-xlf-action-amendment.md). Read-only; no returns,
ranking, training or holdout were computed for this admissibility record.

## Result: **ADMITTED.** All blackout actions are causally handleable with archived evidence.

Amendment 21 removes the fractional / cash-in-lieu obstacle (never hold through a
split / reverse-split / in-kind): the only remaining gate is **causality** — each
action must be *announced on or before its exit-decision date* (the close two
sessions before the ex-date), proven from archived primary evidence, else fail
closed. Every blackout action on the nine-ETF universe clears that gate.

## Universe and data (unchanged from 07-candidate-shortlist)
Fixed nine funds **XLB, XLE, XLF, XLI, XLK, XLP, XLU, XLV, XLY**, free Yahoo daily
bars **2006-01-01 → 2026-10-01** (end exclusive), holdout boundary
**2020-07-10T14:24:00Z**. Re-captured and validated via `data.free_history`
(raw response + URL + UTC retrieval ts + sha256, re-verified on load). Each series:
**5,218 sessions, 2006-01-03 → 2026-09-30, no gaps, no null rows, no issues.**

| ETF | capture sha256 | ETF | capture sha256 |
|---|---|---|---|
| XLB | `d1de6af1…` | XLP | `da885a36…` |
| XLE | `d3241333…` | XLU | `d833afc2…` |
| XLF | `e8a6ed6e…` | XLV | `6f22d626…` |
| XLI | `b9f4244b…` | XLY | `2c777e5c…` |
| XLK | `6807b296…` | | |

(Full hashes in `data/equities/raw/free/<SYM>/manifest.json`, gitignored.)

## Blackout actions (what Yahoo's split field flags on held symbols)
Yahoo reports exactly six non-cash actions across the nine ETFs: one in-kind
distribution (XLF 2016, mislabelled by Yahoo as a `1.231` split) and five 2-for-1
splits on 2025-12-05. Ordinary cash dividends are out of scope (normal entitlement).

| Symbol(s) | Kind | Ex | Record | Payable | Announced | Decision close¹ | Admissible? |
|---|---|---|---|---|---|---|---|
| XLF | in-kind (XLRE) | 2016-09-19 | 2016-09-21 | 2016-09-22 | **2016-09-01** (497) | 2016-09-15 | ✅ |
| XLB,XLE,XLK,XLU,XLY | 2-for-1 split | 2025-12-05 | 2025-12-02 | 2025-12-04 | **2025-11-20** (SSGA) | 2025-12-03 | ✅ |

¹ The close two sessions before the ex-date, at which Amendment 21 decides the exit.

### Archived primary announcement evidence
- **XLF 497 prospectus supplement** — SEC EDGAR filing, **Form 497, Filing Date
  2016-09-01** (accession 0001193125-16-699787), i.e. announced 18 days before the
  exit decision. Archived: `…/xlf-497-edgar-index.html` sha256 `529a3528…`. (The 497
  body itself was already archived by [17](17-xlf-action-amendment.md).)
- **2025 splits** — State Street FAQ: *"On November 20, 2025, State Street … announced
  share splits on the five Select Sector SPDR funds"* (XLK/XLY/XLE/XLU/XLB); the Citi
  custodian corporate-action record shows **Announcement Date 24-Nov-2025**, Ex
  05-Dec-2025, Record 02-Dec-2025, Payment 04-Dec-2025. Archived (regulator-filed
  CEDEVAL reprint, 6 pp): `…/ssga-split-notice-2025-11-25.pdf` sha256 `4175a60c…`.
  (The SSGA investor-news page is JS-rendered; its shell is archived as
  `…/ssga-2025-split-pr.html` sha256 `3eb9776b…` but the date lives in the PDF above.)

Evidence lives under `data/equities/c02/amendment21-evidence/` (gitignored); hashes
are pinned here.

## Blackout date mapping for `tradingbot.research.action_blackout`
`CorporateAction(symbol, kind, announced, ex_date, payable, source)` → `plan_blackouts`
requires `announced ≤ ex_date ≤ payable`. A forward split's distribution (payable)
precedes its ex/effective date, so for the splits we set **ex = payable = 2025-12-05**
(the effective date): exit at the **2025-12-04 open** (decided 2025-12-03 close), flat
through 2025-12-05, re-enter at the **2025-12-08 open**. This is flat across the
share-count change (distributed after the 12-04 close) and needs no split-ratio or
rounding assumption. For XLF: exit **2016-09-16 open** (decided 09-15), flat through
the 09-22 payable, re-enter **2016-09-23 open**.

## Strategy (unchanged signals/costs) and what remains to build
`src/tradingbot/strategy/sector_momentum.py` + `research/c02_sector_momentum.py`:
- **Rule:** rank the nine at month-end; hold the **top three equally** inside the 95%
  total weight; alphabetical ties; replace names leaving the top three; rebalance
  monthly. Score variants (order): **12-month total return; 6-month; mean of
  1/3/6/9/12-month**. Training cost cases **5 bp / 10 bp**; select by 10 bp training
  net $; one holdout run at 10 bp. Reuses the C01 cash/fee/dividend/T+1/terminal
  machinery, extended to multi-leg pro-rata cash rationing across positive target gaps.
- **Blackout integration:** a `BlackoutBook` excludes non-`holdable` symbols from the
  monthly target and forces exits at each `forced_exits` session's open; both forced
  legs pay the 5/10 bp cost + `EquityFeeBook` fees and count as trades. Report
  blackout session counts and how much forced-exit cost falls in each partition.
- **Ledger:** new strategy version (code now includes the blackout) + new trials; the
  prior failed C02 source trial stays. No holdout was ever consumed for C02, so this
  version gets its one 70/30 holdout run (durable single-use admission).

**Next:** build the multi-asset backtester + blackout wiring with unit tests, run the
three variants on the first 70% (5/10 bp), select, then the single 10 bp holdout, and
write `09?`/`22-*-results` with trades, fees, marked max drawdown, per-regime results,
p-value and blackout session counts. No §6 change; `ready-for-live` only after the
promotion checklist.
