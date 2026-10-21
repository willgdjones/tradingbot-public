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
from tradingbot.research import c19_total_return as c19
from tradingbot.strategy.c19_correlation import CorrelationHedge, SYMBOLS, correlation, pearson_returns, defensive_fund
from tradingbot.strategy.interface import MarketEvent


def source(gap=False):
    days = [date(2020,1,2)+timedelta(days=i) for i in range(140)]
    days = [d for d in days if d.weekday()<5]
    rows = []
    for i,day in enumerate(days):
        quotes = {}
        for symbol in SYMBOLS:
            close = D(100)+D(i)/100 if symbol in ('SPY','IEF') else D(100)
            if symbol in ('SPY','GLD') and day==days[-1]: close=D(20 if gap else 110)
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
    strategy=Strategy(key='test-c19-'+suffix,name='Synthetic C19',status='backtest',allocation_usd=D(140))
    db.add(strategy);db.flush()
    ids={}
    for symbol in SYMBOLS:
        market=Market(venue_id=venue.id,external_id='test-c19-'+suffix+symbol,market_type='equity')
        db.add(market);db.flush()
        inst=Instrument(venue_id=venue.id,market_id=market.id,external_id='test-c19-'+suffix+symbol,
            instrument_type='equity',symbol=symbol,currency='USD',contract_multiplier=D(1))
        db.add(inst);db.flush();ids[symbol]=inst.id
    bot=CorrelationHedge(c19.strategy_params(data,ids,variant))
    runtime=c19.C19Backtester(db,strategy=bot,strategy_id=strategy.id,source=data,fx=fx())
    return runtime,bot


def split():
    return HoldoutSplit('test-c19-'+uuid.uuid4().hex,datetime(2020,1,1,tzinfo=UTC),datetime(2023,1,1,tzinfo=UTC))


def test_pearson_returns_and_frozen_branch_equality():
    x=list(map(D,('-1','0','1')))
    assert pearson_returns(x,x)==1
    assert pearson_returns(x,[-v for v in x])==-1
    assert pearson_returns(x,list(map(D,('1','-2','1'))))==0
    assert pearson_returns(x,[D(1)]*3) is None
    assert defensive_fund(D(0))=='IEF' and defensive_fund(D('.001'))=='GLD'
    assert defensive_fund(D('-1'))=='IEF' and defensive_fund(None) is None


def test_exact_lookback_warmup_alignment_and_undefined():
    h={s:[D(100)]*63 for s in ('SPY','IEF')}
    assert correlation(h,'63')==(None,'L+1 complete closes inside partition required')
    for values in h.values(): values.append(D(100))
    assert correlation(h,'63')==(None,'undefined zero-variance correlation')
    h={s:[D(100)+D(i)/10 for i in range(64)] for s in ('SPY','IEF')}
    rho,reason=correlation(h,'63')
    assert abs(rho-1)<D('1e-24') and reason is None
    assert correlation({s:[D(1000)]+v for s,v in h.items()},'63')==(rho,reason)
    assert correlation(h,'126')[0] is None
    with pytest.raises(ValueError,match='unequal'):correlation({**h,'IEF':h['IEF'][:-1]},'63')
    with pytest.raises(ValueError,match='specification'):correlation({**h,'GLD':[D(100)]*64},'63')
    with pytest.raises(ValueError,match='specification'):correlation(h,'64')


def test_shared_ledger_terminal_flat_and_raw_equivalent_fees(db,monkeypatch):
    data,partition=source(),split();runtime,bot=setup(db,data)
    monkeypatch.setattr(c19,'split_for',lambda _:partition)
    observed=[]
    result=runtime.run(c19.events(data,bot.params,10,False,observed),split=partition)
    metrics,trips,fills=c19.finish_metrics(db,result,runtime,expected_trips=2)
    assert result.fills==4 and result.orders_rejected==0 and not any(q for q,_ in runtime.positions.values())
    assert next(d for d in bot.decisions if d['hedge'])['date']=='2020-03-31'
    assert fills[0].fill_ts.astimezone(NEW_YORK).date()==date(2020,4,1)
    assert {f.instrument_id for f in fills}=={bot.ids['SPY'],bot.ids['GLD']}
    assert len(runtime.cash[0])==4
    assert all(f.metadata_['research']['source']=='c19_total_return_equivalent' for f in fills)
    detail=c19.diagnostics(bot,observed,trips,fills,runtime)
    assert detail['terminal_liquidation_fills']==2 and detail['hedge_months']=={'IEF':0,'GLD':2,'cash':2}
    assert detail['luck']['p_value'] is None and detail['luck']['exit_month_clusters']==1
    assert D(detail['benchmarks']['SPY_buy_hold']['total_return'])==D('.1')
    assert all(not f.metadata_['research']['separate_dividend_credit'] for f in fills)


