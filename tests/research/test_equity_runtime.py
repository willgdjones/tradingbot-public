from datetime import date, datetime, timedelta
from decimal import Decimal as D
from types import SimpleNamespace
from zoneinfo import ZoneInfo
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tradingbot.connectors.cash import MarketSession
from tradingbot.data.loader import local_engine
from tradingbot.db.models import Fill, Instrument, Market, Strategy, Venue
from tradingbot.research.equity_runtime import EquityBacktester
from tradingbot.backtest.holdout import HoldoutSplit
from tradingbot.strategy.interface import MarketEvent, PlaceOrder, Strategy as Reactor

NY=ZoneInfo('America/New_York')
SPLIT=HoldoutSplit('test-equity-runtime-fixture',datetime(2026,10,8,tzinfo=NY),datetime(2026,10,18,tzinfo=NY))


@pytest.fixture
def db():
    with local_engine().connect() as connection:
        transaction=connection.begin()
        with Session(connection,expire_on_commit=False) as session:
            yield session
        transaction.rollback()


def setup(db,budget='140'):
    suffix=uuid.uuid4().hex[:10]
    venue=db.scalar(select(Venue).where(Venue.key=='alpaca'))
    market=Market(venue_id=venue.id,external_id='eq-test-'+suffix,market_type='equity')
    strategy=Strategy(key='eq-test-'+suffix,name='Equity test',status='backtest',allocation_usd=D(budget))
    db.add_all([market,strategy]);db.flush()
    instrument=Instrument(venue_id=venue.id,market_id=market.id,external_id='eq-test-'+suffix,
                          instrument_type='equity',symbol='SPY',currency='USD',contract_multiplier=D(1))
    db.add(instrument);db.flush()
    return instrument.id,strategy.id


class Actions(Reactor):
    key='test_actions'
    def on_event(self,ctx,event):
        side=event.meta.get('side')
        if side is None:return []
        return [PlaceOrder(instrument_id=event.instrument_id,side=side,size=D(event.meta.get('size','.04')),
                           order_type='market',intended_liquidity='taker')]


def fixtures(iid):
    days=[date(2026,10,8),date(2026,10,9),date(2026,10,12),date(2026,10,13)]
    settlements=[date(2026,10,9),date(2026,10,13),date(2026,10,13),date(2026,10,14)]
    calendar={d:MarketSession(d,s,datetime.combine(d,datetime.min.time(),NY)+timedelta(hours=9,minutes=30),datetime.combine(d,datetime.min.time(),NY)+timedelta(hours=16)) for d,s in zip(days,settlements)}
    fx=SimpleNamespace(at=lambda ts:(D('.75'),ts.date()-timedelta(days=1)),source_url='fixture',source_hash='test')
    def event(day,side,price='500',size='.04'):
        ts=calendar[days[day]].closes_at-timedelta(minutes=1)
        return MarketEvent.quote(iid,ts,bid=D(price),ask=D(price),mid=D(price),meta={'side':side,'size':size})
    return calendar,fx,event


def test_shared_engine_records_explicit_fees_fx_and_net_pnl(db):
    iid,sid=setup(db);calendar,fx,event=fixtures(iid)
    runtime=EquityBacktester(db,strategy=Actions(),strategy_id=sid,sessions=calendar,fx=fx)
    result=runtime.run([event(0,'buy'),event(1,'sell','505')],split=SPLIT)
    assert result.fills==2 and result.orders_rejected==0
    assert result.report['fees_total']==D('.04')
    assert result.report['pnl_after_fees']==D('.16')
    fills=list(db.scalars(select(Fill).where(Fill.trial_id==result.trial_id).order_by(Fill.fill_ts)))
    assert all(f.usd_gbp_rate==D('.75') for f in fills)
    assert fills[1].metadata_['research']['settlement_date']=='2026-10-13'
    assert runtime.max_drawdown>=D('.01')
    assert runtime.risk.stale_data_check(iid,event(1,'sell').time+timedelta(seconds=31))[0] is False
    assert runtime.risk.stale_data_check(iid,event(0,'buy').time)[0] is False


def test_settlement_holiday_blocks_reuse_until_api_date(db):
    iid,sid=setup(db,'20.01');calendar,fx,event=fixtures(iid)
    runtime=EquityBacktester(db,strategy=Actions(),strategy_id=sid,sessions=calendar,fx=fx,initial_cash=D('20.01'))
    result=runtime.run([event(0,'buy'),event(1,'sell','505'),event(2,'buy'),event(3,'buy')],split=SPLIT)
    assert result.fills==3 and result.orders_rejected==1


def test_risk_cap_and_no_short_guard_are_effective(db):
    iid,sid=setup(db);calendar,fx,event=fixtures(iid)
    runtime=EquityBacktester(db,strategy=Actions(),strategy_id=sid,sessions=calendar,fx=fx)
    result=runtime.run([event(0,'buy',size='.3'),event(1,'sell')],split=SPLIT)  # $150 > $140 slot cap (PRD §6)
    assert result.fills==0 and result.orders_rejected==2


def test_research_kill_is_retained_with_open_position_and_marked_pnl(db):
    from tradingbot.research.turn_of_month import finish_metrics
    iid,sid=setup(db,'20.01');calendar,fx,event=fixtures(iid)
    runtime=EquityBacktester(db,strategy=Actions(),strategy_id=sid,sessions=calendar,fx=fx,initial_cash=D('20.01'))
    result=runtime.run([event(0,'buy'),event(1,'sell','299')],split=SPLIT)
    assert runtime.killed and result.orders_rejected==1
    metrics,_,_=finish_metrics(db,result,runtime,allow_rejections=True,require_flat=False)
    assert metrics['open_positions'][str(iid)]['quantity']=='0.0400000000'
    assert metrics['unrealized_pnl_usd']==D('-8.04')
    assert metrics['ending_marked_equity_usd']==D('11.96')
    assert metrics['halt_events'][0]['kind']=='per_strategy_kill'
    assert db.get(Strategy,sid).status=='backtest'
