# C03 cross-asset momentum — re-admission remains source-failed

2026-10-01; `tradingbot-y2d`; reviewer OrangeCove. **No C03 ranking, signal,
strategy return, training case or final holdout was computed.** Original failed
trial 3516 is unchanged. New source-failure **trial 4067** records this audit
under committed implementation `904e3ae`; no strategy version was replayed.

The fixed SPY/IEF/GLD/EFA/VNQ universe and 2006–2026 source interval remain
unchanged. This re-audit applies the frozen SPY corrections and payment/cash
policy from [report 13](13-equity-data-repair-spy-amendment.md), rather than
re-running the original known-bad strict parser. All five original Yahoo files
still cover the same 5,218 sessions without split events.

## What now reconciles

- **SPY:** hash-bound corrected 83 issuer distributions, regular-session
  open/close evidence and conservative settlement calendar are reusable.
- **IEF:** all 248 ex-date amounts and payment dates reconcile to the archived
  [iShares issuer page](https://www.ishares.com/us/products/239456/ishares-7-10-year-treasury-bond-etf).
  Independent SIP/IEX raw opens and closes have no 1% breaches.
- **EFA:** all 40 distributions reconcile to the
  [issuer page](https://www.ishares.com/us/products/239623/ishares-msci-eafe-etf).
  Pre-2006 rows with null component amounts are outside the fixed source
  interval; no in-interval null was imputed. Both embedded issuer tables must
  agree before parsing. The March 16, 2020 closing discrepancy reconciles to
  the primary NYSE Arca closing print, $47.45.
- **VNQ recent history:** the issuer's published
  [distribution endpoint](https://advisors.vanguard.com/investments/products/api/funds/0986/pricing/distributions)
  supplies 83 cash-component rows covering 40 ex-dates from December 22, 2016.
  Summed INC/ROC/capital-gain/1250 components match every corresponding Yahoo
  total within the original rounding bound. Record/pay dates agree within each
  component group.
- **Independent prices:** each of IEF/EFA/VNQ has 2,701 SIP and 1,553 IEX overlap
  rows. All seven EFA/VNQ open/close breaches reconcile to primary Arca prints
  in the fixed ten-second auction windows. No price replacement or wider
  tolerance was needed. No pre-2016 independent price coverage is claimed.

The broker action request returned 232 ordinary cash events, no noncash events,
and starts in 2016 despite the 2006 request boundary. It is not evidence of
complete pre-2016 action coverage. GLD's original source has no dividends or
splits; C05's separately repaired GLD source is reusable for its 2008+ scope,
but no complete C03 share-action admission is claimed while the cash gate fails.

## Remaining failure

Vanguard's current product interface explicitly offers up to ten years of
distributions, leaving **43 original VNQ ex-dates without issuer rows**.
[Issuer product page](https://advisors.vanguard.com/investments/products/vnq/vanguard-real-estate-etf).
Two free secondary archives were captured as reconciliation evidence:
[DividendHistory](https://dividendhistory.org/payout/VNQ/) and
[StockScan](https://stockscan.io/stocks/VNQ/dividend-history).

DividendHistory has every original ex-date but reports **$1.133** on
December 22, 2006, versus Yahoo's total **$1.494**. StockScan agrees with Yahoo
on its available totals but omits all four 2006 events and June 24, 2009. Thus
the old cash inventory still lacks a documented reconciliation of the complete
distribution and its payment timing. Other DividendHistory component/total
differences in 2018–2019 are resolved by the available issuer rows; the 2006
discrepancy is not.

For 38 of the 43 older dates, the two secondary archives agree on amount and
payment date. That partial corroboration is retained; it does not resolve the
five dates above or establish that all of December 2006's components share the
documented payment timing.

The conservative “latest documented pay date, then next regular open” rule
cannot establish the payment date of an unverified missing cash component.
Neither a guessed capital-gain amount nor the payment timing of another
component is silently substituted. This source attempt therefore fails before
any strategy outcome. The machine-readable [audit](24-c03-c04-c03-source.json)
retains every missing date, discrepancy, reference request and response hash.

Recovery requires original issuer/exchange distribution notices, or sufficiently
corroborated complete-component records, for the remaining older VNQ dates;
then complete the whole-universe action inventory and freeze a new source
receipt before signals. No shortened sample, replacement ETF, paid data,
account/key, capital or §6 change was introduced. C03 remains an idea with zero
allocation; P&L, drawdown and luck p-value remain unmeasured.

Follow-up `tradingbot-2wh` names the five unresolved dates and remaining source
inventory checks. This source re-audit is complete; C03 remains unadmitted.
