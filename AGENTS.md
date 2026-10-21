# AGENTS.md: start here

This repo holds a multi-strategy trading bot that the owner (Will) and AI agents build together. The project is in the **planning-complete, pre-code** stage. It was created on 2026-09-29 and moved to a new laptop to continue under ntm (multi-agent tmux sessions).

## Read first, in order
1. `PRD.md`: every decision, made by the owner during a grilling session. Treat it as binding.
2. `docs/research/`: the evidence the plan rests on (market landscape, academic and hedge-fund work, structural edges).
3. `CHANGELOG.md`: log every meaningful change under today's date.

## Hard rules for every agent
- **Structural edges only.** No sports betting, no LLM as the source of alpha, no HFT.
- **Never change the risk limits** (PRD §6) without explicit approval from the owner.
- **Owner approval is needed for:** adding capital, new venues, accounts or API keys, and **any public post, including on X**.
- Agents may act without asking on: research, backtests, code, live parameter tweaks within the limits, and promotion to live under PRD §4.
- **Before any promotion** (idea → backtest → paper → live), complete `docs/promotion-checklist.md`, including the written "What could blow up this account?" section (PRD §4). Backtest results must report max drawdown and a per-regime breakdown, not just P&L.
- **Accepted risks** (PRD §9) are deliberate owner choices. Do not "fix" them without asking.
- Secrets live only in a gitignored `.env` file. Never commit keys. Keys allow trading only, never withdrawals.
- Every strategy variant goes in the trials ledger, including failures.
- Report to the owner only on incidents. Everything else waits for the weekly review.

## Build order (PRD §7)
1. **Foundation:** Postgres + TimescaleDB schema, ledger, exact fee models (Kalshi and Polymarket US), risk engine, Kalshi historical data downloader.
2. **Backtester:** one strategy interface, where the same code runs in backtest, paper and live.
3. **Paper engine:** a maker order counts as filled only when later trades go *through* its price.
4. **Live connectors** (Kalshi, Polymarket US, Alpaca) and a local read-only dashboard.

## Current priorities (owner, 2026-10-01)
- **Prediction markets are deferred** while the owner gets verified by Kalshi and Polymarket US support (beads labelled `blocked:venue-verification`). The public-data capture and the #1 re-run still finish as research.
- **Alpaca first:** equities, ETFs (including commodity ETFs) and options research. The whole $1k is on Alpaca, in a cash account.
- **Open-minded edges:** structural edges, risk premia, behavioural effects and AI-decided strategies are all allowed (PRD §3). Research as many strategies in parallel as possible.
- **Free data only ($0/month):** Alpaca IEX and indicative options (from Feb 2024), Yahoo/Stooq, FRED, CFTC COT, EIA.
- **Locked holdout:** tune only on the first 70% of the data. The last 30% is run **once** per strategy version (PRD §4). AI-decided strategies must pass a forward paper run of 7+ days and 30+ trades instead.
- **Position cap:** $25 for prediction markets; up to the strategy's slot for equities, ETFs, options and futures (PRD §6, owner-approved).
- **Jev (TypeSafe) is available** (key in `.env`). Call it ONLY through `src/tradingbot/ai/jev.py`, which enforces the owner's $20/month cap and logs every decision for calibration.
- **Jev suite J1–J4** (owner, 2026-10-02): four intraday Jev strategies on real Alpaca paper (J1 gate, J2 menu trader, J3 news reactor, J4 regime switcher).
  - Decide every 15 min, at most 1 entry per symbol per day, settled cash only, flat by the close.
  - Universe: 40 liquid ETFs and mega-caps. Model `jev-latest` pinned. Fail closed.
  - Judged on P&L after costs. Random twins (and an ungated twin for J1) run virtually, for information only.
  - Ready-for-live after 7+ days, 30+ trades and P&L > 0, re-judged weekly.
  - Beads: `yma` data, `96t` events, `8hs` state, `tg6` runner, `1tc`/`pxk`/`369`/`32i` strategies, `2xm` weekly section.
- **Execution-code freeze, 2026-10-08 to 2026-10-15 (coordinator).** Each edit to shared paper-execution code rolls every frozen cohort and restarts its 7-day/30-trade clock, and that happened repeatedly in week 1.
  - Frozen paths: `src/tradingbot/forward/`, `src/tradingbot/connectors/alpaca_paper.py`, `src/tradingbot/ai/`, `src/tradingbot/risk/`.
  - Allowed: only fixes for an incident that stops a cohort from trading or corrupts the ledger. Log each one in INCIDENTS.md first, and say which cohorts it rolls.
  - Cosmetic, refactor and nice-to-have changes wait until after Oct 15. Research, backtests and new strategy files outside these paths are unaffected.
- **No live keys yet.** Strategies that pass queue as `ready-for-live`. Never ask for or create keys; the owner adds them.

