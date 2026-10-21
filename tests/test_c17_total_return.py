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
from tradingbot.research import c17_total_return as c17
from tradingbot.strategy.c17_credit import CreditSignal, SYMBOLS, credit_score
from tradingbot.strategy.interface import MarketEvent


def source(gap=False):
    days = [date(2020,1,2)+timedelta(days=i) for i in range(140)]
    days = [d for d in days if d.weekday()<5]
    rows = []
    for i,day in enumerate(days):
        quotes = {}
        for symbol in SYMBOLS:
            close = D(100)+D(i)/10 if symbol=='HYG' else D(100)
            if symbol=='SPY' and day==days[-1]: close=D(20 if gap else 110)
            factor = D('.5') if i<80 else D('.51')
            quotes[symbol] = {'open':str(close),'close':str(close),'factor':str(factor),
                'raw_open':str(close/factor),'raw_close':str(close/factor)}
        opened=datetime(day.year,day.month,day.day,9,30,tzinfo=NEW_YORK)
        rows.append({'date':str(day),'opens_at':opened.isoformat(),
            'closes_at':opened.replace(hour=16,minute=0).isoformat(),
            'conservative_cash_release':(opened+timedelta(days=2)).isoformat(),'quotes':quotes})
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


def setup(db,data,variant='63'):
    suffix=uuid.uuid4().hex
    venue=db.scalar(select(Venue).where(Venue.key=='alpaca'))
    strategy=Strategy(key='test-c17-'+suffix,name='Synthetic C17',status='backtest',allocation_usd=D(140))
    db.add(strategy);db.flush()
    ids={}
    for symbol in SYMBOLS:
        market=Market(venue_id=venue.id,external_id='test-c17-'+suffix+symbol,market_type='equity')
        db.add(market);db.flush()
        inst=Instrument(venue_id=venue.id,market_id=market.id,external_id='test-c17-'+suffix+symbol,
            instrument_type='equity',symbol=symbol,currency='USD',contract_multiplier=D(1))
        db.add(inst);db.flush();ids[symbol]=inst.id
    bot=CreditSignal(c17.strategy_params(data,ids,variant))
    runtime=c17.C17Backtester(db,strategy=bot,strategy_id=strategy.id,source=data,fx=fx())
    return runtime,bot


def split():
    return HoldoutSplit('test-c17-'+uuid.uuid4().hex,datetime(2020,1,1,tzinfo=UTC),datetime(2023,1,1,tzinfo=UTC))


def test_signal_exact_lookbacks_equality_and_reference_only():
    h={'HYG':[D(100)]*63,'IEF':[D(100)]*63}
    assert credit_score(h,'63') is None
    for values in h.values(): values.append(D(100))
    assert credit_score(h,'63')==0
    h['HYG'][0],h['IEF'][0]=D(80),D(90)
    assert credit_score(h,'63')==D(100)/80-D(100)/90
    assert credit_score(h,'126') is None
    with pytest.raises(ValueError,match='unequal'): credit_score({**h,'IEF':h['IEF'][:-1]},'63')
    with pytest.raises(ValueError,match='specification'): credit_score({**h,'SPY':[D(100)]*64},'63')
    with pytest.raises(ValueError,match='specification'): credit_score(h,'64')


def test_shared_ledger_terminal_flat_and_raw_equivalent_fees(db,monkeypatch):
    data,partition=source(),split();runtime,bot=setup(db,data)
    monkeypatch.setattr(c17,'split_for',lambda _:partition)
    observed=[]
    result=runtime.run(c17.events(data,bot.params,10,False,observed),split=partition)
    metrics,trips,fills=c17.finish_metrics(db,result,runtime,expected_trips=1)
    assert result.fills==2 and result.orders_rejected==0 and not any(q for q,_ in runtime.positions.values())
    assert bot.decisions[0]['date']=='2020-03-31'
    assert fills[0].fill_ts.astimezone(NEW_YORK).date()==date(2020,4,1)
    assert all(f.instrument_id==bot.ids['SPY'] for f in fills)
    assert len(runtime.cash[0])==2
    assert all(f.metadata_['research']['source']=='c17_total_return_equivalent' for f in fills)
    detail=c17.diagnostics(bot,observed,trips,fills,runtime)
    assert detail['terminal_liquidation_fills']==1 and detail['risk_on_months']==2
    assert detail['luck']['p_value'] is None and detail['luck']['exit_month_clusters']==1
    assert D(detail['benchmarks']['SPY_buy_hold']['total_return'])==D('.1')
    assert all(not f.metadata_['research']['separate_dividend_credit'] for f in fills)


