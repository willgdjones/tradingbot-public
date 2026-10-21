"""Fixtures for risk-engine tests (rolled-back DB transaction; seeded reference data)."""

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
def pm_us_venue(session) -> Venue:
    return session.scalar(select(Venue).where(Venue.key == "polymarket_us"))


@pytest.fixture()
def strategy(session) -> Strategy:
    return session.scalar(select(Strategy).where(Strategy.key == "longshot"))


def make_instrument(session, venue) -> Instrument:
    suffix = uuid.uuid4().hex[:12]
    market = Market(
        venue_id=venue.id, external_id=f"RISK-COND-{suffix}",
        market_type=enums.MarketType.BINARY,
    )
    session.add(market)
    session.flush()
    inst = Instrument(
        venue_id=venue.id, market_id=market.id, external_id=f"RISK-TOK-{suffix}",
        instrument_type=enums.InstrumentType.BINARY_YES, outcome="yes",
        contract_multiplier=Decimal("1"),
    )
    session.add(inst)
    session.flush()
    return inst


@pytest.fixture()
def instrument(session, pm_us_venue) -> Instrument:
    return make_instrument(session, pm_us_venue)


@pytest.fixture()
def make_inst(session, pm_us_venue):
    """Factory returning fresh instruments on Polymarket US."""
    def _factory() -> Instrument:
        return make_instrument(session, pm_us_venue)

    return _factory
