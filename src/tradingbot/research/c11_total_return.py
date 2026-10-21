"""C11 adjusted-total-return replay, durable trials and one committed final."""
from __future__ import annotations

import argparse
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D, ROUND_CEILING, ROUND_FLOOR
import json
from pathlib import Path
import subprocess

from sqlalchemy import select

from tradingbot.backtest.holdout import HoldoutSplit, json_value, register_split, strategy_identity
from tradingbot.connectors.cash import MarketSession, NEW_YORK
from tradingbot.data.archive import canonical
from tradingbot.data.disk_budget import CaptureDiskBudget
from tradingbot.db.models import Instrument, Strategy as StrategyRow, Trial
from tradingbot.db.session import session_scope
from tradingbot.research.c06_sources import spy_source
from tradingbot.research.c06_month_end import drawdown, monthly_luck
from tradingbot.research.c11_sources import REVIEWED_DAYS
from tradingbot.research.equity_data import ReferenceFX
from tradingbot.research.equity_fees import EquityFeeBook
from tradingbot.research.equity_runtime import EquityBacktester, EquityContext, EquityResearchLedger, ObservedStrategy
from tradingbot.research.total_return_data import (ROOT, ARCHIVE as PRICE_ARCHIVE, sha, yahoo_prices,
    alpaca_prices, nasdaq_prices, dividend_adjusted_reference, cross_check)
from tradingbot.research.turn_of_month import finish_metrics, instrument_for, vars_trip
from tradingbot.strategy.c11_expiration import ExpirationWeek
from tradingbot.strategy.interface import MarketEvent

ARCHIVE = ROOT / 'data/research/c11-total-return'
PLAN = ROOT / 'docs/research/38-c11-plan.md'
START, END = datetime(2006, 1, 1, tzinfo=UTC), datetime(2026, 10, 1, tzinfo=UTC)
VARIANTS, COSTS = ('expiry-close', 'next-open'), (5, 10)
ZERO = D(0)


def write_once(name, value):
    path = ARCHIVE / name
    raw = (json.dumps(json_value(value), sort_keys=True, indent=2) + '\n').encode()
    with CaptureDiskBudget(ROOT / 'data').reserve(3 * len(raw) + 65536):
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_bytes() != raw:
            raise ValueError('refuse replacement of C11 source/outcome artifact')
        if not path.exists():
            path.write_bytes(raw)
    return str(path.relative_to(ROOT)), sha(raw)


def freeze_source():
    comparison = json.loads((PRICE_ARCHIVE / 'nasdaq-comparison-SPY.json').read_bytes())
    rows, primary = yahoo_prices(ROOT / 'data/research/c03/SPY', 'SPY', START.date(), END.date())
    all_rows, all_meta = alpaca_prices(ROOT / comparison['secondary']['alpaca_all']['path'])
    split_rows, split_meta = alpaca_prices(ROOT / comparison['secondary']['alpaca_split']['path'], adjustment='split')
    nasdaq, nasdaq_meta = nasdaq_prices('SPY', START.date(), END.date()-timedelta(days=1))
    check = cross_check({d: r['close'] for d, r in rows.items()},
        dividend_adjusted_reference(nasdaq, all_rows['SPY'], split_rows['SPY']))
    if not check['passed'] or check != comparison['check'] or primary != comparison['primary']:
        raise ValueError('missing or contradictory SPY price comparison')
    calendar_manifest, calendar_source = spy_source()
    calendar = calendar_source['prices']
    if set(rows) != {date.fromisoformat(r['date']) for r in calendar}:
        raise ValueError('missing primary session price')
    prices = [{k: r[k] for k in ('date', 'opens_at', 'closes_at', 'conservative_cash_release')} |
              {'quote': rows[date.fromisoformat(r['date'])]} for r in calendar]
    inputs = [ROOT / primary['raw_path'], ROOT / 'data/research/c03/SPY/manifest.json',
        ROOT / calendar_manifest['data_path'], ROOT / 'docs/research/13-equity-data-repair-spy-amendment.json',
        PRICE_ARCHIVE / 'nasdaq-comparison-SPY.json']
    for meta in (all_meta, split_meta, nasdaq_meta):
        inputs.extend(p for p in (ROOT / meta['path']).glob('*') if p.is_file())
    source = {'candidate': 'C11', 'primary': primary, 'crosscheck': check,
        'secondary': {'alpaca_all': all_meta, 'alpaca_split': split_meta, 'nasdaq': nasdaq_meta},
        'inputs': {str(p.relative_to(ROOT)): sha(p.read_bytes()) for p in inputs},
        'prices': prices, 'calendar_only_prior_bundle': calendar_manifest['identity']['data_sha256'],
        'model': 'daily adjusted total-return equivalent; no separate dividend cash'}
    windows(prices, 'expiry-close')  # Calendar validation only, no conditional returns.
    path, digest = write_once('source.json', source)
    print(json.dumps({'source': path, 'source_sha256': digest, 'sessions': len(prices), 'check': {
        k: v for k, v in check.items() if k not in ('unpaired_dates', 'disagreeing_days')}}))


