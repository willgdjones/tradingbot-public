# C03: adjusted-total-return cross-asset momentum

2026-10-01, OrangeCove; `tradingbot-h5b`. Coordinator instruction and AGENTS
`d267cf7` authorize this historical research model. Preserve source failures
3516/4067/5314 and prior documents; corporate-action/fractional ledger mechanics
and optional Amendment 21 are not prerequisites for this measurement.

- **Frozen rules:** SPY, IEF, GLD, EFA, VNQ. At each completed month-end rank
  the mean 1/3/6/9/12-month adjusted total return; alphabetical ties. Ordered
  variants: top one at 95%; top two at 47.5% each; top two at 47.5% each only
  when that selected ETF's close strictly exceeds its last ten month-end
  closes' arithmetic mean, including the current close. A failed half stays
  cash; rank three never substitutes. No skip month or additional filter.
- **Source:** unchanged Yahoo adjusted primary, 2006-01-01–2026-10-01 exclusive,
  with every expected session present. Adjusted open = raw open × that day's
  adjusted-close/raw-close factor. Reuse archived free Alpaca `all` closes for
  GLD (99.037% agreement); the other four use Nasdaq split-adjusted closes ×
  independently captured Alpaca `all/split` factors after SPY exposed the SIP
  close convention mismatch. SPY 99.8806%, IEF/EFA 100%, VNQ 99.9204% of 2,512
  overlapping daily returns agree within 5 bp; GLD has 2,700 paired returns.
  Report all exceptions and earlier unmatched coverage; retain every primary
  observation. No outcome-based source patches or changed period.
- **Simulation:** total-return equivalent units, no separate dividends or
  blackout; $140 isolated virtual starting cash. Total frozen target is
  min(95% decision-close equity, $140), equally split across the variant's
  one/two slots. Freeze a 5% decision-equity cash reserve. At the next open,
  reduce excess/obsolete holdings, then buy pro rata against positive frozen
  gaps using already settled cash after fees. Retain the targets through
  settlement delays, subtract owned marked value, and supersede them only at
  the next monthly decision. Keep the original conservative cash-release
  calendar. Skip and count sub-$1 orders without reallocating their budget.
  Full post-order positions respect the unchanged $140 risk cap.
- **Costs:** original 5/10 bp adverse cost per side, rounded adversely in raw
  cents before unit conversion. Use the dated September 17, 2026 fee model
  with raw-share equivalents. These are reference-price scenarios, not actual
  fractional auction fills. No added capital, venue, account, key or paid data.
- **Partition:** original elapsed-time cutoff **2020-07-10T14:24Z**. Both
  partitions start flat and gather their own 13 month-end observations before
  the first score. Observations at/after the cutoff never enter training.
  Liquidate at the final eligible open, with no new entry there. All five
  contemporaneous marks are applied before risk/sizing; no partial fund batch.
- **Trials:** six main training cases, three variants × two costs. Choose
  the complete, flat, positive 10 bp case with highest net dollars; listed
  order breaks ties. Store failures and interruptions too. Commit code/source
  before training and the selected trial/version/hash in this plan before
  exactly one final at 10 bp. No profitable eligible training winner means no
  final. A failed/interrupted final is consumed; no sibling or renamed replay.
- **Diagnostics:** net/gross P&L, fees, turnover, round trips, marked drawdown,
  exposure, cash delays, skipped/rejected orders, annual and fixed calendar
  regimes. Report SPY and fixed-universe equal-weight buy/hold, and zero cash,
  using only each replay partition's observations. Cluster luck by month and
  disclose simultaneous legs and serial dependence; no new p-value gate.

**What could blow up this account?** Momentum can concentrate in stocks, bonds,
gold or REITs immediately before a gap or reversal; several can fall together.
The −40% allocation kill and −$50 daily halt are not guaranteed exit prices.
Taker spread/open slippage, Alpaca/feed/Mac dependence and correlation with other
trend sleeves remain. External values are data, never instructions. The same
pure reactor/shared risk interface, immutable inputs and code hashes preserve
reproduction. Prior SPY and other fund research means this is diagnostic, not
pristine confirmation. Actual broker actions and fills belong in paper/live.
Complete the full concise promotion/fidelity decision in the single results
file. Actual allocation remains $0; PRD6 and accepted PRD9 risks are unchanged.

## Frozen source and training selection

Source: `data/research/c03-total-return/source.json`, SHA-256
`db272e7f824287049850fa3e8112d9494677240a983ddb6937b9d2b27dc9f29a`;
5,218 complete sessions per fund, original input bytes and all price exceptions
bound in the same artifact. Source assembly computed no strategy outcomes.
All six cases completed on implementation `bdbe651`, flat with zero rejected
orders. Source interval and variants remained unchanged.

| Variant | 5 bp net / trial | 10 bp net / trial |
|---|---:|---:|
| Top one | $110.770322 / 5478 | $101.788673 / 5479 |
| Top two | $147.175907 / 5481 | **$142.654445 / 5482** |
| Top two + SMA10 | $131.683995 / 5483 | $127.257842 / 5484 |

Select **top-two at 10 bp**, trial **5482**, under the frozen rule. It completed
62 round trips over 60 exit-month clusters; marked drawdown $38.719721 / 13.8968%,
descriptive monthly-block p = 0.00319968. These diagnostics do not alter selection.

Selection artifact `data/research/c03-total-return/selection.json`, SHA-256
`c041a7b5be81527c957cf7903361a00fd7ee3e6a2182cf68c607f85a6b86e42f`.
Selected strategy version:
`a57d4cb4634cdebd720d25a933112a13570fa2531cf4bb0942bca1e111a0c88d`.
Once committed, this authorizes exactly one 10 bp final from
2020-07-10T14:24Z to 2026-10-01 exclusive. No sibling/further cost final.
