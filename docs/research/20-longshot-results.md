# Full-history favourite–longshot results

The fixed six-variant grid was evaluated separately in each of the five captured categories. The final partition was opened only for a positive-net training selection. All results below use the current PM US fee counterfactual on native public history; they do not establish executable returns on PM US. No paper/live promotion or real funding occurred.

[Preregistration](20-longshot-plan.md) · [Source admission](20-longshot-preparation.md) · [Frozen selection](20-longshot-selection.json) · [Full machine results](20-longshot-results.json) · [Final evidence](20-longshot-final.json) · [Execution audit](20-longshot-execution-audit.json) · [Exact execution receipts](20-longshot-executions.tar.gz)

## Interpretation

International BTC **sell-longshot at offset 0.05** is the only category/choice meeting the declared after-fee profit condition in both partitions: **+$121.781966 training / +$15.638289 final**. The selected version completed 250 training and 111 final trades. The other four categories have no profitable training choice and leave their finals unconsumed.

Retain this candidate in research. Its marked peak-to-trough drawdown is **$175.07 in training and $83.28 in the final**, equal to 125.05% and 59.49% of the initial virtual $140 slot. Training equity grew before retreating; the unchanged loss kill measures equity falling $56 below the initial $140, so these peak drawdowns did not trigger it. Those drawdowns do not demonstrate acceptable risk for this allocation. This review changes no loss limit or selection rule.

The final earns $47.64 in its June/Q2 portion, then **loses $32.00 in Q3**: July +$9.03, August −$16.12 and September −$24.91. Final gross profit is $9.80 plus $5.84 in modeled maker rebates. Its per-trip and date-aggregate one-sided p-values are both **0.43536**; training values are about 0.22. These selected and serially dependent observations provide weak statistical evidence and substantial regime/risk uncertainty. The stated profit condition has passed; native venue execution and promotion suitability remain unestablished.

## Decision by category

| Category | Training trial | Final trial | Historical scenario result | Pipeline decision |
|---|---:|---:|---|---|
| kalshi:KXBTC | none | unconsumed | FAIL_TRAINING | hold in research |
| kalshi:KXHIGHNY | none | unconsumed | FAIL_TRAINING | hold in research |
| kalshi:KXINX | none | unconsumed | FAIL_TRAINING | hold in research |
| polymarket_intl:pm-series:btc-up-or-down-daily | 3935 | 3969 | COUNTERFACTUAL_PROFIT_BOTH_PARTITIONS | hold in research |
| polymarket_intl:pm-series:nyc-daily-weather | none | unconsumed | FAIL_TRAINING | hold in research |

- **kalshi:KXBTC**: 6/6 training variants completed, 0 profitable; net range $-58.8700 to $-43.0400. Permanent kills: 6; variants with a hold over seven days: 0.
- **kalshi:KXHIGHNY**: 6/6 training variants completed, 0 profitable; net range $-53.7800 to $-47.5300. Permanent kills: 6; variants with a hold over seven days: 0.
- **kalshi:KXINX**: 6/6 training variants completed, 0 profitable; net range $-57.9000 to $-54.6600. Permanent kills: 6; variants with a hold over seven days: 0.
- **polymarket_intl:pm-series:btc-up-or-down-daily**: 6/6 training variants completed, 2 profitable; net range $-65.6012 to $121.7820. Permanent kills: 4; variants with a hold over seven days: 0.
- **polymarket_intl:pm-series:nyc-daily-weather**: 6/6 training variants completed, 0 profitable; net range $-56.1991 to $-29.9674. Permanent kills: 6; variants with a hold over seven days: 0.

## Dataset and execution

The original cohort contains 37,384 contracts / 74,768 outcomes. The manifest excludes 53 contracts (30 off-session index contracts, 11 invalid weather windows, one uncertified payout pair and 11 split crossers), leaving 23,632 training and 13,699 final contracts. Zero-volume, empty-tape and catalog-gap observations are retained in the source audit, without fabricated executions.

The elapsed UTC split is 2025-08-29T15:15:47+00:00 to 2026-09-30T23:01:46.460587+00:00 (exclusive), with the fixed 70/30 cutoff at 2026-06-03T18:17:58.622410+00:00.

