"""Postgres paper integration; all writes live inside a rolled-back savepoint."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from tradingbot.db.models import FxRate, Instrument, Market, Quote, Strategy as StrategyRow, Trade, Venue
from tradingbot.db.seed import seed
from tradingbot.db.session import get_engine
from tradingbot.paper import PaperEngine
from tradingbot.paper.feed import quote_event, trade_event
from tradingbot.strategy import Strategy


class Reactor(Strategy):
    key = "paper-test-reactor"

    def __init__(self):
        super().__init__({"test_variant": "strict"})
        self.intents, self.events, self.start_times = [], [], []

    def on_start(self, ctx):
        self.start_times.append(ctx.now)

    def on_event(self, ctx, event):
        self.events.append(event)
        intents, self.intents = self.intents, []
        return intents


@pytest.fixture(scope="session", autouse=True)
def paper_seed():
    seed()


@pytest.fixture
def session():
    connection = get_engine().connect()
    outer = connection.begin()
    sess = Session(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
    try:
        sess.execute(delete(FxRate))  # rollback-only isolation from real ECB rows
        yield sess
    finally:
        sess.close()
        assert outer.is_active, "Paper tests must not escape the rollback transaction"
        outer.rollback()
        connection.close()


class Setup:
    def __init__(self, session):
        self.session = session
        self.clock = [datetime(2026, 9, 30, 18, tzinfo=timezone.utc)]
        self.venue = session.scalar(select(Venue).where(Venue.key == "polymarket_us"))
        self.row = StrategyRow(key="paper-test-" + uuid4().hex, name="Paper test", venue_id=self.venue.id,
                              status="paper", allocation_usd=D(100))
        self.market = Market(venue_id=self.venue.id, external_id="paper-test-" + uuid4().hex,
                             category="economics", market_type="binary", status="open")
        session.add_all([self.row, self.market])
        session.flush()
        self.instrument = Instrument(venue_id=self.venue.id, market_id=self.market.id,
                     external_id="paper-test-" + uuid4().hex, instrument_type="binary_yes", currency="USD")
        session.add_all([self.instrument, FxRate(base="USD", quote="GBP", rate=D(".8"),
                          ts=self.clock[0] - timedelta(days=1), source="paper-test")])
        session.flush()
        self.strategy = Reactor()
        self.engine = self.new_engine()
        self.engine.start()

    def new_engine(self, strategy=None):
        return PaperEngine(self.session, strategy or self.strategy, strategy_id=self.row.id,
                           instrument_ids=[self.instrument.id], now=lambda: self.clock[0])

    def quote(self, *, seconds=1, source="market_data", **kw):
        self.clock[0] += timedelta(seconds=seconds)
        defaults = {"bid": D(".4"), "ask": D(".6"), "mid": D(".5"), "bid_size": D(20), "ask_size": D(20)}
        row = Quote(instrument_id=self.instrument.id, time=self.clock[0],
                    metadata_={"source": source}, **(defaults | kw))
        self.session.add(row)
        self.session.commit()
        return quote_event(row)

    def trade(self, *, seconds=1, price=".39", size="10", occurred=None, trade_id=None,
              source="trade", aggressor_side="sell"):
        self.clock[0] += timedelta(seconds=seconds)
        row = Trade(instrument_id=self.instrument.id, time=self.clock[0], price=D(price), size=D(size),
                    aggressor_side=aggressor_side, external_trade_id=trade_id,
                    metadata_={"source": source, "trade_time": (occurred or self.clock[0]).isoformat()})
        self.session.add(row)
        self.session.commit()
        return trade_event(row)


@pytest.fixture
def setup(session):
    return Setup(session)