def load_source():
    raw = (ARCHIVE / 'source.json').read_bytes()
    digest = sha(raw)
    if digest not in PLAN.read_text():
        raise ValueError('C11 source hash must be recorded in the plan before replay')
    source = json.loads(raw)
    if not source['crosscheck']['passed']:
        raise ValueError('unaccepted source comparison')
    for name, expected in source['inputs'].items():
        if sha((ROOT / name).read_bytes()) != expected:
            raise ValueError('C11 source input changed: ' + name)
    source['sha256'] = digest
    return source


def split_for(source):
    return HoldoutSplit('c11-total-return:' + source['sha256'], START, END)


def windows(prices, variant, offset=0):
    if variant not in VARIANTS or offset not in (-7, 0, 7):
        raise ValueError('outside fixed C11 calendar variants')
    days = [date.fromisoformat(r['date']) for r in prices]
    if days != sorted(set(days)):
        raise ValueError('calendar duplicates or ordering')
    index, result = {d: i for i, d in enumerate(days)}, []
    for year, month in sorted({(d.year, d.month) for d in days}):
        first = date(year, month, 1)
        friday = first + timedelta(days=(4-first.weekday()) % 7 + 14)
        prior = [d for d in days if first <= d <= friday]
        if not prior or days[-1] < friday-timedelta(days=1):
            continue
        expiry = prior[-1]
        if year in REVIEWED_DAYS and expiry.day != REVIEWED_DAYS[year][month-1]:
            raise ValueError('calendar disagrees with reviewed Cboe expiration')
        monday = friday-timedelta(days=4)
        week = [d for d in days if monday <= d <= expiry]
        if not week:
            continue
        entry = week[0]
        if index[entry] == 0 or variant == 'next-open' and index[expiry]+1 == len(days):
            continue
        decision = days[index[entry]-1]
        exit_day = expiry if variant == 'expiry-close' else days[index[expiry]+1]
        shifted = [d+timedelta(days=offset) for d in (decision, entry, exit_day)]
        if any(d not in index for d in shifted):
            continue
        if (index[shifted[1]]-index[shifted[0]] != index[entry]-index[decision]
                or index[shifted[2]]-index[shifted[1]] != index[exit_day]-index[entry]):
            continue
        result.append({'month': f'{year:04}-{month:02}', 'expiry': str(expiry),
            'decision': str(shifted[0]), 'entry': str(shifted[1]), 'exit': str(shifted[2]),
            'exit_phase': 'close' if variant == 'expiry-close' else 'open', 'offset_days': offset})
    return result


def complete_window(window, by_day, split, final):
    return all(split.contains(datetime.fromisoformat(by_day[window[key]][stamp]), final_holdout=final)
               for key, stamp in (('decision', 'closes_at'), ('entry', 'opens_at'),
                                  ('exit', 'closes_at' if window['exit_phase'] == 'close' else 'opens_at')))


class TotalReturnFees:
    def __init__(self, runtime):
        self.runtime, self.raw_fees = runtime, EquityFeeBook()

    def charge(self, *, day, side, price, size, commit=True):
        factor = self.runtime.factor
        fee, evidence = self.raw_fees.charge(day=day, side=side, price=price/factor,
                                            size=size*factor, commit=commit)
        return fee, {**evidence, 'total_return_equivalent': True, 'adjustment_factor': str(factor),
                     'raw_share_equivalent': str(size*factor), 'raw_price_equivalent': str(price/factor)}


class C11Context(EquityContext):
    def marked_equity(self):
        return self.runtime.equity()


class C11Observer(ObservedStrategy):
    def on_start(self, ctx): self.delegate.on_start(C11Context(ctx, self.runtime))
    def on_event(self, ctx, event):
        self.runtime.observe(event)
        return self.delegate.on_event(C11Context(ctx, self.runtime), event)
    def on_finish(self, ctx): self.delegate.on_finish(C11Context(ctx, self.runtime))