Each category deploys an independent **virtual $140 alternative**. Summing these profits does not describe one funded portfolio. Every variant starts flat, reserves held and pending worst-case collateral, obeys the $25 binary-contract cap and unchanged risk veto, and holds until actual terminal settlement. Replay cash is released at the modeled terminal timestamp; native PM US cash availability is unverified. Strictly later through-price prints and observed volume are required for maker fills. Quiet-tape timers pull orders five minutes before scheduled close; later observations still mark positions.

The maker coefficient is −0.0125 and taker coefficient 0.0695; this study is maker-only, with fee-free settlement and a $1 value per binary payout unit, with no invented rewards. Negative fee totals are rebates. Native venue fee economics are not estimated. Source prices are exact Decimals, size rounds down to 10 decimal places, and cash/ledger residuals are explicitly checked against accounting-column precision.

## All training variants

| Category | Side | Offset | Trial | Status | Net $ | Gross $ | Fees $ | Trades | Maker fills | Marked DD $ | DD / $140 | Trip p | Date p (n dates) |
|---|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| kalshi:KXBTC | buy_favourite | 0.01 | 3808 | complete | -49.4900 | -53.3300 | -3.8400 | 118 | 250 | 65.2700 | 46.6% | 0.71781 | 0.88126 (24) |
| kalshi:KXBTC | buy_favourite | 0.02 | 3810 | complete | -58.3200 | -62.0300 | -3.7100 | 99 | 216 | 69.0300 | 49.3% | 0.74903 | 0.93708 (21) |
| kalshi:KXBTC | buy_favourite | 0.05 | 3812 | complete | -55.2400 | -58.5500 | -3.3100 | 82 | 166 | 74.1900 | 53.0% | 0.75037 | 0.99231 (19) |
| kalshi:KXBTC | sell_longshot | 0.01 | 3815 | complete | -49.4900 | -53.3300 | -3.8400 | 118 | 250 | 65.2700 | 46.6% | 0.71781 | 0.88126 (24) |
| kalshi:KXBTC | sell_longshot | 0.02 | 3817 | complete | -58.8700 | -62.5800 | -3.7100 | 99 | 217 | 69.5800 | 49.7% | 0.7508 | 0.93844 (21) |
| kalshi:KXBTC | sell_longshot | 0.05 | 3819 | complete | -43.0400 | -45.6800 | -2.6400 | 65 | 133 | 70.6200 | 50.4% | 0.72012 | 0.97446 (15) |
| kalshi:KXHIGHNY | buy_favourite | 0.01 | 3821 | complete | -53.7800 | -54.8700 | -1.0900 | 24 | 58 | 69.6400 | 49.7% | 0.88341 | 0.88734 (7) |
| kalshi:KXHIGHNY | buy_favourite | 0.02 | 3823 | complete | -48.5300 | -49.6300 | -1.1000 | 22 | 56 | 62.6800 | 44.8% | 0.86077 | 0.89081 (7) |
| kalshi:KXHIGHNY | buy_favourite | 0.05 | 3833 | complete | -52.0900 | -57.2100 | -5.1200 | 115 | 291 | 73.2500 | 52.3% | 0.71038 | 0.80048 (33) |
| kalshi:KXHIGHNY | sell_longshot | 0.01 | 3888 | complete | -48.6100 | -49.7300 | -1.1200 | 24 | 59 | 69.6000 | 49.7% | 0.85731 | 0.86141 (7) |
| kalshi:KXHIGHNY | sell_longshot | 0.02 | 3908 | complete | -47.5300 | -48.6300 | -1.1000 | 22 | 56 | 61.6800 | 44.1% | 0.85773 | 0.89114 (7) |
| kalshi:KXHIGHNY | sell_longshot | 0.05 | 3911 | complete | -49.7000 | -52.1800 | -2.4800 | 53 | 138 | 65.8200 | 47.0% | 0.77677 | 0.87486 (18) |
| kalshi:KXINX | buy_favourite | 0.01 | 3913 | complete | -57.9000 | -59.6100 | -1.7100 | 45 | 96 | 74.6200 | 53.3% | 0.83392 | 0.97325 (15) |
| kalshi:KXINX | buy_favourite | 0.02 | 3915 | complete | -54.6600 | -56.5300 | -1.8700 | 48 | 100 | 73.3900 | 52.4% | 0.81794 | 0.98572 (17) |
| kalshi:KXINX | buy_favourite | 0.05 | 3917 | complete | -55.5900 | -57.4600 | -1.8700 | 45 | 93 | 83.0800 | 59.3% | 0.82902 | 0.96747 (16) |
| kalshi:KXINX | sell_longshot | 0.01 | 3919 | complete | -57.9000 | -59.6100 | -1.7100 | 45 | 96 | 74.6200 | 53.3% | 0.83392 | 0.97325 (15) |
| kalshi:KXINX | sell_longshot | 0.02 | 3921 | complete | -54.6600 | -56.5300 | -1.8700 | 48 | 100 | 73.3900 | 52.4% | 0.81794 | 0.98572 (17) |
| kalshi:KXINX | sell_longshot | 0.05 | 3923 | complete | -55.5900 | -57.4600 | -1.8700 | 45 | 93 | 83.0800 | 59.3% | 0.82902 | 0.96747 (16) |
| polymarket_intl:pm-series:btc-up-or-down-daily | buy_favourite | 0.01 | 3925 | complete | -63.6909 | -64.7409 | -1.0500 | 18 | 47 | 82.1867 | 58.7% | 0.92755 | 0.92755 (18) |
| polymarket_intl:pm-series:btc-up-or-down-daily | buy_favourite | 0.02 | 3927 | complete | -56.9708 | -57.9408 | -0.9700 | 17 | 42 | 72.8008 | 52.0% | 0.91229 | 0.91229 (17) |
| polymarket_intl:pm-series:btc-up-or-down-daily | buy_favourite | 0.05 | 3929 | complete | -62.2418 | -63.3318 | -1.0900 | 20 | 49 | 79.2618 | 56.6% | 0.92845 | 0.92845 (20) |
| polymarket_intl:pm-series:btc-up-or-down-daily | sell_longshot | 0.01 | 3931 | complete | -65.6012 | -81.7412 | -16.1400 | 252 | 714 | 266.1593 | 190.1% | 0.64692 | 0.64526 (248) |
| polymarket_intl:pm-series:btc-up-or-down-daily | sell_longshot | 0.02 | 3933 | complete | 10.3602 | -6.3098 | -16.6700 | 260 | 721 | 252.8694 | 180.6% | 0.47654 | 0.47683 (255) |
| polymarket_intl:pm-series:btc-up-or-down-daily | sell_longshot | 0.05 | 3935 | complete | 121.7820 | 107.3620 | -14.4200 | 250 | 636 | 175.0665 | 125.0% | 0.21994 | 0.2207 (245) |
| polymarket_intl:pm-series:nyc-daily-weather | buy_favourite | 0.01 | 3937 | complete | -56.1991 | -56.9791 | -0.7800 | 42 | 84 | 56.5439 | 40.4% | 0.95912 | 0.99622 (15) |
| polymarket_intl:pm-series:nyc-daily-weather | buy_favourite | 0.02 | 3939 | complete | -52.3435 | -53.2335 | -0.8900 | 45 | 84 | 56.8062 | 40.6% | 0.93403 | 0.98683 (16) |
| polymarket_intl:pm-series:nyc-daily-weather | buy_favourite | 0.05 | 3957 | complete | -45.6603 | -46.6403 | -0.9800 | 45 | 79 | 58.4603 | 41.8% | 0.90903 | 0.96678 (18) |
| polymarket_intl:pm-series:nyc-daily-weather | sell_longshot | 0.01 | 3962 | complete | -29.9674 | -30.7674 | -0.8000 | 25 | 51 | 59.3669 | 42.4% | 0.82745 | 0.8499 (9) |
| polymarket_intl:pm-series:nyc-daily-weather | sell_longshot | 0.02 | 3965 | complete | -37.3555 | -38.1455 | -0.7900 | 23 | 47 | 62.4675 | 44.6% | 0.88029 | 0.92522 (9) |
| polymarket_intl:pm-series:nyc-daily-weather | sell_longshot | 0.05 | 3967 | complete | -50.4442 | -51.1342 | -0.6900 | 15 | 32 | 60.2742 | 43.1% | 0.94401 | 0.98028 (9) |

