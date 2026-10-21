# Trading Bot: Product Requirements

*Decided through a grilling session on 2026-09-29. Every decision below was made by the owner (Will). Where Claude recommended something different, the recommendation is noted.*

## 1. Goal

Build a multi-strategy trading system that **proves real edges** with small live stakes, then grows capital and strategy count as edges are confirmed. The owner and Claude grow it together.

**Non-goals**
- HFT or speed races. The professionals win those.
- ~~AI or an LLM as the source of alpha.~~ *Removed 2026-10-01 by the owner. AI-decided strategies are allowed but must pass the forward-paper rule in §4, because historical backtests of LLM decisions are contaminated by training-data look-ahead. Prior evidence was negative: Alpha Arena, Prediction Arena, and Jev AUC 0.475.*
- Sports betting.

## 2. Constraints

| | |
|---|---|
| Capital | $1,000 of spare cash. About $140 per live strategy. Grows from profits and top-ups. |
| Jurisdiction | Individual retail investor; jurisdiction details omitted. Every account must pass KYC honestly. |
| Venues | **Now (2026-10-01): Alpaca** (US equities, ETFs including commodity ETFs, options, cash account), holding the whole $1k. **Pending verification** (the owner has contacted support): Kalshi and Polymarket US. Their public data is still used for research. **Futures:** a broker will be chosen by research and opened by the owner for research and paper only; it stays unfunded until a commodity edge passes and the owner tops up. Hyperliquid is excluded because it blocks US persons. |
| Data budget | **$0/month** (owner, 2026-10-01). Free sources only: Alpaca IEX and indicative options (from Feb 2024), Yahoo/Stooq daily bars, FRED, CFTC COT, EIA. |
| Time | 5–10 owner hours per week, plus a daily autonomous Claude session. |
| Host | Owner's Mac, kept running with a launchd watchdog and `caffeinate`. |

## 3. Edge philosophy

**Open-minded (owner, 2026-10-01).** Structural edges are preferred: market design, fee and reward programs, settlement mechanics, forced flows, and comparison against a deeper reference market. Also allowed are documented risk premia (trend, carry, momentum, value, low volatility), behavioural effects, and AI/LLM-decided strategies. Every kind must pass §4. Hard risk rules always have the final say. Options are researched now, but only structures a $1k cash account can hold are traded (long options, cash-secured puts on cheap underlyings).

## 4. Proof and promotion

