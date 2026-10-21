"""Synthetic source/driver checks. No historical strategy returns are inspected."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import json
import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from tradingbot.backtest import longshot_history as study
from tradingbot.backtest.holdout import HoldoutSplit, HoldoutViolation
from tradingbot.data.disk_budget import CaptureDiskBudget
from tradingbot.db.models import BacktestDataset, FamilyHoldoutSpend, HoldoutFamilyAlias, Incident, Fill, Instrument, Market, Order, Position, Strategy, Trade, Trial, Venue
from tradingbot.db.session import get_engine
from tradingbot.strategy.interface import MarketEvent

D = Decimal
T0 = datetime(2025, 2, 1, tzinfo=UTC)
SPLIT = HoldoutSplit('synthetic-source-split', T0, T0 + timedelta(days=10))


def source_pair(*, close=2, resolution=2.1, opening=-10, venue='kalshi', contract='strike1', event='event1', start_id=1):
    ts = lambda day: (T0 + timedelta(days=day)).isoformat()
    cohort = {'venue':venue,'contract':contract,'event_id':event,'category':'synthetic','close':ts(close),
              'catalog_page':'synthetic','volume':'0'}
    catalog = []
    for n, outcome in enumerate(('yes','no')):
        catalog.append({'instrument_id':start_id+n,'market_id':10,'venue':venue,
                        'external_id':contract+':'+outcome if venue=='kalshi' else str(start_id+n),
                        'market_external_id':event if venue=='kalshi' else contract,'outcome':outcome,
                        'instrument_type':'binary_'+outcome,'multiplier':D(1),
                        'open_ts':ts(opening),'close_ts':ts(close),'resolve_ts':ts(resolution),
                        'state':{'status':'settled','payout':str(n),'open_ts':ts(opening),
                                 'close_ts':ts(close),'resolve_ts':ts(resolution)}})
    return cohort, catalog


def test_reference_uses_native_kalshi_times_and_binary_pair_not_event():
    a, aa = source_pair()
    b, bb = source_pair(contract='strike2',start_id=3)
    for row in aa + bb:
        row['close_ts'] = '2099-01-01T00:00:00+00:00'  # Event aggregate is deliberately wrong.
    rows = study.reference_rows([a,b],aa+bb,SPLIT)
    assert len(rows) == 4 and all(r['partition']=='training' for r in rows)
    refs = study.reference_maps(rows)
    assert refs['siblings']['1'] == [2] and refs['siblings']['3'] == [4]
    assert refs['market_of']['1'] != refs['market_of']['3']
    assert 'payout' not in json.dumps(refs)
    assert all(r['window_start']==T0.isoformat() for r in rows)
    # Full native reference set is shared across both partitions.
    c, cc = source_pair(close=8,resolution=8.1,contract='strike3',start_id=5)
    rows = study.reference_rows([a,c],aa+cc,SPLIT)
    assert {r['partition'] for r in rows} == {'training','final'}
    assert study.reference_maps(rows)['instruments'] == {'1':True,'2':True,'5':True,'6':True}


@pytest.mark.parametrize('close,resolution,expected',[(6.9,7.1,None),(7,7.2,'final'),(6.5,6.6,'training'),(9.9,10,None)])
def test_both_close_and_terminal_belong_to_partition(close,resolution,expected):
    a, aa = source_pair(close=close,resolution=resolution)
    rows = study.reference_rows([a],aa,SPLIT)
    assert {r['partition'] for r in rows} == {expected}


def test_entry_window_is_not_shifted_by_future_resolution_and_invalid_labels_stay_visible():
    a,aa = source_pair(close=8,resolution=9.5,opening=0)
    rows = study.reference_rows([a],aa,SPLIT)
    assert rows[0]['window_start'] == SPLIT.holdout_start.isoformat()
    assert rows[0]['entry_end'] == (T0+timedelta(days=8,seconds=-300)).isoformat()
    aa[0]['state']['payout'] = None
    rows = study.reference_rows([a],aa,SPLIT)
    assert all('uncertified_payout_pair' in r['exclusions'] and r['partition'] is None for r in rows)
    a,aa = source_pair(venue='polymarket_intl',opening=3,close=2)
    assert 'invalid_catalog_window' in study.reference_rows([a],aa,SPLIT)[0]['exclusions']


def test_selection_keeps_no_fill_and_failed_variants_and_uses_declared_tie_order():
    rows = [{'category':'x','side_rule':side,'offset':offset,'status':'complete','trade_count':1,'pnl_after_fees':'2'}
            for side in study.SIDE_RULES for offset in study.OFFSETS]
    assert study.select_training(rows)['x'] == rows[0]
    rows[0]['trade_count'] = 0
    assert study.select_training(rows)['x'] == rows[1]
    for row in rows:
        row['pnl_after_fees'] = '-1'
    rows[0].update(status='failed',pnl_after_fees=None)
    assert study.select_training(rows)['x'] is None
    with pytest.raises(HoldoutViolation,match='six'):
        study.select_training(rows[:-1])


@pytest.fixture
def durable_study(tmp_path, monkeypatch):
    key = 'test-longshot-study-' + uuid.uuid4().hex
    split = HoldoutSplit(key,T0,T0+timedelta(days=10))
    engine = get_engine()
    ids, mids, rows = [], [], []
    with Session(engine) as session, session.begin():
        venue = session.scalar(select(Venue).where(Venue.key=='kalshi'))
        for part, day in [('training',2),('final',8)]:
            market = Market(venue_id=venue.id,external_id=key+part,market_type='binary')
            session.add(market);session.flush();mids.append(market.id)
            for n, outcome in enumerate(('yes','no')):
                inst = Instrument(venue_id=venue.id,market_id=market.id,external_id=key+part+outcome,
                                  instrument_type='binary_'+outcome,contract_multiplier=D(1))
                session.add(inst);session.flush();ids.append(inst.id)
                rows.append({'instrument_id':inst.id,'market_id':market.id,'instrument_type':'binary_'+outcome,
                    'contract':key+part,'venue':'kalshi','multiplier':'1','category_key':key,'event_id':key+part,
                    'partition':part,'window_start':(T0+timedelta(days=day-1)).isoformat(),
                    'close_ts':(T0+timedelta(days=day)).isoformat(),
                    'entry_end':(T0+timedelta(days=day,seconds=-300)).isoformat(),
                    'resolve_ts':(T0+timedelta(days=day,seconds=60)).isoformat(),'payout':str(1-n)})
    monkeypatch.setattr(study,'SPLIT',split)
    monkeypatch.setattr(study,'legacy_receipt',lambda session: {'synthetic':key})
    monkeypatch.setattr(study,'BUDGET',CaptureDiskBudget(tmp_path))
    manifest = {'rows':rows,'legacy':{'synthetic':key}}
    try:
        yield manifest,key,tmp_path,split
    finally:
        with Session(engine) as session,session.begin():
            sids=select(Strategy.id).where(Strategy.key=='longshot-full-'+study.hashlib.sha256(key.encode()).hexdigest()[:16])
            owned_ids = list(session.scalars(sids))
            session.execute(delete(FamilyHoldoutSpend).where(FamilyHoldoutSpend.trial_id.in_(
                select(Trial.id).where(Trial.strategy_id.in_(owned_ids)))))
            session.execute(delete(HoldoutFamilyAlias).where(HoldoutFamilyAlias.alias.in_(
                ['strategy:' + str(sid) for sid in owned_ids])))
            session.execute(delete(Incident).where(Incident.details['dataset_key'].astext == key))
            session.execute(delete(Trial).where(Trial.strategy_id.in_(sids)))
            session.execute(delete(Strategy).where(Strategy.id.in_(sids)))
            session.execute(delete(Trade).where(Trade.instrument_id.in_(ids)))
            session.execute(delete(Instrument).where(Instrument.id.in_(ids)))
            session.execute(delete(Market).where(Market.id.in_(mids)))
            session.execute(delete(BacktestDataset).where(BacktestDataset.key==key))


def admitted_feed(manifest,key,split,*,failure=False,calls=None):
    def feed(rows,category,partition,digest,root,on_cache):
        with Session(get_engine()) as audit:
            admitted=audit.scalars(select(Trial).where(Trial.dataset_key==split.dataset_key,
                Trial.final_holdout==(partition=='final'))).all()
            assert len(admitted)==1 and admitted[0].status=='running'
        if calls is not None:
            calls.append(partition)
        if failure:
            raise RuntimeError('synthetic feed interruption after admission')
        on_cache({'synthetic':True})
        row=rows[0]; ts=study.instant(row['window_start'])
        yield MarketEvent.trade(row['instrument_id'],ts,price=D('.8'),size=D(10),maker_fill_eligible=True,meta={'trade_id':123,'execution_identity':'synthetic:123'})
        yield MarketEvent.trade(row['instrument_id'],ts+timedelta(seconds=1),price=D('.6'),size=D('1.123456789123'),maker_fill_eligible=True,meta={'trade_id':124,'execution_identity':'synthetic:124'})
        yield MarketEvent.trade(row['instrument_id'],ts+timedelta(seconds=2),price=D('.5'),size=D('8.876543210923'),maker_fill_eligible=True,meta={'trade_id':125,'execution_identity':'synthetic:125'})
        # A new order has a different entry price and a fractional quantity;
        # average-cost and MONEY-column rounding must still reconcile at exit.
        yield MarketEvent.trade(row['instrument_id'],ts+timedelta(seconds=3),price=D('.4'),size=D('1.111111111123'),maker_fill_eligible=True,meta={'trade_id':126,'execution_identity':'synthetic:126'})
    return feed


def test_full_driver_durable_admission_identity_final_once_and_exact_receipt(durable_study,monkeypatch):
    manifest,key,root,split=durable_study
    calls=[]
    monkeypatch.setattr(study,'feed',admitted_feed(manifest,key,split,calls=calls))
    train=study.run_variant(manifest,'synthetic',key,'buy_favourite','.01',root=root)
    assert train['status']=='complete' and train['trade_count']==1
    assert train['metrics']['trial_id']==train['id']
    assert train['metrics']['open_positions']==train['metrics']['active_orders']==0
    assert abs(D(train['metrics']['cash_ledger_residual']))<=D(train['metrics']['accounting_tolerance'])
    receipts=json.loads((root/f"trial-{train['id']}-executions.json").read_text())
    assert receipts['fills'][0]['size']=='1.1234567891'
    assert receipts['fills'][0]['metadata']['source_execution_identity']=='synthetic:124'
    final=study.run_variant(manifest,'synthetic',key,'buy_favourite','.01',final=True,
                            expected_version=train['strategy_version'],root=root)
    assert final['status']=='complete' and final['strategy_version']==train['strategy_version']
    assert calls==['training','final']
    for final_flag in (False,True):
        repeat=study.run_variant(manifest,'synthetic',key,'buy_favourite','.01',final=final_flag,root=root)
        assert repeat['id']==(final['id'] if final_flag else train['id'])
    assert calls==['training','final']
    with Session(get_engine()) as session:
        sids=select(Trial.strategy_id).where(Trial.dataset_key==split.dataset_key)
        assert session.scalar(select(Fill.id).where(Fill.strategy_id.in_(sids))) is None
        assert session.scalar(select(Order.id).where(Order.strategy_id.in_(sids))) is None
        assert session.scalar(select(Position.id).where(Position.strategy_id.in_(sids))) is None


@pytest.mark.parametrize('final',[False,True])
def test_failed_feed_is_durable_and_never_reconsumed(durable_study,monkeypatch,final):
    manifest,key,root,split=durable_study
    calls=[]
    monkeypatch.setattr(study,'feed',admitted_feed(manifest,key,split,failure=True,calls=calls))
    with pytest.raises(RuntimeError,match='synthetic feed interruption'):
        study.run_variant(manifest,'synthetic',key,'buy_favourite','.01',final=final,root=root)
    stored=study.run_variant(manifest,'synthetic',key,'buy_favourite','.01',final=final,root=root)
    assert stored['status']=='failed' and len(calls)==1


def test_changed_final_identity_refused_before_feed(durable_study,monkeypatch):
    manifest,key,root,split=durable_study
    calls=[]
    monkeypatch.setattr(study,'feed',admitted_feed(manifest,key,split,calls=calls))
    with pytest.raises(HoldoutViolation,match='identity differs'):
        study.run_variant(manifest,'synthetic',key,'buy_favourite','.01',final=True,expected_version='wrong',root=root)
    assert calls==[]


def test_cache_selects_exact_eligible_source_and_retains_marks_after_blackout(durable_study):
    manifest,key,root,split=durable_study
    rows=study.category_rows(manifest,key,'training'); row=rows[0]
    iid=row['instrument_id']; deadline=study.instant(row['entry_end']); start=study.instant(row['window_start'])
    observations=[(start-timedelta(seconds=1),True),(start,False),(start+timedelta(seconds=1),True),
                  (deadline+timedelta(seconds=1),True),(study.instant(row['resolve_ts']),True)]
    with Session(get_engine()) as session,session.begin():
        for n,(ts,eligible) in enumerate(observations):
            session.add(Trade(time=ts,instrument_id=iid,price=D('.123456789123456789'),size=D('.987654321987654321'),
                external_trade_id=str(n),metadata_={'historical':{'maker_fill_eligible':eligible}}))
    cache={}
    events=list(study.feed(rows,key,'training','synthetic',root,on_cache=cache.update))
    trades=[e for e in events if not e.meta.get('timer')]
    assert len(trades)==2 and trades[-1].time>deadline
    assert trades[0].price==D('.123456789123456789') and trades[0].size==D('.987654321987654321')
    assert cache['rows']==2 and len([e for e in events if e.meta.get('timer')])==2
    assert events==list(study.feed(rows,key,'training','synthetic',root))
    with pytest.raises(HoldoutViolation,match='mismatch'):
        list(study.feed(rows,key,'training','different manifest',root))