class C11Ledger(EquityResearchLedger):
    def record_fill(self, **kwargs):
        fill = super().record_fill(**kwargs)
        fill.metadata_ = {**fill.metadata_, 'research': {**fill.metadata_['research'],
            'source': 'c11_total_return_equivalent', 'source_sha256': self.runtime.source_hash,
            'separate_dividend_credit': False}}
        return fill


class C11Backtester(EquityBacktester):
    def __init__(self, session, *, strategy, strategy_id, source, fx):
        sessions = {date.fromisoformat(r['date']): MarketSession(date.fromisoformat(r['date']),
            datetime.fromisoformat(r['conservative_cash_release']).astimezone(NEW_YORK).date(),
            datetime.fromisoformat(r['opens_at']), datetime.fromisoformat(r['closes_at'])) for r in source['prices']}
        self.source_hash, self.factor = source['sha256'], D(1)
        self.daily_exposure = []
        super().__init__(session, strategy=strategy, strategy_id=strategy_id, sessions=sessions, fx=fx)
        self.strategy, self.ledger = C11Observer(strategy, self), C11Ledger(session, self)
        self.fees = TotalReturnFees(self)

    def observe(self, event):
        self.factor = D(event.meta['factor'])
        if not self.factor.is_finite() or self.factor <= 0:
            raise ValueError('invalid total-return factor')
        super().observe(event)
        if event.meta['phase'] == 'close':
            owned = sum((q*self.marks[i] for i, (q, _) in self.positions.items()), ZERO)
            self.daily_exposure.append({'date': event.time.astimezone(NEW_YORK).date().isoformat(),
                                        'fraction': str(owned/self.equity())})

    def run(self, events, **kwargs):
        def admitted():
            trial = self.session.get(Trial, self.last_trial_id)
            if trial is None or trial.status != 'running':
                raise ValueError('C11 replay requires an admitted trial')
            self.session.commit()  # Before the first outcome-dependent observation.
            yield from events
        return super().run(admitted(), **kwargs)


def tr_instrument(session, symbol):
    raw_id, venue = instrument_for(session, symbol)
    raw = session.get(Instrument, raw_id)
    external = 'research:total-return:' + symbol
    inst = session.scalar(select(Instrument).where(Instrument.venue_id == venue, Instrument.external_id == external))
    if inst is None:
        inst = Instrument(venue_id=venue, market_id=raw.market_id, external_id=external,
            symbol=symbol, instrument_type='equity', currency='USD', contract_multiplier=D(1),
            metadata_={'research_only': True, 'total_return_equivalent': True, 'not_broker_asset_id': True})
        session.add(inst); session.flush()
    return inst.id, venue


def scenario(iid, ts, quote, phase, bp, **meta):
    factor, raw = D(quote['factor']), D(quote['raw_' + phase])
    slip = D(bp)/10000
    # Round adverse costs in the underlying raw-share price, then convert units.
    bid = (raw*(1-slip)).quantize(D('.01'), rounding=ROUND_FLOOR)*factor
    ask = (raw*(1+slip)).quantize(D('.01'), rounding=ROUND_CEILING)*factor
    return MarketEvent.quote(iid, ts, mid=D(quote[phase]),
        bid=bid.quantize(D('.00000001'), rounding=ROUND_FLOOR),
        ask=ask.quantize(D('.00000001'), rounding=ROUND_CEILING),
        meta={'phase': phase, 'factor': str(factor), 'reference': quote[phase],
              'assumed_execution': True, 'slippage_bp_per_side': bp, **meta})


def events(source, params, bp, final, observed):
    split = split_for(source)
    by_day = {r['date']: r for r in source['prices']}
    valid = {w['decision'] for w in params['windows'] if complete_window(w, by_day, split, final)}
    terminal = max(r['opens_at'] for r in source['prices']
                   if split.contains(datetime.fromisoformat(r['opens_at']), final_holdout=final))
    for row in source['prices']:
        for phase, key in (('open', 'opens_at'), ('close', 'closes_at')):
            stamp = datetime.fromisoformat(row[key])
            if split.contains(stamp, final_holdout=final):
                event = scenario(params['instrument_id'], stamp, row['quote'], phase, bp,
                    terminal_open=phase == 'open' and row[key] == terminal,
                    window_complete_in_partition=row['date'] in valid)
                observed.append(event)
                yield event


