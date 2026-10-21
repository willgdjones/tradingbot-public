from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
import uuid

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from tradingbot.data import iex_intraday as iex
from tradingbot.db.iex_models import IexBar, IexRecorderHealth, IexSnapshot
from tradingbot.db.models import Quote
from tradingbot.db.session import get_engine

OPEN = datetime(2026, 10, 2, 13, 30, tzinfo=UTC)
BOUNDARY = OPEN + iex.QUARTER
OBS = BOUNDARY + timedelta(seconds=10)
INSTRUMENTS = {symbol: i + 100 for i, symbol in enumerate(iex.SYMBOLS)}


@pytest.fixture
def session():
    schema = "test_iex_" + uuid.uuid4().hex
    base = get_engine()
    with base.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        # Standalone reference copies; no production rows or foreign keys.
        for name in ("quotes", "incidents", "venues", "markets", "instruments"):
            connection.execute(text(f'CREATE TABLE "{schema}".{name} (LIKE public.{name} INCLUDING ALL)'))
    engine = create_engine(base.url, execution_options={"schema_translate_map": {None: schema}})
    for model in (IexBar, IexSnapshot, IexRecorderHealth):
        model.__table__.create(engine)
    try:
        with Session(engine, expire_on_commit=False) as value:
            yield value
    finally:
        engine.dispose()
        with base.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))


def bar(stamp=OPEN, **updates):
    return {"t": stamp.isoformat(), "o": "100", "h": "102", "l": "99", "c": "101", "v": 20,
            "n": 2, "vw": "100.5", **updates}


def quote(stamp=OBS - timedelta(seconds=1), **updates):
    return {"t": stamp.isoformat(), "bp": "100", "ap": "101", "bs": 2, "as": 3, **updates}


def count(session, model):
    return session.scalar(select(func.count()).select_from(model))


def test_fixed_universe_and_raw_decimal_validation():
    assert len(iex.SYMBOLS) == len(set(iex.SYMBOLS)) == 40
    stamp, payload = iex.minute_bar(bar(c="100.123456789"), OBS)
    assert stamp == OPEN and payload["c"] == "100.123456789"
    with pytest.raises(ValueError):
        iex.utc(datetime(2026, 10, 2))


@pytest.mark.parametrize("updates", [
    {"h": "98"}, {"l": "102"}, {"o": "NaN"}, {"c": "Infinity"}, {"c": True},
    {"v": -1}, {"v": "1.5"}, {"n": "1.2"}, {"vw": 0}, {"t": BOUNDARY.isoformat()},
    {"t": (OPEN + timedelta(seconds=1)).isoformat()},
])
def test_reject_invalid_or_incomplete_bars(updates):
    with pytest.raises((ValueError, ArithmeticError)):
        iex.minute_bar(bar(**updates), BOUNDARY)


def test_append_revision_and_strict_knowledge_cutoff(session):
    first = OPEN + timedelta(minutes=1, seconds=3)
    second = first + timedelta(seconds=30)
    assert iex.store_bars(session, {"SPY": [bar()]}, first, OPEN, BOUNDARY) == 1
    session.commit()
    assert iex.store_bars(session, {"SPY": [bar()]}, second, OPEN, BOUNDARY) == 0
    assert iex.store_bars(session, {"SPY": [bar(c="100")]}, second, OPEN, BOUNDARY) == 1
    session.commit()
    def at(known):
        return iex.bars_asof(session, symbol="SPY", start=OPEN, end=BOUNDARY, known_before=known)
    assert at(first) == []
    assert at(second)[0].payload["c"] == "101"
    assert at(second + timedelta(microseconds=1))[0].payload["c"] == "100"
    assert count(session, IexBar) == 2


def test_bar_window_duplicate_symbol_and_transaction_validation(session):
    for data in ({"SPY": [bar(), bar()]}, {"FAKE": [bar()]}, {"SPY": [bar(OPEN - iex.MINUTE)]}):
        with pytest.raises(ValueError):
            iex.store_bars(session, data, OBS, OPEN, BOUNDARY)
        assert count(session, IexBar) == 0


