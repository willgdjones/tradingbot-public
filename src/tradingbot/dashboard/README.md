# `tradingbot.dashboard` — local read-only dashboard (PRD §7)

A localhost, read-only view of the ledger and risk state. No web framework, no
new dependencies (stdlib `http.server`), binds to `127.0.0.1`, serves only `GET`
(writes return 405), and never commits to the database.

```bash
uv run python -m tradingbot.dashboard            # http://127.0.0.1:8787
DASHBOARD_PORT=9000 uv run python -m tradingbot.dashboard
```

## What it shows
- **Leaderboard** (per strategy, per mode): P&L after fees, trade count, and luck
  p-value against zero mean (PRD §4), realized drawdown and net execution hit
  rate. Sorted by existing P&L; no statistical score changes ordering or promotion.
- **Trial statistics / final holdouts:** Sharpe, recorded drawdown, hit rate and
  OOS t, with measurement basis and sample counts. Every final remains visible,
  including failed trials/audits and diagnostic research that is held for fidelity.
- **Backtest vs live gap** — does live match the backtest? (PRD §4 proof method.)
- **Kill-switch / risk** — active halts from `risk_halts`, with a banner when any
  halt is live.
- **Incident log** — recent `incidents`, newest first.
- **Pipeline status** — strategy counts by status and trial counts by mode/status.

Switch mode with `?mode=backtest|paper|live` (default `live`).

## Layout
| File | Purpose |
|---|---|
| `reports.py` | Pure read queries → dicts (`dashboard_snapshot`, `leaderboard`, …) |
| `render.py` | Pure snapshot-dict → HTML (dark-mode aware, auto-refresh, HTML-escaped) |
| `server.py` | Stdlib `ThreadingHTTPServer` on localhost; `/`, `/api/snapshot`, `/healthz` |

`reports.py` uses the ledger's same execution P&L, fee, round-trip and luck
functions in batched read queries, so the numbers match the ledger without a
query for every strategy. Everything is read-only.

## Informational statistics (`tradingbot-ss4`)

The shared `ledger/report_stats.py` reads existing fills and trial receipts. It
never writes metrics, changes a trial, replays a final or supplies a promotion
gate. PRD §4 still determines promotion. “Basis & samples” explains each row.

- Live/paper leaderboard drawdown is the peak-to-trough decline of **realized
  execution-ledger P&L**, including fees on still-open entries, from the start
  of the displayed scope. Same-time cash flows are combined. It excludes open
  position marks and model-only income/fees; it is not a marked-risk drawdown.
- Hit rate is positive **net execution** round trips divided by all completed
  round trips, including breakeven trades. Partial exits do not create extra
  successes, open cycles are excluded, and instrument multipliers apply. Nontrade
  income is not allocated to execution hit rate. A runner's recorded win rate is
  used only when the trial has no reconstructable round trips, and is labelled.
- Sharpe requires recorded periodic marked equity, including that producer's
  fees/income. C05 Amendment21 and C04 readmission-v2 support daily close returns
  `E[t]/E[t-1] - 1`; the first recorded close is the baseline. C08 Amendment21
  supports complete interior calendar months, reconstructed from its recorded
  monthly marked P&L and initial slot, reconciled to ending equity. Partial
  boundary months affect equity but are excluded as samples. Unsupported receipts
  stay unmeasured. An existing scalar Sharpe retains its unknown producer basis.
- Sharpe is `mean(return) / sample_stdev(return) × sqrt(252 or 12)`, against an
  explicit **0% cash benchmark**. This is a descriptive annualization convention,
  not a measured Treasury excess return or a dependence correction. The sample
  t-statistic is `mean / (sample_stdev / sqrt(n))`; it appears only for complete
  recorded final holdouts whose entire series is inside the held-out interval.
  Legacy `equity-research-v1` trials without a marked series may instead show t
  over net execution round trips, explicitly labelled in USD: all fills must be
  in the final interval, inventory must be flat, counts must match, and trip P&L
  must reconcile to execution cash flows and the recorded total within one
  database rounding unit per fill. This does not supply a Sharpe return series.
  Serial dependence is not adjusted, and prior inspection/audit holds still apply.
- Empty/one-observation samples, zero variance and malformed/nonfinite series do
  not produce a finite Sharpe/t. Missing data stays null/“—”, distinct from zero.
  No periodic series is synthesized from execution P&L, nor is t inferred from
  a stored p-value. Separate backtest variants are never pooled for these metrics.

Formulas follow [William Sharpe, *The Sharpe Ratio* (1994)](https://stanford.edu/~wfsharpe/art/sr/sr.htm).
Trial drawdown remains the recorded value and basis; no historical result is
overwritten by the realized-ledger statistic. Backtest strategy totals are legacy
rollups across potentially separate experiments; use the individual trial tables
for these statistics. The weekly page uses the same functions with its stated
seven-day scope for paper/live execution statistics.
