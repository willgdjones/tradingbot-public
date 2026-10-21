# Trading Bot

A multi-strategy trading system built to **prove real edges with small live stakes** before growing capital. It is a personal research project, run by one person and a daily autonomous Claude Code session, on about $1,000 of spare cash (roughly $140 per live strategy).

> Not financial advice. Nothing here is a recommendation to trade. Use at your own risk.

## How it works

- **Proof before capital.** A strategy only gets real money after it passes a forward-paper rule: it has to hold up on data it was not tuned on. See [`PRD.md`](PRD.md) §4 and [`docs/promotion-checklist.md`](docs/promotion-checklist.md).
- **Structural edges preferred.** Market design, fee and reward programs, settlement mechanics, forced flows, and cross-venue pricing gaps, rather than speed races.
- **Free data only.** $0/month: Alpaca IEX and indicative options, Yahoo/Stooq daily bars, FRED, CFTC COT, and similar.
- **AI-decided strategies are allowed**, but they face the same forward-paper gate as everything else.
- **Everything is logged.** Each trade is recorded with timestamp, venue, price, size and fees.

## Layout

| Path | What's there |
|---|---|
| `src/tradingbot/` | The Python package: strategies, risk limits, data adapters, ledger |
| `ops/` | launchd jobs, watchdog, daily-session runner, secrets wrapper (1Password references only) |
| `tests/` | Test suite |
| `docs/research/` | Strategy research reports (C01 onward), frozen parameters, holdout results, overfitting ledger |
| `docs/reviews/` | Review notes |
| `PRD.md` | Product requirements and decisions |
| `CHANGELOG.md` | Running log of what changed and why |

## Running it

Python with [`uv`](https://docs.astral.sh/uv/) and Postgres (TimescaleDB). Copy `.env.example` to `.env` and fill in your own keys. This repo contains no credentials; the `ops/secrets.env` file holds 1Password references that only resolve in the author's vault.

```sh
uv sync
uv run alembic upgrade head
uv run pytest
```

Paths in the `ops/launchd` plists point at `/Users/USER/Documents/tradingbot`; change them to your checkout before loading.

## Status

Active. Strategies are at different stages: some in research, some forward-paper, and a small number with live stakes. See `CHANGELOG.md` for the current state.
