"""Fixtures for recorder tests.

DB-backed tests run against the real ``tradingbot`` database inside a transaction
that is rolled back after each test (matching the ledger/risk suites); pure tests
need none of this. Reference data (venues) is ensured once via the idempotent
seed.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tradingbot.db import enums
from tradingbot.db.models import Instrument, Market, Venue
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
def make_market(session, pm_us_venue):
    """Factory: a Polymarket US market whose ``external_id`` is the given slug,
    plus its ``binary_yes`` instrument (``symbol`` also set to the slug). Returns
    ``(slug, instrument_id)``."""

    def _factory(slug: str | None = None) -> tuple[str, int]:
        slug = slug or f"test-market-{uuid.uuid4().hex[:8]}"
        market = Market(
            venue_id=pm_us_venue.id,
            external_id=slug,
            title="Recorder test market",
            market_type=enums.MarketType.BINARY,
        )
        session.add(market)
        session.flush()
        inst = Instrument(
            venue_id=pm_us_venue.id,
            market_id=market.id,
            external_id=f"{slug}-YES",
            symbol=slug,
            instrument_type=enums.InstrumentType.BINARY_YES,
            outcome="yes",
            price_min=Decimal("0"),
            price_max=Decimal("1"),
            contract_multiplier=Decimal("1"),
        )
        session.add(inst)
        session.flush()
        return slug, inst.id

    return _factory
