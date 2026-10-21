"""Unit tests for the Jev state builder (bead tradingbot-8hs).

state.py is a read-only feature layer over the IEX snapshot store and the event
feeds, which each have their own DB suites. Here we stub those two accessors
with realistic synthetic payloads (matching their committed shapes) and test the
assembly, the cost hurdle, context, news capping, warm-up nulls, and the pure
Decimal indicators.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal as D

import pytest

from tradingbot.ai import state
from tradingbot.data.iex_intraday import NY, QUARTER

OPEN = datetime(2026, 10, 1, 9, 30, tzinfo=NY)


def make_snapshot(symbol, closes, *, quote=True, volumes=None):
    intervals = []
    start = OPEN
    for i, close in enumerate(closes):
        c = D(str(close))
        vol = str(volumes[i]) if volumes else str(1000 + 10 * i)
        intervals.append({
            "start": start.isoformat(), "end": (start + QUARTER).isoformat(),
            "complete": True, "missing_minutes": [], "minute_count": 15, "revisions": [],
            "ohlcv": {"o": str(c), "c": str(c), "h": str(c + D("0.5")), "l": str(c - D("0.5")),
                      "v": vol, "vw": str(c), "n": "10"},
        })
        start += QUARTER
    boundary = OPEN + len(closes) * QUARTER
    return {
        "source": "alpaca-iex-intraday-v1", "feed": "iex", "symbol": symbol, "instrument_id": 1,
        "session_open": OPEN.isoformat(), "boundary": boundary.isoformat(),
        "observed_at": (boundary + timedelta(seconds=30)).isoformat(), "intervals": intervals,
        "quote": {"time": boundary.isoformat(), "observed_at": boundary.isoformat(),
                  "bid": "99.95", "ask": "100.05"} if quote else None,
    }


def fake_events(items=(), *, minutes_to_macro=42.0, days_to_earnings=3, earnings_status="scheduled_estimate"):
    return {
        "asof": "x", "symbol": "x", "collection_halted": False,
        "news": {"status": "ok", "untrusted": True, "items": list(items)},
        "macro": {"status": "ok", "next_known": {}, "minutes_to_next": minutes_to_macro},
        "earnings": {"status": earnings_status, "next_known": {}, "days_to_earnings": days_to_earnings},
        "receipts": [],
    }


@pytest.fixture
def patched(monkeypatch):
    snaps, events = {}, {"ret": fake_events()}

    def load(session, symbol, *, decision_at, boundary=None):
        return snaps.get(symbol)

    monkeypatch.setattr(state, "load_snapshot", load)
    monkeypatch.setattr(state, "events_asof", lambda session, symbol, at, shared=None: events["ret"])
    return snaps, events


# --- pure indicators --------------------------------------------------------
def test_pct_guards_zero_and_none():
    assert state._pct(D(100), D(110)) == D("0.1")
    assert state._pct(D(0), D(5)) is None
    assert state._pct(None, D(5)) is None


def test_rsi_extremes_and_midpoint():
    rising = [D(100) + D(i) for i in range(20)]
    assert state._rsi(rising, 14) == D(100)
    falling = [D(100) - D(i) for i in range(20)]
    assert state._rsi(falling, 14) == D(0)
    assert state._rsi([D(100)] * 20, 14) == D(50)
    assert state._rsi([D(100)] * 10, 14) is None  # warm-up


def test_sma_ema_stdev_zscore():
    values = [D(10), D(12), D(14), D(16)]
    assert state._sma(values, 4) == D(13)
    assert state._sma(values, 5) is None
    assert state._stdev([D(2), D(4), D(6)]) == D(2)
    assert state._stdev([D(5)]) is None
    assert state._zscore([D(1), D(1), D(10)], 3) is not None
    assert state._zscore([D(5), D(5), D(5)], 3) is None  # zero variance


# --- build_state ------------------------------------------------------------
def test_build_state_rich_single_name(patched):
    snaps, _ = patched
    closes = [D("100") + D("0.1") * i for i in range(24)]
    for sym in ("AAPL", "SPY", "XLK"):
        snaps[sym] = make_snapshot(sym, closes)
    decision_at = OPEN + 24 * QUARTER + timedelta(seconds=30)

    snap = state.build_state(object(), "AAPL", decision_at=decision_at)
    assert snap["schema"] == "jev_state_v1" and snap["symbol"] == "AAPL"
    assert snap["intervals_observed"] == 24 and snap["warmup"] == ["ret_1d"]
    f = snap["features"]
    assert f["ret_session"] == "0.02300000"          # 102.3 / 100 - 1
    assert f["rsi14"] == "100.00"                      # monotonic gains
    assert all(f[k] is not None for k in ("ret_15m", "ret_1h", "sma20_pos", "ema20_pos", "volume_z"))
    # cost hurdle: 10 bp spread + modeled round-trip fee on the $140 slot
    assert snap["cost"]["spread_bps"] == "10.0000"
    assert snap["cost"]["fee_bps"] == "2.8571"
    assert snap["cost"]["hurdle_bps"] == "12.8571"
    # context: SPY market + XLK sector for a single name
    assert snap["context"]["market"]["symbol"] == "SPY"
    assert snap["context"]["sector_etf"] == "XLK" and snap["context"]["sector"]["symbol"] == "XLK"
    assert snap["events"]["minutes_to_macro"] == 42.0 and snap["events"]["days_to_earnings"] == 3


def test_etf_has_no_sector_and_market_is_self(patched):
    snaps, _ = patched
    snaps["SPY"] = make_snapshot("SPY", [D("100") + D("0.1") * i for i in range(24)])
    snap = state.build_state(object(), "SPY", decision_at=OPEN + 24 * QUARTER + timedelta(seconds=30))
    assert snap["context"]["sector_etf"] is None and snap["context"]["sector"] is None
    assert snap["context"]["market"] is None          # SPY is the market proxy itself


def test_recent_macro_context_preserves_unknown_coverage(patched):
    snaps, events = patched
    snaps["SPY"] = make_snapshot("SPY", [100, 101])
    at = OPEN+2*QUARTER+timedelta(seconds=30)
    unknown = state.build_state(object(), "SPY", decision_at=at)["events"]
    assert unknown["minutes_since_macro"] is None
    assert unknown["macro_recent_window_complete"] is False
    events["ret"]["macro"].update(minutes_since_previous=8.5, recent_window_complete=True)
    known = state.build_state(object(), "SPY", decision_at=at)["events"]
    assert known["minutes_since_macro"] == 8.5
    assert known["macro_recent_window_complete"] is True


def test_warmup_nulls_early_session(patched):
    snaps, _ = patched
    snaps["AAPL"] = make_snapshot("AAPL", [D("100"), D("101")], volumes=[1000, 1000])
    snap = state.build_state(object(), "AAPL", decision_at=OPEN + 2 * QUARTER + timedelta(seconds=30))
    f = snap["features"]
    assert f["ret_15m"] is not None and f["ret_session"] is not None
    for name in ("ret_1h", "sma20_pos", "ema20_pos", "rsi14", "volume_z"):
        assert f[name] is None and name in snap["warmup"]


def test_no_quote_means_unknown_hurdle(patched):
    snaps, _ = patched
    snaps["AAPL"] = make_snapshot("AAPL", [D("100") + D("0.1") * i for i in range(24)], quote=False)
    snap = state.build_state(object(), "AAPL", decision_at=OPEN + 24 * QUARTER + timedelta(seconds=30))
    assert snap["cost"]["spread_bps"] is None and snap["cost"]["hurdle_bps"] is None
    assert "unknown" in state.cost_hurdle_note(snap)


def test_news_capped_and_truncated(patched):
    snaps, events = patched
    snaps["AAPL"] = make_snapshot("AAPL", [D("100") + D("0.1") * i for i in range(24)])
    long_headline = "x" * 500
    events["ret"] = fake_events(items=[{"id": i, "created_at": "t", "updated_at": "t",
                                        "headline": long_headline, "symbols": ["AAPL"]} for i in range(7)])
    snap = state.build_state(object(), "AAPL", decision_at=OPEN + 24 * QUARTER + timedelta(seconds=30))
    assert snap["news"]["untrusted"] is True and len(snap["news"]["items"]) == state.NEWS_MAX_ITEMS
    assert all(len(it["headline"]) == state.NEWS_HEADLINE_CHARS for it in snap["news"]["items"])


def test_missing_snapshot_returns_none(patched):
    assert state.build_state(object(), "AAPL", decision_at=OPEN + 2 * QUARTER) is None


def test_symbol_outside_universe_raises(patched):
    with pytest.raises(ValueError, match="outside universe"):
        state.build_state(object(), "ZZZZ", decision_at=OPEN)


def test_cost_hurdle_note_states_the_hurdle(patched):
    snaps, _ = patched
    snaps["AAPL"] = make_snapshot("AAPL", [D("100") + D("0.1") * i for i in range(24)])
    snap = state.build_state(object(), "AAPL", decision_at=OPEN + 24 * QUARTER + timedelta(seconds=30))
    note = state.cost_hurdle_note(snap)
    assert "12.8571" in note and "no tradable edge" in note


def test_incomplete_latest_interval_never_looks_like_a_complete_return(patched):
    snaps, _ = patched
    snaps["SPY"] = make_snapshot("SPY", list(range(100, 125)))
    snaps["SPY"]["intervals"][-1]["complete"] = False
    snap = state.build_state(object(), "SPY", decision_at=OPEN+25*QUARTER+timedelta(seconds=40))
    assert snap["quality"]["complete_suffix_intervals"] == 0
    assert all(v is None for v in snap["features"].values())


def test_gap_resets_rolling_windows_and_does_not_compress_time(patched):
    snaps, _ = patched
    snaps["AAPL"] = make_snapshot("AAPL", list(range(100, 125)))
    snaps["SPY"] = make_snapshot("SPY", list(range(100, 125)))
    for snap in snaps.values():
        snap["intervals"][-3]["missing_minutes"] = [snap["intervals"][-3]["start"]]
    snap = state.build_state(object(), "AAPL", decision_at=OPEN+25*QUARTER+timedelta(seconds=40))
    assert snap["quality"]["complete_suffix_intervals"] == 2
    assert snap["features"]["ret_15m"] is not None
    for key in ("ret_1h", "ret_session", "sma20_pos", "rsi14", "atr14", "frac_below_high"):
        assert snap["features"][key] is None
    assert snap["context"]["market"]["ret_session"] is None


def test_absent_whole_interval_also_resets_suffix(patched):
    snaps, _ = patched
    snaps["SPY"] = make_snapshot("SPY", list(range(100, 125)))
    snaps["SPY"]["intervals"].pop(-3)
    snap = state.build_state(object(), "SPY", decision_at=OPEN+25*QUARTER+timedelta(seconds=40))
    assert snap["quality"]["complete_suffix_intervals"] == 2
    assert snap["features"]["ret_1h"] is None


def previous_snapshot():
    snap = make_snapshot("SPY", list(range(75, 101)))
    for key in ("session_open", "boundary", "observed_at"):
        snap[key] = (datetime.fromisoformat(snap[key])-timedelta(days=1)).isoformat()
    for iv in snap["intervals"]:
        for key in ("start", "end"):
            iv[key] = (datetime.fromisoformat(iv[key])-timedelta(days=1)).isoformat()
    return snap


def test_prior_official_session_warms_indicators_but_not_intraday_return(patched, monkeypatch):
    snaps, _ = patched
    snaps["SPY"] = make_snapshot("SPY", [101])
    previous = previous_snapshot()
    monkeypatch.setattr(state, "_prior_snapshot", lambda *a: previous)
    snap = state.build_state(object(), "SPY", decision_at=OPEN+QUARTER+timedelta(seconds=40), previous_session=object())
    assert snap["features"]["rsi14"] == "100.00"
    assert snap["features"]["atr14"] is not None
    assert snap["features"]["ret_1d"] == str((D(101)/D(75)-1).quantize(D(".00000001")))
    assert snap["features"]["ret_15m"] is None and snap["features"]["ret_1h"] is None
    assert snap["quality"]["rolling_indicator_intervals"] == 27
    assert snap["source_receipts"]["prior_snapshot_digest"] == state.digest(previous)


def test_current_session_gap_cannot_be_warmed_away_with_prior_bars(patched, monkeypatch):
    snaps, _ = patched
    snaps["SPY"] = make_snapshot("SPY", [101, 102, 103])
    snaps["SPY"]["intervals"][0]["complete"] = False
    monkeypatch.setattr(state, "_prior_snapshot", lambda *a: previous_snapshot())
    snap = state.build_state(object(), "SPY", decision_at=OPEN+3*QUARTER+timedelta(seconds=40), previous_session=object())
    assert snap["features"]["rsi14"] is None
    assert snap["quality"]["rolling_indicator_intervals"] == 2


def test_news_revision_identity_and_source_receipts_survive(patched):
    snaps, events = patched
    snaps["SPY"] = make_snapshot("SPY", [100])
    events["ret"]["news"]["items"] = [{"id": 1, "created_at": "earlier", "updated_at": "revision",
                                          "known_at": "receipt", "headline": "data only"}]
    events["ret"]["receipts"] = [{"source": "news", "digest": "proof"}]
    snap = state.build_state(object(), "SPY", decision_at=OPEN+QUARTER+timedelta(seconds=40))
    assert snap["news"]["items"][0]["known_at"] == "receipt"
    assert snap["news"]["items"][0]["updated_at"] == "revision"
    assert snap["source_receipts"]["event_feeds"] == events["ret"]["receipts"]
