# Open-item checks

Checked 2026-09-30. Primary sources below supersede shorthand in research 02/03;
the PRD and its risk limits are unchanged. Kalshi remains research-only.

## Polymarket US fees and liquidity incentives — tradingbot-2ej

**Finding:** implement the US schedule separately from international Polymarket.
The current [fee schedule](https://docs.polymarket.us/fees), effective
2026-09-25 00:00 ET, specifies `theta * contracts * price * (1-price)`:
taker theta `0.0695`, maker theta `-0.0125`. The maker coefficient is a rebate,
not a flat 1.25% of notional. Round half-even to cents. Makers round each fill;
takers round each fill but reduce charges when needed so cumulative collection
does not exceed rounded cumulative exact fees. Never increase a fill to catch up.
At 1,000 contracts / $0.50: taker $17.38, maker credit $3.12.
Combos have a different taker curve; table-tennis changes tonight. Both are
outside our non-sports standard-contract implementation. Weekly taker rebates
depend on prior-month at-risk volume ($250k/$1m/$10m tiers: 10%/25%/50%);
do not assume eligibility or subtract these from fill charges.

[Execution reports](https://docs.polymarket.us/partners/orders/data-model)
encode commission in units of `price_scale * fractional_quantity_scale`.
Negative commission means a rebate; a missing protobuf commission means zero.
Decode actual charged fees for the ledger and reconcile model predictions against
them. Instrument quantity scales are not universally one.

The [program overview](https://docs.polymarket.us/incentives/overview) describes
liquidity rewards as open, without application. Formal market-maker agreements
are a separate program. Account eligibility and an active eligible instrument
still need checking when the strategy is implemented.

The [liquidity rules](https://docs.polymarket.us/incentives/liquidity) say:

- Random snapshots each second score qualifying orders as size times discount
  factor raised to ticks from best. Normalize each side independently; seconds
  have equal weight.
- Walk aggregate raw depth from best until Target Size is reached. Include that
  price level; worse levels do not score. Target Size is not an individual minimum.
- Without Max Spread, sides qualify independently. With it, both must reach
  Target Size; their depth-adjusted prices must be within twice Max Spread.
  Failed seconds forfeit their allocation. One-sided participants can qualify.
- Calculation takes up to five business days after the period, then credit within
  two more. Payouts below $1 are forfeited. Canceled/postponed games pay nothing.
- Parameters may change between periods; there is no individual payout cap.

The [live rewards page](https://polymarket.us/rewards) lists 141 programs and
72,688 markets in the retrieved snapshot. Pools belong to program/time-period
groups, **not each market**; do not sum repeated pools across markets. Displayed
examples are sports. This check establishes rules, not the availability or
profitability of a non-sports opportunity.

**Implementation consequence:** strategy #2 must record dated program metadata,
filter out sports, estimate competitive depth and qualifying seconds, apply the
$1 threshold, and respect existing inventory/risk caps. Credit rewards only from
confirmed account payments; keep estimates separate. No incentive income is
guaranteed by a fill. No live deployment follows from completing this check.

The [API overview](https://docs.polymarket.us/api-reference/incentives/overview)
documents authenticated `GET /v1/incentives` and earnings on `api.polymarket.us`:
snake_case query parameters, camelCase results, pagination, program IDs, periods,
category, depth, spread, and reward fields. Its explicit casing guidance conflicts
with generated endpoint examples using camelCase; use snake_case and validate
returned filters. This task did not place orders or enroll in any program.

## Exact fee model evidence — tradingbot-di9

The [Kalshi fee PDF](https://kalshi.com/docs/kalshi-fee-schedule.pdf), effective
2026-07-07, specifies quadratic coefficients `0.07` taker and `0.0175` maker,
each with its own multiplier. General taker/maker multipliers are 1/0, with
series-specific exceptions, including zero-fee markets. It has no settlement
fee. Its formula footnote describes aligning fee plus position cost to $0.0001,
but its illustrative table rounds to whole cents (one contract at $0.01 costs
$0.01). **Do not interpret that table as universal direct-member rounding.**

The [API rounding specification](https://docs.kalshi.com/getting_started/fee_rounding)
distinguishes direct-member $0.0001 balances from non-direct/FCM $0.01 balances.
It first rounds the model fee upward to $0.000001, floors signed revenue minus
that fee to the balance grid, and carries the difference in an order accumulator.
Refunds use grid increments, capped to avoid negative net fees. The accumulator
survives taker-to-maker transitions. The official fractional-price example buys
at $0.055: raw fee $0.00363825, trade fee $0.003639, rounding $0.001361,
net fee $0.005 for an FCM account. The same modeled direct-member fill is $0.0037.

**Resolution:** the code tests the PDF table as the cent-cleared case and follows
the explicit API algorithm with caller-selected precision. Its historical rollout
date is not established by these sources; backtests must record that assumption
instead of claiming recovered actual fees.

[Series fee changes](https://docs.kalshi.com/api-reference/exchange/get-series-fee-changes)
support `show_historical=true` and dated fee-type/multiplier records.
[Event fee changes](https://docs.kalshi.com/api-reference/events/get-event-fee-changes)
override the parent series; null overrides clear the event policy. Current
snapshots alone are insufficient for historical selection. The downloader agent
has added both change feeds to the raw archive.

Implementation lives in `src/tradingbot/fees/`: Decimal public amounts, exact
rational arithmetic internally, signed fee breakdowns, one stateful calculator
per order, explicit effective intervals and no global mutable fee state. Unit
tests cover every PM US standard worked example, the complete Kalshi general
table, fractional fills, half-even ties, partial-fill corrections, maker/taker
transitions, fee multipliers, invalid inputs and account-balance alignment.
Supported scope is standard PM US CLOB plus explicitly resolved Kalshi quadratic
research schedules. No assumed incentive income, sports strategy, or live order
was added.

## Alpaca options data quality and history — tradingbot-dkt

**Finding:** indicative data is suitable for integration tests, not an exact
executable reference for the 3-cent discrepancy in strategy #3. Alpaca's
[historical-data documentation](https://docs.alpaca.markets/us/docs/historical-option-data)
describes indicative quotes as modified derivatives of OPRA and its trades as
derived and 15 minutes delayed. OPRA supplies consolidated best bid/offer.
Documented options coverage begins February 2024; this is not 2023 coverage.

The [Trading API plans](https://docs.alpaca.markets/us/docs/about-market-data-api)
list Basic as free, indicative options, 200 quote subscriptions and 200 historical
requests/minute. Algo Trader Plus is $99/month, includes OPRA, 1,000 option quote
subscriptions and 10,000 historical requests/minute. The Basic historical
restriction concerns the most recent 15 minutes, not a 15-minute total archive.
No plan upgrade or agreement was purchased/accepted.

Read-only probes using the existing paper keys (loaded with python-dotenv),
2026-09-30 around 17:03–17:05 UTC:

| Request | Result |
|---|---|
| Paper `/v2/options/contracts`, SPY and SPX, expiry 2026-09-30 through 2026-10-09, limit 1 each | Both HTTP 200; symbols SPY260930C00375000 and SPXW260930C02600000 |
| Data `/v1beta1/options/quotes/latest`, each symbol, `feed=indicative` | Both HTTP 200 with quote timestamps on 2026-09-30 |
| Same requests, `feed=opra` | Both HTTP 403, OPRA agreement not signed |
| Data `/v1beta1/options/trades`, SPY240216C00490000, 2024-02-01 through 2024-02-16, limit 1 | HTTP 200; first timestamp 2024-02-01T14:30:00.941197312Z |
| Same endpoint, SPY240119C00475000, 2024-01-02 through 2024-01-19, limit 1 | HTTP 200; first timestamp 2024-01-18T14:30:00.009729024Z |
| Same endpoint, SPY231215C00470000, 2023-12-01 through 2023-12-15, limit 1 | HTTP 200; empty, no next page |
| Same endpoint, SPXW240216C05000000, 2024-02-01 through 2024-02-16, limit 1 | HTTP 200; empty, no next page |

Thus this account can retrieve some historical trades despite lacking current
OPRA quote access. January data exists for the sampled SPY contract, earlier
than the documented floor; neither that sample nor an empty SPXW response
establishes complete chain coverage. Do not turn empty responses into zero prices.
These are entitlement/coverage probes, not a study of quote accuracy or fills.

The [SDK reference](https://alpaca.markets/sdks/python/api_reference/data/option/historical.html)
exposes historical option bars/trades and latest quotes/snapshots/chains, but no
historical option-quote method. Its seven-day trades wording is contradicted by
our older returned trades and the [REST trades reference](https://docs.alpaca.markets/us/reference/optiontrades).
Do not infer historical BBO/Greeks availability from the name of the historical
client; contemporaneous quote surfaces still need a suitable archive or recorder.

Alpaca [launched retail index options on September 2](https://alpaca.markets/blog/alpaca-launches-index-options-via-trading-api/).
The [index-options docs](https://docs.alpaca.markets/us/docs/index-options) distinguish
contract quotes on OPRA from underlying index spot data, which is not offered
at launch; NDX/NQX are also excluded at launch. An SPY proxy must not silently
replace SPX or Nasdaq settlement. Strategy #3 remains deferred under the Kalshi
account block. The equity-only strategies #5/#6 do not require options history.

## X API cost for 500 tickers — tradingbot-09f

**Finding:** 500 separately identified tickers polled every calendar day do **not**
fit $50/month. The [current official price list](https://docs.x.com/x-api/getting-started/pricing)
charges $0.005 per recent-count request, $0.010 per full-archive count request,
and $0.005 per returned post. It is prepaid usage pricing; do not use old Basic/Pro
subscription prices. Query counts rather than download all matching posts.

Calculated baseline costs, excluding retries, other app use and taxes:

| Collection design | Requests | Published-rate cost |
|---|---:|---:|
| 500 tickers every day, 30-day month | 15,000 recent-count requests | $75.00 |
| Same, 31-day month | 15,500 | $77.50 |
| 500 tickers, 23 trading days | 11,500 | $57.50 |
| 500 tickers every two days, at most 16 runs/month | 8,000 | $40.00 |
| 300 tickers every day, 31 days | 9,300 | $46.50 |
| Optional 30-day initial archive baseline, one page/ticker | 500 full-archive requests | $5.00 |

The [counts docs](https://docs.x.com/x-api/posts/counts/introduction) support daily
buckets across seven recent days, so one call can collect multiple completed days
for **one** ticker. An OR of 500 tickers returns an aggregate, not 500 independent
counts. Full-archive daily counts paginate at 31 days. Count totals can differ
from search because the compliance filtering differs.

One read-only test on the existing bearer token, 2026-09-30 around 17:06 UTC:
`GET https://api.x.com/2/tweets/counts/recent`, query `$SPY -is:retweet`,
start `2026-09-28T00:00:00Z`, end `2026-09-30T00:00:00Z`, granularity `day`.
HTTP 200 returned two buckets: September 28 = 3,765 and September 29 = 4,642.
This single call has a published rate of $0.005; actual account billing was not
audited. No post contents, account identifiers or secrets were saved.
No public post, write endpoint, credit purchase, or billing-setting change occurred.

The returned rate-limit headers were limit 300, remaining 299, matching the
[300 requests/15 minutes app limit](https://docs.x.com/x-api/fundamentals/rate-limits).
A full 500-ticker sweep must span rate windows or run at a suitably paced rate;
respect the reset header instead of retrying aggressively.

**Decision for the later `tradingbot-iox` implementation:** retain the $50 ceiling.
The every-two-day design preserves daily observations for all 500 tickers but
introduces up to roughly 48 hours of detection delay; it is a candidate for an
offline event study, not equivalent to daily actionable detection. Store both
event date and first-observed time to prevent look-ahead in a tradable simulation.
Alternatively, a smaller daily universe changes the research population. Neither
change was implemented here. A 30-day forward warm-up costs no extra backfill
calls and honors the PRD's forward-recording approach. Fix the ticker dictionary,
cashtag/alias, language and repost rules before collection; the test query is not
an approved study definition. Preserve unseen confirmation data and log every
tested variant. Leave room for retries/other usage and enforce the budget before
requests; API rate limits are not a dollar-spend limit.

## Alpaca adoption of PDT-rule removal — tradingbot-sbl

**Finding:** yes. Alpaca's [production announcement](https://alpaca.markets/blog/finra-retires-the-pdt-rule-introducing-alpacas-new-intraday-margin-framework/),
updated June 4, 2026, explicitly confirms adoption for both Trading API and
Broker API users. It removes the PDT designation, $25,000 PDT minimum and
day-trade counting, replacing them with intraday margin controls. The article
directs integrations to `buying_power` as legacy day-trading fields disappear.

This is a broker implementation finding, not an inference from regulatory
approval alone. [FINRA Regulatory Notice 26-10](https://www.finra.org/rules-guidance/notices/26-10)
sets June 4, 2026 as the effective date and permits firms to transition through
October 20, 2027; Alpaca has already implemented it. The current
[Alpaca FAQ](https://docs.alpaca.markets/us/docs/the-intraday-margin-rule)
confirms the PDT minimum is gone while ordinary margin requirements remain.

The [June 3 Trading API changelog](https://docs.alpaca.markets/us/changelog/2026-06-03-pdt-f3c04da)
says accounts are no longer flagged as pattern day traders and schedules removal
of `pattern_day_trader` and configuration `pdt_check` for July 6, 2026. Older
user-protection pages still describing PDT should not override these dated
implementation announcements.

Read-only evidence using the existing paper keys, loaded with python-dotenv,
2026-09-30 around 17:08 UTC: `GET https://paper-api.alpaca.markets/v2/account`
returned HTTP 200, status `ACTIVE`, `trading_blocked=false`, and a present
`buying_power` field. The fields `pattern_day_trader`, `daytrade_count`,
`last_daytrade_count`, `last_daytrading_buying_power` and
`daytrading_buying_power` were absent. This matches the announced schema
transition; it is not a live-account execution test. No balance, account ID or
secret was recorded, and no account setting or order was changed.

**Integration consequence:** do not require the removed fields or impose an
obsolete PDT counter. The paper account reports `multiplier="4"`; neither that
simulated leverage nor broker `buying_power` authorizes the bot to use margin.
Keep the PRD's cash-only treatment, T+1 settlement discipline and alternate-half
allocation unless the owner explicitly changes them. The PRD and §6 limits are
unchanged by this check.
