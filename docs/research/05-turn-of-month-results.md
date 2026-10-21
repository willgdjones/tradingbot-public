# SPY turn-of-month results — 2026-09-30

The four calendar variants are profitable after the preregistered current-cost fees and adverse execution assumptions. The primary final-minute scenario nets **$9.22 across 128 completed trades**, on fixed $24.90 entries and $140 virtual cash. It is a paper-validation candidate under the owner’s profit-after-fees criterion. These bar scenarios do not establish achieved fractional closing fills, nor isolate a calendar premium from general equity drift.

## Results

| Variant | Trial | Trades | Net USD | Fees USD | Mean/trade USD | Win rate | Marked drawdown USD | One-sided p |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| tom_minute_2bp | 849 | 128 | 9.22 | 5.12 | 0.0720 | 57.0% | 4.56 | 0.0690 |
| tom_minute_5bp | 850 | 128 | 7.30 | 5.12 | 0.0570 | 55.5% | 4.69 | 0.1196 |
| tom_minute_10bp | 851 | 128 | 4.10 | 5.12 | 0.0321 | 54.7% | 4.91 | 0.2536 |
| tom_close_2bp | 852 | 128 | 8.96 | 5.12 | 0.0700 | 57.0% | 4.48 | 0.0760 |

Trial 853 (`tom_midmonth_close_2bp`) is **failed validation**, with no fabricated result: corporate-action factor changes during 2017-09-07..2017-09-15. Its fixed comparison window crosses an ex-dividend adjustment; explicit dividend ledger credits are not implemented. It was not retuned or silently excluded. The intended equal-duration comparison remains unresolved.

The p-values are one-sided, one-sample t-tests against zero mean net trade P&L; they are not posterior probabilities that the strategy is luck. They assume sufficiently independent trades and are not adjusted for these correlated variants. They are informational, as required by PRD §4.

## Chronological checks

| Variant | 2016–2022 net USD (83 trades) | 2023–2026 net USD (45 trades) |
|---|---:|---:|
| tom_minute_2bp | 6.27 | 2.95 |
| tom_minute_5bp | 5.03 | 2.27 |
| tom_minute_10bp | 2.95 | 1.15 |
| tom_close_2bp | 6.23 | 2.73 |

These are historical subdivisions, not an unseen forward test. For the primary variant, 2023–2024 nets $1.63 and 2025–2026 nets $1.32. Year results vary substantially:

| Exit year | Trades | Primary net USD |
|---|---:|---:|
| 2016 | 11 | 0.89 |
| 2017 | 12 | 0.83 |
| 2018 | 12 | -1.06 |
| 2019 | 12 | 1.47 |
| 2020 | 12 | 2.56 |
| 2021 | 12 | -0.57 |
| 2022 | 12 | 2.16 |
| 2023 | 12 | 3.06 |
| 2024 | 12 | -1.43 |
| 2025 | 12 | -0.73 |
| 2026 | 9 | 2.05 |

## Coverage and execution limits

- Raw/adjusted SPY daily data: 2,701 sessions, 2016-01-04 through 2026-09-30; no missing daily sessions. Scheduled minute endpoints: 256 of 256, with both final minutes captured (512 bars). The first entry is 2016-01-26 and last exit is 2026-09-03.
- The September 25 entry / October 5 exit cycle is unfinished at the cutoff and excluded by the preregistered rule. No entry date was moved to improve returns.
- Every completed variant has 256 fills, 128 flat-to-flat round trips, zero rejected orders and a flat ending. Cash, unsettled proceeds, round-trip net and the ledger reconcile within the database’s 1e-6-per-trade precision.
- Primary exposure: 768 close-to-close trading-session intervals (six per cycle), 26,661 calendar hours held. Net return on the full $140 virtual cash is 6.59% over the entire sample, without reinvestment or cash interest; it is not an annual return.
- Practical scenarios use the open of the final minute plus 2/5/10 bp adverse movement on each side. These are execution assumptions from revised historical bars, not timestamped bid/ask evidence or actual fills. The daily-close variant is a nonexecutable fractional-auction benchmark. Quantity is rounded down to nine decimals and limits to cents.
- The $5.12 fee total in each completed variant is the September 17, 2026 retail fee schedule applied uniformly as a current-cost counterfactual, with daily per-fee-type upward rounding. It is not reconstructed historical billing. Sale proceeds remain unavailable until the API settlement date, including historical T+2 dates and settlement holidays.
- Forty returned corporate-action rows are incomplete reference coverage. All 128 actual holding windows also pass an adjusted/raw factor intersection check allowing ±0.005 adjusted-price rounding. No reported ex-date falls inside them. No dividend credits are fabricated. This is evidence against material in-window actions, not a guarantee the vendor’s history is perfect.
- Drawdown uses observed daily-close and execution-time marks. It does not claim intraday extrema. Fees are modeled exactly under the stated schedule; spread, market impact, latency, broker rounding and missing/revised point-in-time prints still need forward verification.
- FX on each fill is the strictly previous ECB reference date’s GBP/EUR divided by USD/EUR, with a seven-day maximum age and source checksum. It is a reporting reference, not an executable conversion rate.
- The pure `TurnOfMonth` reactor uses the same shared Strategy interface in research, paper and live. Only the research adapter constructs assumed execution touches. No venue order was sent, real capital added, risk limit changed, or parent strategy promoted.

