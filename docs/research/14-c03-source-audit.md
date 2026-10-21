# C03 cross-asset momentum: data failure before replay

**DATA_FAIL.** The fixed SPY/IEF/GLD/EFA/VNQ candidate stops at its preregistered
data gate. No ranking, strategy return, training variant or final holdout was
calculated. Profitability, fees, trades, marked drawdown, regimes and luck p-value
remain **unmeasured**, not zero. No promotion or live order occurred.

The [audit receipt](14-c03-source-audit.json) binds five exact Yahoo responses,
request URLs, UTC retrieval times, SHA-256 hashes, issuer workbook, official
session archive, committed shared repair receipts and adjustment policy.
Raw responses remain under `data/research/c03/`; resume verifies their integrity.

Durable failed source-audit trial **3516** belongs to strategy **6030** and
committed audit code `08768a5`. A database readback confirms one failed trial,
null performance fields, zero orders/fills and zero final-holdout attempts.
The strategy remains `idea` with zero allocation.

| ETF | Daily sessions | Vendor dividend events | Vendor split events |
|---|---:|---:|---:|
| SPY | 5,218 | 83 | 0 |
| IEF | 5,218 | 248 | 0 |
| GLD | 5,218 | 0 | 0 |
| EFA | 5,218 | 40 | 0 |
| VNQ | 5,218 | 83 | 0 |

Each series matches the regular-session calendar from 2006-01-03 through
2026-09-30, without missing/extra/null/invalid rows, duplicate dates or orphaned
actions. These establish coverage and internal consistency, not executable
prices or reconciled corporate actions. Vendor dividend fields are only
`amount` and `date`; they do not establish spendable cash dates.

The fixed interval remains **2006-01-01 00:00 UTC to 2026-10-01 00:00 UTC**,
end exclusive; `HoldoutSplit` gives **2020-07-10 14:24 UTC**. Session coverage
uses actual closing timestamps, so that day's later close is outside training.

## Failed prerequisite and updated evidence

The checksum-verified primary SPY workbook still has ex-date **2006-06-16**,
record date **2006-06-20**, payable date **2006-06-16**, amount **$0.555470**.
The strict issuer reader rejects payment before record date.

[Shared repair 900](13-equity-data-repair.md) supports a **scheduled July 31
payment** from the contemporaneous [SPY prospectus](https://www.sec.gov/Archives/edgar/data/884394/000095013606000650/file001.htm)
and explains disputed closing-price bases. The proposed corrections still need
a frozen, validated source/action policy, including the December 2021 dividend
amount discrepancy. C03 does not silently overwrite the workbook or use the old
payment-date proxy.

The [2006–2026 settlement schedule](13-equity-data-repair-calendar.json) is now
reconciled against independent primary notices. C03 does not repeat the earlier
missing-calendar conclusion. Scheduled settlement, completion rollovers and
broker credit remain distinct. The proposed next-open-after-completion cash
convention is not yet an admitted strategy source/cash amendment. XLF's separate
action problem is not asserted as a failure in C03's different universe.

After this failed common gate, the attempt stops. Full issuer payment-date
reconciliation for IEF/EFA/VNQ, GLD action validation, five-fund independent
same-basis price checks and execution conversions remain explicitly incomplete.

## Decision and account risks

The [original specification](07-candidate-shortlist.md) remains unchanged:
mean 1/3/6/9/12-month total-return ranking, alphabetical ties, monthly decisions,
and ordered variants top one at 95%, top two at 47.5% each, and top two with
each half in cash unless its ETF exceeds its 10-month SMA. A failed filter does
not promote rank three. Both 5/10 bp training cases remain unattempted. The
$140 simulated allocation, fees, cash rules, §6 limits and single final remain
intact. One failed source-audit trial records the stop, with null performance;
the strategy stays at idea status. Identical audit repeats are idempotent.

**What could blow up the account?** Winner concentration, duration shocks,
simultaneous stock/bond/REIT losses, monthly exit delays, gaps and incorrect cash
availability can cause losses or rejected replacements. GLD is not a diversified
commodity basket. C02/C03 share selection risk and C01/C03/C05 share trend risk.
These are predeclared failure mechanisms, not measured C03 outcomes.

SPY overlaps previously inspected #5/#6/C01 history. Issuer pages also contain
published fund performance incidentally visible during source discovery; it was
not used to rank ETFs or select a variant. No pristine unseen-evidence claim is
made. Resolve shared repair and finish the remaining candidate checks before a
new documented audit attempt. Preserve this failure and the untouched final;
no paper/live transition is justified.

## Reproduce

```sh
uv run python -m tradingbot.research.c03_source_audit --capture
uv run pytest tests/research/test_c03_source_audit.py -q
# Commit the audit code before recording its durable failure:
uv run python -m tradingbot.research.c03_source_audit --record-ledger
```

Seven checks pass: integrity/bounds, bad coverage, invalid prices, symbol/date
identity, orphaned actions, exact cutoff, and failed-trial idempotence with no
holdout consumption. Shared receipts must match committed files. This module
has no strategy replay or final-holdout admission path.