def test_quote_poll_does_not_refresh_exchange_time_or_round_lot_units(session):
    source_time = OBS - timedelta(seconds=2)
    data = {"SPY": quote(source_time)}
    result = iex.store_quotes(session, data, OBS, INSTRUMENTS)
    session.commit()
    assert result["fresh_symbols"] == 1
    iex.store_quotes(session, data, OBS + timedelta(seconds=15), INSTRUMENTS)
    session.commit()
    assert count(session, Quote) == 1
    row = session.scalar(select(Quote))
    assert row.time == source_time and row.bid_size is None
    assert row.metadata_["size_unit"] == "round_lots" and row.metadata_["observed_at"] == OBS.isoformat()
    result = iex.store_quotes(session, data, OBS + timedelta(seconds=31), INSTRUMENTS)
    assert result["symbols"]["SPY"]["status"] == "stale"
    assert count(session, Quote) == 1


@pytest.mark.parametrize("updates", [{"bp": 0}, {"ap": "99"}, {"bs": -1}, {"ap": "NaN"},
                                     {"t": (OBS + timedelta(seconds=1)).isoformat()}])
def test_bad_quotes_never_enter_risk_tape(session, updates):
    result = iex.store_quotes(session, {"SPY": quote(**updates)}, OBS, INSTRUMENTS)
    assert result["fresh_symbols"] == 0
    assert count(session, Quote) == 0


def test_snapshot_is_immutable_and_reports_gaps_without_fill_forward(session):
    rows = [bar(OPEN + i * iex.MINUTE) for i in range(15) if i != 4]
    iex.store_bars(session, {"SPY": rows}, OBS - timedelta(seconds=2), OPEN, BOUNDARY)
    iex.store_quotes(session, {"SPY": quote()}, OBS - timedelta(milliseconds=100), INSTRUMENTS)
    session.commit()
    assert iex.create_snapshots(session, boundary=BOUNDARY, observed_at=OBS, opening=OPEN, instruments=INSTRUMENTS) == 40
    session.commit()
    assert iex.load_snapshot(session, "SPY", decision_at=OBS) is None
    captured = iex.load_snapshot(session, "SPY", decision_at=OBS + timedelta(seconds=1))
    interval = captured["intervals"][0]
    assert interval["minute_count"] == 14 and not interval["complete"]
    assert interval["missing_minutes"] == [(OPEN + 4 * iex.MINUTE).isoformat()]
    assert Decimal(interval["ohlcv"]["v"]) == 280
    assert captured["quote"]["time"] == (OBS - timedelta(seconds=1)).isoformat()
    iex.store_bars(session, {"SPY": [bar(OPEN + 4 * iex.MINUTE), bar(c="100")]}, OBS + iex.MINUTE, OPEN, BOUNDARY)
    session.commit()
    assert iex.create_snapshots(session, boundary=BOUNDARY, observed_at=OBS + iex.MINUTE, opening=OPEN, instruments=INSTRUMENTS) == 0
    assert iex.load_snapshot(session, "SPY", decision_at=OBS + 2 * iex.MINUTE) == captured
    empty = iex.load_snapshot(session, "QQQ", decision_at=OBS + iex.MINUTE)
    assert empty["intervals"][0]["ohlcv"] is None and empty["quote"] is None
    assert iex.load_snapshot(session, "SPY", decision_at=BOUNDARY + timedelta(minutes=17)) is None
    assert iex.load_snapshot(session, "SPY", decision_at=OBS + timedelta(days=1)) is None


def test_snapshot_strictly_excludes_equal_receipt_quote_and_bar(session):
    iex.store_bars(session, {"SPY": [bar()]}, OBS, OPEN, BOUNDARY)
    iex.store_quotes(session, {"SPY": quote()}, OBS, INSTRUMENTS)
    session.commit()
    iex.create_snapshots(session, boundary=BOUNDARY, observed_at=OBS, opening=OPEN, instruments=INSTRUMENTS)
    session.commit()
    snap = iex.load_snapshot(session, "SPY", decision_at=OBS + iex.MINUTE)
    assert snap["quote"] is None and snap["intervals"][0]["minute_count"] == 0


