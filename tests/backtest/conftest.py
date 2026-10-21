"""Fixtures for backtester tests (rolled-back DB transaction; seeded reference
data). Mirrors the ledger/risk suites."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tradingbot.db import enums
from tradingbot.db.models import Instrument, Market, Quote, Strategy, Trade, Venue
from tradingbot.db.seed import seed
from tradingbot.db.session import get_engine


@pytest.fixture(scope="session", autouse=True)
def _seed_reference_data():
    seed()


@pytest.fixture()
def session():
    engine = get_engine()
    connection = engine.connect()
    trans = connection.begin()
    sess = Session(bind=connection, expire_on_commit=False)
    try:
        yield sess
    finally:
        sess.close()
        trans.rollback()
        connection.close()


@pytest.fixture()
def pm_us_venue(session) -> Venue:
    return session.scalar(select(Venue).where(Venue.key == "polymarket_us"))


@pytest.fixture()
def instrument_id(session, pm_us_venue) -> int:
    suffix = uuid.uuid4().hex[:10]
    market = Market(venue_id=pm_us_venue.id, external_id=f"BT-COND-{suffix}",
                    market_type=enums.MarketType.BINARY)
    session.add(market)
    session.flush()
    inst = Instrument(
        venue_id=pm_us_venue.id, market_id=market.id, external_id=f"BT-TOK-{suffix}:yes",
        instrument_type=enums.InstrumentType.BINARY_YES, outcome="yes",
        price_min=Decimal("0"), price_max=Decimal("1"), contract_multiplier=Decimal("1"),
    )
    session.add(inst)
    session.flush()
    return inst.id


@pytest.fixture()
def strategy_id(session) -> int:
    strat = Strategy(
        key=f"bt-strat-{uuid.uuid4().hex[:8]}", name="Backtest test strategy",
        status=enums.StrategyStatus.BACKTEST, allocation_usd=Decimal("100"),
    )
    session.add(strat)
    session.flush()
    return strat.id


@pytest.fixture()
def add_quote(session):
    def _add(instrument_id, time, **kw):
        q = Quote(instrument_id=instrument_id, time=time,
                  metadata_=kw.pop("metadata", {"source": "market_data"}), **kw)
        session.add(q)
        session.flush()
        return q
    return _add


@pytest.fixture()
def add_trade(session):
    def _add(instrument_id, time, *, price, size, **kw):
        t = Trade(instrument_id=instrument_id, time=time, price=price, size=size,
                  metadata_=kw.pop("metadata", {"source": "trade"}), **kw)
        session.add(t)
        session.flush()
        return t
    return _add
