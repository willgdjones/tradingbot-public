# Full-history longshot selection before final evaluation

Recorded 2026-10-01 after all 30 training variants completed and before any
final admission. The [exact selection](20-longshot-selection.json) and
[complete training records](20-longshot-training.json) are byte-identical to
the driver's immutable artifacts. The [training receipt audit](20-longshot-training-audit.json)
verifies all 30 completed attempts. Final count at this checkpoint: **zero**.

The preregistered rule selects **international Polymarket daily BTC,
sell-longshot, offset 0.05**, trial **3935**, for one final evaluation. It has
the largest positive after-fee training profit among that category's six
variants. Size, other parameters, reference maps, fee scenario and execution
implementation remain frozen. The exact strategy version is
`9184763a9ab5d6daaac3cd2356f25724ec88c7ae32c9eba24fcb460718fe5283`.

| Training evidence | Value |
|---|---:|
| Gross P&L | $107.361966 |
| Fees / rebates | −$14.42 |
| Net P&L | $121.781966 |
| Completed trades / UTC exit dates | 250 / 245 |
| Marked peak-to-trough drawdown | $175.06646047 |
| Drawdown / initial $140 virtual slot | 125.05% |
| Per-trip / date-aggregate one-sided p-values | 0.219943 / 0.220702 |
| 2026 Q2 training net | −$108.39424007 |
| Permanent kills / holds over seven days | 0 / 0 |

The training profit comes with a substantial drawdown and a losing recent
calendar quarter. Training equity had grown before retreating; the unchanged
loss kill triggers when equity falls $56 below its initial $140. The reported
p-values are descriptive, with serial-dependence and six-variant-selection
limitations. They are not probabilities that the hypothesis is true, and no
new statistical or risk threshold has been imposed after seeing outcomes.

The three Kalshi categories and international NYC weather have no profitable
training variant. Their final partitions **remain unconsumed**. Across the
entire training grid, two variants are profitable, 28 triggered the permanent
simulated kill, and none recorded a holding-period breach.

The selected final starts flat with an independent virtual $140 book and the
same frozen version. Durable admission precedes all final-price access; an
interrupted or failed final remains consumed. The choice must be committed
and pushed before admission. The final is evidence about a PM US fee
counterfactual on international history, with the source and execution
limitations in the [preregistration](20-longshot-plan.md) and
[account-risk preparation](20-longshot-preparation.md).

This is a research selection, with $0 real allocation and no paper/live
promotion. Native PM US execution and cash-release fidelity remain unproven,
and prediction venues remain deferred for verification.