def test_no_historical_snapshot_replay_or_early_close_overrun():
    close = OPEN + timedelta(hours=3, minutes=30)
    assert iex.snapshot_boundary(OPEN + iex.MINUTE, OPEN, close) is None
    assert iex.snapshot_boundary(BOUNDARY, OPEN, close) is None
    assert iex.snapshot_boundary(BOUNDARY + timedelta(seconds=5), OPEN, close) == BOUNDARY
    assert iex.snapshot_boundary(BOUNDARY + timedelta(seconds=91), OPEN, close) is None
    assert iex.snapshot_boundary(close + timedelta(seconds=10), OPEN, close) == close
    assert iex.snapshot_boundary(close + iex.QUARTER + timedelta(seconds=10), OPEN, close) is None


class FakeAPI:
    def __init__(self, clock):
        self.clock = clock
        self.requests = []

    def calendar(self, day):
        self.requests.append("calendar")
        return [{"date": "2026-10-02", "open": "09:30", "close": "13:00"}]

    def bars(self, start, end):
        self.requests.append((start, end))
        return {"SPY": [bar(start + i * iex.MINUTE) for i in range(int((end - start) / iex.MINUTE))]}

    def quotes(self):
        self.clock[0] += timedelta(milliseconds=10)
        return {"SPY": quote(self.clock[0] - timedelta(seconds=1))}


def test_recorder_warmup_overlap_early_close_and_no_duplicate_step(session):
    clock = [OBS]
    api = FakeAPI(clock)
    recorder = iex.Recorder(session, api, INSTRUMENTS, now=lambda: clock[0], budget=SimpleNamespace(check=lambda s: None))
    state = recorder.step()
    assert state["status"] == "partial_quotes" and state["bars_added"] == 15
    assert state["snapshots_added"] == 40
    clock[0] += timedelta(seconds=15)
    assert recorder.step()["snapshots_added"] == 0
    assert len(api.requests) == 2
    clock[0] += iex.MINUTE
    recorder.step()
    assert api.requests[-1][0] == BOUNDARY - timedelta(minutes=3)
    clock[0] = OPEN + timedelta(hours=3, minutes=32)
    assert recorder.step()["status"] == "outside_regular_session"
    assert count(session, IexSnapshot) == 40


def test_transport_pagination_explicit_free_feed_and_bounds():
    api = iex.IexAPI.__new__(iex.IexAPI)
    api.data = object()
    requests = []
    def get(client, path, params):
        requests.append((path, dict(params)))
        return {"bars": {"SPY": [bar()]}, "next_page_token": "next"} if len(requests) == 1 else {
            "bars": {"QQQ": [bar()]}, "next_page_token": None}
    api._get = get
    result = api.bars(OPEN, BOUNDARY)
    assert set(result) == {"SPY", "QQQ"} and len(requests) == 2
    assert all(params["feed"] == "iex" and params["adjustment"] == "raw" and params["asof"] == "-" for _, params in requests)
    assert requests[1][1]["page_token"] == "next"
    assert iex.utc(requests[0][1]["end"]) < BOUNDARY
    with pytest.raises(ValueError):
        api.bars(OPEN, OPEN + timedelta(days=1))


def test_repeating_page_token_and_malformed_payload_fail_closed():
    api = iex.IexAPI.__new__(iex.IexAPI)
    api.data = object()
    for body in ({"bars": {"SPY": [bar()]}, "next_page_token": "same"},
                 {"bars": {"UNAPPROVED": []}, "next_page_token": None}):
        api._get = lambda *args: body
        with pytest.raises(ValueError):
            api.bars(OPEN, BOUNDARY)


def test_storage_includes_database_and_never_deletes(monkeypatch):
    budget = iex.StorageBudget()
    budget.last_check = -100
    budget.disk = SimpleNamespace(check_free=lambda: None, check=lambda: SimpleNamespace(data_bytes=2_000_000_000))
    session = SimpleNamespace(scalar=lambda query: 18_000_000_000)
    with pytest.raises(iex.DiskBudgetExceeded):
        budget.check(session)


def test_readonly_transport_rejects_post_before_network():
    adapter = iex._ReadOnlyAdapter()
    with pytest.raises(ValueError, match="GET only"):
        adapter.send(SimpleNamespace(method="POST"))