## Once-only selected finals

| Category | Trial | Net $ | Gross $ | Fees $ | Trades | Maker fills | Marked DD $ | DD / $140 | Trip p | Date p (n dates) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| kalshi:KXBTC | unconsumed | unconsumed_no_profitable_training_variant | — | — | — | — | — | — | — | — |
| kalshi:KXHIGHNY | unconsumed | unconsumed_no_profitable_training_variant | — | — | — | — | — | — | — | — |
| kalshi:KXINX | unconsumed | unconsumed_no_profitable_training_variant | — | — | — | — | — | — | — | — |
| polymarket_intl:pm-series:btc-up-or-down-daily | 3969 | 15.6383 | 9.7983 | -5.8400 | 111 | 268 | 83.2834 | 59.5% | 0.43536 | 0.43536 (111) |
| polymarket_intl:pm-series:nyc-daily-weather | unconsumed | unconsumed_no_profitable_training_variant | — | — | — | — | — | — | — | — |

## Regimes, dependence and risk events

The JSON includes month, quarter and fixed first-execution-price bands for **every variant**, with trade counts, gross/net P&L, fees and realized drawdown; zero-fill observed calendar months remain visible. Marked daily equity, monthly marked drawdowns, all simulated risk halts, rejection reasons, actual holds over seven days and maximum collateral are also retained. These are calendar buckets, not independently identified economic regimes. Marked drawdown uses observed public prints, not a continuous executable bid/ask series; quiet-period price moves can remain unobserved. First-entry bands use the price of the first execution, after the fixed quote offset.