def period(curve, low, high):
    previous, values = D(140), []
    for stamp, value in curve:
        day = stamp.astimezone(NEW_YORK).date().isoformat()
        if low <= day < high:
            if not values: values.append(previous)
            values.append(value)
        previous = value
    return {'covered': bool(values), 'marked_net_usd': str(values[-1]-values[0]) if values else None,
            'marked_drawdown': drawdown(values) if values else None}


def diagnostics(bot, observed, trips, fills, runtime):
    month_ends = {}
    for stamp, value in runtime.curve:
        month_ends[stamp.astimezone(NEW_YORK).strftime('%Y-%m')] = value
    previous, monthly = D(140), {}
    for month, value in sorted(month_ends.items()):
        monthly[month], previous = value-previous, value
    closes = [e.mid for e in observed if e.meta['phase'] == 'close']
    def regime(low, high):
        selected = [t for t in trips if low <= t.exit_ts.astimezone(NEW_YORK).date().isoformat() < high]
        return {**period(runtime.curve, low, high), 'trades': len(selected),
                'net_usd': str(sum((t.net_pnl for t in selected), ZERO))}
    return {'decisions': bot.decisions, 'skips': bot.skips,
        'max_marked_drawdown': drawdown([D(140)] + [v for _, v in runtime.curve]),
        'monthly_marked_net_usd': json_value(monthly), 'luck': monthly_luck(monthly, len(trips)),
        'calendar_regimes': {name: regime(lo, hi) for name, lo, hi in (
            ('2006-2009', '2006-01-01', '2010-01-01'), ('2010-2019', '2010-01-01', '2020-01-01'),
            ('2020-2021', '2020-01-01', '2022-01-01'), ('2022', '2022-01-01', '2023-01-01'),
            ('2023-2026', '2023-01-01', '2027-01-01'))},
        'weekday_expiry_structure_break': {'before_2022': regime('2006-01-01', '2022-01-01'),
                                         'since_2022': regime('2022-01-01', '2027-01-01')},
        'marked_calendar_years': {str(y): regime(f'{y}-01-01', f'{y+1}-01-01')
            for y in sorted({t.astimezone(NEW_YORK).year for t, _ in runtime.curve})},
        'benchmarks': {'cash': {'total_return': '0'}, 'SPY_buy_hold': {
            'total_return': str(closes[-1]/closes[0]-1) if closes else None, 'max_drawdown': drawdown(closes),
            'basis': 'same-partition adjusted completed closes, no costs, full exposure'}},
        'fees_usd': str(sum((f.fee for f in fills), ZERO)),
        'adverse_cost_usd': str(sum((abs(f.price-D(f.metadata_['research']['execution']['reference']))*f.size
                                    for f in fills), ZERO)),
        'daily_exposure': runtime.daily_exposure,
        'average_exposure': str(sum((D(r['fraction']) for r in runtime.daily_exposure), ZERO)/len(runtime.daily_exposure))
            if runtime.daily_exposure else None, 'promotion_eligible': False}


def dependencies():
    names = ['research/c11_total_return.py', 'strategy/c11_expiration.py', 'research/total_return_data.py',
        'research/c06_sources.py', 'research/c11_sources.py', 'research/c06_month_end.py', 'research/turn_of_month.py',
        'research/equity_runtime.py', 'research/equity_fees.py', 'research/equity_data.py',
        'backtest/engine.py', 'backtest/holdout.py', 'backtest/fills.py', 'connectors/cash.py',
        'strategy/interface.py', 'ledger/ledger.py', 'ledger/accounting.py', 'risk/engine.py', 'risk/limits.py']
    return {p: sha((ROOT / 'src/tradingbot' / p).read_bytes()) for p in names}


def require_committed():
    paths = ['src/tradingbot/' + p for p in dependencies()] + [str(PLAN.relative_to(ROOT))]
    if subprocess.check_output(['git', 'status', '--porcelain', '--', *paths], cwd=ROOT).strip():
        raise ValueError('commit C11 plan and dependencies before outcomes')
    return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()


