from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
from types import SimpleNamespace
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tradingbot.backtest.holdout import HoldoutSplit
from tradingbot.connectors.cash import NEW_YORK
from tradingbot.data.loader import local_engine
from tradingbot.db.models import Instrument, Market, Strategy, Venue, Trial, Incident
from tradingbot.research import c10_total_return as c10
from tradingbot.strategy.c10_month_end import TreasuryMonthEnd


def source(exit_price='110'):
    days=[date(2026,2,2)+timedelta(days=i) for i in range(33)]
    days=[d for d in days if d.weekday()<5 and d!=date(2026,2,16)]
    rows=[]
    for i,day in enumerate(days):
        price=D(exit_price if day>=date(2026,3,2) else '100')
        factor=D('.5' if day<date(2026,2,27) else '.51')
        opened=datetime(day.year,day.month,day.day,9,30,tzinfo=NEW_YORK)
        rows.append({'date':str(day),'opens_at':opened.isoformat(),
            'closes_at':opened.replace(hour=16,minute=0).isoformat(),
            'conservative_cash_release':(opened+timedelta(days=2)).isoformat(),
            'quote':{'open':str(price),'close':str(price),'factor':str(factor),
                     'raw_open':str(price/factor),'raw_close':str(price/factor)}})
    return {'sha256':'synthetic-'+uuid.uuid4().hex,'prices':rows,'unexpected_closures':[]}


@pytest.fixture
def db():
    with local_engine().connect() as conn:
        tx=conn.begin()
        with Session(conn,expire_on_commit=False,join_transaction_mode='create_savepoint') as session:
            yield session
        tx.rollback()


def fx():
    return SimpleNamespace(at=lambda ts:(D('.75'),ts.date()-timedelta(days=1)),source_hash='synthetic',source_url='synthetic')


def setup(db,data):
    suffix=uuid.uuid4().hex
    venue=db.scalar(select(Venue).where(Venue.key=='alpaca'))
    strategy=Strategy(key='test-c10-'+suffix,name='Synthetic C10',status='backtest',allocation_usd=D(140))
    market=Market(venue_id=venue.id,external_id='test-c10-'+suffix,market_type='equity')
    db.add_all([strategy,market]);db.flush()
    inst=Instrument(venue_id=venue.id,market_id=market.id,external_id='test-c10-'+suffix,
        instrument_type='equity',symbol='TLT',currency='USD',contract_multiplier=D(1))
    db.add(inst);db.flush()
    bot=TreasuryMonthEnd({'instrument_id':inst.id,'slot_usd':'140','windows':c10.windows(data,'3')[0]})
    runtime=c10.C10Backtester(db,strategy=bot,strategy_id=strategy.id,source=data,fx=fx())
    return runtime,bot


def split():
    return HoldoutSplit('test-c10-'+uuid.uuid4().hex,datetime(2026,1,1,tzinfo=UTC),datetime(2027,1,1,tzinfo=UTC))


def calendar_source(start, end, excluded):
    rows=[]
    while start<=end:
        if start.weekday()<5 and str(start) not in excluded:
            rows.append({'date':str(start)})
        start+=timedelta(days=1)
    return {'prices':rows}


def test_sandy_keeps_original_ranked_entry_and_fixed_exit():
    data=calendar_source(date(2012,10,1),date(2012,11,30),{'2012-10-29','2012-10-30','2012-11-22'})
    third,skips=c10.windows(data,'3');fifth,_=c10.windows(data,'5')
    assert (third[0]['decision'],third[0]['planned_entry'],third[0]['entry'],third[0]['exit'])==('2012-10-26','2012-10-29','2012-10-31','2012-11-01')
    assert (fifth[0]['decision'],fifth[0]['planned_entry'],fifth[0]['entry'])==('2012-10-24','2012-10-25','2012-10-25')
    assert third[0]['closure_entry_delay'] and not fifth[0]['closure_entry_delay']
    assert skips==[{'id':'month:2012-11','reason':'next-month source exit unavailable'}]


def test_ford_exit_rolls_without_changing_december_entry():
    data=calendar_source(date(2006,12,1),date(2007,1,31),{'2006-12-25','2007-01-01','2007-01-02','2007-01-15'})
    third,_=c10.windows(data,'3');fifth,_=c10.windows(data,'5')
    assert (third[0]['entry'],fifth[0]['entry'])==('2006-12-27','2006-12-22')
    assert third[0]['planned_exit']=='2007-01-02' and third[0]['exit']=='2007-01-03'
    assert third[0]['closure_exit_delay']


def test_invalid_calendar_is_rejected_and_boundary_month_stays_untraded():
    data=source();planned,skips=c10.windows(data,'3')
    assert len(planned)==1 and planned[0]['entry']=='2026-02-25' and planned[0]['exit']=='2026-03-02'
    assert skips[0]['id']=='month:2026-03'
    with pytest.raises(ValueError,match='variants'):
        c10.windows(data,'4')
    data['prices'].append(data['prices'][-1])
    with pytest.raises(ValueError,match='duplicates'):
        c10.windows(data,'3')
    data=source();data['unexpected_closures']=['2026-02-25']
    with pytest.raises(ValueError,match='real price session'):
        c10.windows(data,'3')


def test_market_beta_uses_returns_and_flat_strategy_has_no_correlation():
    from tradingbot.strategy.interface import MarketEvent
    times=[datetime(2026,2,d,16,tzinfo=NEW_YORK) for d in (2,3,4,5)]
    prices=[D(100),D(110),D(105),D(120)]
    events=[MarketEvent.quote(1,t,mid=p,meta={'phase':'close'}) for t,p in zip(times,prices)]
    result=c10.market_beta(events,[(t,p*D('1.4')) for t,p in zip(times,prices)])
    assert result['observations']==3 and D(result['beta'])==1 and D(result['correlation'])==1
    flat=c10.market_beta(events,[(t,D(140)) for t in times])
    assert D(flat['beta'])==0 and flat['correlation'] is None