- **Pipeline:** idea → backtest → paper → live. Any number of strategies may sit in backtest or paper. The number of live slots is limited by capital.
- **Proof method:** the backtest proves the edge, and live trading verifies it. A strategy must be profitable after fees on historical data before it gets money.
- **Locked holdout (owner, 2026-10-01):** the last 30% of each dataset, by time, is a holdout. Design and tuning use only the first 70%. A strategy passes only if it is profitable after fees in-sample **and** on a single holdout run per strategy version. The backtester enforces this, and a second holdout run is refused and logged as an incident.
- **AI-decided strategies (owner, 2026-10-01):** no historical backtest counts (training-data look-ahead). The strategy must be profitable after costs on forward paper trading for **at least 7 calendar days and at least 30 trades**, whichever comes later. Live trading then checks that fills, fees and slippage match the backtest.
- **Success criterion (owner's choice):** profit after all fees. *Claude recommended adding luck filters.* The dashboard must show each strategy's trade count and the probability that its result is luck (p-value against zero edge), so noise is visible.
- **Owner override (2026-10-14):** IBS QQQ v1, which passed its holdout, goes live on its $140 slot without a paper stage ("I want to start trading on real money now"). §6 limits are unchanged. Other strategies still follow the pipeline.
- **Trials ledger:** every strategy variant and parameter set tried is recorded, including failures.
- Promotion and demotion happen at the weekly review or in the daily autonomous session.

## 5. Strategies: first batch

| # | Strategy | Venue | Mode | Key rules |
|---|---|---|---|---|
| 1 | Favourite–longshot bias | Kalshi (+PM US) | Live | Rest maker orders on the side the backtest picks for each category (all categories are eligible). Hold to settlement. Only markets that resolve within 7 days. |
| 2 | Liquidity rewards farming | Kalshi + PM US from day one | Live | Two-sided quotes near the reference price. Cap net inventory at $15 per market, then quote only the side that reduces it. Rank markets daily by reward pool ÷ competing depth. |
| 3 | S&P/Nasdaq ranges vs SPX options | Kalshi, with Alpaca options data | Live | Trade when the Kalshi price minus the options-implied probability exceeds the fee plus 3¢. Trade only 2:00–3:30pm ET. Hold to settlement. |
| 4 | Weather: high already recorded | Kalshi | Live | Use NOAA METAR data from the settlement station. Trade only after the historical time by which the day's high is already set, and only when the recorded high is more than 1°F from any range boundary. Buy the range the high has already landed in while it is priced below about 97¢. |
| 5 | End-of-day leveraged-ETF rebalance | Alpaca (SPY/QQQ) | Live | Enter at 3:30pm ET in the direction of the day's large move and exit at the close. Backtest on 2023–2026 only. Because the account is cash with T+1 settlement, split the slice into two halves that trade on alternate days. |
| 6 | Turn of the month | Alpaca (SPY) | Live | Buy at the close of the 4th-to-last trading day. Sell at the close of the 3rd trading day of the next month. |
| 7 | Promotions + Kalshi interest | — | Manual | Claim the guaranteed bonuses. Keep at least $250 on Kalshi to earn 3.75% APY. |
| 8 | X mention-spike event study | Alpaca | Paper | Event = a ticker receives more than 5× its 30-day average mentions. Measure abnormal returns vs SPY on days 1–5. Record data going forward using the owner's X API, budget ≤$50/month. No money goes in until an unseen data period confirms the effect. |

**Adverse-selection guards (strategies 1–2):**
- Pull quotes before scheduled events.
- Skip markets exposed to insider information (company or government announcements).
- Cap the number of fills per market per time window.


**Kalshi status (2026-09-29, owner decision):** the owner could not set up a Kalshi account, so Kalshi is blocked for trading for now.
- Kalshi public historical data is still downloaded and used as research evidence (longshot bias etc.).
- **Polymarket US is the first live prediction-market venue.** Strategies #1 and #2 run there first.
- #3 (SPX ranges) and #4 (weather) are deferred until a Kalshi account exists.
- Backtests may use both Polymarket US and international Polymarket history. Trading is on **Polymarket US only**.
- The Kalshi interest part of #7 is on hold.

**Dead or not provable in 60 days (do not build):** overnight drift, pre-FOMC drift, S&P inclusion, large-cap PEAD, BTC funding carry, MEV and CEX–DEX arbitrage, sum-to-100% arbitrage, short-vol and VIX ETPs, micro-futures carry at this capital size.

**Items to check during the build:**
- Alpaca options data quality: indicative vs OPRA quotes and how far history goes back.
- Whether X API pricing fits $50/month for about 500 tickers.
- Whether Alpaca has adopted the removal of the PDT rule.
- The exact Weather Company settlement values vs METAR.

## 6. Risk limits (hard-coded, never delegated to a model)

| Limit | Value |
|---|---|
| Per-strategy kill | Stop permanently at −40% of its allocation |
| Global daily halt | Halt everything at −$50 in one day |
| Per-market position | **Prediction markets: $25 maximum.** **Equities, ETFs, options, futures: up to the strategy's allocation (its slot, about $140).** *Changed by the owner on 2026-10-01.* |
| Stale data | Halt if data is more than 30 seconds old |
| API errors | Halt at 5 errors per minute |

API keys must allow trading only, never withdrawals.

## 7. Architecture

- **Language:** Python with the official SDKs (`kalshi-python`, Polymarket `py-sdk`, `alpaca-py`).
- **Storage:** Postgres + TimescaleDB (owner's choice; *Claude recommended SQLite with Parquet and DuckDB*). Back up nightly with `pg_dump`.
- **Core modules:**
  - Venue adapters, behind a common interface.
  - Market data recorder.
  - Fee models that match each venue's published schedule exactly.
  - Strategy interface: one file per strategy, and the same code runs in backtest, paper and live.
  - Risk engine, which has absolute veto power.
  - Ledger, the single source of truth.
  - Backtester.
  - Paper engine, which counts a maker order as filled only when later trades go *through* the order's price.
  - Reconciliation and reporting.
- **Dashboard:** local only, read-only, served on localhost. Shows the leaderboard (P&L after fees, trade count, luck odds), backtest vs live gap, kill-switch and incident log, and pipeline status.
- **Secrets:** a gitignored `.env` file.

### Build order
1. Shared foundation: Kalshi data downloader, fee models, Postgres schema, ledger, risk engine.
2. Backtester, running every strategy on historical data.
3. Paper engine (same strategy code, live data).
4. Live connectors (Kalshi, PM US, Alpaca) and the dashboard.
5. The owner claims promotions manually in week 1.

## 8. Collaboration model

- **Claude may act without asking:** research, backtests, new strategy ideas, code changes, tweaks to live parameters within the risk limits, and promoting strategies to live when they meet §4.
- **Needs owner approval:** changes to risk limits, adding capital, new venues or accounts or keys, and any public post (including X).
- **Cadence:** a daily autonomous Claude session (scheduled) and a weekly review with the owner. The weekly page is published on Fridays after the US close, as a password-protected (StatiCrypt) Cloudflare Pages site. Claude reports only on incidents in between.
- Every change is logged in `CHANGELOG.md`.

## 9. Accepted risks (owner decisions, do not "fix" without asking)

- **No dead-man protection.** No short-expiry orders and no reconciliation on startup. If the Mac or the bot dies, resting orders stay live with nothing managing them. The $25 per-market cap bounds the loss.
- **Runs whatever is checked out.** There is no gate on tagged releases or tests before a live restart.
- **No technical guardrails on risk limits.** Protection relies on process and on Claude never editing the limits without approval.
- **Live P&L success criterion without luck filters.** The luck odds are shown for information only. The locked holdout (§4) is part of the backtest itself, not a luck filter.
- **Wide strategy funnel (2026-10-01).** The approach is open-minded, as many strategies as possible are researched in parallel, and agents promote without a gate (the owner reads the weekly page). Some promotions will be luck, and the −40% per-strategy kill bounds each one.
- **Live keys come last.** The owner funds Alpaca live and adds live keys once implementation is complete. Until then, strategies that pass queue as `ready-for-live`.
- **Mac hosting.** Sleep, network loss and power cuts will cause downtime.

## 10. Tax and records

The owner is a retail investor. The UK tax treatment of Kalshi and PM US gains is unclear (gambling vs CGT vs income). The ledger records every trade with timestamp, venue, price, size, fees and the USD/GBP rate, so an accountant can decide. Take professional advice before scaling.