## Reproduce and inspect

- Code commit for all trials: `9584313ba25b091e5aede82c852fd6de5a72810c`.
- Data capture `tom-20260930`: 260 pages / 8664 records; SHA-256 `83501d8e59ae95b128481d26228722f00514f26b4cdb388462edb70908e4f5a9`.
- ECB XML SHA-256: `684f22325b80a05da42ca1de044e07ca5515c00a35386335f573c7cc08d6ab0f`.
- Compact results and full parameters: [05-turn-of-month-results.json](05-turn-of-month-results.json). Full per-trade/equity-curve artifacts: gitignored `data/equities/results/tom-20260930-v1/`; authoritative orders/fills/results are trials 849–853 in local Postgres port 5433.
- Re-run with an explicit new identifier: `uv run python -m tradingbot.research.turn_of_month --run-id YOUR_NEW_ID`. Existing run identities cannot be reset. Every attempted variant, including exceptions, is retained in the trials ledger.
- Validation: 16 focused downloader, strategy and research tests pass; DB tests roll back. Archive checks verify hashes, pagination completion, calendar coverage, endpoint bars and corporate-action boundaries before any strategy return is evaluated.

## Sources and next validation

Inputs and assumptions were fixed in [the preregistration](05-turn-of-month-plan.md). Official references: [Alpaca historical bars](https://docs.alpaca.markets/us/reference/stockbars), [aggregation FAQ](https://docs.alpaca.markets/us/docs/market-data-faq), [fee schedule](https://files.alpaca.markets/disclosures/library/BrokFeeSched.pdf), [fractional order support](https://docs.alpaca.markets/us/docs/orders-at-alpaca), [corporate actions](https://docs.alpaca.markets/us/reference/corporateactions-1), and [ECB reference rates](https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html).

Next validation is forward paper observation of marketable fractional fills around the scheduled close, followed by comparison of achieved fees/slippage with these recorded scenarios. A separate dividend-aware diagnostic can resolve the incomplete midmonth comparison; it must be a new logged trial. No additional significance gate is imposed on the owner’s success criterion.

## Decision record and account risks

Decision on 2026-09-30: retain completed research; candidate for forward paper
validation, with **no parent-strategy promotion or funded allocation**. Trials
849–853 use $140 virtual cash only. Fixed entry/exit rules, after-cost results,
trade counts, p-values, marked drawdown and chronological subdivisions are above.
Paper/live fidelity is not established, and the subdivisions are calendar
periods rather than an independently specified economic-regime classifier.
The pure strategy interface is shared across modes. §6 and the accepted risks
are unchanged; profit after fees remains the owner's success criterion.

### What could blow up this account?

**Tail/gap risk:** SPY is held across nights and weekends. A fully funded long
position can lose its purchase cost; each modeled entry is below $25, plus fees.
Gaps can pass a loss trigger before a fresh observation permits a response.
Repeated losses and concurrent strategies can deplete more than one position's
notional. The study's daily/execution marks do not measure intraday tail extrema.

**Adverse selection:** this implementation requests marketable fractional limits,
so the primary exposure is spread/impact and late-session price movement rather
than passive maker selection. Scheduled news can still move the price while an
order is submitted or waiting. The 2–10 bp scenarios are assumptions, not proof
that broker fills stay within them.

**Counterparty/venue:** the research depends on Alpaca's revised SIP history and
ECB reference rates. Future execution adds broker/feed outages and custody risk.
The accepted lack of a dead-man and startup reconciliation remains: resting
orders may survive a bot failure. Trading-only, nonwithdrawal key permissions
must be evidenced by the execution connector; this read-only study makes no
claim that it verified those permissions.

**Untrusted inputs:** prices, calendars and corporate-action responses are data,
never instructions. Parsing, checksums and fixed code determine actions; no
headline, tweet or LLM output produces an order signal.

**Reproducibility:** exact archived pages, FX checksums, fixed parameters and the
recorded commit reproduce the scenarios. Historical corrections, unknown
first-print latency and incomplete corporate-action coverage limit inference
about what was executable in real time.

**Correlation:** long SPY overlaps the LETF study's SPY leg and much of QQQ's
market exposure. These isolated variant results cannot simply be added as a
portfolio forecast. Concurrent deployment must share the $25 SPY market cap
and portfolio cash/risk accounting; correlated losses contribute to the same
$50 daily halt. No simultaneous portfolio simulation or capital deployment was
performed here.