The following quarterly matrix retains every variant. Cells show net dollars (completed trades). A zero after a permanent kill means no trading, not evidence of later regime stability.

| Category | Partition / trial | 2025-Q3 | 2025-Q4 | 2026-Q1 | 2026-Q2 | 2026-Q3 |
|---|---|---:|---:|---:|---:|---:|
| kalshi:KXBTC | buy_favourite 0.01 / 3808 | -49.4900 (118) | 0.0000 (0) | 0.0000 (0) | 0.0000 (0) | — |
| kalshi:KXBTC | buy_favourite 0.02 / 3810 | -58.3200 (99) | 0.0000 (0) | 0.0000 (0) | 0.0000 (0) | — |
| kalshi:KXBTC | buy_favourite 0.05 / 3812 | -55.2400 (82) | 0.0000 (0) | 0.0000 (0) | 0.0000 (0) | — |
| kalshi:KXBTC | sell_longshot 0.01 / 3815 | -49.4900 (118) | 0.0000 (0) | 0.0000 (0) | 0.0000 (0) | — |
| kalshi:KXBTC | sell_longshot 0.02 / 3817 | -58.8700 (99) | 0.0000 (0) | 0.0000 (0) | 0.0000 (0) | — |
| kalshi:KXBTC | sell_longshot 0.05 / 3819 | -43.0400 (65) | 0.0000 (0) | 0.0000 (0) | 0.0000 (0) | — |
| kalshi:KXHIGHNY | buy_favourite 0.01 / 3821 | -53.7800 (24) | 0.0000 (0) | 0.0000 (0) | 0.0000 (0) | — |
| kalshi:KXHIGHNY | buy_favourite 0.02 / 3823 | -48.5300 (22) | 0.0000 (0) | 0.0000 (0) | 0.0000 (0) | — |
| kalshi:KXHIGHNY | buy_favourite 0.05 / 3833 | -43.8100 (102) | -8.2800 (13) | 0.0000 (0) | 0.0000 (0) | — |
| kalshi:KXHIGHNY | sell_longshot 0.01 / 3888 | -48.6100 (24) | 0.0000 (0) | 0.0000 (0) | 0.0000 (0) | — |
| kalshi:KXHIGHNY | sell_longshot 0.02 / 3908 | -47.5300 (22) | 0.0000 (0) | 0.0000 (0) | 0.0000 (0) | — |
| kalshi:KXHIGHNY | sell_longshot 0.05 / 3911 | -49.7000 (53) | 0.0000 (0) | 0.0000 (0) | 0.0000 (0) | — |
| kalshi:KXINX | buy_favourite 0.01 / 3913 | -57.9000 (45) | 0.0000 (0) | 0.0000 (0) | 0.0000 (0) | — |
| kalshi:KXINX | buy_favourite 0.02 / 3915 | -54.6600 (48) | 0.0000 (0) | 0.0000 (0) | 0.0000 (0) | — |
| kalshi:KXINX | buy_favourite 0.05 / 3917 | -55.5900 (45) | 0.0000 (0) | 0.0000 (0) | 0.0000 (0) | — |
| kalshi:KXINX | sell_longshot 0.01 / 3919 | -57.9000 (45) | 0.0000 (0) | 0.0000 (0) | 0.0000 (0) | — |
| kalshi:KXINX | sell_longshot 0.02 / 3921 | -54.6600 (48) | 0.0000 (0) | 0.0000 (0) | 0.0000 (0) | — |
| kalshi:KXINX | sell_longshot 0.05 / 3923 | -55.5900 (45) | 0.0000 (0) | 0.0000 (0) | 0.0000 (0) | — |
| polymarket_intl:pm-series:btc-up-or-down-daily | buy_favourite 0.01 / 3925 | -63.6909 (18) | 0.0000 (0) | 0.0000 (0) | 0.0000 (0) | — |
| polymarket_intl:pm-series:btc-up-or-down-daily | buy_favourite 0.02 / 3927 | -56.9708 (17) | 0.0000 (0) | 0.0000 (0) | 0.0000 (0) | — |
| polymarket_intl:pm-series:btc-up-or-down-daily | buy_favourite 0.05 / 3929 | -62.2418 (20) | 0.0000 (0) | 0.0000 (0) | 0.0000 (0) | — |
| polymarket_intl:pm-series:btc-up-or-down-daily | sell_longshot 0.01 / 3931 | 38.8470 (27) | 100.0025 (88) | -55.2319 (87) | -149.2188 (50) | — |
| polymarket_intl:pm-series:btc-up-or-down-daily | sell_longshot 0.02 / 3933 | 38.6512 (26) | 155.9044 (87) | -8.5689 (87) | -175.6267 (60) | — |
| polymarket_intl:pm-series:btc-up-or-down-daily | sell_longshot 0.05 / 3935 | 37.6220 (24) | 178.5228 (85) | 14.0315 (85) | -108.3942 (56) | — |
| polymarket_intl:pm-series:nyc-daily-weather | buy_favourite 0.01 / 3937 | -56.1991 (42) | 0.0000 (0) | 0.0000 (0) | 0.0000 (0) | — |
| polymarket_intl:pm-series:nyc-daily-weather | buy_favourite 0.02 / 3939 | -52.3435 (45) | 0.0000 (0) | 0.0000 (0) | 0.0000 (0) | — |
| polymarket_intl:pm-series:nyc-daily-weather | buy_favourite 0.05 / 3957 | -45.6603 (45) | 0.0000 (0) | 0.0000 (0) | 0.0000 (0) | — |
| polymarket_intl:pm-series:nyc-daily-weather | sell_longshot 0.01 / 3962 | -29.9674 (25) | 0.0000 (0) | 0.0000 (0) | 0.0000 (0) | — |
| polymarket_intl:pm-series:nyc-daily-weather | sell_longshot 0.02 / 3965 | -37.3555 (23) | 0.0000 (0) | 0.0000 (0) | 0.0000 (0) | — |
| polymarket_intl:pm-series:nyc-daily-weather | sell_longshot 0.05 / 3967 | -50.4442 (15) | 0.0000 (0) | 0.0000 (0) | 0.0000 (0) | — |
| polymarket_intl:pm-series:btc-up-or-down-daily | final / 3969 | — | — | — | 47.6374 (26) | -31.9991 (85) |