def run_variant(session, source, variant, bp, *, offset=0, final=False, expected_version=None):
    commit = require_committed()
    if variant not in VARIANTS or bp not in COSTS or offset not in (-7, 0, 7) or final and (bp != 10 or offset):
        raise ValueError('configuration outside frozen C11 family')
    key = f'c11-tr-{source["sha256"][:12]}-{variant}-{bp}-{offset}-' + ('final' if final else 'train')
    if session.scalar(select(StrategyRow.id).where(StrategyRow.key == key)):
        raise ValueError('C11 configuration already attempted; use stored evidence')
    CaptureDiskBudget(ROOT / 'data').check()
    iid, venue = tr_instrument(session, 'SPY')
    params = {'instrument_id': iid, 'variant': variant, 'slot_usd': '140',
              'windows': windows(source['prices'], variant, offset), 'source_sha256': source['sha256']}
    fx = ReferenceFX(ROOT / 'data/equities/fx/ecb-20260930.xml')
    version = {'cost_bp': bp, 'offset_days': offset, 'dependencies': dependencies(),
               'source_sha256': source['sha256'], 'fx_source_sha256': fx.source_hash,
               'model': 'total_return_equivalent_v1', 'fee_policy': 'dated 2026-09-17 raw-share equivalent'}
    row = StrategyRow(key=key, name=f'C11 {variant} {bp}bp offset {offset}', venue_id=venue,
        status='backtest', allocation_usd=D(140),
        config={'research_only': True, 'candidate': 'C11', 'research_family': 'c11', 'params': params})
    session.add(row); session.commit()
    split, runtime, calculated = split_for(source), None, None
    try:
        bot = ExpirationWeek(params)
        runtime = C11Backtester(session, strategy=bot, strategy_id=row.id, source=source, fx=fx)
        calculated, _ = strategy_identity(runtime.version_strategy, type(runtime),
            {'runtime': runtime.version_context, 'run': version}, (type(runtime.ledger), type(runtime.risk)))
        if final and calculated != expected_version:
            raise ValueError('final differs from committed selected version')
        observed = []
        result = runtime.run(events(source, params, bp, final, observed), split=split,
            final_holdout=final, version_params=version,
            notes='C11 total-return equivalent, scheduled expiration, virtual cash, dated fees and conservative settlement')
        metrics, trips, fills = finish_metrics(session, result, runtime, allow_rejections=True, require_flat=False)
        metrics.update(diagnostics(bot, observed, trips, fills, runtime))
        by_day = {r['date']: r for r in source['prices']}
        expected = sum(complete_window(w, by_day, split, final) for w in params['windows'])
        metrics.update({'expected_round_trips': expected,
            'complete_execution': not metrics['open_positions'] and result.orders_rejected == 0 and len(trips) == expected})
        trial = session.get(Trial, result.trial_id)
        trial.git_commit, trial.code_version, trial.metrics = commit, 'c11-total-return-v1', json_value(metrics)
        trial.pnl_after_fees, trial.pnl, trial.max_drawdown = D(metrics['net_usd']), D(metrics['net_usd'])+runtime.charged, runtime.max_drawdown
        p = metrics['luck']['p_value']
        trial.luck_p_value = D(str(p)) if p is not None else None
        session.commit()
        return {'status': 'complete', 'variant': variant, 'cost_bp': bp, 'offset_days': offset,
            'final_holdout': final, 'trial_id': trial.id, 'strategy_id': row.id, 'git_commit': commit,
            'strategy_version': trial.strategy_version, 'version_params': version, 'metrics': json_value(metrics),
            'trades': json_value([vars_trip(t) for t in trips]), 'curve': json_value(runtime.curve), 'fill_ids': [f.id for f in fills]}
    except BaseException as error:
        if not session.is_active: session.rollback()
        trial = session.get(Trial, runtime.last_trial_id) if runtime and runtime.last_trial_id else None
        if trial is None:
            register_split(session, split)
            trial = Trial(strategy_id=row.id, mode='backtest', final_holdout=False, dataset_key=split.dataset_key,
                holdout_start=split.holdout_start, data_start=split.data_start, data_end=split.data_end,
                strategy_version=calculated, params={'strategy': params, 'version_params': version,
                    'requested_final': final, 'final_feed_consumed': False, '_holdout': split.metadata()})
            session.add(trial)
        trial.status, trial.git_commit, trial.code_version = 'failed', commit, 'c11-total-return-v1'
        trial.completed_ts = datetime.now(UTC)
        trial.notes = f'C11 failed; any consumed final and partial fills preserved: {type(error).__name__}: {error}'
        if runtime:
            trial.max_drawdown, trial.fees_total = runtime.max_drawdown, runtime.charged
            trial.pnl_after_fees = runtime.realized-runtime.charged
            trial.metrics = json_value({'complete_execution': False, 'partial_replay': True,
                'last_processed_at': runtime.now, 'fees_usd': runtime.charged,
                'ending_marked_equity_usd': runtime.equity(), 'open_positions': runtime.positions,
                'halt_events': runtime.halt_events, 'curve': runtime.curve, 'promotion_eligible': False})
        session.commit()
        if not isinstance(error, Exception): raise
        return {'status': 'failed', 'variant': variant, 'cost_bp': bp, 'offset_days': offset,
            'final_holdout': bool(trial.final_holdout), 'requested_final': final, 'trial_id': trial.id,
            'strategy_id': row.id, 'git_commit': commit, 'error': str(error),
            'strategy_version': trial.strategy_version, 'metrics': trial.metrics}


