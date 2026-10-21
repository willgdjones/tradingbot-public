"""Fixtures for ledger tests.

The DB-backed tests run against the real ``tradingbot`` database but inside a
transaction that is rolled back after each test, so nothing persists. Reference
data (venues, strategies) is ensured once via the idempotent seed.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from tradingbot.db import enums
from tradingbot.db.models import Instrument, Market, Strategy, Venue
from tradingbot.db.seed import seed
from tradingbot.db.session import get_engine


@pytest.fixture(scope="session", autouse=True)
def _seed_reference_data():
    seed()


@pytest.fixture()
def session():
    """A session wrapped in a transaction that is rolled back after the test."""
    engine = get_engine()
    connection = engine.connect()
    trans = connection.begin()
    from sqlalchemy.orm import Session

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
def longshot_strategy(session) -> Strategy:
    return session.scalar(select(Strategy).where(Strategy.key == "longshot"))


@pytest.fixture()
def pm_instrument(session, pm_us_venue) -> Instrument:
    """A fresh binary-yes instrument on Polymarket US (rolled back after test)."""
    suffix = uuid.uuid4().hex[:12]
    market = Market(
        venue_id=pm_us_venue.id,
        external_id=f"TEST-COND-{suffix}",
        title="Ledger test market",
        market_type=enums.MarketType.BINARY,
    )
    session.add(market)
    session.flush()
    inst = Instrument(
        venue_id=pm_us_venue.id,
        market_id=market.id,
        external_id=f"TEST-TOK-{suffix}",
        symbol=f"TEST-{suffix}",
        instrument_type=enums.InstrumentType.BINARY_YES,
        outcome="yes",
        price_min=Decimal("0"),
        price_max=Decimal("1"),
        contract_multiplier=Decimal("1"),
    )
    session.add(inst)
    session.flush()
    return inst