The risk and effective sample counts below distinguish completed contracts from correlated events.

| Trial | Contracts | Events | Exit dates | Realized DD $ | Max collateral $ | Max hold days | Kill / daily halts | Rejected intents |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 3808 | 118 | 24 | 24 | 67.2100 | 131.7000 | 1.002 | 1 / 0 | 281,721 |
| 3810 | 99 | 21 | 21 | 65.4700 | 136.1000 | 1.001 | 1 / 0 | 281,810 |
| 3812 | 82 | 19 | 19 | 66.9000 | 138.6000 | 0.909 | 1 / 0 | 282,021 |
| 3815 | 118 | 24 | 24 | 67.2100 | 131.7000 | 1.002 | 1 / 0 | 280,654 |
| 3817 | 99 | 21 | 21 | 66.0200 | 136.1000 | 1.001 | 1 / 0 | 280,679 |
| 3819 | 65 | 15 | 15 | 68.4700 | 138.6000 | 0.909 | 1 / 0 | 281,535 |
| 3821 | 24 | 7 | 7 | 72.0500 | 138.5300 | 2.096 | 1 / 0 | 1,072,947 |
| 3823 | 22 | 7 | 7 | 62.6200 | 133.0400 | 2.096 | 1 / 0 | 1,072,907 |
| 3833 | 115 | 34 | 33 | 69.6700 | 122.4800 | 2.965 | 1 / 0 | 1,042,770 |
| 3888 | 24 | 7 | 7 | 70.9100 | 139.6300 | 2.096 | 1 / 0 | 1,083,020 |
| 3908 | 22 | 7 | 7 | 61.6200 | 133.0400 | 2.096 | 1 / 0 | 1,082,982 |
| 3911 | 53 | 18 | 18 | 72.4500 | 113.9100 | 2.096 | 1 / 0 | 1,072,608 |
| 3913 | 45 | 15 | 15 | 77.3100 | 135.7000 | 3.396 | 1 / 0 | 110,356 |
| 3915 | 48 | 17 | 17 | 70.8100 | 140.0000 | 3.362 | 1 / 0 | 110,330 |
| 3917 | 45 | 16 | 16 | 78.4700 | 139.0000 | 2.205 | 1 / 0 | 110,218 |
| 3919 | 45 | 15 | 15 | 77.3100 | 135.7000 | 3.396 | 1 / 0 | 109,622 |
| 3921 | 48 | 17 | 17 | 70.8100 | 140.0000 | 3.362 | 1 / 0 | 109,595 |
| 3923 | 45 | 16 | 16 | 78.4700 | 139.0000 | 2.205 | 1 / 0 | 109,482 |
| 3925 | 18 | 18 | 18 | 77.8509 | 30.2000 | 2.550 | 1 / 0 | 200,124 |
| 3927 | 17 | 17 | 17 | 67.4408 | 34.6000 | 1.264 | 1 / 0 | 200,188 |
| 3929 | 20 | 20 | 20 | 73.3018 | 27.6000 | 1.675 | 1 / 0 | 200,075 |
| 3931 | 252 | 252 | 248 | 259.4929 | 39.5000 | 3.857 | 1 / 0 | 4,054 |
| 3933 | 260 | 260 | 255 | 244.3902 | 43.7000 | 3.857 | 0 / 0 | 0 |
| 3935 | 250 | 250 | 245 | 168.1815 | 28.8144 | 3.797 | 0 / 0 | 0 |
| 3937 | 42 | 15 | 15 | 57.1091 | 131.7757 | 3.381 | 1 / 0 | 173,278 |
| 3939 | 45 | 16 | 16 | 55.7335 | 131.9693 | 3.218 | 1 / 0 | 173,195 |
| 3957 | 45 | 19 | 18 | 48.3303 | 124.0313 | 2.678 | 1 / 0 | 172,954 |
| 3962 | 25 | 10 | 9 | 48.3022 | 117.7588 | 3.130 | 1 / 0 | 153,282 |
| 3965 | 23 | 10 | 9 | 50.6588 | 120.1315 | 3.130 | 1 / 0 | 153,292 |
| 3967 | 15 | 9 | 9 | 57.0842 | 111.9000 | 2.428 | 1 / 0 | 153,326 |
| 3969 | 111 | 111 | 111 | 75.5029 | 23.3000 | 1.611 | 0 / 0 | 0 |

