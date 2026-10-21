# C06 month-end stock/bond underweight flow

Source admission precedes all strategy outcomes. The binding rule remains in
[the candidate preregistration](07-candidate-shortlist.md): SPY traded, IEF
reference, thresholds 0.600/0.595/0.590, 5/10 bp training costs, one frozen 10 bp
final if training qualifies. Source interval is 2006-01-01 through 2026-10-01
exclusive; holdout begins 2020-07-10 14:24 UTC. No boundary or variant changes.

At the penultimate session's close, month-to-date total returns use the previous
month's final close and only subsequent completed closes/ex-date distributions.
Daily factors use `(close + distribution) / previous_close`; their product is
the total-return factor. No adjusted close plus extra dividend. Weight is
`0.6 * SPY_factor / (0.6 * SPY_factor + 0.4 * IEF_factor)`. Entry is the final
session's reference open and exit the next month's first reference open. No
final-session observation selects that morning's trade. Both signal history and
the complete planned round trip must be inside the same partition.

The opt-in [SPY source amendment](13-equity-data-repair-spy-amendment.md) supplies
only open/close prices and exact distributions; its explicit correction and cash
policies are retained. IEF's existing C03 Yahoo archive is an immutable input,
not C03 strategy evidence. Audit full issuer ex-dates/amounts and independent
price overlap before computing C06 outcomes. IEF is never owned in this rule;
its payment dates are retained as evidence but cannot create spendable strategy
cash. SPY receivables become spendable only under the frozen conservative
cash-release convention; actual forward trading still uses ledger availability.

Use $140 virtual initial cash, target at most 95% of decision equity and no more
than the unchanged $140 strategy slot, floor fractional quantities, skip buys
under $1, retain the cash reserve, and run all orders through shared RiskEngine
and Ledger. Current dated equity fees are a historical counterfactual. Source
prices are execution references, not proof of fractional auction fills or live
freshness. Previously viewed SPY history and issuer-page fund performance remain
contaminated; no repaired source resets a consumed final or proves fresh alpha.

Report qualifying windows against all eligible month-end windows, completed
round trips, costs, cash delays, exposure, drawdown, regimes and month-clustered
luck odds. Benchmark windows are diagnostics. Source failure stops before
signals/outcomes and is recorded with null performance in the trials ledger.

What could blow up this account? A Treasury move can change the proxy without
causing balanced-fund buying; fund timing can drift; overnight gaps can exceed
the assumed spread; dividend/settlement errors can spend unavailable cash; a
slow monthly signal supplies few independent observations. The unchanged
strategy/global loss limits and settled-cash checks constrain orders. Prior
SPY inspection prevents calling a historical positive result untouched proof.

## Idea-to-backtest checklist and decision

Completed against [the promotion checklist](../promotion-checklist.md),
2026-10-01, OrangeCove. Decision: **backtest research only**, $140 virtual
allocation per isolated configuration, no funded allocation or concurrent
portfolio claim. Structural scheduled-flow hypothesis and exact entry/exit are
specified. Source admission is frozen before outcomes. Profitability, trade
count, drawdown, regimes and luck remain unmeasured until the recorded training
runs; these are pending outcome checks, not asserted passes. Each later stage
needs its own decision. No paper/live execution fidelity is claimed.

The same pure reactor uses runtime observations and read-only settled cash and
marked equity. The historical runtime supplies explicit assumed opening fills;
a future paper/live adapter must supply actual fresh quotes and account state.
It is not activated here. All §6 values remain unchanged, including the current
owner-approved equity slot cap rather than the older prediction-market $25
wording in the generic checklist. No capital, venue, account, key or public post.

- **Tail/gaps:** owned SPY can lose nearly the $140 slot. Gaps can cross the
  $56 strategy loss trigger or $50 daily halt before an executable observation;
  daily observations cannot bound intraday extremes.
- **Adverse selection:** these are assumed taker opening fills, not maker
  rewards. Auction imbalance, spread, fractional execution delays and informed
  flow can overwhelm the modeled 5/10 bp costs. Prediction-market maker guards
  are inapplicable to this SPY rule.
- **Counterparty/venue:** future execution would depend on Alpaca and current
  quotes. Accepted no-dead-man/no-startup-reconciliation exposure remains;
  outages can leave holdings or orders. No live keys or orders are used, and
  eventual keys must be trading-only.
- **Untrusted inputs:** issuer, exchange and price responses are validated data;
  none supplies instructions or changes hard risk limits.
- **Reproducibility:** immutable source receipts and committed code bind the
  scenarios. Training has three thresholds and two fixed costs; monthly luck
  uses a fixed three-month circular-block bootstrap, 10,000 draws, seed 6062026,
  and reports null below 30 completed trades/months. Final admission is durable
  before feed iteration; interrupted finals cannot be replayed. Source repair
  never makes previously inspected history unseen.
- **Correlation:** SPY overlaps #6 and other long-equity exposures. Results are
  isolated $140 scenarios, not permission to reuse the same capital across
  strategies; a concurrent portfolio could hit the global halt sooner.
