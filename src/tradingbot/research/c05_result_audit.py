"""Read stored C05 evidence and reconcile it. Never run strategy decisions."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal as D
import json

from sqlalchemy import select

from tradingbot.backtest.holdout import json_value
from tradingbot.connectors.cash import CashMovement, NEW_YORK, cash_balance
from tradingbot.data.archive import canonical
from tradingbot.data.disk_budget import CaptureDiskBudget
from tradingbot.db.models import Fill, Order, Strategy, Trial
from tradingbot.db.session import session_scope
from tradingbot.research.c05_replay import ARCHIVE, ROOT, SOURCE_RECEIPT, SYMBOLS, load_source, split_for
from tradingbot.research.c05_blackout import sha
from tradingbot.research.c06_month_end import drawdown
from tradingbot.research.equity_fees import EquityFeeBook

ZERO = D(0)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def period(curve, first, last):
    previous, values = ZERO, []
    for day, value in curve:
        if first <= day < last:
            if not values:
                values.append(previous)
            values.append(value)
        previous = value
    return {'covered': bool(values), 'marked_contribution_usd': str(values[-1]-values[0]) if values else None}


def audit_run(session, source, result):
    trial, strategy = session.get(Trial, result['trial_id']), session.get(Strategy, result['strategy_id'])
    require(trial is not None and strategy is not None and trial.strategy_id == strategy.id, 'missing stored identity')
    require(trial.status == result['status'] and trial.final_holdout == result['final_holdout'], 'stored status disagrees')
    require(trial.strategy_version == result['strategy_version'] and trial.metrics == result['metrics'], 'stored metrics/version differs')
    require(strategy.config['params']['source_receipt'] == SOURCE_RECEIPT, 'source receipt differs')
    require(trial.status == 'complete', 'failed run requires partial-evidence audit')
    ids = strategy.config['params']['instrument_ids']
    symbols = {iid: symbol for symbol, iid in ids.items()}
    fills = list(session.scalars(select(Fill).where(Fill.trial_id == trial.id).order_by(Fill.fill_ts, Fill.id)))
    orders = list(session.scalars(select(Order).where(Order.trial_id == trial.id).order_by(Order.id)))
    require([f.id for f in fills] == result['fill_ids'], 'fill inventory differs')
    require(sum(o.status == 'rejected' for o in orders) == result['metrics']['rejected_orders'], 'rejection count differs')
    split = split_for(source)
    rows = [r for r in source['prices'] if split.contains(datetime.fromisoformat(r['closes_at']), final_holdout=trial.final_holdout)]
    by_day, distributions = {}, {r['ex_date']: r for r in source['distributions']}
    for fill in fills:
        day = fill.fill_ts.astimezone(NEW_YORK).date().isoformat()
        by_day.setdefault(day, []).append(fill)
        require(split.contains(fill.fill_ts, final_holdout=trial.final_holdout), 'fill outside partition')
    quantities, cash, curves = {s: ZERO for s in SYMBOLS}, {s: ZERO for s in SYMBOLS}, {s: [] for s in SYMBOLS}
    moves, income = [], []
    fee_book, bp = EquityFeeBook(), D(result['cost_bp'])/10000
    maximum_difference = ZERO
    runtime_close_equity = {datetime.fromisoformat(stamp): D(value) for stamp, value in result['curve']}
    forced, reentry = 0, 0
    total_income = ZERO
    for row in rows:
        day = row['date']
        opened, closed = datetime.fromisoformat(row['opens_at']), datetime.fromisoformat(row['closes_at'])
        distribution = distributions.get(day)
        if distribution:
            symbol = distribution['symbol']
            credit = quantities[symbol] * D(distribution['amount'])
            if credit:
                cash[symbol] += credit
                total_income += credit
                moves.append(CashMovement('sell', credit, ZERO, date.fromisoformat(distribution['cash_available_session'])))
                income.append({'symbol': symbol, 'ex_date': day, 'cash_amount': str(credit)})
        for fill in by_day.get(day, []):
            symbol = symbols[fill.instrument_id]
            require(fill.fill_ts == opened, 'fill is not at declared regular open')
            reference = D(row['quotes'][symbol]['open'])
            expected = (reference*(1+bp if fill.side == 'buy' else 1-bp)).quantize(D('.00000001'))
            require(fill.price == expected, 'fill price is not the fixed adverse-cost scenario')
            fee, _ = fee_book.charge(day=date.fromisoformat(day), side=fill.side, price=fill.price, size=fill.size)
            require(fee == fill.fee, 'dated fee replay disagrees with stored fill')
            metadata = fill.metadata_['research']
            require(metadata['source_receipt'] == SOURCE_RECEIPT, 'fill missing bound source identity')
            require(metadata['conservative_cash_release'] == row['conservative_cash_release'], 'fill cash calendar differs')
            release = date.fromisoformat(row['conservative_cash_release'][:10])
            if fill.side == 'buy':
                require(fill.price*fill.size+fill.fee <= cash_balance(D(140), moves, ZERO, opened).available,
                        'buy spent unsettled proceeds or unpaid dividend')
                require(not any(p['symbol'] == symbol and p['exit'] <= day < p['reentry'] for p in source['blackouts']),
                        'buy inside blackout')
                quantities[symbol] += fill.size
                cash[symbol] -= fill.price*fill.size+fill.fee
            else:
                require(quantities[symbol] >= fill.size, 'short sale in stored fills')
                quantities[symbol] -= fill.size
                cash[symbol] += fill.price*fill.size-fill.fee
            moves.append(CashMovement(fill.side, fill.price*fill.size, fill.fee, release))
            if metadata['forced_blackout_exit']:
                require(any(p['symbol'] == symbol and p['exit'] == day and p['decision'] < day
                            for p in source['blackouts']), 'forced exit missing causal plan')
                forced += 1
            reentry += bool(metadata['blackout_reentry'])
        for plan in source['blackouts']:
            if plan['exit'] <= day < plan['reentry']:
                require(quantities[plan['symbol']] == 0, 'held at close inside blackout')
        for symbol in SYMBOLS:
            curves[symbol].append((day, cash[symbol]+quantities[symbol]*D(row['quotes'][symbol]['close'])))
        equity = D(140)+sum((curves[s][-1][1] for s in SYMBOLS), ZERO)
        require(closed in runtime_close_equity, 'runtime daily mark missing')
        maximum_difference = max(maximum_difference, abs(equity-runtime_close_equity[closed]))
    tolerance = D('.000001')*max(1, len(fills))
    require(maximum_difference <= tolerance, 'daily equity does not reconcile independently')
    require(total_income == D(result['metrics']['dividend_income_usd']), 'dividend entitlement amount differs')
    require(len(income) == len(result['metrics']['dividend_entitlements']), 'dividend entitlement count differs')
    require(all(q == 0 for q in quantities.values()), 'nonflat terminal inventory')
    net = sum(cash.values(), ZERO)
    require(abs(net-D(result['metrics']['net_usd'])) <= tolerance, 'portfolio net differs from stored cash and fills')
    require(abs(D(trial.pnl_after_fees)-net) <= tolerance, 'trial numeric net disagrees with full cash evidence')
    require(sum((f.fee for f in fills), ZERO) == trial.fees_total, 'trial fee field differs')
    decisions = result['metrics']['monthly_decisions']
    for decision in decisions:
        equity = D(decision['equity'])
        require(D(decision['reserve']) == D('.05')*equity, 'decision cash reserve differs')
        require(all(D(v) in (ZERO, min(D('.19')*equity, D(28))) for v in decision['targets'].values()),
                'decision target not an equal 19% sleeve with aggregate slot cap')
    uso = curves['USO']
    return {'trial_id': trial.id, 'strategy_id': strategy.id, 'status': 'PASS', 'fills_checked': len(fills),
        'orders_checked': len(orders), 'daily_marks_checked': len(rows), 'cash_entitlements_checked': len(income),
        'cash_and_marks_max_difference_usd': str(maximum_difference), 'tolerance_usd': str(tolerance),
        'independent_net_usd': str(net), 'final_holdout': trial.final_holdout,
        'blackout_forced_exits': forced, 'blackout_reentry_fills': reentry,
        'symbol_contribution_usd': {s: str(cash[s]) for s in SYMBOLS},
        'uso_marked_regimes': {name: period(uso, lo, hi) for name, lo, hi in (
            ('before_2020', '2008-01-01', '2020-01-01'),
            ('2020_dislocation_before_transition', '2020-01-01', '2020-04-27'),
            ('transition_remainder_2020', '2020-04-27', '2021-01-01'),
            ('post_2020', '2021-01-01', '2026-10-01'))},
        'daily_portfolio_drawdown': drawdown([D(140)]+[D(140)+sum((curves[s][i][1] for s in SYMBOLS), ZERO)
                                                              for i in range(len(rows))]),
        'no_strategy_replay': True}


def audit_available():
    source = load_source()
    paths = sorted((ARCHIVE/'runs').glob('train-*.json'))
    if (ARCHIVE/'runs/final.json').exists():
        paths.append(ARCHIVE/'runs/final.json')
    require(bool(paths), 'no completed run artifacts')
    records = []
    with session_scope() as session:
        old = {name: {c.name: getattr(session.get(cls, key), c.name) for c in cls.__table__.columns}
               for name, cls, key in [('strategy', Strategy, 6032), ('trial', Trial, 3518)]}
        old_hash = sha(canonical(json_value(old)).encode())
        require(old_hash == source['receipt']['original_failed_rows_sha256'], 'original failed rows changed')
        for path in paths:
            raw = path.read_bytes()
            result = json.loads(raw)
            records.append({**audit_run(session, source, result), 'artifact': str(path.relative_to(ROOT)), 'sha256': sha(raw)})
        finals = list(session.scalars(select(Trial.id).join(Strategy, Trial.strategy_id == Strategy.id).where(
            Trial.final_holdout.is_(True), Strategy.config['candidate'].astext == 'C05-amendment21')))
        require(len(finals) <= 1, 'more than one family final trial')
    output = {'status': 'PASS', 'source_receipt': SOURCE_RECEIPT, 'original_failed_rows_sha256': old_hash,
        'auditor_sha256': sha((ROOT/'src/tradingbot/research/c05_result_audit.py').read_bytes()),
        'no_strategy_replay': True, 'final_trials': finals, 'runs': records}
    encoded = json.dumps(output, sort_keys=True, indent=2)+'\n'
    with CaptureDiskBudget(ROOT/'data').reserve(3*len(encoded.encode())+65536):
        (ARCHIVE/'ledger-audit.json').write_text(encoded)
    (ROOT/'docs/research/23-c05-ledger-audit.json').write_text(encoded)
    print(json.dumps({'status': 'PASS', 'runs': len(records), 'final_trials': finals}))
    return output


if __name__ == '__main__':
    audit_available()