def test_unchanged_kills_keep_rejected_terminal_and_inventory(db,monkeypatch):
    data,partition=source(True),split();runtime,bot=setup(db,data)
    monkeypatch.setattr(c19,'split_for',lambda _:partition)
    result=runtime.run(c19.events(data,bot.params,10,False,[]),split=partition)
    assert runtime.killed and runtime.daily_halted and runtime.positions
    assert {x['kind'] for x in runtime.halt_events}=={'per_strategy_kill','global_daily_halt'}
    assert result.orders_rejected==2 and result.fills==2


def test_intraday_cutoff_and_partition_warmup(db,monkeypatch):
    data=source();runtime,bot=setup(db,data)
    cutoff=datetime(2020,4,1,19,tzinfo=UTC)
    start=datetime(2020,1,1,tzinfo=UTC)
    partition=HoldoutSplit('test-c19-cutoff',start,start+(cutoff-start)*10/7)
    monkeypatch.setattr(c19,'split_for',lambda _:partition)
    feed=list(c19.events(data,bot.params,10,False,[]))
    assert all(e.time<partition.holdout_start for e in feed)
    terminal=[e for e in feed if e.meta.get('terminal_open')]
    assert len(terminal)==9 and terminal[0].time.astimezone(NEW_YORK).date()==date(2020,4,1)
    # A fresh final has no access to the pre-cutoff references.
    ctx=Context();bot.on_start(ctx)
    orders=[]
    for event in c19.events(data,bot.params,10,True,[]):
        ctx.books[event.instrument_id]=event.as_snapshot()
        orders.extend(bot.on_event(ctx,event))
    assert all(d['hedge'] is None for d in bot.decisions) and not orders


def test_final_admission_before_feed(db,monkeypatch):
    from tradingbot.backtest import engine
    data,partition=source(),split();runtime,bot=setup(db,data);observed=[]
    def refuse(*args,**kwargs):
        assert not observed
        raise ValueError('synthetic final refused')
    monkeypatch.setattr(engine,'claim_final',refuse)
    with pytest.raises(ValueError,match='final refused'):
        runtime.run(c19.events(data,bot.params,10,True,observed),split=partition,final_holdout=True)
    assert not observed


def test_mismatched_selected_version_logs_without_feed(db,monkeypatch):
    data,partition=source(),split()
    monkeypatch.setattr(c19,'require_committed',lambda:'synthetic')
    monkeypatch.setattr(c19,'split_for',lambda _:partition)
    monkeypatch.setattr(c19,'ReferenceFX',lambda _:fx())
    monkeypatch.setattr(c19,'CaptureDiskBudget',lambda _:SimpleNamespace(check=lambda:None))
    def forbidden(*args): raise AssertionError('feed must not be constructed')
    monkeypatch.setattr(c19,'events',forbidden)
    result=c19.run_variant(db,data,'63',10,final=True,expected_version='wrong')
    assert result['status']=='failed' and not result['final_holdout']
    assert 'committed selected version' in result['error']
    assert db.get(Trial,result['trial_id']).params['final_feed_consumed'] is False


def test_repeat_final_preflight_records_incident(db,monkeypatch):
    data=source();key=f'c19-tr-{data["sha256"][:12]}-63-10-final'
    strategy=Strategy(key=key,name='Synthetic old final',status='backtest',allocation_usd=140)
    db.add(strategy);db.flush()
    monkeypatch.setattr(c19,'require_committed',lambda:'synthetic')
    with pytest.raises(ValueError,match='already attempted'):
        c19.run_variant(db,data,'63',10,final=True,expected_version='synthetic')
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
    params=c19.strategy_params(source(),dict(zip(SYMBOLS,range(1,4))),'63')
    params['month_ends']=['2020-03-31','2020-04-30']
    params['next_session']={'2020-03-31':'2020-04-01','2020-04-30':'2020-05-01'}
    bot=CorrelationHedge(params);ctx=Context();bot.on_start(ctx)
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


def set_history(bot,positive=True):
    spy=[D(100)+D(i)/100 for i in range(64)]
    ief=[D(100)]
    for a,b in zip(spy,spy[1:]):ief.append(ief[-1]*(b/a if positive else 2-b/a))
    bot.history['SPY'],bot.history['IEF']=spy[:-1],ief[:-1]
    return {'SPY':str(spy[-1]),'IEF':str(ief[-1]),'GLD':'100'}


def test_fixed_halves_pro_rata_delayed_cash_and_frozen_target():
    bot,ctx=pure();set_history(bot)
    batch(bot,ctx,'2020-03-31','close',{'SPY':'100.63','IEF':'100.63','GLD':'100'})
    assert bot.targets=={'SPY':D('66.5'),'IEF':0,'GLD':D('66.5')} and bot.reserve==7
    ctx.equity,ctx.cash=D(1000),D(57)
    batch(bot,ctx,'2020-04-01','observe_open');batch(bot,ctx,'2020-04-01','reduce')
    orders=batch(bot,ctx,'2020-04-01','buy')
    assert len(orders)==2 and all(o.size*o.limit_price==D('24.99') for o in orders)
    assert bot.pending=={'SPY','GLD'}
    for o in orders:ctx.quantities[o.instrument_id]=o.size
    ctx.cash=D(140);batch(bot,ctx,'2020-04-02','observe_open')
    later=batch(bot,ctx,'2020-04-02','buy')
    assert len(later)==2 and all(o.size*o.limit_price==D('41.51') for o in later)
    assert not bot.pending and bot.targets['SPY']==D('66.5')


