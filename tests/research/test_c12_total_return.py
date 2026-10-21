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
from tradingbot.research import c12_total_return as c12
from tradingbot.strategy.c12_macro import ScheduledMacro


def source(exit_price='110'):
    days=[date(2026,2,2)+timedelta(days=i) for i in range(33)]
    days=[d for d in days if d.weekday()<5 and d!=date(2026,2,16)]
    rows=[]
    for i,day in enumerate(days):
        price=D(exit_price if day>=date(2026,2,17) else '100')
        factor=D('.5' if day<date(2026,2,13) else '.51')
        opened=datetime(day.year,day.month,day.day,9,30,tzinfo=NEW_YORK)
        rows.append({'date':str(day),'opens_at':opened.isoformat(),
            'closes_at':opened.replace(hour=16,minute=0).isoformat(),
            'conservative_cash_release':(opened+timedelta(days=2)).isoformat(),
            'quote':{'open':str(price),'close':str(price),'factor':str(factor),
                     'raw_open':str(price/factor),'raw_close':str(price/factor)}})
    return {'sha256':'synthetic-'+uuid.uuid4().hex,'prices':rows,'calendar':{
        'announcements':[{'family':'empsit','reference_month':'2026-01','announced_date':'2026-02-13',
            'available_at':'2026-01-09T13:30:00+00:00','source_sha256':'synthetic'}],
        'suspensions':[], 'fed':{'announcements':[{'meeting_id':'2026-01','announced_date':'2026-01-28',
            'available_at':'2025-08-01T04:00:00+00:00','source_sha256':'synthetic'}]}}}


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
    strategy=Strategy(key='test-c12-'+suffix,name='Synthetic C12',status='backtest',allocation_usd=D(140))
    market=Market(venue_id=venue.id,external_id='test-c12-'+suffix,market_type='equity')
    db.add_all([strategy,market]);db.flush()
    inst=Instrument(venue_id=venue.id,market_id=market.id,external_id='test-c12-'+suffix,
        instrument_type='equity',symbol='SPY',currency='USD',contract_multiplier=D(1))
    db.add(inst);db.flush()
    bot=ScheduledMacro({'instrument_id':inst.id,'slot_usd':'140','windows':c12.windows(data,'empsit')[0]})
    runtime=c12.C12Backtester(db,strategy=bot,strategy_id=strategy.id,source=data,fx=fx())
    return runtime,bot


def split():
    return HoldoutSplit('test-c12-'+uuid.uuid4().hex,datetime(2026,1,1,tzinfo=UTC),datetime(2027,1,1,tzinfo=UTC))


def test_shared_ledger_preserves_raw_share_fees_without_dividend_cash(db,monkeypatch):
    data,partition=source(),split();runtime,bot=setup(db,data)
    monkeypatch.setattr(c12,'split_for',lambda _:partition);observed=[]
    result=runtime.run(c12.events(data,bot.params,10,False,observed),split=partition)
    metrics,trips,fills=c12.finish_metrics(db,result,runtime,expected_trips=1)
    assert result.orders_rejected==0 and metrics['net_usd']>0 and len(runtime.cash[0])==2
    assert all(f.metadata_['research']['macro_window_id']=='empsit:2026-01@2026-02-13' for f in fills)
    assert all(not f.metadata_['research']['separate_dividend_credit'] for f in fills)
    assert D(fills[0].metadata_['research']['fee']['raw_share_equivalent'])==fills[0].size*D('.5')
    assert D(fills[1].metadata_['research']['fee']['raw_share_equivalent'])==fills[1].size*D('.51')
    detail=c12.diagnostics(bot,observed,trips,fills,runtime)
    assert detail['luck']['exit_month_clusters']==1 and detail['luck']['p_value'] is None
    assert detail['terminal_liquidation_fills']==0