def test_unchanged_kills_keep_rejected_terminal_and_inventory(db,monkeypatch):
    data,partition=source(True),split();runtime,bot=setup(db,data)
    monkeypatch.setattr(c17,'split_for',lambda _:partition)
    result=runtime.run(c17.events(data,bot.params,10,False,[]),split=partition)
    assert runtime.killed and runtime.daily_halted and runtime.positions
    assert {x['kind'] for x in runtime.halt_events}=={'per_strategy_kill','global_daily_halt'}
    assert result.orders_rejected==1 and result.fills==1


def test_intraday_cutoff_and_partition_warmup(db,monkeypatch):
    data=source();runtime,bot=setup(db,data)
    cutoff=datetime(2020,4,1,19,tzinfo=UTC)
    start=datetime(2020,1,1,tzinfo=UTC)
    partition=HoldoutSplit('test-c17-cutoff',start,start+(cutoff-start)*10/7)
    monkeypatch.setattr(c17,'split_for',lambda _:partition)
    feed=list(c17.events(data,bot.params,10,False,[]))
    assert all(e.time<partition.holdout_start for e in feed)
    terminal=[e for e in feed if e.meta.get('terminal_open')]
    assert len(terminal)==9 and terminal[0].time.astimezone(NEW_YORK).date()==date(2020,4,1)
    # A fresh final has no access to the pre-cutoff references.
    ctx=Context();bot.on_start(ctx)
    orders=[]
    for event in c17.events(data,bot.params,10,True,[]):
        ctx.books[event.instrument_id]=event.as_snapshot()
        orders.extend(bot.on_event(ctx,event))
    assert not bot.decisions and not orders


def test_final_admission_before_feed(db,monkeypatch):
    from tradingbot.backtest import engine
    data,partition=source(),split();runtime,bot=setup(db,data);observed=[]
    def refuse(*args,**kwargs):
        assert not observed
        raise ValueError('synthetic final refused')
    monkeypatch.setattr(engine,'claim_final',refuse)
    with pytest.raises(ValueError,match='final refused'):
        runtime.run(c17.events(data,bot.params,10,True,observed),split=partition,final_holdout=True)
    assert not observed


def test_mismatched_selected_version_logs_without_feed(db,monkeypatch):
    data,partition=source(),split()
    monkeypatch.setattr(c17,'require_committed',lambda:'synthetic')
    monkeypatch.setattr(c17,'split_for',lambda _:partition)
    monkeypatch.setattr(c17,'ReferenceFX',lambda _:fx())
    monkeypatch.setattr(c17,'CaptureDiskBudget',lambda _:SimpleNamespace(check=lambda:None))
    def forbidden(*args): raise AssertionError('feed must not be constructed')
    monkeypatch.setattr(c17,'events',forbidden)
    result=c17.run_variant(db,data,'63',10,final=True,expected_version='wrong')
    assert result['status']=='failed' and not result['final_holdout']
    assert 'committed selected version' in result['error']
    assert db.get(Trial,result['trial_id']).params['final_feed_consumed'] is False


def test_repeat_final_preflight_records_incident(db,monkeypatch):
    data=source();key=f'c17-tr-{data["sha256"][:12]}-63-10-final'
    strategy=Strategy(key=key,name='Synthetic old final',status='backtest',allocation_usd=140)
    db.add(strategy);db.flush()
    monkeypatch.setattr(c17,'require_committed',lambda:'synthetic')
    with pytest.raises(ValueError,match='already attempted'):
        c17.run_variant(db,data,'63',10,final=True,expected_version='synthetic')
    incident=db.scalar(select(Incident).where(Incident.details['requested_strategy_id'].as_integer()==strategy.id))
    assert incident.details['kind']=='holdout_reuse'


class Context:
    def __init__(self):
        self.books,self.quantities={},{}
        self.cash=self.equity=D(140)
    def snapshot(self,iid): return self.books.get(iid)
    def position(self,iid): return self.quantities.get(iid,D(0))
    def available_cash(self,iid): return self.cash
    def marked_equity(self): return self.equity