## Research data standard (coordinator, 2026-10-01)
Too many candidates stopped at DATA_FAIL before any edge was measured, so these rules now apply:
- **Historical research backtests** of daily equity/ETF strategies use **split- and dividend-adjusted daily total-return series** from free sources (Yahoo/Stooq/Alpaca adjusted).
  - Cross-check two sources. Accept the series if daily returns agree within 5 bp on at least 99% of days, and log the disagreeing days.
  - Exact fractional-share and corporate-action ledger mechanics are **not** a precondition for a research backtest. Model them as a total-return equivalent.
- **Paper and live** use the broker's actual fills and corporate-action records. That's where exact mechanics belong.
- **DATA_FAIL** means missing or contradictory *prices* only, never "an unmodelled ledger mechanic".
- The corporate-action blackout (amendment 21) is **optional**, not mandatory.
- **Keep documentation lean:** one plan file (the pre-registration) and one results file per candidate. No separate freeze, admission or audit documents. Spend the time on testing more ideas.

## Strategy intake
The owner sends strategy ideas (posts, screenshots, papers) to any session. Evaluate each one with `docs/strategy-intake/README.md`: save the source, write up the evaluation against the rubric, log it, and create beads only for the parts worth pursuing.

The owner also **bookmarks ideas on X**. `ops/x_bookmarks.py` pulls them into `docs/strategy-intake/bookmarks.jsonl` (status new/done/skipped), and the daily session evaluates the new ones.

## Machine resources (shared laptop)
- The machine is shared with other swarms.
- Wrap heavy commands (full `pytest` suites, large backtests, bulk downloads) in `cpu-guard run -- <cmd>`.
- Run one heavy job at a time per agent, and keep parallelism low.
- Don't loosen timing budgets because of load. Stop any watchers or servers you started.

## Coordination
- **Work tracking:** beads. Run `br ready` to see unblocked work and `bv` for triage. Claim a bead before starting it, and close it with a note when done.
- **File ownership:** reserve paths through MCP Agent Mail (`file_reservation_paths`) before editing. Release them when done. Message other agents when you change a shared interface.
- **Commits:** commit and push to `origin main` at every slice boundary. Keep commits small and coherent. Never commit `.env`.
- **Environment:**
  - Python 3.12 via uv. Use `uv run ...` and `uv add <pkg>`.
  - **Secrets are in 1Password, not `.env`.** `.env` holds `${NAME}` placeholders. Run anything that needs a key (Alpaca, X, Jev, Cloudflare) as `ops/with-secrets <cmd>`, e.g. `ops/with-secrets uv run python -m ...`. Without it, keys load as empty strings. Never write key values to disk. New or rotated keys go in the 1Password item `env-tradingbot` (owner), plus a reference line in `ops/secrets.env`.
  - The DB is local Postgres 18 (brew `postgresql@18`) + TimescaleDB on **port 5433**, database `tradingbot`. `DATABASE_URL` is set in `.env`. Port 5432 belongs to an unrelated Postgres.app, so don't use it.
- **Claude accounts (owner, 2026-10-15):** never run agents on the the owner's personal account Claude subscription (the default `~/.claude`). Worker panes run with `CLAUDE_CONFIG_DIR` set: pane 1 uses `~/.claude-account-1`, panes 2–3 use `~/.claude-account-2`, and so does the daily session. `ops/agent_recovery.py` respawns with the same pinned accounts (not `ntm respawn`). Don't spawn agents with plain `ntm spawn`.
- **Services** (paper runners, recorders, scheduler/nudger) run in the tmux session `tradingbot-svc`, one window per service, managed by `ops/services.sh`. Agents run in the ntm session `tradingbot`.
- **Ops:** launchd jobs live in `ops/launchd/`. They cover caffeinate, the watchdog, the nightly pg_dump, and the daily autonomous session at 07:30.

## ntm work split
Built in phases; speed doesn't matter.

| Phase | Agent | Workstream | Depends on |
|---|---|---|---|
| A | Claude | Foundation: schema, ledger, risk engine, fee models (PM US first, Kalshi for research) | — |
| A | Codex | Historical downloaders: Kalshi public + Polymarket (US + intl), then the live PM US recorder | schema, for loading |
| A | Codex | Alpaca paper connector, #5 EOD LETF and #6 turn of month research, Alpaca/X open items | ledger |
| B | Claude | Backtester + strategy interface, #1 longshot research | data + schema |
| C | any | Paper engine, PM US connector, #2 rewards, dashboard | backtester |

## Open items to check early
- Alpaca options data quality (indicative vs OPRA) and how far its history goes.
- Whether X API pricing covers about 500 tickers a day within $50/month.
- Whether Alpaca has adopted the PDT-rule removal.
- How the Weather Company settlement values compare with METAR readings.
- Current Kalshi and Polymarket US liquidity-incentive terms, and their fee schedules.
