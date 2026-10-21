import calendar
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
from types import SimpleNamespace
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tradingbot.backtest.holdout import HoldoutSplit, strategy_identity
from tradingbot.connectors.cash import NEW_YORK
from tradingbot.data.loader import local_engine
from tradingbot.db.models import Instrument, Market, Strategy, Venue, Trial, Incident
from tradingbot.research import c03_total_return as c03
from tradingbot.strategy.c03_momentum import CrossAssetMomentum, SYMBOLS
from tradingbot.strategy.interface import MarketEvent


def source(gap=False):
    days = []
    for i in range(13):
        year, month = 2020+i//12, 1+i%12
        day = date(year,month,calendar.monthrange(year,month)[1])
        while day.weekday()>4: day -= timedelta(days=1)
        days.append(day)
    days += [date(2021,2,d) for d in [1,2,3]]
    rows = []
    for i, day in enumerate(days):
        quotes = {}
        for symbol, growth in zip(SYMBOLS,['1','.1','.8','0','.05']):
            close = D(100)+i*D(growth)
            if gap and day >= date(2021,2,3): close = D(20)
            factor = D('.5') if i<14 else D('.51')
            quotes[symbol] = {'open':str(close), 'close':str(close), 'factor':str(factor),
                'raw_open':str(close/factor), 'raw_close':str(close/factor)}
        opened = datetime(day.year,day.month,day.day,9,30,tzinfo=NEW_YORK)
        rows.append({'date':str(day), 'opens_at':opened.isoformat(),
            'closes_at':opened.replace(hour=16,minute=0).isoformat(),
            'conservative_cash_release':(opened+timedelta(days=2)).isoformat(), 'quotes':quotes})
    return {'sha256':'synthetic-'+uuid.uuid4().hex,'prices':rows}


@pytest.fixture
def db():
    with local_engine().connect() as conn:
        tx=conn.begin()
        with Session(conn,expire_on_commit=False,join_transaction_mode='create_savepoint') as session:
            yield session
        tx.rollback()


def fx():
    return SimpleNamespace(at=lambda ts:(D('.75'),ts.date()-timedelta(days=1)),source_hash='synthetic',source_url='synthetic')


def setup(db,data,variant='top-two'):
    suffix=uuid.uuid4().hex
    venue=db.scalar(select(Venue).where(Venue.key=='alpaca'))
    strategy=Strategy(key='test-c03-'+suffix,name='Synthetic C03',status='backtest',allocation_usd=D(140))
    db.add(strategy);db.flush()
    ids={}
    for symbol in SYMBOLS:
        market=Market(venue_id=venue.id,external_id='test-c03-'+suffix+symbol,market_type='equity')
        db.add(market);db.flush()
        inst=Instrument(venue_id=venue.id,market_id=market.id,external_id='test-c03-'+suffix+symbol,
            instrument_type='equity',symbol=symbol,currency='USD',contract_multiplier=D(1))
        db.add(inst);db.flush();ids[symbol]=inst.id
    bot=CrossAssetMomentum(c03.strategy_params(data,ids,variant))
    runtime=c03.C03Backtester(db,strategy=bot,strategy_id=strategy.id,source=data,fx=fx())
    return runtime,bot


def split():
    return HoldoutSplit('test-c03-'+uuid.uuid4().hex,datetime(2020,1,1,tzinfo=UTC),datetime(2023,1,1,tzinfo=UTC))


def test_shared_ledger_total_return_and_terminal_liquidation(db,monkeypatch):
    data,partition=source(),split()
    runtime,bot=setup(db,data)
    monkeypatch.setattr(c03,'split_for',lambda _:partition)
    observed=[]
    result=runtime.run(c03.events(data,bot.params,10,False,observed),split=partition)
    metrics,trips,fills=c03.finish_metrics(db,result,runtime,expected_trips=2)
    assert result.fills==4 and result.orders_rejected==0
    assert bot.decisions[0]['date']=='2021-01-29'
    assert bot.decisions[0]['selected']==['SPY','GLD']
    assert fills[0].fill_ts.astimezone(NEW_YORK).date()==date(2021,2,1)
    assert len(runtime.cash[0])==4  # no additional cash distribution credits
    assert all(f.metadata_['research']['source']=='c03_total_return_equivalent' for f in fills)
    assert all(not f.metadata_['research']['separate_dividend_credit'] for f in fills)
    detail=c03.diagnostics(bot,observed,trips,fills,runtime)
    assert detail['terminal_liquidation_fills']==2
    assert detail['luck']['exit_month_clusters']==1 and detail['luck']['p_value'] is None
    assert D(detail['benchmarks']['equal_weight_buy_hold']['total_return'])>0


