# Alpaca #6 forward paper

`turn_of_month` uses the existing `AlpacaPaperAPI` (hard-coded paper transport),
`AlpacaPaperConnector`, `Ledger`, `RiskEngine`, and unchanged pure `TurnOfMonth`
reactor. The primary rule buys SPY in the last minute on the fourth-last exchange
session and sells owned shares in the last minute of the third session of the
next month. $24.90 entry, $140 **simulated** allocation; no broker funding/reset.

Complete the promotion record in `docs/research/08-turn-of-month-paper.md` first.
Prepare an explicit future calendar and a new ledger trial:

```sh
uv run python -m tradingbot.forward.turn_of_month prepare --through 2027-10-08
mkdir -p data/forward
# Write the returned numeric trial ID, with a newline, to:
# data/forward/turn_of_month.trial
uv run python -m tradingbot.forward.turn_of_month run --trial-id TRIAL --once
```

`prepare` is not idempotent creation: an existing running trial must be resumed
explicitly, never replaced. Failed preparation attempts are retained as failed
paper trials. It loads prior-day ECB USD/GBP reference rates. Only existing
`.env` Alpaca paper credentials are read. Never print the SDK exception body.

The launchd plist in `ops/launchd/com.tradingbot.alpaca-tom-paper.plist` runs
`ops/alpaca_tom_paper.sh`. A ten-second loop checks the stored New York calendar,
so host timezone, DST and early closes do not change the rule. The exchange's
current session must still match. The loop refreshes only this trial's durable
active order IDs and marks owned positions during regular hours. A dedicated
Postgres advisory lock prevents duplicate daemon instances across commits.

An attempt is committed before submission; the connector also commits its
reservation before POST. A restart cannot repeat a calendar-day attempt, even
if it crashed before the POST. Unknown POST outcomes remain reserved and are
polled, never resubmitted. A missed buy is skipped, a flat exit sends nothing,
and an exit with residual shares is an incident. There is no off-schedule
liquidation or retry of the same day's rejected/partially filled order. DAY
orders and the existing connector handle expiry/fill races. Stopping the
process does not cancel orders; there is no account-wide startup reconciliation.

The calendar covers a finite reviewed experiment; after its last exit, no new
entry is scheduled. Review results and explicitly prepare a later experiment
after completing the current flat trial. A residual position must be resolved
explicitly. No automatic live promotion exists.

Ledger fills contain actual paper activities and the broker's zero reported
fees. `Trial.metrics.alpaca_tom_forward_v1` separately records the fixed
September 2026 fee scenario, fee-adjusted marked equity, observed drawdown,
daily equity, decision bid/ask/timestamps and durable request IDs. This avoids
presenting omitted paper regulatory charges as evidence of costless trading.
It is a fixed comparison scenario, not a forecast of future fee schedules.
Compare achieved fractional fills and slippage against trials 849–852; 853 is
a failed dividend-control trial and supplies no profit claim.

Prepared trial 2344 passed an outside-hours one-shot check without orders. The
shared overnight daily-P&L defect `tradingbot-1oh` has been repaired and verified.
The job remains unloaded under the owner's subsequent 2026-10-01 instruction:
`tradingbot-gat` must re-run #6 under the locked holdout and new equity allocation
before continuing paper. Historical 849–853 are legacy evidence, not a passed
locked holdout. Keep 2344's $24.90 parameters intact as the prepared execution
experiment; record any new sizing/version as a separate ledger trial.
