"""Offline tests for the free (Yahoo) daily-history fetcher/archive/loader."""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
import hashlib
import json

import pytest

from tradingbot.data import free_history as fh


def _epoch_ny_open(d: date) -> int:
    # 14:30 UTC falls on NY date d (09:30 EST / 10:30 EDT) year-round for these dates.
    return int(datetime(d.year, d.month, d.day, 14, 30, tzinfo=UTC).timestamp())


def _yahoo_json(dates, opens, highs, lows, closes, vols, adjs, *, dividends=None,
                null_index=None):
    stamps = [_epoch_ny_open(d) for d in dates]
    def nullify(seq):
        if null_index is None:
            return list(seq)
        s = list(seq); s[null_index] = None; return s
    events = {}
    if dividends:
        events["dividends"] = {str(_epoch_ny_open(d)): {"amount": amt, "date": _epoch_ny_open(d)}
                               for d, amt in dividends.items()}
    return json.dumps({"chart": {"result": [{
        "meta": {"symbol": "SPY"},
        "timestamp": stamps,
        "events": events,
        "indicators": {
            "quote": [{"open": nullify(opens), "high": nullify(highs), "low": nullify(lows),
                        "close": nullify(closes), "volume": vols}],
            "adjclose": [{"adjclose": adjs}],
        },
    }], "error": None}})


def test_parse_basic_with_dividend():
    dates = [date(2020, 1, 2), date(2020, 1, 3), date(2020, 1, 6)]
    raw = _yahoo_json(dates, [100, 101, 102], [101, 102, 103], [99, 100, 101],
                      [100.5, 101.5, 102.5], [1000, 1100, 1200], [90.0, 91.0, 92.0],
                      dividends={date(2020, 1, 3): 1.25})
    meta, bars = fh.parse_yahoo(raw)
    assert [b.date for b in bars] == dates
    assert bars[0].open == Decimal("100") and bars[0].close == Decimal("100.5")
    assert bars[1].dividend == Decimal("1.25")
    assert bars[0].dividend == Decimal("0") and bars[0].split_ratio == Decimal("1")
    assert meta["null_rows"] == 0


def test_parse_drops_null_rows():
    dates = [date(2020, 1, 2), date(2020, 1, 3), date(2020, 1, 6)]
    raw = _yahoo_json(dates, [100, 101, 102], [101, 102, 103], [99, 100, 101],
                      [100.5, 101.5, 102.5], [1000, 1100, 1200], [90.0, 91.0, 92.0],
                      null_index=1)
    meta, bars = fh.parse_yahoo(raw)
    assert [b.date for b in bars] == [date(2020, 1, 2), date(2020, 1, 6)]
    assert meta["null_rows"] == 1


def test_parse_errors_on_yahoo_error():
    with pytest.raises(fh.FreeHistoryError):
        fh.parse_yahoo(json.dumps({"chart": {"result": None, "error": {"code": "x"}}}))


def test_validate_coverage_flags_gap_and_counts():
    dates = [date(2020, 1, 2), date(2020, 1, 3), date(2020, 2, 10)]  # big gap
    raw = _yahoo_json(dates, [100, 101, 102], [101, 102, 103], [99, 100, 101],
                      [100.5, 101.5, 102.5], [1, 1, 1], [90.0, 91.0, 92.0],
                      dividends={date(2020, 1, 3): 1.0})
    _, bars = fh.parse_yahoo(raw)
    q = fh.validate_coverage(bars, date(2020, 1, 1), date(2020, 2, 11))
    assert q["n_sessions"] == 3 and q["n_dividends"] == 1 and q["n_splits"] == 0
    assert len(q["large_calendar_gaps"]) == 1
    assert q["issues"] == []


def test_validate_coverage_detects_bad_prices():
    dates = [date(2020, 1, 2), date(2020, 1, 3)]
    raw = _yahoo_json(dates, [100, 101], [101, 100], [99, 102], [100.5, 101.5],
                      [1, 1], [90.0, 91.0])  # second row high<low
    _, bars = fh.parse_yahoo(raw)
    q = fh.validate_coverage(bars, date(2020, 1, 1), date(2020, 1, 4))
    assert any("bad prices" in s for s in q["issues"])


def test_load_capture_verifies_checksum(tmp_path):
    dates = [date(2020, 1, 2), date(2020, 1, 3)]
    raw = _yahoo_json(dates, [100, 101], [101, 102], [99, 100], [100.5, 101.5],
                      [1, 1], [90.0, 91.0])
    cap = tmp_path / "SPY"; cap.mkdir()
    (cap / "raw.json").write_text(raw)
    (cap / "manifest.json").write_text(json.dumps(
        {"sha256": hashlib.sha256(raw.encode()).hexdigest()}))
    manifest, bars = fh.load_capture(cap)
    assert len(bars) == 2
    # Corrupt the raw payload -> checksum mismatch is raised.
    (cap / "raw.json").write_text(raw + " ")
    with pytest.raises(fh.FreeHistoryError):
        fh.load_capture(cap)


def test_cross_check_closes():
    dates = [date(2020, 1, 2), date(2020, 1, 3)]
    raw = _yahoo_json(dates, [100, 101], [101, 102], [99, 100], [100.0, 200.0],
                      [1, 1], [90.0, 91.0])
    _, bars = fh.parse_yahoo(raw)
    other = {date(2020, 1, 2): Decimal("100.2"), date(2020, 1, 3): Decimal("150.0")}
    res = fh.cross_check_closes(bars, other, rel_tol=Decimal("0.01"))
    assert res["n_overlap"] == 2
    assert res["n_mismatch_over_tol"] == 1  # the 200 vs 150 close disagrees