Per-trip p-values and UTC-exit-date aggregate p-values test positive mean net outcomes against zero. They are descriptive after selection from six variants. Buy-favourite and sell-longshot variants can express the same economic exposure on complementary binary prints; they are not independent replications. Sibling strikes, complement projections, shared BTC/weather events and serially correlated dates do not supply independent observations. A p-value is not the probability that a hypothesis is true. Undefined values with fewer than two observations are reported as such. No p-value threshold was added to the owner's profit criterion.

## Ledger and execution verification

The receipt audit checked 7,562 simulated entry/terminal fills and 2,240 completed round trips across 31 recorded attempts.
It matched each maker fill to its exact cached public print and source identity, checked later timestamps, through prices, volume caps, blackout deadlines, per-contract fill limits, fees and terminal payouts, and reconciled terminal cash and flat inventory with the ledger. Per-trip arithmetic, date/event counts and all monthly/quarterly gross/net/fee/trade totals also reconcile. Independently reconstructed filled collateral stays within the fixed limits; canceled pending orders are covered by the frozen runner checks and reported maximum, not reconstructed from fill receipts. Savepoint order/fill/position rows do not persist; hashed execution receipts survive with the durable trial and in the deterministic receipt archive. Archive members preserve the exact bytes whose hashes the audit checked; price tapes remain in the frozen local capture. Failed or zero-fill variants are never dropped. The six earlier KXCPI trials remain unchanged under their full-row hash.

