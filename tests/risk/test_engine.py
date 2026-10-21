"""Risk-engine tests: the PRD §6 hard limits and absolute veto."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from tradingbot.db import enums
from tradingbot.db.models import Incident, Quote, RiskHalt
from tradingbot.ledger import Ledger
from tradingbot.risk import RiskEngine, limits

D = Decimal
NOW = datetime(2026, 9, 30, 16, 0, tzinfo=timezone.utc)


def _fresh_quote(session, instrument_id, at):
    session.add(Quote(time=at, instrument_id=instrument_id, bid=D("0.39"), ask=D("0.41")))
    session.flush()


# --- limits canary --------------------------------------------------------
def test_limits_match_prd_section_6():
    # Guardrail: if someone edits the §6 limits, this fails loudly (AGENTS.md).
    assert limits.PER_STRATEGY_KILL_FRACTION == D("0.40")
    assert limits.GLOBAL_DAILY_HALT_USD == D("-50")
    assert limits.PER_MARKET_POSITION_MAX_USD == D("25")
    # Asset-class split approved by the owner 2026-10-01: $25 on prediction
    # markets, the strategy's allocation elsewhere.
    assert limits.position_cap_usd("prediction_market", D("140")) == D("25")
    assert limits.position_cap_usd("equities", D("140")) == D("140")
    assert limits.position_cap_usd("options", D("140")) == D("140")
    assert limits.position_cap_usd(None, D("140")) == D("25")
    assert limits.position_cap_usd("equities", None) == D("25")
    assert limits.STALE_DATA_MAX_SECONDS == 30
    assert limits.API_ERROR_MAX_PER_MINUTE == 5


# --- position cap ---------------------------------------------------------
def test_position_cap_allows_within_25(session, instrument, strategy):
    eng = RiskEngine(session)
    ok, _ = eng.position_cap_check(
        strategy_id=strategy.id, mode=enums.Mode.LIVE, instrument_id=instrument.id,
        side=enums.Side.BUY, size=D("60"), price=D("0.40"),  # 60*0.40 = 24
    )
    assert ok


def test_position_cap_vetoes_over_25_and_reports_max(session, instrument, strategy):
    eng = RiskEngine(session)
    ok, max_add = eng.position_cap_check(
        strategy_id=strategy.id, mode=enums.Mode.LIVE, instrument_id=instrument.id,
        side=enums.Side.BUY, size=D("70"), price=D("0.40"),  # 70*0.40 = 28 > 25
    )
    assert not ok
    assert max_add == D("62.5")  # 25 / 0.40


def test_position_cap_allows_reducing(session, instrument, strategy):
    led = Ledger(session)
    order = led.record_order(
        instrument_id=instrument.id, mode=enums.Mode.LIVE, side=enums.Side.BUY,
        order_type=enums.OrderType.LIMIT, size=D("60"), strategy_id=strategy.id,
    )
    led.record_fill(order=order, price=D("0.40"), size=D("60"),
                    liquidity=enums.Liquidity.MAKER, fill_ts=NOW, fee=D("0"))
    eng = RiskEngine(session)
    ok, _ = eng.position_cap_check(
        strategy_id=strategy.id, mode=enums.Mode.LIVE, instrument_id=instrument.id,
        side=enums.Side.SELL, size=D("100"), price=D("0.40"),  # closing + then some
    )
    assert ok  # reduces absolute exposure


# --- stale data -----------------------------------------------------------
def test_stale_data_no_data_is_stale(session, instrument):
    eng = RiskEngine(session)
    fresh, age = eng.stale_data_check(instrument.id, NOW)
    assert not fresh and age is None


def test_stale_data_fresh_and_old(session, instrument, make_inst):
    eng = RiskEngine(session)
    _fresh_quote(session, instrument.id, NOW - timedelta(seconds=10))
    fresh, age = eng.stale_data_check(instrument.id, NOW)
    assert fresh and age == 10

    old_inst = make_inst()
    _fresh_quote(session, old_inst.id, NOW - timedelta(seconds=60))
    fresh2, age2 = eng.stale_data_check(old_inst.id, NOW)
    assert not fresh2 and age2 == 60


# --- evaluate_order integration ------------------------------------------
def test_evaluate_order_allows_when_all_clear(session, instrument, strategy):
    _fresh_quote(session, instrument.id, NOW - timedelta(seconds=5))
    eng = RiskEngine(session)
    decision = eng.evaluate_order(
        instrument_id=instrument.id, mode=enums.Mode.LIVE, side=enums.Side.BUY,
        size=D("10"), price=D("0.40"), strategy_id=strategy.id, now=NOW,
    )
    assert decision.allowed
    assert decision.reasons == []


def test_evaluate_order_vetoes_on_stale_data(session, instrument, strategy):
    eng = RiskEngine(session)  # no quotes -> stale
    decision = eng.evaluate_order(
        instrument_id=instrument.id, mode=enums.Mode.LIVE, side=enums.Side.BUY,
        size=D("10"), price=D("0.40"), strategy_id=strategy.id, now=NOW,
    )
    assert not decision.allowed
    assert any("stale" in r for r in decision.reasons)


# --- strategy kill (−40%) -------------------------------------------------
def test_refresh_halts_kills_strategy_on_40pct_loss(session, instrument, strategy):
    strategy.allocation_usd = D("100")
    session.flush()
    led = Ledger(session)
    o1 = led.record_order(instrument_id=instrument.id, mode=enums.Mode.LIVE,
                          side=enums.Side.BUY, order_type=enums.OrderType.LIMIT,
                          size=D("100"), strategy_id=strategy.id)
    led.record_fill(order=o1, price=D("0.50"), size=D("100"),
                    liquidity=enums.Liquidity.MAKER, fill_ts=NOW, fee=D("0"))
    o2 = led.record_order(instrument_id=instrument.id, mode=enums.Mode.LIVE,
                          side=enums.Side.SELL, order_type=enums.OrderType.LIMIT,
                          size=D("100"), strategy_id=strategy.id)
    led.record_fill(order=o2, price=D("0.10"), size=D("100"),
                    liquidity=enums.Liquidity.MAKER, fill_ts=NOW, fee=D("0"))  # realized -40

    eng = RiskEngine(session)
    triggered = eng.refresh_halts(enums.Mode.LIVE, now=NOW)
    assert any("longshot" in t for t in triggered)
    assert eng.is_strategy_killed(strategy.id)
    # a killed strategy's orders are vetoed even with fresh data
    _fresh_quote(session, instrument.id, NOW - timedelta(seconds=1))
    decision = eng.evaluate_order(
        instrument_id=instrument.id, mode=enums.Mode.LIVE, side=enums.Side.BUY,
        size=D("1"), price=D("0.40"), strategy_id=strategy.id, now=NOW,
    )
    assert not decision.allowed
    assert any("killed" in r for r in decision.reasons)
    assert session.scalar(
        select(RiskHalt).where(RiskHalt.scope == enums.HaltScope.STRATEGY)
    ) is not None


# --- global daily halt (−$50) --------------------------------------------
def test_refresh_halts_daily_on_50_loss(session, instrument, strategy):
    # longshot has allocation 0, so only the daily halt should trip (no kill).
    led = Ledger(session)
    o1 = led.record_order(instrument_id=instrument.id, mode=enums.Mode.LIVE,
                          side=enums.Side.BUY, order_type=enums.OrderType.LIMIT,
                          size=D("200"), strategy_id=strategy.id)
    led.record_fill(order=o1, price=D("0.50"), size=D("200"),
                    liquidity=enums.Liquidity.MAKER, fill_ts=NOW, fee=D("0"))
    o2 = led.record_order(instrument_id=instrument.id, mode=enums.Mode.LIVE,
                          side=enums.Side.SELL, order_type=enums.OrderType.LIMIT,
                          size=D("200"), strategy_id=strategy.id)
    led.record_fill(order=o2, price=D("0.10"), size=D("200"),
                    liquidity=enums.Liquidity.MAKER, fill_ts=NOW, fee=D("0"))  # -80

    eng = RiskEngine(session)
    assert eng.daily_pnl(enums.Mode.LIVE, NOW.date()) == D("-80")
    triggered = eng.refresh_halts(enums.Mode.LIVE, now=NOW)
    assert any("daily halt" in t for t in triggered)
    assert eng.daily_halt_active(enums.Mode.LIVE, NOW.date())

    _fresh_quote(session, instrument.id, NOW - timedelta(seconds=1))
    decision = eng.evaluate_order(
        instrument_id=instrument.id, mode=enums.Mode.LIVE, side=enums.Side.BUY,
        size=D("1"), price=D("0.40"), strategy_id=strategy.id, now=NOW,
    )
    assert not decision.allowed
    assert any("daily halt" in r for r in decision.reasons)
    # paper mode is unaffected by the live daily halt
    assert not eng.daily_halt_active(enums.Mode.PAPER, NOW.date())


def test_daily_halt_is_idempotent(session, instrument, strategy):
    eng = RiskEngine(session)
    first = eng.trigger_daily_halt(enums.Mode.LIVE, D("-60"), NOW)
    second = eng.trigger_daily_halt(enums.Mode.LIVE, D("-60"), NOW)
    assert first is not None and second is None


# --- API error halt -------------------------------------------------------
def test_api_error_halt_after_5_per_minute(session):
    eng = RiskEngine(session)
    for i in range(4):
        eng.record_api_error(NOW + timedelta(seconds=i))
    assert not eng.api_error_rate_exceeded(NOW + timedelta(seconds=4))
    eng.record_api_error(NOW + timedelta(seconds=5))
    assert eng.api_error_rate_exceeded(NOW + timedelta(seconds=5))
    # window rolls off after 60s
    assert not eng.api_error_rate_exceeded(NOW + timedelta(seconds=90))


def test_api_error_halt_logs_incident(session):
    eng = RiskEngine(session)
    for i in range(5):
        eng.record_api_error(NOW + timedelta(seconds=i))
    inc = session.scalar(
        select(Incident).where(Incident.category == enums.IncidentCategory.API_ERROR)
    )
    assert inc is not None


def test_daily_halt_logs_incident(session, strategy):
    eng = RiskEngine(session)
    eng.trigger_daily_halt(enums.Mode.LIVE, D("-60"), NOW)
    inc = session.scalar(
        select(Incident).where(Incident.category == enums.IncidentCategory.DAILY_HALT)
    )
    assert inc is not None
    assert inc.severity == enums.Severity.CRITICAL


# --- asset-class cap (PRD §6, owner-approved 2026-10-01) -------------------
def _equity_setup(session, allocation):
    import uuid
    from tradingbot.db.models import Instrument, Market, Strategy, Venue
    venue = session.scalar(select(Venue).where(Venue.key == "alpaca"))
    sfx = uuid.uuid4().hex[:10]
    market = Market(venue_id=venue.id, external_id=f"CAP-{sfx}", market_type=enums.MarketType.EQUITY)
    strat = Strategy(key=f"cap-{sfx}", name="cap test", status="backtest", allocation_usd=D(allocation))
    session.add_all([market, strat])
    session.flush()
    inst = Instrument(venue_id=venue.id, market_id=market.id, external_id=f"CAP-{sfx}",
                      instrument_type=enums.InstrumentType.EQUITY, contract_multiplier=D("1"))
    session.add(inst)
    session.flush()
    return strat, inst


def test_equity_position_may_use_strategy_allocation(session):
    strat, inst = _equity_setup(session, "140")
    ok, _ = RiskEngine(session).position_cap_check(
        strategy_id=strat.id, mode=enums.Mode.PAPER, instrument_id=inst.id,
        side=enums.Side.BUY, size=D("0.2"), price=D("500"),  # $100
    )
    assert ok


def test_equity_position_over_allocation_is_vetoed(session):
    strat, inst = _equity_setup(session, "140")
    ok, max_add = RiskEngine(session).position_cap_check(
        strategy_id=strat.id, mode=enums.Mode.PAPER, instrument_id=inst.id,
        side=enums.Side.BUY, size=D("0.3"), price=D("500"),  # $150 > $140
    )
    assert not ok
    assert max_add == D("140") / D("500")


def test_prediction_market_cap_stays_25_despite_allocation(session, instrument, strategy):
    ok, _ = RiskEngine(session).position_cap_check(
        strategy_id=strategy.id, mode=enums.Mode.LIVE, instrument_id=instrument.id,
        side=enums.Side.BUY, size=D("75"), price=D("0.40"),  # $30 > $25
    )
    assert not ok