def test_complete_mark_batch_avoids_false_intrafund_halt(db):
    data=source();runtime,bot=setup(db,data)
    ids=bot.params['instrument_ids']
    a,b=ids['SPY'],ids['GLD']
    runtime.positions={a:(D('.7'),D(100)),b:(D('.7'),D(100))}
    runtime.marks={i:D(100) for i in ids.values()}
    marks={str(i):str(100) for i in ids.values()}
    marks[str(a)],marks[str(b)]='20','180'
    stamp=datetime(2021,2,2,9,30,tzinfo=NEW_YORK)
    event=MarketEvent.quote(a,stamp,mid=D(20),meta={'phase':'observe_open','factor':'.5',
        'batch_marks':marks,'batch_last':False})
    runtime.observe(event)
    assert runtime.equity()==140 and not runtime.killed and not runtime.daily_halted
    bad=MarketEvent.quote(a,stamp,mid=D(20),meta={**event.meta,'batch_marks':{str(a):'20'}})
    with pytest.raises(ValueError,match='incomplete'):
        runtime.observe(bad)


def test_simultaneous_gap_trips_unchanged_limits_and_retains_positions(db,monkeypatch):
    data,partition=source(True),split()
    runtime,bot=setup(db,data)
    monkeypatch.setattr(c03,'split_for',lambda _:partition)
    result=runtime.run(c03.events(data,bot.params,10,False,[]),split=partition)
    assert runtime.killed and runtime.daily_halted
    assert {x['kind'] for x in runtime.halt_events}=={'per_strategy_kill','global_daily_halt'}
    assert result.fills==2 and result.orders_rejected==2


def test_intraday_cutoff_keeps_all_later_closes_out(monkeypatch):
    data=source()
    partition=HoldoutSplit('test-c03-intraday',datetime(2021,2,3,tzinfo=UTC),datetime(2021,2,4,6,tzinfo=UTC))
    assert partition.holdout_start==datetime(2021,2,3,21,tzinfo=UTC)
    monkeypatch.setattr(c03,'split_for',lambda _:partition)
    params=c03.strategy_params(data,dict(zip(SYMBOLS,range(1,6))),'top-one')
    feed=list(c03.events(data,params,10,False,[]))
    assert len(feed)==15 and all(e.meta['terminal_open'] for e in feed)
    assert not any(e.meta['phase']=='close' for e in feed)


def test_final_claim_precedes_any_feed_consumption(db,monkeypatch):
    from tradingbot.backtest import engine
    data,partition=source(),split();runtime,bot=setup(db,data);observed=[]
    def refuse(*args,**kwargs):
        assert not observed
        raise ValueError('test final refused')
    monkeypatch.setattr(engine,'claim_final',refuse)
    with pytest.raises(ValueError,match='final refused'):
        runtime.run(c03.events(data,bot.params,10,True,observed),split=partition,final_holdout=True)
    assert not observed


def test_wrong_frozen_final_version_is_logged_without_feed(db,monkeypatch):
    data,partition=source(),split()
    monkeypatch.setattr(c03,'require_committed',lambda:'synthetic')
    monkeypatch.setattr(c03,'split_for',lambda _:partition)
    monkeypatch.setattr(c03,'ReferenceFX',lambda _:fx())
    monkeypatch.setattr(c03,'CaptureDiskBudget',lambda _:SimpleNamespace(check=lambda:None))
    def forbidden(*args): raise AssertionError('feed must not be constructed')
    monkeypatch.setattr(c03,'events',forbidden)
    result=c03.run_variant(db,data,'top-one',10,final=True,expected_version='wrong')
    assert result['status']=='failed' and not result['final_holdout']
    assert 'committed selected version' in result['error']
    assert db.get(Trial,result['trial_id']).params['final_feed_consumed'] is False


def test_duplicate_final_preflight_records_incident(db,monkeypatch):
    data=source();key=f'c03-tr-{data["sha256"][:12]}-top-one-10-final'
    strategy=Strategy(key=key,name='Synthetic old final',status='backtest',allocation_usd=140)
    db.add(strategy);db.flush()
    monkeypatch.setattr(c03,'require_committed',lambda:'synthetic')
    with pytest.raises(ValueError,match='already attempted'):
        c03.run_variant(db,data,'top-one',10,final=True,expected_version='synthetic')
    incident=db.scalar(select(Incident).where(Incident.details['requested_strategy_id'].as_integer()==strategy.id))
    assert incident.details['kind']=='holdout_reuse'