## Promotion checklist and account-risk review

- Rule and behavioural-edge hypothesis: explicit favourite/longshot quoting, size/offset/fill cap and terminal exit; same reactor as paper/live.
- Profit, trade counts, drawdown and regimes: disclosed for every attempt above and in the JSON; category decisions explain failed gates.
- Paper/live fidelity: unproven. Historical queue priority, native PM US liquidity and fee transfer are not established.
- Risk constants: unchanged. Each trial used isolated virtual collateral; requested real allocation is $0.
- Decision: hold in research. No account, key, venue, capital, public-post or live-state change.

**What could blow up this account? — Tail and gap risk.** Binary terminal losses can hit several sibling strikes at once. The $25 contract collateral limit does not make event-level exposures independent, and a gap can overshoot the $50 daily halt or $56 strategy kill before orders can be canceled. The contract cap bounds funded entry exposure; it does not cap the aggregate loss across correlated contracts.

**Adverse selection.** Through-price makers may be selected by faster or better-informed flow; the scheduled blackout and three-fill cap reduce exposure but do not prove queue fills. The fixed BTC, temperature and index cohort excludes sports and discretionary insider-sensitive event intake. A settlement delay can violate the seven-day mandate and tie up collateral.

**Counterparty and venue.** Counterparty rules, rebates and product availability may differ materially from this historical scenario. Accepted Mac/network downtime and absence of dead-man/startup reconciliation remain unchanged: resting live orders could survive a failure. No withdrawal-capable keys are introduced.

**Untrusted inputs.** External payloads remain data, never instructions. No model decides entries or interprets source payloads as commands.

**Reproducibility.** Frozen source hashes and deterministic strategy code support reproducibility, while already-consumed finals are reviewed through stored receipts only. Retrospective catalog state lacks a complete point-in-time revision record, so even positive numerical results do not establish a deployable PM US edge. The [receipt audit](20-longshot-audit.py) and [report builder](20-longshot-build-report.py) are review tools and do not invoke a strategy or reopen an unconsumed final.

**Correlation.** Shared venue, event and direction exposures can coincide with other strategies and concentrate the global daily-loss risk. These five alternative studies do not model a concurrent funded portfolio or establish its combined risk.

Decision recorded 2026-10-01 by OrangeCove: hold in research, $0 real allocation, with the trial IDs and individual reasons preserved above and in the machine results.
