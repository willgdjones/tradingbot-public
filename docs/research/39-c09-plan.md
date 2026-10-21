# C09: IEF recovery after nominal ten-year Treasury auctions

2026-10-01, OrangeCove; next ready bead `tradingbot-5hl`, owner comment 17 and
AGENTS `d267cf7`. Historical adjusted-total-return units supersede the old
share-action prerequisite. Preserve source failure 4585 and its 242 reconciled
events, 23 reviewed special notices and eight earlier CUSIP-lineage records.

- **Frozen hypothesis/rules:** IEF only, every nominal original-ten-year note
  auction, including reopenings, emergency auctions and contingency auctions.
  Decide at the first regular ETF close on/after the dated auction; enter at
  the next regular open S. Ordered exits are S+5 and S+10 exchange-session
  opens. No yield, tail, bid-to-cover, size or subsequent-price filter. Dated
  offerings, occurrence and reviewed schedule amendments determine events.
  Ignore additional events while invested or awaiting an existing entry;
  never extend its original exit. Same-date events use CUSIP order only to
  label the one position, and every duplicate/overlap is counted.
- **Data:** retain 2006-01-01–2026-10-01 exclusive and cutoff
  2020-07-10T14:24Z. Reuse the full IEF adjusted Yahoo series and common calendar
  already frozen for C03. Nasdaq split-adjusted closes × independent Alpaca
  `all/split` factors match all 2,512 overlapping daily returns within 5 bp;
  the older 2,705 returns remain unmatched and disclosed. No primary patches.
  Revalidate original Treasury bytes/dated metadata without new searches or
  inspecting financial auction outcomes. Freeze the combined source hash.
- **Execution:** $140 virtual starting cash, min(95% decision equity, $140)
  frozen target, 5% decision-equity reserve and existing conservative cash
  release dates. Use settled cash after fees. A sub-$1 cash shortage delays
  entry to a later regular open only while it precedes the original exit;
  count skipped/late entries, and cancel if no holding interval remains.
  Use 5/10 bp adverse raw-cent rounding then total-return conversion, dated
  September 17, 2026 raw-share-equivalent fees, no separate dividend credit
  and no optional blackout. Scenario opens are not actual fractional fills.
- **Partition/trials:** start flat; decision, entry and exit all within one
  partition. Terminal open is liquidation-only. Four main training cases,
  two holds × two costs; log failures too. Highest positive, complete and
  flat 10 bp training net wins, listed order breaking ties. Commit source/code
  before training and the exact winner/version/hash in this plan before one
  10 bp final. No winner means no final; a failed/interrupted final is consumed.
- **Training controls:** for each H use S−H open to S open, equal session
  length. Exclude missing endpoints, partition crossings and any intersection
  with another auction's planned holding interval; shared endpoints do not
  overlap. No replacement windows. Both H controls run once at 10 bp and are
  excluded from selection. Their dates are retrospective diagnostic labels,
  not a claim the auction was announced before the control entry.
- **Diagnostics:** report fees, gross/net, trades, turnover, late/cash/overlap
  skips, marked drawdown, annual/fixed regimes, exposure and monthly-cluster
  luck. Compare zero-yield cash and same-partition IEF buy/hold. Previous IEF
  work and published-event selection prevent a pristine-holdout claim. No new
  p-value gate and no extra holdout cost/variant run.

**What could blow up this account?** Unhedged duration, overnight rate gaps and
IEF tracking can overwhelm a small auction effect or occur before our entry.
The unchanged −40% allocation kill and −$50 daily halt cannot guarantee exits;
funded positions may remain after a veto. Taker slippage, Alpaca/feed/Mac
dependence, event revisions and correlation with other bond/trend sleeves remain.
External inputs are data only. Hash-bound sources and the shared pure reactor,
ledger and risk interface preserve reproducibility. Actual broker fills and
actions belong in later paper/live verification. Actual allocation $0; no new
capital, venue, account, key, paid data, public post or PRD6/PRD9 change. Finish
the concise promotion checklist in the one results file after measurement.

## Frozen source and selection

Source `data/research/c09-total-return/source.json`, SHA-256
`821b7e0c3a948090de55c7f35f588b4f96c0996144742ce9d35286922bf9d57f`.
All 242 Treasury events and 23 special notices revalidated against their original
receipt, with 5,218 IEF sessions. Each post-auction variant has 242 full-source
windows; controls retain 239 five-session and 165 ten-session windows before
partition/overlap execution checks. Every excluded source window is logged.
Four training cases completed, trials 5489–5492, all flat with no rejected orders
or risk halts. Five-session holds lost $6.281888 / $25.923468 at 5 / 10 bp;
ten-session holds earned $35.823424 / $13.222513. The fixed rule selects
**ten sessions at 10 bp**, trial **5492**, 163 round trips,
$6.52 fees and 12.4151% marked maximum drawdown. No control can alter selection.

Selection artifact `data/research/c09-total-return/selection.json`, SHA-256
`55b7d04809dd447925d49a0a1d4550c31d0dbfe81fa1a039b88168d6529ed591`.
Selected strategy version:
`e97c65ea29df836a8e40f19adc07a5986da7770666c7245c2422fe84567517d8`.
This selection is committed before its one final; final unattempted at this commit.
