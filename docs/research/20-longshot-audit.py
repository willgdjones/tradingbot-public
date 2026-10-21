"""Receipt accounting audit only; never invokes a strategy or replays a final."""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_EVEN, localcontext
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from sqlalchemy import select

from tradingbot.backtest.longshot_history import ROOT, SPLIT, encoded, instant, legacy_receipt, load_manifest, sha
from tradingbot.db.models import Fill, Order, Position, Trial
from tradingbot.db.session import SessionLocal

D = Decimal


def audit(*, require_finished=True):
    manifest, digest = load_manifest()
    references = {r['instrument_id']: r for r in manifest['rows']}
    checks=[]
    tapes={}
    with SessionLocal() as session:
        assert legacy_receipt(session)==manifest['legacy']
        trials=list(session.scalars(select(Trial).where(Trial.dataset_key==SPLIT.dataset_key).order_by(Trial.id)))
        if require_finished:
            assert not any(t.status=='running' for t in trials), 'running attempt needs an interruption audit'
        else:
            trials=[t for t in trials if t.status!='running']
        for t in trials:
            if t.status!='complete':
                checks.append({'trial_id':t.id,'status':t.status,'notes':t.notes})
                continue
            m=t.metrics
            assert m['trial_id']==t.id
            path=Path(m['execution_receipt']); assert sha(path)==m['execution_sha256']
            evidence=json.loads(path.read_text())
            assert evidence['durable_trial_id']==t.id and evidence['strategy_version']==t.strategy_version
            part='final' if t.final_holdout else 'training'
            cache_path=ROOT/(m['category'].replace(':','_').replace('/','_')+'-'+part+'.parquet')
            assert m['tape']['sha256']==evidence['tape']['sha256']==sha(cache_path)
            assert m['tape']['manifest_sha256']==digest and m['tape']['partition']==part
            # Only completed, durably admitted final receipts can reach this path.
            needed={f['metadata']['public_trade_id'] for f in evidence['fills'] if not f['metadata'].get('settlement')}
            wanted={}
            native_ids=pa.array(sorted(needed),type=pa.int64())
            for batch in pq.ParquetFile(cache_path).iter_batches(batch_size=25000):
                # Same exact rows as the original audit; avoid materializing
                # millions of unrelated source observations as Python dicts.
                matched=batch.filter(pc.is_in(batch.column('id'),value_set=native_ids))
                for row in matched.to_pylist():
                    assert row['id'] not in wanted
                    wanted[row['id']]=row
            assert set(wanted)==needed
            quantities=defaultdict(lambda:D(0)); cash=fees=D(0)
            matched_sizes=defaultdict(lambda:D(0)); contract_fills=defaultdict(int)
            collateral=defaultdict(lambda:D(0)); max_held=max_contract=D(0)
            instrument_cash=defaultdict(lambda:D(0)); instrument_fees=defaultdict(lambda:D(0))
            entry_price={}
            first_entry={}; settled=set(); max_holding=0
            for f in evidence['fills']:
                iid=f['instrument_id']; ref=references[iid]
                ts=instant(f['time']); size=D(f['size']); price=D(f['price']); fee=D(f['fee'])
                SPLIT.require(ts,final_holdout=t.final_holdout)
                assert ref['partition']==part and f['contract']==ref['contract'] and f['event_id']==ref['event_id']
                assert iid not in settled and size>0
                if f['metadata'].get('settlement'):
                    assert ts==instant(ref['resolve_ts']) and price==D(ref['payout']) and fee==0
                    assert size==abs(quantities[iid]) and ((quantities[iid]>0)==(f['side']=='sell'))
                    assert instant(f['order_created_ts'])==ts
                    settled.add(iid)
                    collateral[iid]=D(0)
                    max_holding=max(max_holding,(ts-first_entry[iid]).total_seconds())
                else:
                    assert f['liquidity']=='maker'
                    source=wanted[f['metadata']['public_trade_id']]
                    assert iid==source['instrument_id'] and ts==source['time']
                    assert instant(f['order_created_ts'])<ts<instant(ref['entry_end'])
                    assert instant(ref['window_start'])<=instant(f['order_created_ts'])
                    assert f['metadata']['source_execution_identity']==ref['contract']+':'+source['external_trade_id']
                    assert D(f['metadata']['trade_through'])==D(source['price'])
                    assert price==D(f['order_limit_price'])
                    assert D(source['price'])<price if f['side']=='buy' else D(source['price'])>price
                    assert size==size.quantize(D('.0000000001'),rounding=ROUND_DOWN)
                    expected_fee=(D('-.0125')*size*price*(1-price)).quantize(D('.01'),rounding=ROUND_HALF_EVEN)
                    assert fee==expected_fee
                    matched_sizes[source['id']]+=size
                    assert matched_sizes[source['id']]<=D(source['size']).quantize(D('.0000000001'),rounding=ROUND_DOWN)
                    contract_fills[ref['contract']]+=1
                    assert contract_fills[ref['contract']]<=3
                    first_entry.setdefault(iid,ts)
                    entry_price.setdefault(iid,price)
                    assert quantities[iid]==0 or (quantities[iid]>0)==(f['side']=='buy')
                    collateral[iid]+=size*(price if f['side']=='buy' else 1-price)
                signed=size if f['side']=='buy' else -size
                quantities[iid]+=signed; cash-=signed*price+fee; fees+=fee
                instrument_cash[iid]-=signed*price+fee; instrument_fees[iid]+=fee
                held=sum(collateral.values(),D(0))
                contract_held=sum(value for key,value in collateral.items()
                                  if references[key]['contract']==ref['contract'])
                max_held=max(max_held,held); max_contract=max(max_contract,contract_held)
                assert held<=140 and contract_held<=25
                short_liability=sum((-q for q in quantities.values() if q<0),D(0))
                assert D(140)+cash-short_liability>=0
            assert not any(quantities.values())
            assert fees==t.fees_total and len(evidence['trips'])==t.trade_count
            tolerance=D(m['accounting_tolerance'])
            assert abs(cash-t.pnl_after_fees)<=tolerance
            assert abs(cash-D(m['cash_net_pnl']))<=tolerance
            assert len(evidence['fills'])==m['fill_count']
            assert len(first_entry)==t.trade_count==len(contract_fills)
            trips={trip['instrument_id']:trip for trip in evidence['trips']}
            assert len(trips)==len(evidence['trips']) and set(trips)==set(first_entry)
            months=defaultdict(lambda:[0,D(0),D(0),D(0)])
            quarters=defaultdict(lambda:[0,D(0),D(0),D(0)])
            days=defaultdict(lambda:D(0))
            # Weighted-average trip arithmetic can leave a sub-1e-40 Decimal
            # remainder at the frozen 60-digit precision. Source/fee checks stay exact.
            arithmetic_epsilon=D('1e-40')
            for iid,trip in trips.items():
                ref=references[iid]
                assert trip['contract']==ref['contract'] and trip['event_id']==ref['event_id']
                assert instant(trip['entry_ts'])==first_entry[iid]
                end=instant(trip['exit_ts'])
                assert end==instant(ref['resolve_ts']) and D(trip['entry_price'])==entry_price[iid]
                assert abs(D(trip['net_pnl'])-instrument_cash[iid])<=arithmetic_epsilon
                assert D(trip['fees'])==instrument_fees[iid]
                assert abs(D(trip['gross_pnl'])-instrument_cash[iid]-instrument_fees[iid])<=arithmetic_epsilon
                days[end.date().isoformat()]+=instrument_cash[iid]
                for buckets,label in ((months,end.strftime('%Y-%m')),(quarters,f'{end.year}-Q{(end.month-1)//3+1}')):
                    bucket=buckets[label]; bucket[0]+=1
                    bucket[1]+=instrument_cash[iid]; bucket[2]+=instrument_cash[iid]+instrument_fees[iid]
                    bucket[3]+=instrument_fees[iid]
            assert set(m['date_aggregate_net'])==set(days)
            assert all(abs(D(m['date_aggregate_net'][key])-value)<=arithmetic_epsilon for key,value in days.items())
            assert len(days)==m['unique_exit_dates'] and len(trips)==m['unique_contracts']
            assert len({references[iid]['event_id'] for iid in trips})==m['unique_events']
            for kind,buckets in (('month',months),('quarter',quarters)):
                assert set(buckets)<=set(m['regimes'][kind])
                for label,reported in m['regimes'][kind].items():
                    observed=buckets.get(label,[0,D(0),D(0),D(0)])
                    assert reported['trades']==observed[0]
                    assert all(abs(D(reported[field])-value)<=arithmetic_epsilon
                               for field,value in zip(('net_pnl','gross_pnl','fees'),observed[1:]))
            assert abs(max_holding-m['maximum_holding_seconds'])<.000002
            assert m['maximum_collateral'] is not None and D(m['maximum_collateral'])<=140
            assert max_held<=D(m['maximum_collateral']) and not any(collateral.values())
            assert m['open_positions']==m['active_orders']==0
            assert session.scalar(select(Fill.id).where(Fill.trial_id==t.id)) is None
            assert session.scalar(select(Order.id).where(Order.trial_id==t.id)) is None
            assert session.scalar(select(Position.id).where(Position.strategy_id==t.strategy_id,Position.mode=='backtest')) is None
            checks.append({'trial_id':t.id,'status':'verified','partition':part,'fills_checked':len(evidence['fills']),
                           'maker_fills_checked':len(evidence['fills'])-len(settled),'cash_net':str(cash),
                           'ledger_net':str(t.pnl_after_fees),'cash_ledger_residual':str(cash-t.pnl_after_fees),
                           'maximum_filled_collateral':str(max_held),'maximum_contract_filled_collateral':str(max_contract),
                           'round_trips_checked':len(trips),'calendar_regimes_reconciled':True,
                           'receipt_sha256':m['execution_sha256'],'tape_sha256':sha(cache_path)})
        assert legacy_receipt(session)==manifest['legacy']
    return {'manifest_sha256':digest,'audit_script_sha256':sha(__file__),'legacy':manifest['legacy'],
            'checks':checks,'all_complete_trials_verified':all(c['status'] in {'verified','failed'} for c in checks),
            'basis':'Receipt arithmetic/source verification only; no strategy callback or final replay invoked.'}


if __name__=='__main__':
    with localcontext() as context:
        context.prec=60
        result=audit()
    (ROOT/'execution-audit.json').write_bytes(encoded(result))
    print(json.dumps(result,indent=2))
