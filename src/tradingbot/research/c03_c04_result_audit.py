"""Read stored C04 outcomes, fills and source cash facts; never replay a strategy."""
from datetime import datetime
from decimal import Decimal as D
import json

from sqlalchemy import select, text

from tradingbot.connectors.cash import CashMovement, cash_balance, NEW_YORK
from tradingbot.data.archive import canonical
from tradingbot.db.models import Fill, Order, Strategy, Trial
from tradingbot.db.session import session_scope
from tradingbot.research.c03_c04_replay_v2 import ROOT, sha, load_source
from tradingbot.research.equity_fees import EquityFeeBook


def trial_hash(session, tid):
    body = session.execute(text('SELECT row_to_json(t) FROM trials t WHERE id=:id'), {'id':tid}).scalar_one()
    return sha(canonical(body).encode())


def audit():
    source = load_source()
    by_day = {r['date']:r for r in source['prices']}
    divs = {r['ex_date']:r for r in source['distributions']}
    selection_raw = (ROOT/'docs/research/24-c03-c04-c04-v2-selection.json').read_bytes()
    choice = json.loads(selection_raw)
    final = json.loads((ROOT/'docs/research/24-c03-c04-c04-v2-final.json').read_text())
    if final['selection_sha256'] != sha(selection_raw): raise ValueError('final selection fingerprint changed')
    results = [*choice['training'],final]
    checked = []
    with session_scope() as session:
        for result in results:
            trial = session.get(Trial,result['trial_id'])
            if (trial.status != 'complete' or trial.metrics != result['metrics']
                    or trial.strategy_version != result['strategy_version']):
                raise ValueError('stored outcome disagrees with trial')
            raw = (ROOT/result['artifact']).read_bytes()
            if sha(raw) != result['artifact_sha256']: raise ValueError('outcome artifact changed')
            artifact = json.loads(raw)
            fills = list(session.scalars(select(Fill).where(Fill.trial_id==trial.id).order_by(Fill.fill_ts,Fill.id)))
            if [f.id for f in fills] != artifact['fill_ids']: raise ValueError('stored fill inventory changed')
            quantity, movements, fee_book = D(0), [], EquityFeeBook()
            for fill in fills:
                order = session.get(Order,fill.order_id)
                if order.status != 'filled' or order.side != fill.side or order.size != fill.size:
                    raise ValueError('order/fill mismatch')
                if fill.side == 'buy' and (quantity+fill.size)*order.limit_price > D(140):
                    raise ValueError('buy exceeds unchanged cap at rounded limit')
                quantity += fill.size if fill.side == 'buy' else -fill.size
                if quantity < 0: raise ValueError('short position')
                day = fill.fill_ts.astimezone(NEW_YORK).date().isoformat(); row = by_day[day]
                if fill.fill_ts != datetime.fromisoformat(row['opens_at']): raise ValueError('fill is not a reference open')
                lower = trial.holdout_start if trial.final_holdout else trial.data_start
                upper = trial.data_end if trial.final_holdout else trial.holdout_start
                if not lower <= fill.fill_ts < upper: raise ValueError('fill crosses partition')
                base = D(row['quotes']['SPY']['open']); bp = D(result['cost_bp'])/10000
                expected = base*(1+bp if fill.side=='buy' else 1-bp)
                if abs(fill.price-expected)>D('.00000001'): raise ValueError('fill cost differs from frozen case')
                fee,_ = fee_book.charge(day=fill.fill_ts.astimezone(NEW_YORK).date(),side=fill.side,price=fill.price,size=fill.size)
                if fee != fill.fee: raise ValueError('fee book disagrees with fill')
                meta = fill.metadata_['research']
                if (meta['source_receipt']!=choice['source_receipt']
                        or meta['conservative_cash_release']!=row['conservative_cash_release']):
                    raise ValueError('source or cash policy changed')
                release = datetime.fromisoformat(row['conservative_cash_release']).astimezone(NEW_YORK).date()
                movements.append(CashMovement(fill.side,fill.price*fill.size,fill.fee,release))
            if quantity: raise ValueError('terminal position remains open')
            income = D(0)
            for entitlement in trial.metrics['dividend_entitlements']:
                dist = divs[entitlement['ex_date']]
                opened = datetime.fromisoformat(by_day[entitlement['ex_date']]['opens_at'])
                prior = sum((f.size if f.side=='buy' else -f.size for f in fills if f.fill_ts<opened),D(0))
                amount = prior*D(dist['amount'])
                if (amount!=D(entitlement['cash_amount']) or prior!=D(entitlement['quantity_before_ex_open'])
                        or entitlement['cash_available_session']!=dist['cash_available_session']):
                    raise ValueError('dividend entitlement or release differs from owned shares and issuer')
                income += amount
                movements.append(CashMovement('sell',amount,D(0),datetime.fromisoformat(dist['cash_available_session']).date()))
            last = datetime.fromisoformat(artifact['curve'][-1][0]); cash = cash_balance(D(140),movements,D(0),last)
            tolerance = D('.000001')*max(1,len(fills))
            if (abs(cash.settled-D(trial.metrics['ending_settled_cash_usd']))>tolerance
                    or abs(cash.unsettled-D(trial.metrics['ending_unsettled_cash_and_receivables_usd']))>tolerance
                    or abs(cash.settled+cash.unsettled-140-D(trial.metrics['net_usd']))>tolerance
                    or income!=D(trial.metrics['dividend_income_usd'])):
                raise ValueError('independent cash/receivable reconciliation failed')
            rejects = list(session.scalars(select(Order.id).where(Order.trial_id==trial.id,Order.status=='rejected')))
            if rejects or not trial.metrics['complete_execution']: raise ValueError('incomplete execution')
            checked.append({'trial_id':trial.id,'row_sha256':trial_hash(session,trial.id),
                'final_holdout':trial.final_holdout,'fills':len(fills),'net_usd':trial.metrics['net_usd'],
                'checks':['artifact','orders','rounded_limit_cap','partition','reference_open_cost','fee_book',
                          'dividend_prior_ownership','cash_release','cash_reconciliation','terminal_flat','no_rejects'],
                'cash_reconciliation_tolerance_usd':str(tolerance)})
        finals = list(session.scalars(select(Trial.id).join(Strategy,Trial.strategy_id==Strategy.id).where(
            Trial.final_holdout.is_(True),Strategy.config['candidate'].astext=='C04-readmission').order_by(Trial.id)))
        if finals != [final['trial_id']]: raise ValueError('C04 family final inventory is not exactly one')
        protected = {}
        for name in ['24-c03-c04-preserved-trials.json','24-c03-c04-c04-v1-preserved.json']:
            for tid,row in json.loads((ROOT/'docs/research'/name).read_text()).items():
                if tid.isdigit():
                    found=trial_hash(session,int(tid))
                    if found!=row['row_sha256']: raise ValueError('protected trial changed')
                    protected[tid]=found
        prior=json.loads((ROOT/'docs/research/24-c03-c04-c04-training-audit.json').read_text())
        if any(trial_hash(session,r['trial_id'])!=r['row_sha256'] for r in prior['trials']):
            raise ValueError('v2 training trial changed after selection')
    return {'status':'PASS_STORED_LEDGER_AUDIT','price_replays':0,'trials':checked,
        'consumed_family_finals':finals,'protected_trial_hashes':protected,
        'selection_sha256':sha(selection_raw),'promotion':'none'}


if __name__ == '__main__':
    result=audit()
    (ROOT/'docs/research/24-c03-c04-c04-ledger-audit.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'status':result['status'],'trials':len(result['trials']),
        'consumed_family_finals':result['consumed_family_finals'],'price_replays':0}))
