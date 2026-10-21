# Live runners

Real-money strategies on `connectors/alpaca_live.py` (cash account, unchanged
§6 `RiskEngine`, persistent kill switch). Every order needs a running `live`
trial, a positive strategy allocation and the live cash book.

## IBS QQQ v1 (`ibs_qqq.py`, tradingbot-752)

The owner override of 2026-10-14 (PRD §4) sends the IBS rule that passed its
holdout (trial 8804) live on its $140 slot without paper. Live trial **8815**,
strategy `ibs-QQQ-live-v1`, starts flat on the 2026-10-14 bar.

- **Service:** `ops/ibs_live.sh` in `tradingbot-svc` (window `svc-ibs-live`,
  log `logs/ibs-live.log`).
- **Dry run until the keys exist:** with `ALPACA_LIVE_KEY`/`ALPACA_LIVE_SECRET`
  empty in 1Password, decisions fill a virtual book at the IEX quote and nothing
  is sent. The process restarts outside the order window, so the first restart
  after the owner adds the keys initializes the $140 live book, registers QQQ,
  writes one line to `logs/INCIDENTS.md` and trades from then on. If the broker
  has less than $140 settled cash, it stays dry and retries hourly.
- **Daily cycle:** from 09:00 ET, step `strategy.ibs.Signal` over every completed
  session's SIP daily bar (never IEX, see tradingbot-3xw). From 09:30:30 to
  10:30 ET, sell everything if the signal is flat, or buy min(95% equity, $140)
  if it is long and the strategy is flat. Orders are fractional marketable DAY
  limits at ask +25 bp / bid −25 bp. An order still open after 2 minutes is
  cancelled and retried, up to 5 attempts a day. An unfinished entry or exit
  carries to the next open.
- **Risk:** the connector checks the −40% strategy kill, −$50 daily halt,
  position cap, stale data and API-error limits on every order. The runner marks
  the position every 5 minutes in regular hours. A killed strategy cannot even
  sell, so the runner then asks the owner (INCIDENTS.md) to close QQQ in Alpaca.
- **Owner controls:** `uv run python -m tradingbot.connectors.alpaca_live kill
  --reason "..."` stops all live orders until `clear-kill --note "..."`.
- **Evidence:** `uv run python -m tradingbot.live.ibs_qqq status` shows the
  signal, decisions, fills and each fill's slippage against the official SIP
  open (backtest assumption 10 bp/side, break-even ~33 bp).

Differences from the backtest, all small and deliberate:

- Sale proceeds are usable on the settlement date (T+1), as at the broker. The
  backtest waited one more open.
- Size is computed at the open from realized equity. This is identical while
  flat.
- Fills are real, not open +10 bp.