def test_hedge_switch_reduces_obsolete_then_cash_rations_new_leg():
    bot,ctx=pure();prices=set_history(bot,positive=False)
    ctx.quantities[bot.ids['SPY']]=ctx.quantities[bot.ids['GLD']]=D('.665')
    ctx.cash=D(7)
    batch(bot,ctx,'2020-03-31','close',prices)
    assert bot.targets=={'SPY':D('66.5'),'IEF':D('66.5'),'GLD':0}
    batch(bot,ctx,'2020-04-01','observe_open')
    sold,=batch(bot,ctx,'2020-04-01','reduce')
    assert sold.instrument_id==bot.ids['GLD'] and sold.size==D('.665')
    ctx.quantities[bot.ids['GLD']]=D(0)
    assert batch(bot,ctx,'2020-04-01','buy')==[]
    assert bot.pending=={'IEF'}  # Sale proceeds not yet settled.
    ctx.cash=D('73.49');batch(bot,ctx,'2020-04-02','observe_open')
    bought,=batch(bot,ctx,'2020-04-02','buy')
    assert bought.instrument_id==bot.ids['IEF'] and bought.size*bought.limit_price==D('66.48')


def test_undefined_correlation_targets_cash_and_expires_delayed_target():
    bot,ctx=pure();set_history(bot);batch(bot,ctx,'2020-03-31','close',{'SPY':'100.63','IEF':'100.63','GLD':'100'})
    ctx.quantities[bot.ids['SPY']]=D('.665');bot.history={s:[D(100)]*63 for s in SYMBOLS}
    batch(bot,ctx,'2020-04-30','close')
    assert all(v==0 for v in bot.targets.values())
    assert bot.decisions[-1]['reason']=='undefined zero-variance correlation'
    batch(bot,ctx,'2020-05-01','observe_open');order,=batch(bot,ctx,'2020-05-01','reduce')
    assert order.side=='sell' and order.size==D('.665')
    assert batch(bot,ctx,'2020-05-01','buy')==[]


def test_adverse_price_caps_full_halves_and_no_terminal_buy():
    bot,ctx=pure();set_history(bot);ctx.equity=ctx.cash=D(1000)
    batch(bot,ctx,'2020-03-31','close',{'SPY':'100.63','IEF':'100.63','GLD':'100'})
    assert bot.targets['SPY']==bot.targets['GLD']==70
    ctx.quantities[bot.ids['SPY']]=D('.69')
    batch(bot,ctx,'2020-04-01','observe_open');iid=bot.ids['SPY'];snap=ctx.books[iid]
    ctx.books[iid]=MarketEvent.quote(iid,snap.time,mid=D(100),bid=D(99),ask=D('100.05')).as_snapshot()
    dollars,_=bot._allocate_buys(ctx,'2020-04-01')['SPY']
    assert dollars+ctx.quantities[iid]*D('100.05')<=70
    order,=batch(bot,ctx,'2020-04-01','reduce',terminal_open=True)
    assert order.size==D('.69')
    assert batch(bot,ctx,'2020-04-01','buy',terminal_open=True)==[]


def test_incomplete_and_duplicate_close_batch_refused():
    bot,ctx=pure();iid=bot.ids['GLD']
    event=MarketEvent.quote(iid,datetime(2020,3,31,16,tzinfo=NEW_YORK),mid=D(100),meta={'phase':'close','batch_last':True})
    with pytest.raises(ValueError,match='incomplete'):bot.on_event(ctx,event)
    with pytest.raises(ValueError,match='duplicate'):bot.on_event(ctx,event)


def test_atomic_marks_avoid_artificial_sequence_halt(db):
    data=source();runtime,bot=setup(db,data);ids=bot.params['instrument_ids']
    a,b=ids['SPY'],ids['GLD'];runtime.positions={a:(D('.7'),D(100)),b:(D('.7'),D(100))}
    runtime.marks={i:D(100) for i in ids.values()};marks={str(i):'100' for i in ids.values()}
    marks[str(a)],marks[str(b)]='20','180'
    event=MarketEvent.quote(a,datetime(2020,4,1,9,30,tzinfo=NEW_YORK),mid=D(20),
        meta={'phase':'observe_open','factor':'.5','batch_marks':marks,'batch_last':False})
    runtime.observe(event)
    assert runtime.equity()==140 and not runtime.killed and not runtime.daily_halted


@pytest.mark.parametrize('variant',['63','126'])
def test_each_lookback_uses_exactly_L_return_pairs(variant):
    lag=int(variant)
    h={s:[D(100)+i for i in range(lag+1)] for s in ('SPY','IEF')}
    rho,reason=correlation(h,variant)
    assert abs(rho-1)<D('1e-24') and reason is None
    assert correlation({s:[D(20000)]+v for s,v in h.items()},variant)==(rho,reason)
    assert correlation({s:v[:-1] for s,v in h.items()},variant)[0] is None
