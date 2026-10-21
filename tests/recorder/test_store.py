"""DB-backed store tests: subscription resolution, writes, and the tie-in to the
risk engine's §6 staleness gate. Run inside a rolled-back transaction."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from tradingbot.db import enums
from tradingbot.db.models import Instrument, Market, Quote, Trade
from tradingbot.recorder.decode import QuoteObs, TradeObs
from tradingbot.recorder.store import DbSink, SubscriptionError, resolve_subscriptions
from tradingbot.risk.engine import RiskEngine
from tradingbot.risk.limits import STALE_DATA_MAX_SECONDS

TS = datetime(2026, 9, 30, 12, 0, 0, tzinfo=timezone.utc)


def test_resolve_by_market_slug_to_binary_yes(session, make_market):
    # Canonical loader mapping: markets.external_id == slug -> Yes (long) leg.
    slug, inst_id = make_market()
    assert resolve_subscriptions(session, [slug]) == {slug: inst_id}


def test_resolve_symbol_fallback_when_no_matching_market(session, pm_us_venue):
    # No market has this slug as external_id; an instrument carries it as symbol.
    slug = f"hand-seeded-{uuid.uuid4().hex[:8]}"
    market = Market(venue_id=pm_us_venue.id, external_id=f"other-{uuid.uuid4().hex[:8]}",
                    market_type=enums.MarketType.BINARY)
    session.add(market)
    session.flush()
    inst = Instrument(venue_id=pm_us_venue.id, market_id=market.id,
                      external_id=f"{slug}-tok", symbol=slug,
                      instrument_type=enums.InstrumentType.BINARY_YES, outcome="yes")
    session.add(inst)
    session.flush()
    assert resolve_subscriptions(session, [slug]) == {slug: inst.id}


def test_resolve_falls_back_to_market_slug_then_binary_yes(session, pm_us_venue):
    # Instrument whose symbol does NOT match the slug; only the market's
    # external_id does. Resolution should still find the binary_yes leg.
    slug = f"cond-{uuid.uuid4().hex[:8]}"
    market = Market(venue_id=pm_us_venue.id, external_id=slug,
                    market_type=enums.MarketType.BINARY)
    session.add(market)
    session.flush()
    yes = Instrument(venue_id=pm_us_venue.id, market_id=market.id,
                     external_id=f"{slug}-Y", symbol="something-else",
                     instrument_type=enums.InstrumentType.BINARY_YES, outcome="yes")
    no = Instrument(venue_id=pm_us_venue.id, market_id=market.id,
                    external_id=f"{slug}-N", symbol="no-side",
                    instrument_type=enums.InstrumentType.BINARY_NO, outcome="no")
    session.add_all([yes, no])
    session.flush()
    assert resolve_subscriptions(session, [slug]) == {slug: yes.id}


def test_resolve_unknown_slug_raises(session):
    with pytest.raises(SubscriptionError, match="no Polymarket US instrument"):
        resolve_subscriptions(session, ["does-not-exist-xyz"])


def test_write_quotes_persists_fields_and_metadata(session, make_market):
    slug, inst_id = make_market()
    sink = DbSink(session, {slug: inst_id})
    obs = QuoteObs(slug, TS, Decimal("0.40"), Decimal("0.44"),
                   Decimal("100"), Decimal("60"), Decimal("0.42"), Decimal("0.43"),
                   {"source": "market_data", "state": "MARKET_STATE_OPEN"})
    assert sink.write_quotes([obs]) == 1

    row = session.scalar(select(Quote).where(Quote.instrument_id == inst_id))
    assert row.bid == Decimal("0.40") and row.ask == Decimal("0.44")
    assert row.bid_size == Decimal("100") and row.ask_size == Decimal("60")
    assert row.mid == Decimal("0.42") and row.last == Decimal("0.43")
    assert row.metadata_ == {"source": "market_data", "state": "MARKET_STATE_OPEN"}
    assert row.time == TS


def test_write_trades_persists_fields(session, make_market):
    slug, inst_id = make_market()
    sink = DbSink(session, {slug: inst_id})
    obs = TradeObs(slug, TS, Decimal("0.51"), Decimal("30"), enums.Side.BUY, None,
                   {"source": "trade"})
    assert sink.write_trades([obs]) == 1

    row = session.scalar(select(Trade).where(Trade.instrument_id == inst_id))
    assert row.price == Decimal("0.51") and row.size == Decimal("30")
    assert row.aggressor_side == enums.Side.BUY
    assert row.metadata_ == {"source": "trade"}


def test_write_skips_unsubscribed_slug(session, make_market):
    slug, inst_id = make_market()
    sink = DbSink(session, {slug: inst_id})
    other = QuoteObs("not-subscribed", TS, Decimal("0.4"), Decimal("0.5"),
                     None, None, None, None, {})
    assert sink.write_quotes([other]) == 0
    assert session.scalar(select(Quote).where(Quote.instrument_id == inst_id)) is None


def test_written_quote_makes_the_risk_gate_read_fresh_then_stale(session, make_market):
    """The whole point: a recorder write is exactly what the §6 staleness gate
    reads. A fresh write reads fresh; the same row read 40 s later reads stale."""
    slug, inst_id = make_market()
    DbSink(session, {slug: inst_id}).write_quotes([
        QuoteObs(slug, TS, Decimal("0.4"), Decimal("0.5"), None, None,
                 Decimal("0.45"), None, {"source": "market_data"})
    ])
    risk = RiskEngine(session)

    fresh, age = risk.stale_data_check(inst_id, TS + timedelta(seconds=10))
    assert fresh is True and age == pytest.approx(10.0)

    stale, age = risk.stale_data_check(
        inst_id, TS + timedelta(seconds=STALE_DATA_MAX_SECONDS + 10))
    assert stale is False and age == pytest.approx(STALE_DATA_MAX_SECONDS + 10)
