"""Compact numeric point-in-time Jev state snapshot per symbol.

Read-only over the IEX intraday snapshot store (``data.iex_intraday``, bead
yma) and the point-in-time event feeds (``data.event_feeds``, bead 96t).
:func:`build_state` returns a JSON-serializable dict of numeric features for one
symbol as of a decision time, plus a separate length-capped ``news`` field, or
``None`` when no fresh same-session snapshot is known.

Conventions (mirroring the data layer's explicit-unknown discipline):
- Decimal features are emitted as strings; unknown / warm-up features are
  ``null`` rather than fabricated, and listed under ``warmup``.
- Technical windows reset at missing/incomplete intervals. When the runner
  supplies the broker's immediately preceding session, complete prior-session
  bars warm up RSI/ATR/trend features across the overnight break. Intraday
  return windows never cross that break; 1d compares the same elapsed session
  boundary on the two consecutive sessions.
- The state carries a ``cost`` block with ``hurdle_bps`` = bid/ask spread +
  modeled round-trip :class:`EquityFeeBook` fees. Callers that pose Jev
  questions about this state **must state that hurdle** (a predicted move has to
  beat it to be a tradable edge) — see :func:`cost_hurdle_note`.

Nothing here calls a model, places an order, or mutates the stores.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal as D

from sqlalchemy import select

from tradingbot.data.event_feeds import events_asof
from tradingbot.data.iex_intraday import NY, QUARTER, SYMBOLS, digest, load_snapshot
from tradingbot.db.iex_models import IexSnapshot
from tradingbot.research.equity_fees import EquityFeeBook

ZERO = D(0)
SCHEMA = "jev_state_v1"
MARKET = "SPY"
ETF_SYMBOLS = frozenset(SYMBOLS[:20])
SLOT_USD = D("140")          # PRD §6 equity slot; the round-trip fee basis
NEWS_MAX_ITEMS = 5
NEWS_HEADLINE_CHARS = 240
HOUR_INTERVALS = 4           # 15-minute intervals per hour
TREND_WINDOW = 20            # SMA / EMA window, in 15-minute intervals
RSI_PERIOD = 14              # in 15-minute intervals
VOL_Z_WINDOW = 20            # volume z-score window, in 15-minute intervals

# GICS sector SPDR for each single-name symbol (the last 20 of SYMBOLS); the 20
# ETFs are their own sector/market proxies. V/MA follow the 2023 GICS move to
# Financials. Every target here is itself in SYMBOLS, so it always has a store.
SECTOR_ETF = {
    "AAPL": "XLK", "MSFT": "XLK", "NVDA": "XLK", "AVGO": "XLK", "AMD": "XLK",
    "AMZN": "XLY", "TSLA": "XLY", "HD": "XLY",
    "GOOGL": "XLC", "META": "XLC", "NFLX": "XLC",
    "JPM": "XLF", "V": "XLF", "MA": "XLF",
    "UNH": "XLV", "LLY": "XLV", "JNJ": "XLV",
    "XOM": "XLE", "COST": "XLP", "PG": "XLP",
}


# --- pure Decimal indicator helpers (None on insufficient / degenerate data) --
def _pct(base, value):
    if base is None or value is None or not base.is_finite() or base <= 0:
        return None
    change = value / base - 1
    return change if change.is_finite() else None


def _mean(values):
    return sum(values, ZERO) / len(values) if values else None


def _stdev(values):
    if len(values) < 2:
        return None
    mean = _mean(values)
    variance = sum(((v - mean) ** 2 for v in values), ZERO) / (len(values) - 1)
    return variance.sqrt() if variance.is_finite() and variance >= 0 else None


def _sma(values, window):
    return _mean(values[-window:]) if len(values) >= window else None


def _ema(values, window):
    if len(values) < window:
        return None
    k = D(2) / (window + 1)
    ema = values[0]
    for value in values[1:]:
        ema = value * k + ema * (1 - k)
    return ema


def _rsi(values, period):
    if len(values) < period + 1:
        return None
    gains = losses = ZERO
    for previous, current in zip(values[-period - 1:-1], values[-period:]):
        change = current - previous
        gains += change if change > 0 else ZERO
        losses += -change if change < 0 else ZERO
    average_loss = losses / period
    if average_loss == 0:
        return D(100) if gains > 0 else D(50)
    rs = (gains / period) / average_loss
    return D(100) - D(100) / (1 + rs)


def _zscore(values, window):
    sample = values[-window:]
    mean, stdev = _mean(sample), _stdev(sample)
    if mean is None or stdev is None or stdev == 0:
        return None
    return (values[-1] - mean) / stdev


def _returns(closes):
    out = []
    for previous, current in zip(closes, closes[1:]):
        change = _pct(previous, current)
        if change is not None:
            out.append(change)
    return out


def _q(value, places):
    if value is None or not value.is_finite():
        return None
    return str(value.quantize(D(places)))


def _closes(intervals):
    """Only the complete contiguous suffix; missing intervals reset a window."""
    rows = [iv["ohlcv"] for iv in _complete_suffix(intervals)]
    closes = [D(r["c"]) for r in rows]
    highs = [D(r["h"]) for r in rows]
    lows = [D(r["l"]) for r in rows]
    volumes = [D(r["v"]) for r in rows]
    first_open = D(rows[0]["o"]) if rows else None
    return first_open, closes, highs, lows, volumes


def _complete_suffix(intervals):
    rows, next_start = [], None
    for iv in reversed(intervals):
        if (iv.get("complete") is not True or iv.get("missing_minutes") or not iv.get("ohlcv")
                or iv.get("minute_count") != 15
                or datetime.fromisoformat(iv["end"])-datetime.fromisoformat(iv["start"]) != QUARTER
                or next_start is not None and iv["end"] != next_start):
            break
        rows.append(iv)
        next_start = iv["start"]
    return list(reversed(rows))


def _prior_snapshot(session, symbol, previous_session, decision_at):
    """A full prior session certified by the broker calendar, never weekdays.

    The runner supplies an already observed calendar session. No fallback to
    an older available day: missing prior-session evidence stays unknown.
    """
    if previous_session is None:
        return None
    row = session.scalar(select(IexSnapshot).where(IexSnapshot.symbol == symbol,
        IexSnapshot.boundary == previous_session.closes_at, IexSnapshot.observed_at < decision_at))
    if row is None:
        return None
    if digest(row.payload) != row.digest:
        raise ValueError("prior snapshot digest mismatch")
    if datetime.fromisoformat(row.payload["session_open"]) != previous_session.opens_at:
        raise ValueError("prior snapshot differs from the official session")
    return row.payload


def _atr(intervals, period=14):
    if len(intervals) < period+1:
        return None
    values = []
    for previous, current in zip(intervals[-period-1:-1], intervals[-period:]):
        close = D(previous["ohlcv"]["c"])
        high, low = D(current["ohlcv"]["h"]), D(current["ohlcv"]["l"])
        values.append(max(high-low, abs(high-close), abs(low-close)))
    return _mean(values)


def _session_phase(boundary, session_open):
    minutes = (boundary - session_open).total_seconds() / 60
    if minutes < 30:
        return "opening"
    if minutes < 120:
        return "morning"
    if minutes < 240:
        return "midday"
    if minutes < 360:
        return "afternoon"
    return "closing"


def _spread_bps(quote):
    if not quote:
        return None, None
    bid, ask = D(quote["bid"]), D(quote["ask"])
    mid = (bid + ask) / 2
    if not mid.is_finite() or mid <= 0 or ask < bid:
        return None, None
    return (ask - bid) / mid * 10000, mid


def _fee_bps(mid, day):
    """Conservative modeled round-trip EquityFeeBook cost at the $140 slot."""
    if mid is None or mid <= 0:
        return None
    size = SLOT_USD / mid
    book = EquityFeeBook()
    buy, _ = book.charge(day=day, side="buy", price=mid, size=size, commit=False)
    sell, _ = book.charge(day=day, side="sell", price=mid, size=size, commit=False)
    return (buy + sell) / SLOT_USD * 10000


def _context(session, symbol, decision_at, boundary=None):
    """Coarse trend context for a reference symbol (session return + EMA position)."""
    snap = load_snapshot(session, symbol, decision_at=decision_at, boundary=boundary)
    if snap is None:
        return None
    first_open, closes, _, _, _ = _closes(snap["intervals"])
    if not closes:
        return None
    last = closes[-1]
    full_session = (len(closes) == len(snap["intervals"])
                    and snap["intervals"][0]["start"] == snap["session_open"]
                    and snap["intervals"][-1]["end"] == snap["boundary"])
    return {"symbol": symbol, "ret_session": _q(_pct(first_open, last) if full_session else None, "0.00000001"),
            "complete_session_so_far": full_session,
            "ema_pos": _q(_pct(_ema(closes, TREND_WINDOW), last), "0.00000001")}


def build_state(session, symbol, *, decision_at: datetime, boundary: datetime | None = None,
                previous_session=None, shared: dict | None = None):
    """Point-in-time numeric snapshot for ``symbol`` as of ``decision_at``.

    Returns a JSON-serializable dict, or ``None`` when no fresh same-session IEX
    snapshot is known before ``decision_at`` (stale, cross-day or absent).
    """
    if symbol not in SYMBOLS:
        raise ValueError("symbol outside universe")
    snap = load_snapshot(session, symbol, decision_at=decision_at, boundary=boundary)
    if snap is None:
        return None
    session_open = datetime.fromisoformat(snap["session_open"])
    boundary_ts = datetime.fromisoformat(snap["boundary"])
    first_open, closes, highs, lows, volumes = _closes(snap["intervals"])
    current = _complete_suffix(snap["intervals"])
    full_session = (bool(current) and len(current) == len(snap["intervals"])
                    and datetime.fromisoformat(current[0]["start"]) == session_open
                    and datetime.fromisoformat(current[-1]["end"]) == boundary_ts)
    prior = _prior_snapshot(session, symbol, previous_session, decision_at)
    prior_rows = _complete_suffix(prior["intervals"]) if prior else []
    # Across the overnight break, continuity is supported only by complete
    # current bars starting at today's official open and ending at the boundary.
    rolling = prior_rows+current if full_session else current
    rolling_closes = [D(iv["ohlcv"]["c"]) for iv in rolling]
    rolling_volumes = [D(iv["ohlcv"]["v"]) for iv in rolling]
    prior_same_clock = None
    if prior and current:
        elapsed = boundary_ts-session_open
        for iv in prior["intervals"]:
            if (datetime.fromisoformat(iv["end"])-datetime.fromisoformat(prior["session_open"]) == elapsed
                    and _complete_suffix([iv])):
                prior_same_clock = D(iv["ohlcv"]["c"])
    last = closes[-1] if closes else None
    day = decision_at.astimezone(NY).date()

    spread_bps, mid = _spread_bps(snap["quote"])
    fee_bps = _fee_bps(mid, day)
    hurdle_bps = spread_bps + fee_bps if spread_bps is not None and fee_bps is not None else None

    features = {
        "ret_15m": _q(_pct(closes[-2], last) if len(closes) >= 2 else None, "0.00000001"),
        "ret_1h": _q(_pct(closes[-HOUR_INTERVALS - 1], last) if len(closes) >= HOUR_INTERVALS + 1 else None, "0.00000001"),
        "ret_1d": _q(_pct(prior_same_clock, last), "0.00000001"),
        "ret_session": _q(_pct(first_open, last) if full_session else None, "0.00000001"),
        "realized_vol_15m": _q(_stdev(_returns(closes)), "0.00000001"),
        "sma20_pos": _q(_pct(_sma(rolling_closes, TREND_WINDOW), last), "0.00000001"),
        "ema20_pos": _q(_pct(_ema(rolling_closes, TREND_WINDOW), last), "0.00000001"),
        "rsi14": _q(_rsi(rolling_closes, RSI_PERIOD), "0.01"),
        "atr14": _q(_atr(rolling), "0.00000001"),
        "volume_z": _q(_zscore(rolling_volumes, VOL_Z_WINDOW) if len(rolling_volumes) >= VOL_Z_WINDOW else None, "0.0001"),
        "current_close": _q(last, "0.00000001"),
        "prior_1h_high": _q(max(highs[-5:-1]) if len(highs) >= 5 else None, "0.00000001"),
        "volume_ratio": _q(volumes[-1]/_mean(rolling_volumes[-21:-1])
                           if len(rolling_volumes) >= 21 and _mean(rolling_volumes[-21:-1]) > 0 else None, "0.0001"),
        "frac_below_high": _q(_pct(last, max(highs)) if highs and full_session else None, "0.00000001"),
        "frac_above_low": _q(_pct(min(lows), last) if lows and full_session else None, "0.00000001"),
    }
    warmup = sorted(name for name, value in features.items() if value is None)

    sector_etf = None if symbol in ETF_SYMBOLS else SECTOR_ETF.get(symbol)
    events = events_asof(session, symbol, decision_at, shared=shared)
    news = events["news"]
    items = [{"id": e.get("id"), "created_at": e.get("created_at"),
              "updated_at": e.get("updated_at"), "known_at": e.get("known_at"),
              "headline": (e.get("headline") or "")[:NEWS_HEADLINE_CHARS]}
             for e in news["items"][:NEWS_MAX_ITEMS]]

    return {
        "schema": SCHEMA,
        "symbol": symbol,
        "decision_at": decision_at.astimezone(NY).isoformat(),
        "boundary": snap["boundary"],
        "session_phase": _session_phase(boundary_ts, session_open),
        "intervals_observed": len(closes),
        "quality": {"complete_session_so_far": full_session, "complete_suffix_intervals": len(current),
                    "total_session_intervals": len(snap["intervals"]), "previous_session_observed": prior is not None,
                    "rolling_indicator_intervals": len(rolling)},
        "source_receipts": {"snapshot_observed_at": snap["observed_at"], "snapshot_digest": digest(snap),
                            "prior_snapshot_observed_at": prior["observed_at"] if prior else None,
                            "prior_snapshot_digest": digest(prior) if prior else None,
                            "event_feeds": events.get("receipts", [])},
        "features": features,
        "warmup": warmup,
        "cost": {"spread_bps": _q(spread_bps, "0.0001"), "fee_bps": _q(fee_bps, "0.0001"),
                 "hurdle_bps": _q(hurdle_bps, "0.0001"), "slot_usd": str(SLOT_USD),
                 "basis": "round-trip bid/ask spread + modeled EquityFeeBook fees on the $140 slot"},
        "context": {"market": _context(session, MARKET, decision_at, boundary_ts) if symbol != MARKET else None,
                    "sector_etf": sector_etf,
                    "sector": _context(session, sector_etf, decision_at, boundary_ts) if sector_etf else None},
        "events": {
            "minutes_to_macro": events["macro"]["minutes_to_next"],
            "minutes_since_macro": events["macro"].get("minutes_since_previous"),
            "macro_recent_window_complete": events["macro"].get("recent_window_complete", False),
            "macro_status": events["macro"]["status"],
            "days_to_earnings": events["earnings"]["days_to_earnings"],
            "earnings_status": events["earnings"]["status"],
            "collection_halted": events["collection_halted"],
        },
        "news": {"untrusted": True, "status": news["status"], "items": items},
    }


def cost_hurdle_note(state: dict) -> str:
    """One-line hurdle statement for a Jev question's instructions.

    Any question posed about a :func:`build_state` snapshot must include this so
    the model treats a move below the round-trip cost hurdle as no edge.
    """
    hurdle = state.get("cost", {}).get("hurdle_bps")
    if hurdle is None:
        return ("Trading cost hurdle is unknown (no fresh quote); do not assume a "
                "tradable edge and prefer no trade.")
    spread = state["cost"].get("spread_bps")
    fee = state["cost"].get("fee_bps")
    return (f"Trading cost hurdle: a predicted move must exceed {hurdle} bps round-trip "
            f"(bid/ask spread {spread} bps + fees {fee} bps). A smaller expected move is "
            f"no tradable edge — prefer no trade.")