def pure():
    params=c17.strategy_params(source(),dict(zip(SYMBOLS,range(1,4))),'63')
    params['month_ends']=['2020-03-31','2020-04-30']
    params['next_session']={'2020-03-31':'2020-04-01','2020-04-30':'2020-05-01'}
    bot=CreditSignal(params);ctx=Context();bot.on_start(ctx)
    bot.history={s:[D(100)]*63 for s in SYMBOLS}
    return bot,ctx


def batch(bot,ctx,day,phase,prices=None,**meta):
    prices=prices or {s:'100' for s in SYMBOLS}
    stamp=datetime.fromisoformat(day+('T16:00:00' if phase=='close' else 'T09:30:00')).replace(tzinfo=NEW_YORK)
    output=[]
    for index,s in enumerate(SYMBOLS):
        price=D(prices[s]);iid=bot.ids[s]
        event=MarketEvent.quote(iid,stamp,mid=price,ask=price,bid=price,
            meta={'phase':phase,'batch_last':index==2,'next_open_in_partition':True,**meta})
        ctx.books[iid]=event.as_snapshot();output.extend(bot.on_event(ctx,event))
    return output


def test_equality_cash_frozen_budget_delayed_topup_and_expiry():
    bot,ctx=pure();batch(bot,ctx,'2020-03-31','close')
    assert bot.targets=={'SPY':0}
    bot,ctx=pure();batch(bot,ctx,'2020-03-31','close',{'SPY':'100','HYG':'110','IEF':'100'})
    assert bot.targets=={'SPY':D(133)} and bot.reserve==7
    ctx.equity,ctx.cash=D(1000),D(57)
    batch(bot,ctx,'2020-04-01','observe_open');batch(bot,ctx,'2020-04-01','reduce')
    order,=batch(bot,ctx,'2020-04-01','buy')
    assert order.size*order.limit_price==D('49.99') and bot.pending=={'SPY'}
    ctx.quantities[bot.ids['SPY']]=order.size;ctx.cash=D(140)
    batch(bot,ctx,'2020-04-02','observe_open')
    order2,=batch(bot,ctx,'2020-04-02','buy')
    assert order2.size*order2.limit_price==D('83.01') and not bot.pending
    assert bot.targets['SPY']==133
    # A cash signal expires a partially unfilled target; no reference orders.
    bot.pending={'SPY'}
    batch(bot,ctx,'2020-04-30','close',{'SPY':'100','HYG':'90','IEF':'100'})
    assert bot.targets=={'SPY':0}
    batch(bot,ctx,'2020-05-01','observe_open')
    sell,=batch(bot,ctx,'2020-05-01','reduce')
    assert sell.side=='sell' and sell.instrument_id==bot.ids['SPY']


def test_adverse_price_caps_owned_plus_addition_and_no_terminal_buy():
    bot,ctx=pure();batch(bot,ctx,'2020-03-31','close',{'SPY':'100','HYG':'110','IEF':'100'})
    ctx.quantities[bot.ids['SPY']]=D('1.32')
    batch(bot,ctx,'2020-04-01','observe_open')
    iid=bot.ids['SPY'];snap=ctx.books[iid]
    ctx.books[iid]=MarketEvent.quote(iid,snap.time,mid=D(100),bid=D(99),ask=D('100.05')).as_snapshot()
    dollars,_=bot._allocate_buys(ctx,'2020-04-01')['SPY']
    assert dollars+ctx.quantities[iid]*D('100.05')<=D(133)
    order,=batch(bot,ctx,'2020-04-01','reduce',terminal_open=True)
    assert order.size==D('1.32')
    assert batch(bot,ctx,'2020-04-01','buy',terminal_open=True)==[]


def test_incomplete_and_duplicate_close_batch_refused():
    bot,ctx=pure();iid=bot.ids['IEF']
    event=MarketEvent.quote(iid,datetime(2020,3,31,16,tzinfo=NEW_YORK),mid=D(100),meta={'phase':'close','batch_last':True})
    with pytest.raises(ValueError,match='incomplete'):bot.on_event(ctx,event)
    with pytest.raises(ValueError,match='duplicate'):bot.on_event(ctx,event)
