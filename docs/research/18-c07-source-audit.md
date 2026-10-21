# C07 weekly sector reversal: source gate failed

**DATA_FAIL before rankings or returns.** `tradingbot-a9d` stops under the
[preregistered failure rule](07-candidate-shortlist.md). All three variants,
six planned training cases and the final holdout remain unattempted. This is
a data-admission result; the reversal hypothesis has not been tested.

The [machine-readable receipt](18-c07-source-audit.json) binds the unchanged
XLB/XLE/XLF/XLI/XLK/XLP/XLU/XLV/XLY captures to the SPY reference amendment,
calendar evidence, XLF action receipt, policy and audit code hashes. Each sector
has **5,218 sessions**, with no missing, extra, duplicated, null or invalid
sessions in this source-integrity check. That coverage does not validate its
corporate-action treatment or executable prices.

The interval remains **2006-01-01 00:00 UTC to 2026-10-01 00:00 UTC**, end
exclusive. The `HoldoutSplit` boundary is still **2020-07-10 14:24 UTC**.
No later start, ticker substitution, deleted corporate-action date or shortened
window is used. All original C02 source files and failed trial 3491 are retained.

## Admission decision

The [XLF evidence audit](17-xlf-action-amendment.md) remains an explicit
unresolved-data failure. Its closed bead does not admit XLF. C07 verifies the
frozen receipt and underlying primary bytes rather than relying on task status.
The missing account-level fractional allocation, cash-in-lieu and delivery
availability evidence prevents a faithful XLF/XLRE ledger replay. Validated
XLRE disposal prices are also absent. Neither Yahoo's approximate split nor
Alpaca's mislabeled cash-dividend field fills these gaps.

The [SPY open/close amendment](13-equity-data-repair-spy-amendment.md) and
reconciled T+1 counterfactual settlement schedule are now available. Those
earlier shared prerequisites are not repeated as current failures. They do not
resolve the XLF action or admit the other eight sectors. Full nine-sector
issuer payment reconciliation, independent price comparison and actual-share
conversion remain incomplete after this failed gate.

SPY is the reference only. XLRE never becomes a tenth ranked asset. The fixed
rules remain 5-session/top-three, 10-session/top-three, then 5-session/top-one;
negative residuals only, alphabetical ties, 95% aggregate target and the
original $140 simulated allocation. The next-week entry, subsequent-week
mandatory exit and original exit for delayed entries are unchanged. No VIX
filter or alternative holding period was tried.

## Evidence and measurement status

| Item | Result |
|---|---|
| Source coverage and hashes | Nine original sector captures verified; SPY amendment verified. |
| Training selection | None; 0 of 6 planned cases attempted. |
| Final holdout | No admission or replay. |
| Net/gross P&L, fees, turnover and trades | Unmeasured, not zero-profit results. |
| Maximum drawdown and regime breakdown | Unmeasured; no marked-equity replay. |
| Luck p-value | Null; no weekly outcome sample exists. |
| Benchmarks | Not computed. |
| Promotion | None; strategy remains at idea with no allocation or activation. |

Existing SPY outcome inspection by #5/#6/C01/C06 remains disclosed. Reusing a
source or applying an amendment cannot make inspected history unseen or restore
consumed finals. A future eligible C07 run still needs its own frozen strategy,
shared risk/ledger execution and durable final-admission check.

## What could blow up this account?

**Tail and gap risk:** a losing sector can continue falling or gap down before
the scheduled weekly exit. Three sector positions can fall together; the
single-name variant concentrates the whole target. The unchanged equity slot
cap and 95% target constrain exposure, while the −40% strategy kill and −$50
daily halt cannot guarantee execution through gaps. No new capital is allocated.

**Adverse selection:** weak sector prices may reflect lasting information rather
than temporary selling pressure. Reference-open costs may understate stressed
spreads; settlement delays may miss a reversal. This is a long ETF rule, not a
prediction-market quoting rule. Future execution must satisfy the existing
risk and fresh-data checks; no profit claim follows from this audit.

**Venue and operations:** a future run would depend on Alpaca and the existing
ledger. Source errors can corrupt quantities and cash, which is why admission
stops here. The owner's accepted lack of dead-man protection and startup
reconciliation remains unchanged. No key, account, order or restart is created.

**Untrusted inputs:** vendor and issuer content is evidence only. Hash and
field checks reject changed or contradictory records; no feed text is executed
as instructions and no model chooses trades in this candidate.

**Reproducibility:** the audit is offline and uses exact immutable captures.
Ledger recording is idempotent and cannot turn this failure into a performance
trial or consume a final. The strategy implementation is intentionally left
unattempted after the required source stop.

**Correlation:** sector losses can coincide with other equity strategies and
concentrate the account's daily drawdown. Weekly, dependence-aware inference
would be required; simultaneous legs would not count as independent trials.
Neither realized correlation nor drawdown has been measured here.

## Reproduction and decision record

Run `uv run python -m tradingbot.research.c07_source_audit` for the offline source
check. After committing the audit, `--record-ledger` records or returns the
same failed data-quality trial for that immutable identity. Eight focused tests
pass, including fixed bounds, hash tampering, rejection of a changed XLF
admission receipt, invalid trial labeling and rollback-contained database
idempotency without holdout consumption.

Decision: **hold at idea; no promotion**, October 1, 2026, NavyLantern. Failed
data-audit **trial 3548**, strategy **6080**, records audit commit `bc4758f`.
Repeated recording returns the same trial; the strategy has no allocation and
no final attempt. P&L, drawdown, regimes and inference cannot satisfy promotion
while the source gate fails.
All PRD §6 limits and accepted §9 risks remain unchanged.
