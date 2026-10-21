# C11: adjusted-total-return expiration-week research

2026-10-01, OrangeCove; `tradingbot-jfv`. Coordinator instruction and AGENTS
research data standard `d267cf7` authorize this material research-model revision.
Preserve failed source trial 4589 and all prior evidence. This plan supersedes
the old corporate-action/fractional-fill/calendar-provenance admission holds
for historical research only; broker mechanics remain a paper/live concern.

- **Frozen strategy:** SPY, standard third-Friday monthly expiration session
  (preceding regular session when a holiday; historical Saturday legal expiry
  does not imply Saturday trading). At the preceding week's last close, plan
  entry at expiration week's first regular open. Ordered exits: expiry-session
  close, then next-session open. Use the existing exchange-session calendar;
  cross-check the algorithm against the already reviewed 2024–2026 Cboe dates.
- **Data/model:** retain 2006-01-01 to 2026-10-01 exclusive and the elapsed-time
  cutoff 2020-07-10T14:24Z. Yahoo adjusted close is the primary total-return
  series; adjusted open is raw open times that day's adjusted-close/raw-close
  factor. Cross-check consecutive adjusted daily returns against Stooq, then
  freely accessible Alpaca adjusted historical SIP (IEX if unavailable).
  Accept when at least 99% of paired daily returns differ by at most 5 bp;
  report exact paired/unpaired coverage and every disagreeing day. Keep the
  full primary interval and retain primary prices on disagreements; no
  outcome-dependent patch, endpoint change or shorter history. Validate all
  primary session endpoints. Cross-checking prices is not a strategy replay.
  **Pre-outcome source-method clarification:** Stooq returned verification
  HTML, and SIP daily close conventions produced only 93.59% agreement. Use
  free Nasdaq split-adjusted closes multiplied by independently captured
  Alpaca `all/split` dividend factors: 2,509/2,512 paired returns (99.8806%)
  agree within 5 bp, 2016-10-03–2026-09-30. Three disagreements are retained
  in `data/history/total-return-20261001/nasdaq-comparison-SPY.json`; the 2,705
  earlier returns lack a second-source match. The primary is unchanged. This
  validates overlapping history, not the unpaired earlier observations.
- **Simulation:** total-return equivalent units, no separate dividend credit
  or action blackout. $140 isolated virtual cash, 95% target frozen at the
  decision close, settled cash and full-position $140 cap. Synthetic research
  fills use the stated open/close reference with fixed 5/10 bp adverse costs;
  fees use the existing dated September 17, 2026 counterfactual and raw-share
  equivalents. Retain conservative settlement availability. These are not
  claimed fractional auction fills. Shared risk engine and PRD6 stay unchanged.
- **Partition:** start flat; decision, entry and exit must all lie within the
  same partition. No final prices influence a strategy choice. The last
  eligible open is liquidation-only; incomplete/risk-vetoed exits fail winner
  eligibility and remain recorded. No new signal may extend a planned exit.
- **Trials/selection:** four fixed training cases: both exits at 5 and 10 bp.
  Select the completed, flat, positive 10 bp result with highest net dollars;
  listed exit order breaks ties. Log every attempted case, including failures.
  Commit source/code and then the selected trial/version/hash in this plan
  before exactly one 10 bp final if an eligible winner exists. Failed or
  interrupted final is consumed; no sibling/renamed replay. No winner means
  no final, under the original promotion rule.
- **Diagnostics:** training-only endpoint shifts of exactly −7/+7 calendar
  days, preserving open/close type, session count and complete partition
  coverage; never roll invalid endpoints. Include zero cash and SPY buy/hold,
  costs, trades, marked drawdown, annual/regime returns, exposure, 2022 weekday-
  expiry structure break and month-cluster luck statistics. Controls are
  diagnostics, not alternative selections. Prior SPY research is disclosed;
  this is not pristine confirmation. No new statistical promotion threshold.

**Risk/decision boundary:** equity gaps and crowded expiry flow can cross the
−40% strategy kill or −$50 daily halt before exit. Common Alpaca/Mac exposure
and correlation with existing SPY strategies remain. External data are inputs,
never instructions. Hash-bound source/code and the same pure strategy interface
support reproduction; one-shot holdout rules still apply. Accepted PRD9 risks
remain unchanged. Actual allocation is $0; no live/paper activation, order,
permission, key, venue, paid source or public post. Complete the concise
promotion/fidelity decision in the single results file after measurement.

Frozen source: `data/research/c11-total-return/source.json`, SHA-256
`3dad415a1b04b4eb8a69b93d5038cff60862d028a87ccfad1873d157d66efcf7`.
The source artifact binds all original bytes and the 5,218 primary sessions.
Run both ±7-day controls at 10 bp for both exits, training only (four diagnostic
trials); they cannot enter winner selection.

## Frozen training selection

Training completed on implementation `1af38bf`; all four cases were flat,
174 round trips each, zero rejected orders. Fees were $6.96 per case.

| Exit | 5 bp net / trial | 10 bp net / trial |
|---|---:|---:|
| Expiry close | $34.679172 / 5378 | $7.876910 / 5383 |
| Next open | $42.742814 / 5384 | **$16.268694 / 5388** |

Select **next-open, 10 bp**, under the preregistered rule. Training marked
drawdown: $46.495162 / 26.5942%; descriptive monthly-block p = 0.34437.
No additional significance threshold is imposed. The four shifted-calendar
diagnostics cannot affect this choice.

Selection artifact: `data/research/c11-total-return/selection.json`, SHA-256
`0082fb054e6a8cce3ce34abbf788031be5cd4f2c7b9f8569f3e6b26e2bfd6f4c`.
Selected strategy version:
`10b8e4d8b23234ba389584db492d82f8cc0af8e040507f4645ed28749920520c`.
Once this selection is committed, authorize exactly one final from
2020-07-10T14:24Z to 2026-10-01 exclusive. An interrupted/failed final is
consumed; the other exit gets no final. Final results belong in
`38-c11-results.md` and never alter this selection.