def test_overlap_excludes_shared_endpoint_and_names_potential_c06_exposure():
    from tradingbot.connectors.cash import MarketSession
    rows=source()['prices']
    sessions={date.fromisoformat(r['date']):MarketSession(date.fromisoformat(r['date']),
        date.fromisoformat(r['date']),datetime.fromisoformat(r['opens_at']),datetime.fromisoformat(r['closes_at'])) for r in rows}
    def stamp(day): return datetime.fromisoformat(day+'T09:30:00').replace(tzinfo=NEW_YORK)
    trips=[SimpleNamespace(entry_ts=stamp('2026-02-25'),exit_ts=stamp('2026-02-27')),
           SimpleNamespace(entry_ts=stamp('2026-02-27'),exit_ts=stamp('2026-03-02'))]
    result=c10.calendar_overlap(sessions,trips,[])
    assert result['round_trips']==2 and result['strategy6']==2 and result['c06_potential']==1
    assert result['c09_five_session']==result['c09_ten_session']==0


def test_shared_ledger_preserves_raw_share_fees_without_dividend_cash(db,monkeypatch):
    data,partition=source(),split();runtime,bot=setup(db,data)
    monkeypatch.setattr(c10,'split_for',lambda _:partition);observed=[]
    result=runtime.run(c10.events(data,bot.params,10,False,observed),split=partition)
    metrics,trips,fills=c10.finish_metrics(db,result,runtime,expected_trips=1)
    assert result.orders_rejected==0 and metrics['net_usd']>0 and len(runtime.cash[0])==2
    assert all(f.metadata_['research']['month_window_id']=='month:2026-02' for f in fills)
    assert all(not f.metadata_['research']['separate_dividend_credit'] for f in fills)
    assert D(fills[0].metadata_['research']['fee']['raw_share_equivalent'])==fills[0].size*D('.5')
    assert D(fills[1].metadata_['research']['fee']['raw_share_equivalent'])==fills[1].size*D('.51')
    detail=c10.diagnostics(bot,observed,trips,fills,runtime)
    assert detail['luck']['exit_month_clusters']==1 and detail['luck']['p_value'] is None
    assert detail['terminal_liquidation_fills']==0


def test_real_gap_keeps_kill_and_daily_halt_exit_veto(db,monkeypatch):
    data,partition=source('30'),split();runtime,bot=setup(db,data)
    monkeypatch.setattr(c10,'split_for',lambda _:partition)
    result=runtime.run(c10.events(data,bot.params,10,False,[]),split=partition)
    assert runtime.killed and {h['kind'] for h in runtime.halt_events}=={'per_strategy_kill','global_daily_halt'}
    assert result.fills==1 and result.orders_rejected==2


def test_partition_excludes_incomplete_window_and_later_close(monkeypatch):
    data=source()
    partition=HoldoutSplit('test-c10-cutoff',datetime(2026,2,13,tzinfo=UTC),datetime(2026,2,14,6,tzinfo=UTC))
    monkeypatch.setattr(c10,'split_for',lambda _:partition)
    params={'instrument_id':1,'windows':c10.windows(data,'3')[0]}
    events=list(c10.events(data,params,10,False,[]))
    assert len(events)==1 and events[0].meta['terminal_open'] and not events[0].meta['admitted_windows']


def test_final_claim_precedes_feed(db,monkeypatch):
    from tradingbot.backtest import engine
    data,partition=source(),split();runtime,bot=setup(db,data);observed=[]
    def refuse(*args,**kwargs):
        assert not observed
        raise ValueError('test final refused')
    monkeypatch.setattr(engine,'claim_final',refuse)
    with pytest.raises(ValueError,match='final refused'):
        runtime.run(c10.events(data,bot.params,10,True,observed),split=partition,final_holdout=True)
    assert not observed


def test_wrong_frozen_version_fails_before_feed_and_records_trial(db,monkeypatch):
    data,partition=source(),split()
    monkeypatch.setattr(c10,'require_committed',lambda:'synthetic')
    monkeypatch.setattr(c10,'split_for',lambda _:partition)
    monkeypatch.setattr(c10,'ReferenceFX',lambda _:fx())
    monkeypatch.setattr(c10,'CaptureDiskBudget',lambda _:SimpleNamespace(check=lambda:None))
    def forbidden(*args): raise AssertionError('feed must not be built')
    monkeypatch.setattr(c10,'events',forbidden)
    result=c10.run_variant(db,data,'3',10,final=True,expected_version='wrong')
    assert result['status']=='failed' and not result['final_holdout']
    assert 'committed selected version' in result['error']
    assert db.get(Trial,result['trial_id']).params['final_feed_consumed'] is False


def test_duplicate_final_is_an_incident_before_feed(db,monkeypatch):
    data=source();key=f'c10-tr-{data["sha256"][:12]}-3-10-final'
    strategy=Strategy(key=key,name='Synthetic old C10 final',status='backtest',allocation_usd=140)
    db.add(strategy);db.flush()
    monkeypatch.setattr(c10,'require_committed',lambda:'synthetic')
    with pytest.raises(ValueError,match='already attempted'):
        c10.run_variant(db,data,'3',10,final=True,expected_version='synthetic')
    incident=db.scalar(select(Incident).where(Incident.details['requested_strategy_id'].as_integer()==strategy.id))
    assert incident.details['kind']=='holdout_reuse'
