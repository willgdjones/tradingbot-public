# C04 inverse-variance SPY — source readmission

2026-10-01; `tradingbot-y2d`; reviewer OrangeCove.

The frozen SPY source passed re-admission. The first six execution attempts are
retained as incomplete evidence because their buys encountered the unchanged
rounded-limit position cap. The documented v2 sizing repair completed all six
fixed training configurations without a rejected order. It changed requested
quantities to respect the existing cap; signals, sources and §6 are unchanged.

## Fixed training selection

Each run starts with $140 virtual cash. P&L includes modeled costs/fees and
separately reconciled issuer dividends. Current fees, T+1 and cash release are
counterfactuals. Training ends at 2020-07-10 14:24 UTC.

| c | Cost per side | Trial | Net USD | Fees USD | Maximum marked drawdown USD | Drawdown from peak |
|---|---:|---:|---:|---:|---:|---:|
| 0.0225 | 5 bp | 4058 | 157.222724 | 3.44 | 44.854326 | 24.73% |
| 0.0225 | 10 bp | 4059 | 155.690769 | 3.41 | 44.738918 | 24.91% |
| 0.01 | 5 bp | 4060 | 118.705792 | 3.48 | 27.854179 | 13.32% |
| 0.01 | 10 bp | 4061 | 115.828820 | 3.48 | 27.786440 | 13.44% |
| 0.04 | 5 bp | 4062 | 182.569108 | 3.44 | 52.932216 | 30.78% |
| **0.04** | **10 bp** | **4063** | **181.451416** | **3.38** | **53.097999** | **30.90%** |

The fixed rule selects **c = 0.04** from trial 4063 by highest positive complete
10 bp training net. No alternative scaling constant or threshold was searched.
The [frozen selection](24-c03-c04-c04-v2-selection.json) binds every training
artifact, source/dependency hash, split and the chosen strategy version. Its
SHA-256 is `48dc41d9ec859291a59457b10c47346e4810e863e402312770ba78d8686ca026`.

All six runs end flat with one completed position lifecycle. Hundreds of
monthly observations or partial rebalances do not become independent completed
trades. The predeclared luck estimate is **null** for insufficient independent
completed exits. Selected training has 148 fills, $37.231420 dividend income,
and 60.89% average marked exposure. The full artifact includes annual and
calendar-regime P&L/drawdowns, turnover, cash delays, skips, dividends and SPY/
cash diagnostics. These benchmarks are uncosted diagnostics, not executable
alternatives or proof of alpha.

The [stored-ledger audit](24-c03-c04-c04-training-audit.json) independently checks
all six artifacts against trial metrics and fill IDs, every buy's complete
position at the rounded limit against $140, fees, partition bounds and terminal
flatness. It did not replay prices. Both original source failures and all six
v1 trial rows retain their original full-row hashes.

## Final and review disposition

Final **4066** consumed the one committed-choice 10 bp attempt and completed
with **+$121.931558 net**, including $11.251265 issuer dividends and $1.61 fees.
It has 67 fills, one completed position lifecycle, zero rejected orders, no
remaining shares and no recorded risk halt. Maximum marked drawdown is
**$38.094083 / 20.26%**; daily-close drawdown is $35.490338 / 18.92%. Average
exposure is 68.06%; turnover is $1,060.68. Luck p-value remains **null** for
insufficient independent exits. This final is consumed and must never be rerun.

Ending marked equity is $261.93; approximately $120.91 is settled cash and
$141.02 is unsettled sale proceeds/dividend receivables. Flat inventory does
not mean all proceeds are immediately spendable. The source-bound cash
convention and issuer schedule remain counterfactual broker assumptions.
The audit reconciles journal/marked values within the documented accumulated
sub-cent rounding tolerance ($0.000067 for this 67-fill final).

| Calendar regime | Selected training marked net USD | Final marked net USD |
|---|---:|---:|
| 2006–2009 | +17.284567 | outside partition |
| 2010–2019 | +185.042859 | outside partition |
| 2020–2021, each partition's covered dates | −20.876011 | +46.759740 |
| 2022 | outside partition | −26.063517 |
| 2023–2026 | outside partition | +101.235332 |

The [final receipt](24-c03-c04-c04-v2-final.json) carries annual/regime
drawdowns and all diagnostics. Final strategy net is 87.09% of initial virtual
cash; uncosted, fully exposed SPY total return is 161.48% over the same observed
close partition, with 24.50% peak drawdown. Different exposure and cash costs
prevent treating that simple comparison as a causal alpha test.

The [final stored-ledger audit](24-c03-c04-c04-ledger-audit.json) verifies all
seven v2 trials, independently reconstructing fee charges, source-open costs,
dividend ownership and cash release/receivables from stored fills. It confirms
exactly one C04 family final, unchanged training/old failure rows and no price
replay. All final economics come from the consumed attempt, not recomputation
of strategy decisions.

**Hold; no paper/live promotion.** The [account-risk review](24-c03-c04-c04-preflight.md)
remains applicable. The selected training drawdown is $53.10, or 37.93% of the
initial $140 slot, close to the $56 strategy loss budget even though no kill
was triggered. Drawdown from a prior profit peak is different from loss versus
initial capital; the comparison does not change the kill definition. Prior
SPY #5/#6/C01 inspection also prevents a fresh-unseen-evidence claim, and native
forward fills/cash/fees remain unvalidated. The source amendment and positive
historical P&L do not remove those limitations. No real allocation, order, key,
account, venue or §6 change is made.
