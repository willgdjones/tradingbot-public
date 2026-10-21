"""Reconcile stored C07 fills, income and marks without replaying decisions."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal as D
import json

from sqlalchemy import select, text

from tradingbot.connectors.cash import CashMovement, NEW_YORK, cash_balance
from tradingbot.data.disk_budget import CaptureDiskBudget
from tradingbot.db.models import Fill, Order, Strategy, Trial
from tradingbot.db.session import session_scope
from tradingbot.research.c07_blackout_sources import sha
from tradingbot.research.c07_replay import ARCHIVE, ROOT, SOURCE_RECEIPT, SYMBOLS, load_source, split_for
from tradingbot.research.c06_month_end import drawdown
from tradingbot.research.equity_fees import EquityFeeBook

ZERO = D(0)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def audit_run(session, source, result):
    trial, strategy = session.get(Trial, result['trial_id']), session.get(Strategy, result['strategy_id'])
    require(trial is not None and strategy is not None and trial.strategy_id == strategy.id, 'stored identity differs')
    require(trial.status == result['status'] and trial.final_holdout == result['final_holdout'], 'stored status differs')
    require(trial.strategy_version == result['strategy_version'] and trial.metrics == result['metrics'], 'stored metrics/version differs')
    require(strategy.config['params']['source_receipt'] == SOURCE_RECEIPT, 'source receipt differs')
    metrics = result['metrics']
    require('partial_measurement_error' not in metrics, 'partial evidence lacks reconciled measurements')
    ids = strategy.config['params']['instrument_ids']
    symbols = {iid: symbol for symbol, iid in ids.items()}
    fills = list(session.scalars(select(Fill).where(Fill.trial_id == trial.id).order_by(Fill.fill_ts, Fill.id)))
    orders = list(session.scalars(select(Order).where(Order.trial_id == trial.id).order_by(Order.id)))
    if 'fill_ids' in result:
        require([f.id for f in fills] == result['fill_ids'], 'fill inventory differs')
    require(len(fills) == metrics['fills'], 'fill count differs')
    require(sum(o.status == 'rejected' for o in orders) == metrics['rejected_orders'], 'rejection count differs')
    split = split_for(source)
    curve = result.get('curve', metrics.get('curve'))
    require(bool(curve), 'no stored marks to audit')
    marks = {datetime.fromisoformat(stamp): D(value) for stamp, value in curve}
    last = max(marks)
    rows = [r for r in source['prices'] if any(
        split.contains(datetime.fromisoformat(r[field]), final_holdout=trial.final_holdout)
        and datetime.fromisoformat(r[field]) <= last for field in ('opens_at', 'closes_at'))]
    by_day, distributions = {}, {}
    for distribution in source['distributions']:
        distributions.setdefault(distribution['ex_date'], []).append(distribution)
    for fill in fills:
        require(split.contains(fill.fill_ts, final_holdout=trial.final_holdout), 'fill outside partition')
        by_day.setdefault(fill.fill_ts.astimezone(NEW_YORK).date().isoformat(), []).append(fill)
    quantities, cash = {s: ZERO for s in SYMBOLS}, {s: ZERO for s in SYMBOLS}
    moves, income, daily_equity = [], [], [D(140)]
    fee_book, bp = EquityFeeBook(), D(result['cost_bp']) / 10000
    difference, total_income, unavailable = ZERO, ZERO, ZERO
    forced, reentry, marks_checked = 0, 0, 0
    expiries = {}
    for row in rows:
        day = row['date']
        opened, closed = datetime.fromisoformat(row['opens_at']), datetime.fromisoformat(row['closes_at'])
        for distribution in distributions.get(day, []):
            symbol = distribution['symbol']
            quantity = quantities[symbol]
            credit = quantity * D(distribution['amount'])
            if credit:
                cash[symbol] += credit
                total_income += credit
                if distribution['cash_release'] is None:
                    unavailable += credit
                else:
                    moves.append(CashMovement('sell', credit, ZERO,
                        datetime.fromisoformat(distribution['cash_release']).astimezone(NEW_YORK).date()))
                income.append((symbol, day, quantity, credit, distribution['cash_release']))
        for fill in by_day.get(day, []):
            symbol = symbols[fill.instrument_id]
            require(fill.fill_ts == opened, 'fill is not at declared regular open')
            reference = D(row['quotes'][symbol]['open'])
            expected = (reference * (1+bp if fill.side == 'buy' else 1-bp)).quantize(D('.00000001'))
            require(fill.price == expected, 'fill price is not the fixed adverse-cost scenario')
            fee, _ = fee_book.charge(day=date.fromisoformat(day), side=fill.side, price=fill.price, size=fill.size)
            require(fee == fill.fee, 'dated fees disagree')
            metadata = fill.metadata_['research']
            require(metadata['source_receipt'] == SOURCE_RECEIPT, 'fill source identity differs')
            require(metadata['conservative_cash_release'] == row['conservative_cash_release'], 'fill cash calendar differs')
            release = date.fromisoformat(row['conservative_cash_release'][:10])
            cycle = metadata['weekly_cycle']
            expiry = cycle['original_scheduled_exit']
            if fill.side == 'buy':
                require(fill.price*fill.size+fill.fee <= cash_balance(D(140), moves, ZERO, opened).available,
                        'buy spent unsettled proceeds or unpaid income')
                require(not any(p['symbol'] == symbol and p['exit'] <= day < p['reentry'] for p in source['blackouts']),
                        'buy inside blackout')
                require(cycle['entry_decision'] < cycle['initial_entry_session'] <= day < expiry, 'entry extended its weekly cycle')
                require(not quantities[symbol] or expiries[symbol] == expiry, 'new cycle absorbed unexited old shares')
                expiries[symbol] = expiry
                quantities[symbol] += fill.size
                cash[symbol] -= fill.price*fill.size+fill.fee
            else:
                require(quantities[symbol] >= fill.size, 'short sale in stored fills')
                require(expiries[symbol] == expiry, 'exit changed original weekly expiry')
                require(day >= expiry or metadata['forced_blackout_exit'] or metadata['terminal_liquidation'],
                        'early exit lacks declared reason')
                quantities[symbol] -= fill.size
                cash[symbol] += fill.price*fill.size-fill.fee
            moves.append(CashMovement(fill.side, fill.price*fill.size, fill.fee, release))
            if metadata['forced_blackout_exit']:
                require(any(p['symbol'] == symbol and p['exit'] == day and p['decision'] < day
                            for p in source['blackouts']), 'forced exit missing causal plan')
                forced += 1
            reentry += bool(metadata['blackout_reentry'])
        for plan in source['blackouts']:
            if plan['exit'] <= day < plan['reentry'] and quantities[plan['symbol']]:
                require(trial.status == 'failed' and day == rows[-1]['date'] and day < plan['ex_date'],
                        'owned shares crossed unresolved action')
        for stamp, field in ((opened, 'open'), (closed, 'close')):
            if stamp not in marks:
                continue
            equity = D(140) + sum((cash[s]+quantities[s]*D(row['quotes'][s][field]) for s in SYMBOLS), ZERO)
            difference = max(difference, abs(equity-marks[stamp]))
            marks_checked += 1
            if field == 'close':
                daily_equity.append(equity)
    tolerance = D('.000001') * max(1, len(fills))
    require(difference <= tolerance, 'stored open/close equity does not reconcile independently')
    reported_income = [(r['symbol'], r['ex_date'], D(r['quantity_before_ex_open']), D(r['cash_amount']), r['cash_release'])
                       for r in metrics['dividend_entitlements']]
    require(income == reported_income and total_income == D(metrics['dividend_income_usd']), 'dividend entitlements differ')
    ending = rows[-1]
    mark_field = 'close' if datetime.fromisoformat(ending['closes_at']) in marks else 'open'
    contributions = {s: cash[s]+quantities[s]*D(ending['quotes'][s][mark_field]) for s in SYMBOLS}
    marked_net = sum(contributions.values(), ZERO)
    require(abs(marked_net+140-D(metrics['ending_marked_equity_usd'])) <= tolerance, 'ending marked equity differs')
    require(abs(marked_net-D(metrics['net_usd'])-D(metrics['unrealized_pnl_usd'])) <= tolerance, 'marked and realized net differ')
    require(abs(D(trial.pnl_after_fees)-D(metrics['net_usd'])) <= tolerance, 'trial numeric net differs')
    require(sum((f.fee for f in fills), ZERO) == trial.fees_total == D(metrics['fees_usd']), 'trial fees differ')
    balance = cash_balance(D(140), moves, ZERO, last)
    require(abs(balance.settled-D(metrics['ending_settled_cash_usd'])) <= tolerance, 'settled cash differs')
    require(abs(balance.unsettled+unavailable-D(metrics['ending_unsettled_cash_and_receivables_usd'])) <= tolerance,
            'unsettled cash and receivables differ')
    if metrics['complete_execution']:
        require(trial.status == 'complete' and all(q == 0 for q in quantities.values()) and not metrics['rejected_orders'],
                'complete execution assertion is false')
    for decision in metrics['weekly_decisions']:
        equity = D(decision['equity'])
        require(D(decision['reserve']) == D('.05')*equity, 'decision reserve differs')
        slots = strategy.config['params']['top_n']
        expected = min(D('.95')*equity, D(140))/slots
        ranked = sorted((D(value), s) for s, value in decision['residuals'].items() if D(value) < 0)
        require(decision['selected'] == [s for _, s in ranked[:slots]], 'negative residual rank/tie policy differs')
        require(set(decision['targets']) == set(decision['selected']) and all(D(v) == expected for v in decision['targets'].values()),
                'weekly decision targets differ')
    return {'trial_id': trial.id, 'strategy_id': strategy.id, 'audit_status': 'PASS', 'execution_status': trial.status,
        'complete_execution': metrics['complete_execution'], 'fills_checked': len(fills), 'orders_checked': len(orders),
        'open_and_close_marks_checked': marks_checked, 'cash_entitlements_checked': len(income),
        'cash_and_marks_max_difference_usd': str(difference), 'tolerance_usd': str(tolerance),
        'independent_marked_net_usd': str(marked_net), 'realized_net_usd': metrics['net_usd'],
        'ending_quantities': {s: str(q) for s, q in quantities.items()}, 'final_holdout': trial.final_holdout,
        'blackout_forced_exits': forced, 'blackout_reentry_fills': reentry,
        'symbol_marked_contribution_usd': {s: str(v) for s, v in contributions.items()},
        'daily_portfolio_drawdown': drawdown(daily_equity), 'no_strategy_replay': True}


def audit_available():
    source = load_source()
    paths = sorted((ARCHIVE/'runs').glob('train-*.json'))
    if (ARCHIVE/'runs/final.json').exists():
        paths.append(ARCHIVE/'runs/final.json')
    require(bool(paths), 'no stored run artifacts')
    records = []
    with session_scope() as session:
        old = session.execute(text("SELECT jsonb_build_object('strategy', (SELECT to_jsonb(s) FROM strategies s WHERE id=6080), "
            "'trial', (SELECT to_jsonb(t) FROM trials t WHERE id=3548))")).scalar_one()
        old_raw = (json.dumps(old, sort_keys=True, indent=2)+'\n').encode()
        old_hash = sha(old_raw)
        require(old_raw == (ARCHIVE/'original-rows.json').read_bytes(), 'original failed rows changed')
        for path in paths:
            raw = path.read_bytes()
            records.append({**audit_run(session, source, json.loads(raw)), 'artifact': str(path.relative_to(ROOT)), 'sha256': sha(raw)})
        finals = list(session.scalars(select(Trial.id).join(Strategy, Trial.strategy_id == Strategy.id).where(
            Trial.final_holdout.is_(True), Strategy.config['candidate'].astext == 'C07-amendment21')))
        require(len(finals) <= 1, 'more than one C07 family final')
    output = {'status': 'PASS', 'source_receipt': SOURCE_RECEIPT, 'original_failed_rows_sha256': old_hash,
        'auditor_sha256': sha((ROOT/'src/tradingbot/research/c07_result_audit.py').read_bytes()),
        'no_strategy_replay': True, 'final_trials': finals, 'runs': records}
    encoded = json.dumps(output, sort_keys=True, indent=2)+'\n'
    with CaptureDiskBudget(ROOT/'data').reserve(3*len(encoded.encode())+65536):
        (ARCHIVE/'ledger-audit.json').write_text(encoded)
    (ROOT/'docs/research/24-c07-ledger-audit.json').write_text(encoded)
    print(json.dumps({'status': 'PASS', 'runs': len(records), 'final_trials': finals}))
    return output


if __name__ == '__main__':
    audit_available()
