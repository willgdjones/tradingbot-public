"""Fixtures for dashboard tests (rolled-back DB transaction; seeded reference data)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tradingbot.db import enums
from tradingbot.db.models import Instrument, Market, Strategy, Venue
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
def strategy(session) -> Strategy:
    return session.scalar(select(Strategy).where(Strategy.key == "longshot"))


@pytest.fixture()
def instrument(session) -> Instrument:
    venue = session.scalar(select(Venue).where(Venue.key == "polymarket_us"))
    suffix = uuid.uuid4().hex[:12]
    market = Market(venue_id=venue.id, external_id=f"DASH-COND-{suffix}",
                    market_type=enums.MarketType.BINARY)
    session.add(market)
    session.flush()
    inst = Instrument(venue_id=venue.id, market_id=market.id, external_id=f"DASH-TOK-{suffix}",
                      instrument_type=enums.InstrumentType.BINARY_YES, outcome="yes",
                      contract_multiplier=Decimal("1"))
    session.add(inst)
    session.flush()
    return inst
