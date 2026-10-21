"""Live paper exposure cannot enter rollback fixtures; fixture risk stays real."""
from decimal import Decimal as D
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, aliased

from connectors.conftest import (  # noqa: F401
    connector_seed, session, setup, ready,
)
from tradingbot.connectors.cash import timestamp
from tradingbot.db.models import Fill, Instrument, Order, Position, Strategy, Venue
from tradingbot.db.base import Base
from tradingbot.db.seed import seed
from tradingbot.db.session import get_engine, SessionLocal
from tradingbot.forward.ai_paper_costs import AIPaperCostGuard
from tradingbot.forward.paper_evidence import required_instrument_ids
from tradingbot.ledger import Ledger
from tradingbot.risk import RiskEngine

NOW = timestamp("2026-09-30T14:00:00Z")


def exposure(session, *, first_id=None):
    """Three instruments exercise held, pending and anonymous-fill paths."""
    venue = Venue(key="exposure-" + uuid4().hex, name="Fixture exposure", kind="equities")
    session.add(venue)
    session.flush()
    instruments = [Instrument(id=None if first_id is None else first_id + i,
                              venue_id=venue.id, external_id=uuid4().hex,
                              symbol="TEST", instrument_type="equity") for i in range(3)]
    strategy = Strategy(key="exposure-" + uuid4().hex, name="Fixture exposure",
                        venue_id=venue.id, status="paper", allocation_usd=D(100))
    session.add_all([*instruments, strategy])
    session.flush()
    held, pending, anonymous = instruments
    session.add(Position(strategy_id=strategy.id, instrument_id=held.id, mode="paper",
                         quantity=D(1), avg_price=D(10), cost_basis=D(10), opened_ts=NOW))
    ledger = Ledger(session)
    ledger.record_order(instrument_id=pending.id, strategy_id=strategy.id, mode="paper",
                        side="buy", order_type="limit", size=D(1), limit_price=D(10))
    order = ledger.record_order(instrument_id=anonymous.id, mode="paper", side="buy",
                                order_type="limit", size=D(1), limit_price=D(10))
    ledger.record_fill(order=order, price=D(10), size=D(1), liquidity="taker", fill_ts=NOW,
                       fee=D(0), usd_gbp_rate=D(".8"))
    session.commit()
    return {i.id for i in instruments}


@pytest.mark.parametrize("background_first", [True, False])
def test_existing_and_later_background_exposure_stays_outside_fixture(background_first, background_db):
    # The neighbor schema stands in for production. Both engines perform normal
    # account-wide queries, and the neighbor can commit while our fixture runs.
    with get_engine().connect() as connection:
        outer = connection.begin()
        try:
            with Session(bind=background_db, expire_on_commit=False) as background, \
                    Session(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint") as fixture:
                if background_first:
                    other = exposure(background, first_id=1_000_000_000)
                owned = exposure(fixture)
                if not background_first:
                    other = exposure(background, first_id=1_000_000_000)
                assert required_instrument_ids(fixture) == owned
                assert required_instrument_ids(background) == other
                background.commit()
                for model in (Position, Order, Fill):
                    assert {r.instrument_id for r in fixture.scalars(select(model))} <= owned
                    assert set(fixture.scalars(select(model.instrument_id))) <= owned
                    alias = aliased(model)
                    assert set(fixture.scalars(select(alias.instrument_id))) <= owned
                    assert fixture.scalar(select(func.count()).select_from(model)) > 0
                joined = fixture.scalars(select(Fill.instrument_id).join(Order, Fill.order_id == Order.id))
                assert set(joined) <= owned
                assert RiskEngine(fixture).daily_pnl("paper", marks={i: D(11) for i in owned}, now=NOW) == 2
                # Core SQL is isolated too; no ORM risk-query monkeypatch.
                assert set(fixture.scalars(text("SELECT instrument_id FROM positions"))) <= owned
                assert required_instrument_ids(background) == other
                background.commit()
                fixture.commit()
                assert required_instrument_ids(fixture) == owned
        finally:
            assert outer.is_active
            outer.rollback()


@pytest.fixture
def background_db(paper_test_database):
    schema = "test_paper_neighbor_" + uuid4().hex
    admin = paper_test_database.admin
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(admin.url, connect_args={"options": f"-csearch_path={schema}"},
                           execution_options={"schema_translate_map": {None: schema}})
    try:
        Base.metadata.create_all(engine)
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))


def test_committed_factory_writes_and_raw_sql_never_use_public(paper_test_database):
    external_id = "isolation-" + uuid4().hex
    with SessionLocal() as session:
        assert session.scalar(text("SELECT current_schemas(false)")) == [paper_test_database.schema]
        venue = session.scalar(select(Venue).where(Venue.key == "alpaca"))
        session.add(Instrument(venue_id=venue.id, external_id=external_id,
                               symbol="ISOLATION", instrument_type="equity"))
        session.commit()
    with get_engine().connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM instruments WHERE external_id=:external"),
                                  {"external": external_id}) == 1
    with paper_test_database.admin.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM public.instruments WHERE external_id=:external"),
                                  {"external": external_id}) == 0


def test_leaked_fixture_transaction_fails_later_writers_instead_of_hanging(paper_test_database):
    # 2026-10-05: a setup error leaked an outer transaction holding the alpaca
    # venue, and the next seed() upsert waited on it forever, hanging the suite.
    seed()
    with SessionLocal() as session:
        assert session.scalar(text("SHOW lock_timeout")) == "1min"
    leaked = get_engine().connect()
    leaked.begin()
    try:
        leaked.execute(text("UPDATE venues SET name = name WHERE key = 'alpaca'"))
        with get_engine().connect() as waiting:
            waiting.execute(text("SET lock_timeout = '1s'"))  # same mechanism, shorter for the test
            with pytest.raises(OperationalError):
                waiting.execute(text("UPDATE venues SET name = name WHERE key = 'alpaca'"))
    finally:
        leaked.rollback()
        leaked.close()


def test_fixture_foreign_venue_exposure_still_blocks_account_guard(ready):
    connector, *_ = ready
    guard = AIPaperCostGuard()
    guard.capture(connector)
    owned = exposure(connector.session)
    assert owned <= required_instrument_ids(connector.session)
    with pytest.raises(ValueError, match="All paper exposure must have supported Alpaca marks"):
        guard.capture(connector)


def test_autoflush_tracks_new_instruments_and_second_session_fills(ready):
    connector, _, _, original, *_ = ready
    session = connector.session
    instrument = Instrument(venue_id=original.venue_id, external_id=uuid4().hex,
                            symbol="SECOND", instrument_type="equity")
    session.add(instrument)
    # Ordinary ORM autoflush and another session's fixture fills stay visible.
    assert session.scalar(select(Instrument).where(Instrument.external_id == instrument.external_id)) is instrument
    session.commit()
    with Session(bind=session.get_bind(), join_transaction_mode="create_savepoint") as second:
        ledger = Ledger(second)
        order = ledger.record_order(instrument_id=instrument.id, mode="paper", side="buy",
                                    order_type="limit", size=D(1), limit_price=D(10))
        ledger.record_fill(order=order, price=D(10), size=D(1), liquidity="taker", fill_ts=NOW,
                           fee=D(0), usd_gbp_rate=D(".8"))
        second.commit()
    assert required_instrument_ids(session) == {instrument.id}
    assert session.scalar(select(func.sum(Fill.size)).where(Fill.strategy_id.is_(None))) == 1
