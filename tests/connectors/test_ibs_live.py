"""IBS QQQ live runner (tradingbot-752) on the live connector with fake broker and market data."""
from datetime import date, timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy import select

from tradingbot.connectors.alpaca_live import NAME as BOOK
from tradingbot.connectors.cash import MarketSession, timestamp
from tradingbot.db.models import Fill, FxRate, Incident, Order, Strategy, Venue
from tradingbot.live import ibs_qqq
from tradingbot.live.ibs_qqq import ALLOCATION, NAME, Runner, entry_size, limit_price, prepare, step

from .test_alpaca_live import LiveFakeAPI

SETTLES = {"2026-09-29": "2026-09-30", "2026-09-30": "2026-10-01", "2026-10-01": "2026-10-02",
           "2026-10-02": "2026-10-05"}


def bar(ibs, low=100, high=110):
    close = D(low) + D(str(ibs)) * (D(high) - D(low))
    return {"open": str(close), "high": str(high), "low": str(low), "close": str(close)}


class FakeMarket:
    def __init__(self):
        # 09-29 anchor 0.5; 09-30 crosses under 0.10 (buy 10-01); 10-01 crosses over 0.90 (sell 10-02).
        self.bars = {date(2026, 9, 29): bar("0.5"), date(2026, 9, 30): bar("0.05"), date(2026, 10, 1): bar("0.95")}
        self.bars[date(2026, 10, 1)]["open"] = "100"

    def calendar(self, start, end):
        if start > end:
            raise RuntimeError("end should not be before start")  # as Alpaca's HTTP 400
        return [MarketSession.from_api({"date": d, "open": "09:30", "close": "16:00", "settlement_date": s})
                for d, s in SETTLES.items() if start <= date.fromisoformat(d) <= end]

    def daily_bars(self, start, end):
        return {d: dict(b) for d, b in self.bars.items() if start <= d <= end.date()}

    def quote(self):
        return {"bid": "100.00", "ask": "100.02", "time": "2026-10-01T13:31:00Z"}


@pytest.fixture
def env(session):
    clock = [timestamp("2026-09-30T12:00:00Z")]
    api = LiveFakeAPI(clock)
    api.asset_row["symbol"] = "QQQ"
    api.account_row.update(cash="1000", buying_power="1000")
    for day in ("2026-09-30", "2026-10-01"):
        session.add(FxRate(base="USD", quote="GBP", rate=D("0.8"), ts=timestamp(day + "T00:00:00Z"),
                           source="ibs-live-test"))
    session.flush()
    market = FakeMarket()
    trial_id = prepare(session, market, commit="test", evidence={"final": {"trial": 8804}}, now=clock[0])
    incidents = []
    return session, api, clock, market, trial_id, incidents


def runner(env, live=True):
    session, api, clock, market, trial_id, incidents = env
    return Runner(session, trial_id, market, api if live else None, now=lambda: clock[0],
                  incident=incidents.append, log=lambda line: None)


def test_sizing_and_marketable_limits_follow_the_plan():
    assert limit_price("buy", D("100"), D("100.01")) == D("100.27")   # ask +25 bp, rounded up
    assert limit_price("sell", D("100"), D("100.01")) == D("99.75")   # bid −25 bp, rounded down
    # min(95% of equity, $140) with a 5% reserve and $0.01 buffer, floored to 1e-9.
    assert entry_size(D(140), D(140), D(100)) == D("1.329900000")
    assert entry_size(D(200), D(200), D(100)) == D("1.400000000")
    assert entry_size(D(140), D("7.50"), D(100)) == 0  # below the $1 minimum


def test_step_crosses_and_refuses_a_missing_session():
    state = {"last_bar": "2026-09-29", "previous": "0.5", "units": 0}
    days = [date(2026, 9, 30), date(2026, 10, 1)]
    bars = FakeMarket().bars
    new, rows = step(state, days[:1], bars)
    assert new == {"last_bar": "2026-09-30", "previous": "0.05", "units": 1}
    assert rows["2026-09-30"]["units"] == 1
    new, _ = step(new, days[1:], bars)
    assert new["units"] == 0
    assert step(state, days, {days[0]: bars[days[0]]}) is None


def test_prepare_anchors_flat_on_the_last_completed_session(env):
    session, _, _, _, trial_id, _ = env
    trial = runner(env).trial()
    state = trial.metrics[NAME]
    assert state["signal"] == {"last_bar": "2026-09-29", "previous": "0.5", "units": 0}
    strategy = session.get(Strategy, trial.strategy_id)
    assert (strategy.key, strategy.status, strategy.allocation_usd, trial.mode) == (
        "ibs-QQQ-live-v1", "live", ALLOCATION, "live")
    with pytest.raises(ValueError, match="running live IBS trial"):
        prepare(session, FakeMarket(), commit="test", evidence={}, now=timestamp("2026-09-30T12:00:00Z"))


