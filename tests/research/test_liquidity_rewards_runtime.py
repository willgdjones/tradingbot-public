from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
import json
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from tradingbot.db.models import Fill, FxRate, Instrument, Market, Order, Quote, Strategy, Trade, Trial, Venue
from tradingbot.db.seed import seed
from tradingbot.db.session import get_engine
from tradingbot.paper import PaperEngine
from tradingbot.paper.feed import quote_event, trade_event
from tradingbot.research.liquidity_rewards import WithFillReceipts, book_from_response, discovery_summary, public_programs, record_readiness_failure
from tradingbot.strategy.liquidity_rewards import LiquidityRewards


@pytest.fixture
def session():
    seed()
    connection = get_engine().connect()
    outer = connection.begin()
    s = Session(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
    try:
        s.execute(delete(FxRate))  # rollback-only isolation from real ECB rows
        yield s
    finally:
        s.close()
        assert outer.is_active
        outer.rollback()
        connection.close()


def test_real_paper_engine_receipts_stop_after_first_trade_through(session):
    now = [datetime(2026, 9, 30, 18, tzinfo=timezone.utc)]
    venue = session.scalar(select(Venue).where(Venue.key == "polymarket_us"))
    strategy = Strategy(key="reward-test-" + uuid4().hex, name="Rewards test", venue_id=venue.id,
                        status="paper", allocation_usd=D(100))
    market = Market(venue_id=venue.id, external_id="reward-test-" + uuid4().hex, category="crypto", market_type="binary")
    session.add_all([strategy, market]); session.flush()
    instrument = Instrument(venue_id=venue.id, market_id=market.id, external_id=market.external_id + ":yes",
                            instrument_type="binary_yes", currency="USD", contract_multiplier=D(1))
    session.add_all([instrument, FxRate(base="USD", quote="GBP", ts=now[0] - timedelta(days=1), rate=D(".8"), source="reward-test")])
    session.flush()
    params = {"markets": {str(instrument.id): {"market_id": market.id, "reviewed_non_sports": True,
        "insider_exposed": False, "review_note": "test-only", "selected": True, "ranked_at": now[0].isoformat(),
        "minimum_quantity": ".01", "events_reviewed_through": "2026-10-01T04:00:00Z", "event_times": [],
        "terms": {"program_id": "test", "start": "2026-09-30T04:00:00Z", "end": "2026-10-01T04:00:00Z",
            "observed_at": now[0].isoformat(), "pool": "100", "target": "100", "discount": ".3", "tick": ".01",
            "status": "active", "pool_scope": "verified_market_period"}}}}
    core = LiquidityRewards(params)
    adapter = WithFillReceipts(core, session, strategy_id=strategy.id)
    engine = PaperEngine(session, adapter, strategy_id=strategy.id, instrument_ids=[instrument.id], now=lambda: now[0])
    engine.start()
    now[0] += timedelta(seconds=1)
    row = Quote(instrument_id=instrument.id, time=now[0], bid=D(".49"), ask=D(".51"), metadata_={"source": "market_data",
        "full_book": {"state": "open", "observed_at": now[0].isoformat(), "bids": [[".49", "100"]], "asks": [[".51", "100"]]}})
    session.add(row); session.commit()
    engine.process(quote_event(row))
    assert len(engine.ctx.resting_tags()) == 2
    now[0] += timedelta(seconds=1)
    tape = Trade(instrument_id=instrument.id, time=now[0], price=D(".48"), size=D(2), aggressor_side="sell",
                 external_trade_id="reward-test-trade", metadata_={"source": "trade", "trade_time": now[0].isoformat()})
    session.add(tape); session.commit()
    engine.process(trade_event(tape))
    assert engine.ctx.position(instrument.id) == 2
    assert engine.ctx.resting_tags() == ()
    assert not core.execution_unknown and len(core.fill_times[instrument.id]) == 1
    fills = list(session.scalars(select(Fill).where(Fill.trial_id == engine.trial_id)))
    assert len(fills) == 1 and fills[0].price == D(".49") and fills[0].usd_gbp_rate == D(".8")
    assert not any("reward_income" in (f.metadata_ or {}) for f in fills)


def test_readiness_failure_logged_once_without_promoting_or_faking_profit(session):
    now = datetime(2026, 9, 30, 18, tzinfo=timezone.utc)
    snapshot = {"html_sha256": "test-" + uuid4().hex, "program_groups": 139, "non_sports_groups": 21}
    strategy = session.scalar(select(Strategy).where(Strategy.key == "rewards"))
    old_status, old_allocation = strategy.status, strategy.allocation_usd
    before = session.scalar(select(func.count()).select_from(Trial).where(Trial.strategy_id == strategy.id))
    trial = record_readiness_failure(session, observed_at=now, snapshot=snapshot, git_commit="test-only")
    assert record_readiness_failure(session, observed_at=now, snapshot=snapshot, git_commit="test-only").id == trial.id
    assert trial.status == "failed" and trial.pnl_after_fees is None and trial.luck_p_value is None
    assert trial.max_drawdown is None and trial.trade_count is None
    assert (strategy.status, strategy.allocation_usd) == (old_status, old_allocation)
    assert session.scalar(select(func.count()).select_from(Trial).where(Trial.strategy_id == strategy.id)) == before + 1
    assert session.scalar(select(Order.id).where(Order.trial_id == trial.id)) is None


def test_public_hydration_is_only_discovery_data():
    rows = [{"programId": "example", "category": "CRY", "rewardPool": 10, "symbols": [{"slug": "one"}]}]
    payload = '27:["$","$L3",null,' + json.dumps({"programs": rows}) + ']'
    html = '<script>self.__next_f.push(' + json.dumps([1, payload]) + ')</script>'
    assert public_programs(html) == rows
    summary = discovery_summary(html, observed_at="2026-09-30T18:00:00Z")
    assert summary["non_sports_groups"] == 1 and not summary["account_eligibility_verified"]
    assert not summary["promoted"] and summary["symbol_occurrences"] == 1
    with pytest.raises(ValueError): public_programs('<script>throw new Error("do not execute")</script>')


def test_full_book_decoder_rejects_bbo_and_preserves_fractional_depth():
    raw = {"marketData": {"marketSlug": "example", "state": "MARKET_STATE_OPEN",
        "bids": [{"px": {"value": ".1234", "currency": "USD"}, "qty": ".1234567890"}], "offers": []}}
    book = book_from_response(raw, observed_at="2026-09-30T18:00:00Z")
    assert book["bids"] == [["0.1234", "0.1234567890"]]
    with pytest.raises(KeyError): book_from_response({"marketData": {"marketSlug": "example", "state": "MARKET_STATE_OPEN", "bestBid": {}}}, observed_at="2026-09-30T18:00:00Z")
