"""Executable review repros. Strict xfails describe known, filed defects."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tradingbot.db.models import FxRate, Instrument, Market, Position, Quote, Strategy as Row, Trade, Venue
from tradingbot.db.seed import seed
from tradingbot.db.session import get_engine
from tradingbot.paper import PaperEngine
from tradingbot.paper.feed import quote_event
from tradingbot.research.liquidity_rewards import WithFillReceipts
from tradingbot.risk import RiskEngine
from tradingbot.strategy import CancelOrder, PlaceOrder, Strategy
from tradingbot.strategy.liquidity_rewards import LiquidityRewards


@pytest.fixture
def session():
    seed()
    connection = get_engine().connect()
    outer = connection.begin()
    s = Session(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
    try:
        yield s
    finally:
        s.close()
        assert outer.is_active
        outer.rollback()
        connection.close()


def universe(s):
    venue = s.scalar(select(Venue).where(Venue.key == "polymarket_us"))
    key = "review-" + uuid4().hex
    row = Row(key=key, name=key, venue_id=venue.id, status="paper", allocation_usd=D(140))
    market = Market(venue_id=venue.id, external_id=key, category="crypto", market_type="binary")
    s.add_all([row, market]); s.flush()
    instrument = Instrument(venue_id=venue.id, market_id=market.id, external_id=key + ":yes",
                            instrument_type="binary_yes", currency="USD", contract_multiplier=D(1))
    s.add(instrument); s.flush()
    return row, market, instrument


def quote(s, iid, at, bid=".49", ask=".51"):
    row = Quote(instrument_id=iid, time=at, bid=D(bid), ask=D(ask),
                metadata_={"source": "market_data", "full_book": {"state": "open",
                    "observed_at": at.isoformat(), "bids": [[bid, "100"]], "asks": [[ask, "100"]]}})
    s.add(row); s.commit()
    return row


def test_daily_halt_counts_loss_on_overnight_positions(session):
    now = datetime(2031, 1, 15, 18, tzinfo=timezone.utc)
    marks = {}
    for _ in range(3):
        row, _, instrument = universe(session)
        session.add(Position(strategy_id=row.id, mode="paper", instrument_id=instrument.id,
            quantity=D(50), avg_price=D(".5"), cost_basis=D(25), opened_ts=now - timedelta(days=1)))
        quote(session, instrument.id, now - timedelta(days=1), ".5", ".5")
        marks[instrument.id] = D(".16")  # -$17 today, -$51 across three markets
    risk = RiskEngine(session)
    risk.refresh_halts("paper", marks, now=now)
    assert risk.daily_halt_active("paper", now.date())


class CancelOnLowerQuote(Strategy):
    key = "review-ordering"

    def on_start(self, ctx):
        self.placed = False

    def on_event(self, ctx, event):
        if not self.placed:
            self.placed = True
            return [PlaceOrder(event.instrument_id, "buy", D(2), limit_price=D(".49"), tag="bid")]
        if event.is_quote and event.bid < D(".49"):
            return [CancelOrder("bid")]
        return []


def test_backlog_does_not_fill_an_order_after_its_cancellation_quote(session):
    now = [datetime(2031, 1, 15, 18, tzinfo=timezone.utc)]
    row, _, instrument = universe(session)
    session.add(FxRate(base="USD", quote="GBP", ts=now[0], rate=D(".8"), source="review"))
    engine = PaperEngine(session, CancelOnLowerQuote(), strategy_id=row.id,
                         instrument_ids=[instrument.id], now=lambda: now[0])
    engine.start()
    engine.process(quote_event(quote(session, instrument.id, now[0])))
    quote(session, instrument.id, now[0] + timedelta(seconds=1))
    quote(session, instrument.id, now[0] + timedelta(seconds=2), ".47", ".51")
    now[0] += timedelta(seconds=3)
    session.add(Trade(instrument_id=instrument.id, time=now[0], price=D(".48"), size=D(2),
        aggressor_side="sell", external_trade_id=uuid4().hex,
        metadata_={"source": "trade", "trade_time": now[0].isoformat()}))
    session.commit()
    engine.poll(batch_size=1)
    engine.poll(batch_size=1)
    engine.poll(batch_size=1)  # consume the later trade after cancellation
    assert engine.ctx.position(instrument.id) == 0
    assert engine.ctx.resting_tags() == ()


@pytest.mark.xfail(strict=True, reason="Quiet-feed tick never invokes scheduled rewards cancellation")
def test_running_rewards_engine_pulls_quotes_before_scheduled_event_without_feed(session):
    now = [datetime(2031, 1, 15, 18, tzinfo=timezone.utc)]
    row, market, instrument = universe(session)
    end = now[0] + timedelta(hours=6)
    event = now[0] + timedelta(minutes=15)
    params = {"markets": {str(instrument.id): {"market_id": market.id,
        "reviewed_non_sports": True, "insider_exposed": False, "review_note": "test",
        "selected": True, "ranked_at": now[0].isoformat(), "minimum_quantity": ".01",
        "events_reviewed_through": end.isoformat(), "event_times": [event.isoformat()],
        "terms": {"program_id": "test", "start": now[0].isoformat(), "end": end.isoformat(),
            "observed_at": now[0].isoformat(), "pool": "100", "target": "100", "discount": ".3",
            "tick": ".01", "status": "active", "pool_scope": "verified_market_period"}}}}
    strategy = WithFillReceipts(LiquidityRewards(params), session, strategy_id=row.id)
    engine = PaperEngine(session, strategy, strategy_id=row.id, instrument_ids=[instrument.id], now=lambda: now[0])
    engine.start()
    engine.process(quote_event(quote(session, instrument.id, now[0])))
    assert len(engine.ctx.resting_tags()) == 2
    now[0] = event - timedelta(seconds=299)
    engine.tick()
    assert engine.ctx.resting_tags() == ()