def test_live_round_trip_initializes_the_book_buys_after_a_cross_under_and_sells_after_a_cross_over(env):
    session, api, clock, market, trial_id, incidents = env
    r = runner(env)
    clock[0] = timestamp("2026-10-01T13:00:00Z")  # 09:00 ET: go live, then decide
    r.tick()
    venue = session.scalar(select(Venue).where(Venue.key == "alpaca"))
    assert venue.metadata_[BOOK]["initial_cash"] == "140"
    assert r.live and any("real-money orders are enabled" in line for line in incidents)
    assert r.state()["decisions"]["2026-10-01"]["units"] == 1
    assert not api.submissions  # nothing before the order window

    clock[0] = timestamp("2026-10-01T13:31:00Z")
    r.tick()
    [payload] = api.submissions
    assert payload["side"] == "buy" and payload["limit_price"] == "100.25" and payload["time_in_force"] == "day"
    assert D(payload["qty"]) == entry_size(ALLOCATION, ALLOCATION, D("100.25"))
    r.tick()  # an active order blocks a second submission
    assert len(api.submissions) == 1

    clock[0] += timedelta(seconds=1)
    api.fill("ibs20261001b1", qty=payload["qty"], price="100.10")
    clock[0] += timedelta(seconds=40)
    r.tick()
    assert r.held() == D(payload["qty"])

    clock[0] = timestamp("2026-10-02T13:00:00Z")
    r.tick()
    state = r.state()
    assert state["decisions"]["2026-10-02"]["units"] == 0
    [fill] = state["fidelity"]["fills"]
    assert (fill["official_open"], fill["adverse_bp"]) == ("100", "10.00")  # 100.10 vs the 100 official open

    clock[0] = timestamp("2026-10-02T13:31:00Z")
    r.tick()
    sell = api.submissions[-1]
    assert (sell["side"], D(sell["qty"]), sell["limit_price"]) == ("sell", D(payload["qty"]), "99.75")
    clock[0] += timedelta(seconds=1)
    api.fill("ibs20261002s1", qty=sell["qty"], price="99.90")
    clock[0] += timedelta(seconds=40)
    r.tick()
    assert r.held() == 0
    fills = session.scalars(select(Fill).join(Order, Fill.order_id == Order.id).where(Order.trial_id == trial_id))
    assert [f.mode for f in fills] == ["live", "live"]


def test_dry_run_without_keys_fills_only_the_virtual_book(env):
    session, api, clock, *_ = env
    r = runner(env, live=False)
    clock[0] = timestamp("2026-10-01T13:00:00Z")
    r.tick()
    clock[0] = timestamp("2026-10-01T13:31:00Z")
    r.tick()
    r.tick()
    book = r.state()["virtual"]
    [trade] = book["trades"]
    assert (trade["side"], trade["price"]) == ("buy", "100.02")
    assert D(book["qty"]) == entry_size(ALLOCATION, ALLOCATION, D("100.02"))
    assert not api.submissions and not r.live


def test_a_missing_bar_trades_nothing_and_reports_once(env):
    session, api, clock, market, trial_id, incidents = env
    del market.bars[date(2026, 9, 30)]
    r = runner(env)
    for stamp in ("2026-10-01T13:00:00Z", "2026-10-01T13:31:00Z", "2026-10-01T14:31:00Z", "2026-10-01T14:40:00Z"):
        clock[0] = timestamp(stamp)
        r.tick()
    assert "2026-10-01" not in r.state()["decisions"] and not api.submissions
    assert sum("no decision for 2026-10-01" in line for line in incidents) == 1


def test_kill_switch_blocks_the_entry_without_burning_attempts(env):
    session, api, clock, *_ = env
    r = runner(env)
    clock[0] = timestamp("2026-10-01T13:00:00Z")
    r.tick()
    r.connector.engage_kill_switch("owner test")
    clock[0] = timestamp("2026-10-01T13:31:00Z")
    r.tick()
    assert not api.submissions
    assert r.state()["days"]["2026-10-01"]["attempts"] == []
    assert session.scalar(select(Incident.id).where(Incident.message.like("%kill switch engaged; buy%")))


def test_after_going_live_missing_keys_never_fall_back_to_the_virtual_book(env):
    session, api, clock, market, trial_id, incidents = env
    clock[0] = timestamp("2026-10-01T13:00:00Z")
    runner(env).tick()  # live from here on
    r = runner(env, live=False)
    clock[0] = timestamp("2026-10-01T13:31:00Z")
    r.tick()
    assert r.state()["virtual"]["trades"] == [] and not api.submissions
    assert any("live keys did not resolve" in line for line in incidents)


def test_cli_status_reads_the_running_trial(env):
    session, *_ = env
    report = ibs_qqq.status(session)
    assert report["strategy"] == "ibs-QQQ-live-v1" and report["live_since"] is None


def test_the_session_after_the_anchor_decides_flat_without_a_calendar_range(env):
    session, api, clock, *_ = env
    r = runner(env, live=False)
    clock[0] = timestamp("2026-09-30T13:00:00Z")  # anchor 09-29; no completed session in between
    r.tick()
    assert r.state()["decisions"]["2026-09-30"] == {
        "units": 0, "through": "2026-09-29", "ibs": "0.5", "decided_at": "2026-09-30T13:00:00+00:00"}