def test_real_gap_keeps_kill_and_daily_halt_exit_veto(db,monkeypatch):
    data,partition=source('30'),split();runtime,bot=setup(db,data)
    monkeypatch.setattr(c12,'split_for',lambda _:partition)
    result=runtime.run(c12.events(data,bot.params,10,False,[]),split=partition)
    assert runtime.killed and {h['kind'] for h in runtime.halt_events}=={'per_strategy_kill','global_daily_halt'}
    assert result.fills==1 and result.orders_rejected==2


def test_partition_excludes_incomplete_window_and_later_close(monkeypatch):
    data=source()
    partition=HoldoutSplit('test-c12-cutoff',datetime(2026,2,13,tzinfo=UTC),datetime(2026,2,14,6,tzinfo=UTC))
    monkeypatch.setattr(c12,'split_for',lambda _:partition)
    params={'instrument_id':1,'windows':c12.windows(data,'empsit')[0]}
    events=list(c12.events(data,params,10,False,[]))
    assert len(events)==1 and events[0].meta['terminal_open'] and not events[0].meta['admitted_windows']


def test_final_claim_precedes_feed(db,monkeypatch):
    from tradingbot.backtest import engine
    data,partition=source(),split();runtime,bot=setup(db,data);observed=[]
    def refuse(*args,**kwargs):
        assert not observed
        raise ValueError('test final refused')
    monkeypatch.setattr(engine,'claim_final',refuse)
    with pytest.raises(ValueError,match='final refused'):
        runtime.run(c12.events(data,bot.params,10,True,observed),split=partition,final_holdout=True)
    assert not observed


def test_wrong_frozen_version_fails_before_feed_and_records_trial(db,monkeypatch):
    data,partition=source(),split()
    monkeypatch.setattr(c12,'require_committed',lambda:'synthetic')
    monkeypatch.setattr(c12,'split_for',lambda _:partition)
    monkeypatch.setattr(c12,'ReferenceFX',lambda _:fx())
    monkeypatch.setattr(c12,'CaptureDiskBudget',lambda _:SimpleNamespace(check=lambda:None))
    def forbidden(*args): raise AssertionError('feed must not be built')
    monkeypatch.setattr(c12,'events',forbidden)
    result=c12.run_variant(db,data,'empsit',10,final=True,expected_version='wrong')
    assert result['status']=='failed' and not result['final_holdout']
    assert 'committed selected version' in result['error']
    assert db.get(Trial,result['trial_id']).params['final_feed_consumed'] is False


def test_duplicate_final_is_an_incident_before_feed(db,monkeypatch):
    data=source();key=f'c12-tr-{data["sha256"][:12]}-empsit-10-0-final'
    strategy=Strategy(key=key,name='Synthetic old C12 final',status='backtest',allocation_usd=140)
    db.add(strategy);db.flush()
    monkeypatch.setattr(c12,'require_committed',lambda:'synthetic')
    with pytest.raises(ValueError,match='already attempted'):
        c12.run_variant(db,data,'empsit',10,final=True,expected_version='synthetic')
    incident=db.scalar(select(Incident).where(Incident.details['requested_strategy_id'].as_integer()==strategy.id))
    assert incident.details['kind']=='holdout_reuse'


def test_partition_does_not_warm_up_an_event_specific_signal(monkeypatch):
    data=source()
    partition=HoldoutSplit('test-c12-signal',datetime(2026,1,20,tzinfo=UTC),datetime(2027,1,1,tzinfo=UTC))
    monkeypatch.setattr(c12,'split_for',lambda _:partition)
    params={'instrument_id':1,'windows':c12.windows(data,'empsit')[0]}
    assert c12.shared.complete_window(params['windows'][0],{r['date']:r for r in data['prices']},partition,False)
    assert not any(e.meta['admitted_windows'] for e in c12.events(data,params,10,False,[]))


def test_shifted_control_cannot_request_a_final_before_strategy_creation(db,monkeypatch):
    monkeypatch.setattr(c12,'require_committed',lambda:'synthetic')
    with pytest.raises(ValueError,match='configuration'):
        c12.run_variant(db,source(),'empsit',10,control=True,final=True)
