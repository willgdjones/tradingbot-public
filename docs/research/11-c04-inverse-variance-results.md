# C04 result: stopped at data audit

**DATA_FAIL; no performance result, no holdout consumed, no promotion.**
The candidate's preregistration says to record and stop on a data failure.
The machine-readable [audit record](11-c04-inverse-variance-results.json)
binds source hashes, the unchanged split and the failed ledger trial.

| Check | Evidence | Decision |
|---|---|---|
| Primary daily coverage | 5,218 Yahoo bars exactly match official sessions; no splits or missing sessions | Passed |
| Distribution dates | 83 Yahoo/issuer ex-dates match | Passed |
| Actual dividend cash availability | Issuer SPY row: ex-date 2006-06-16, record 2006-06-20, **pay 2006-06-16** | Failed: payment precedes record date |
| Independent closing-price basis | Yahoo 548.619995 vs IEX 542.955 on 2025-04-09 (1.0434%); existing SIP 548.62 agrees with Yahoo, but has separate March 2020 discrepancies up to 2.7934% | Basis remains unresolved |
| T+1 counterfactual | Official native calendar gives 2006-01-03 → 2006-01-06 (T+3) | Required historical T+1 calendar not established |

Public secondary dividend tables suggest 2006-07-31 for the disputed payment.
That is a lead for a source correction, not an applied overwrite of the archived
issuer evidence. No issuer correction or contemporaneous primary record was
established during this bounded audit. The current [issuer definitions](https://www.ssga.com/us/en/intermediary/resources/documents/etf-dividend-distributions)
make the record/pay inconsistency explicit. Neither a fixed 30-day lag nor an
ex-date cash credit is a valid substitute.

The raw data is useful for a later properly documented repair, but the current
bundle is inadmissible for this preregistered replay. The $140 budget, time
bounds and risk limits were not changed. No strategy implementation or return
analysis was needed after the data gate failed. All six contemplated training
cases and the once-only holdout remain unattempted; profitability, fees, marked
drawdown, regimes and luck statistics are **not available**, not zero.

Blow-up assessment remains the preregistered one: variance can be low before a
crash and high before a rebound, causing maximum exposure before loss and
de-risking before recovery. Shared SPY exposure also overlaps C01/C06. These
are hypotheses and portfolio risks, not measured C04 results. A future study
must use the common strategy/risk/ledger path, resolve actual cash availability,
and finish the promotion checklist before any paper/live transition.