def train():
    source, results = load_source(), []
    for variant in VARIANTS:
        for bp in COSTS:
            with session_scope() as session:
                result = run_variant(session, source, variant, bp)
            path, digest = write_once(f'train-{variant}-{bp}.json', result)
            results.append({k: v for k, v in result.items() if k not in ('curve', 'trades', 'fill_ids')} |
                           {'artifact': path, 'artifact_sha256': digest})
            print(json.dumps({k: result.get(k) for k in ('variant', 'cost_bp', 'status', 'trial_id', 'error')}), flush=True)
    eligible = [r for r in results if r['status'] == 'complete' and r['cost_bp'] == 10
                and r['metrics']['complete_execution'] and D(r['metrics']['net_usd']) > 0]
    selected = max(eligible, key=lambda r: (D(r['metrics']['net_usd']), -VARIANTS.index(r['variant']))) if eligible else None
    choice = {'source_sha256': source['sha256'], 'dependencies': dependencies(), 'split': split_for(source).metadata(),
        'training': results, 'selected': selected['variant'] if selected else None,
        'selected_trial_id': selected['trial_id'] if selected else None,
        'selected_strategy_version': selected['strategy_version'] if selected else None,
        'rule': 'highest positive complete 10bp training net; listed order ties', 'holdout_attempted': False}
    _, digest = write_once('selection.json', choice)
    print(json.dumps({'selected': choice['selected'], 'selection_sha256': digest}), flush=True)


def controls():
    source = load_source()
    for variant in VARIANTS:
        for offset in (-7, 7):
            with session_scope() as session:
                result = run_variant(session, source, variant, 10, offset=offset)
            write_once(f'control-{variant}-{offset}.json', result)
            print(json.dumps({k: result.get(k) for k in ('variant', 'offset_days', 'trial_id', 'status', 'error')}), flush=True)


def final():
    source, commit = load_source(), require_committed()
    raw = (ARCHIVE / 'selection.json').read_bytes()
    committed = subprocess.check_output(['git', 'show', commit+':'+str(PLAN.relative_to(ROOT))], cwd=ROOT)
    if sha(raw) not in committed.decode() or committed != PLAN.read_bytes():
        raise ValueError('selection hash must be in committed plan before final')
    choice = json.loads(raw)
    if (choice['source_sha256'] != source['sha256'] or choice['dependencies'] != dependencies()
            or choice['split'] != split_for(source).metadata() or choice['selected'] not in VARIANTS):
        raise ValueError('invalid or absent frozen C11 winner')
    chosen = next(r for r in choice['training'] if r['trial_id'] == choice['selected_trial_id'])
    with session_scope() as session:
        trial = session.get(Trial, chosen['trial_id'])
        if (trial is None or trial.status != 'complete' or trial.final_holdout
                or trial.strategy_version != choice['selected_strategy_version'] or trial.metrics != chosen['metrics']
                or D(trial.metrics['net_usd']) <= 0 or not trial.metrics['complete_execution']):
            raise ValueError('frozen selection differs from durable training')
        result = run_variant(session, source, choice['selected'], 10, final=True,
                             expected_version=choice['selected_strategy_version'])
    _, digest = write_once('final.json', result)
    print(json.dumps({'trial_id': result['trial_id'], 'status': result['status'],
                      'net_usd': result.get('metrics', {}).get('net_usd'), 'artifact_sha256': digest}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('source', 'train', 'controls', 'final'))
    args = parser.parse_args()
    {'source': freeze_source, 'train': train, 'controls': controls, 'final': final}[args.phase]()


if __name__ == '__main__':
    main()
