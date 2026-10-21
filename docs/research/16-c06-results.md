# C06: training failed; final holdout not run

All six preregistered cases lost money after costs. No 10 bp variant qualified,
so **no final was selected or attempted**. The six completed research trials
remain in the ledger, including their losses. No paper/live promotion or real
order followed. Bead `tradingbot-kc4`, 2026-10-01.

The [frozen training receipt](16-c06-selection.json) preserves exact metrics,
source identity, code/dependency fingerprints, local artifact hashes and the
null selection. Implementation `c870b45` and source slice `6ad1c58` were
committed and pushed before training. See the [plan and completed research
checklist](16-c06-month-end-plan.md) and [source audit](16-c06-source-audit.json).

## Six fixed training cases

Each isolated case started with $140 virtual cash. Prices are the explicit
opening-reference scenarios, with 5 or 10 bp adverse cost per side and the
dated current-fee counterfactual. Net P&L already includes both. Fees below are
the separately charged regulatory fees, not an additional subtraction.

| Threshold | Cost/side | Trial | Round trips | Net P&L | Fees | Max marked drawdown | Drawdown % | Monthly-block p |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.600 | 5 bp | 3541 | 61 | −$19.19 | $2.44 | $21.24 | 14.95% | 0.922 |
| 0.600 | 10 bp | 3542 | 61 | −$26.06 | $2.44 | $26.85 | 19.07% | 0.971 |
| 0.595 | 5 bp | 3543 | 38 | −$14.94 | $1.52 | $21.57 | 14.71% | 0.877 |
| 0.595 | 10 bp | 3544 | 38 | −$19.40 | $1.52 | $24.71 | 17.01% | 0.931 |
| 0.590 | 5 bp | 3545 | 31 | −$12.11 | $1.24 | $19.66 | 13.32% | 0.880 |
| 0.590 | 10 bp | 3546 | 31 | −$15.84 | $1.24 | $22.34 | 15.25% | 0.940 |

All orders filled under the declared scenario, with zero rejections and flat
ending positions. Independent database readback verified 122/122/76/76/62/62
fills, every entry's limit notional below $140, metrics/version equality with
the receipt, and no fills at or beyond the cutoff. Monetary ledger rounding
differs from full-precision round-trip sums by less than the declared
one-microdollar-per-trip tolerance. The displayed cents agree.

The p-values are descriptive one-sided, centered, three-month circular-block
bootstrap estimates over 175 calendar months, using the fixed seed and 10,000
draws. They are not posterior probabilities that the hypothesis is true/false,
and do not correct for selecting from several hypotheses. They impose no extra
promotion gate: the family stops because net training profitability failed.

## Regimes and calendar exposure

The 10 bp cases show the following marked net P&L. Complete annual marked P&L,
annual/regime drawdowns, exit-year trade summaries, turnover, exposure and
benchmark diagnostics are in the receipt.

| Threshold | 2006–2009 | 2010–2019 | 2020 through training cutoff |
|---|---:|---:|---:|
| 0.600 | −$10.56 | −$11.61 | −$3.88 |
| 0.595 | −$5.74 | −$11.15 | −$2.51 |
| 0.590 | +$1.03 | −$14.29 | −$2.58 |

The training partition contains 173 complete calendar-eligible month-end
windows. Their mean gross open-to-open return is **−2.19 bp**, before modeled
trading costs. Qualified windows average −11.06 bp (61 windows), −16.63 bp (38)
and −16.25 bp (31), respectively. Thus this training sample does not support
the proposed long-only underweight condition. This is a diagnostic comparison,
not an executable all-month-end strategy or evidence for a replacement rule.

## Locked final and decision

The full source remains 2006-01-01 through 2026-10-01 exclusive; the cutoff is
2020-07-10 14:24 UTC. Training observations stop before that instant. Database
readback confirms **zero final trials** for this dataset; all final P&L, fees,
drawdown, trades, regimes and p-values are unmeasured. In particular, there are
no claimed 2021/2022/2023–2026 strategy results. The rule was not retuned after
these losses, and no alternative threshold/cost was added.

Decision: **hold/reject this candidate's preregistered family**. Retain all six
completed losing trials and immutable artifacts; do not advance to paper/live.
The written account-risk checklist remains applicable. Prior SPY inspection in
#5/#6/C01 and issuer-page performance information stays disclosed; even a
positive historical result would not become untouched proof through this source
amendment. All §6 limits and accepted operational risks remain unchanged.
