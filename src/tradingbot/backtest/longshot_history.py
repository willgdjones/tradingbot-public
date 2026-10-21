"""Frozen full-cohort longshot study: source manifest, exact tape, durable trials.

Prepare reads reference data only. A final tape is materialized only inside the
shared backtester's post-admission iterator. Replays are isolated by savepoint;
all attempted variants and their execution receipts survive that rollback.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
import hashlib
import heapq
import json
import os
from pathlib import Path
import subprocess

import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import select, text

from tradingbot.data.disk_budget import CaptureDiskBudget
from tradingbot.db.models import Fill, Order, Position, Strategy as StrategyRow, Trial
from tradingbot.db.session import SessionLocal, get_engine
from tradingbot.ledger.accounting import FillEvent, iter_round_trips
from tradingbot.ledger.stats import luck_probability, max_drawdown
from tradingbot.strategy.favourite_longshot import FavouriteLongshotBias, SIDE_RULES
from tradingbot.strategy.interface import MarketEvent
from .engine import Settlement
from .holdout import HoldoutSplit, HoldoutViolation, json_value, register_split, strategy_identity, utc
from .prediction_runtime import PredictionBacktester

D = Decimal
ROOT = Path('data/history/longshot-replay-20261001')
COHORT = Path('data/history/longshot-20260930/cohort.json')
AUDIT = Path('docs/research/08-history-capture.json')
PLAN = Path('docs/research/20-longshot-plan.md')
COHORT_SHA = '35c64518ea06b437e6c4a614d43f1650333ac5e9c66da7800825e7b7700be0d9'
SPLIT = HoldoutSplit('longshot:' + COHORT_SHA, datetime.fromisoformat('2025-08-29T15:15:47+00:00'),
                     datetime.fromisoformat('2026-09-30T23:01:46.460587+00:00'))
OFFSETS = ('0.01', '0.02', '0.05')
LEGACY_IDS = (1756, 1758, 1761, 1763, 1765, 1767)
BUDGET = CaptureDiskBudget(Path('data'))


def sha(path):
    with Path(path).open('rb') as file:
        return hashlib.file_digest(file, 'sha256').hexdigest()


def encoded(value):
    return json.dumps(json_value(value), sort_keys=True, indent=2, allow_nan=False).encode() + b'\n'


def immutable_json(path, value):
    path = Path(path)
    body = encoded(value)
    if path.exists():
        if path.read_bytes() != body:
            raise HoldoutViolation(f'immutable artifact differs: {path}')
        return
    with BUDGET.reserve(3 * len(body)):
        path.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation prevents accidental concurrent replacement.
        temporary = path.with_suffix(path.suffix + '.tmp')
        with temporary.open('xb') as out:
            out.write(body); out.flush(); os.fsync(out.fileno())
        os.link(temporary, path)
        temporary.unlink()


def instant(value):
    return utc(datetime.fromisoformat(value) if isinstance(value, str) else value)


def reference_rows(cohort, catalog, split=SPLIT):
    """Pure reference gate; no prices are inputs and no payouts reach the reactor."""
    wanted = {(r['venue'], r['contract']): r for r in cohort}
    if len(wanted) != len(cohort):
        raise ValueError('duplicate source cohort contracts')
    grouped = defaultdict(list)
    for row in catalog:
        contract = row['external_id'].rsplit(':', 1)[0] if row['venue'] == 'kalshi' else row['market_external_id']
        if (row['venue'], contract) in wanted:
            grouped[row['venue'], contract].append(row)
    result = []
    for key, source in wanted.items():
        inputs = grouped[key]
        reasons = []
        if len(inputs) != 2 or {i['instrument_type'] for i in inputs} != {'binary_yes', 'binary_no'}:
            reasons.append('incomplete_binary_pair')
        values = [r['state'].get('payout') for r in inputs]
        try:
            certified = (len(values) == 2 and all(v is not None and D(v).is_finite()
                         and 0 <= D(v) <= 1 for v in values) and sum(map(D, values), D(0)) == 1)
        except (ValueError, ArithmeticError):
            certified = False
        if not certified:
            reasons.append('uncertified_payout_pair')
        if source['event_id'] == 'KXINX-26JAN19H1600':
            reasons.append('documented_off_session_event')
        derived = []
        for row in inputs:
            state = row['state']
            raw = state if key[0] == 'kalshi' else row
            fields = {}
            try:
                fields = {name: instant(raw[name]) for name in ('open_ts', 'close_ts', 'resolve_ts')}
            except (KeyError, TypeError, ValueError):
                reasons.append('missing_or_invalid_reference_timestamp')
            if fields:
                op, cl, rs = (fields[n] for n in ('open_ts', 'close_ts', 'resolve_ts'))
                if cl <= op or rs <= op:
                    reasons.append('invalid_catalog_window')
                if cl != instant(source['close']):
                    reasons.append('cohort_close_disagreement')
            if state.get('status') != 'settled':
                reasons.append('not_certified_settled')
            if D(row['multiplier']) != 1:
                reasons.append('non_unit_multiplier')
            derived.append((row, fields))
        if len(derived) == 2 and derived[0][1] != derived[1][1]:
            reasons.append('outcome_reference_disagreement')
        partition = None
        if derived and derived[0][1]:
            fields = derived[0][1]
            for final in (False, True):
                if all(split.contains(fields[n], final_holdout=final) for n in ('close_ts', 'resolve_ts')):
                    partition = 'final' if final else 'training'
            if partition is None:
                reasons.append('partition_boundary_crossing_or_outside')
        reasons = sorted(set(reasons))
        if not inputs:
            # Preserve absent source contracts as an explicit audit record.
            result.append({**source, 'contract': ':'.join(key), 'instrument_id': None,
                           'exclusions': reasons, 'partition': None})
        for row, fields in derived:
            valid = partition if not reasons else None
            lower = split.holdout_start if partition == 'final' else split.data_start
            window_start = max(fields['open_ts'], fields['close_ts'] - timedelta(days=7), lower) if fields else None
            result.append({
                'instrument_id': row['instrument_id'], 'market_id': row['market_id'],
                'external_id': row['external_id'], 'instrument_type': row['instrument_type'],
                'multiplier': str(row['multiplier']), 'outcome': row['outcome'],
                'venue': key[0], 'native_contract': key[1], 'contract': ':'.join(key),
                'event_id': source['event_id'], 'category': source['category'],
                'category_key': key[0] + ':' + source['category'], 'catalog_page': source['catalog_page'],
                'catalog_volume': source['volume'], 'payout': row['state'].get('payout'),
                'open_ts': fields.get('open_ts'), 'close_ts': fields.get('close_ts'),
                'resolve_ts': fields.get('resolve_ts'), 'window_start': window_start,
                'entry_end': fields['close_ts'] - timedelta(seconds=300) if fields else None,
                'partition': valid, 'exclusions': reasons,
            })
    return json_value(sorted(result, key=lambda r: (r['contract'], r['instrument_id'] or -1)))


def legacy_receipt(session):
    rows = session.execute(select(Trial.__table__).where(Trial.id.in_(LEGACY_IDS)).order_by(Trial.id)).mappings().all()
    if len(rows) != len(LEGACY_IDS):
        raise ValueError('legacy trial inventory changed')
    return {'trial_ids': list(LEGACY_IDS), 'full_rows_sha256': hashlib.sha256(encoded([dict(r) for r in rows])).hexdigest()}


def prepare(root=ROOT):
    audit = json.loads(AUDIT.read_text())
    if sha(COHORT) != COHORT_SHA or audit['cohort_sha256'] != COHORT_SHA:
        raise ValueError('captured cohort changed')
    for item in audit['receipt_hashes']:
        if sha(item['path']) != item['sha256']:
            raise ValueError(f"capture receipt changed: {item['path']}")
    with SessionLocal() as session:
        catalog = [dict(r) for r in session.execute(text("""
            SELECT i.id AS instrument_id, i.market_id, i.external_id, i.outcome,
                   i.instrument_type, i.contract_multiplier AS multiplier, v.key AS venue,
                   i.metadata->'historical'->'state' AS state, m.external_id AS market_external_id,
                   m.open_ts, m.close_ts, m.resolve_ts
            FROM instruments i JOIN markets m ON m.id=i.market_id JOIN venues v ON v.id=i.venue_id
            WHERE v.key IN ('kalshi','polymarket_intl') AND i.metadata->'historical' IS NOT NULL
        """)).mappings()]
        old = legacy_receipt(session)
    rows = reference_rows(json.loads(COHORT.read_text()), catalog)
    if len(rows) != 74768 or any(r['instrument_id'] is None for r in rows):
        raise ValueError('full cohort instrument count changed')
    first = min(instant(c['first_trade']) for c in audit['database']['categories'])
    last = max(instant(r['resolve_ts']) for r in rows if r['resolve_ts']) + timedelta(microseconds=1)
    if first != SPLIT.data_start or last != SPLIT.data_end:
        raise HoldoutViolation('preregistered full-source bounds changed')
    manifest = {'schema': 1, 'cohort_sha256': COHORT_SHA, 'capture_audit_sha256': sha(AUDIT),
                'preregistration_sha256': sha(PLAN), 'split': SPLIT.metadata(), 'legacy': old,
                'rows': rows, 'source_receipts': audit['receipt_hashes']}
    immutable_json(root / 'manifest.json', manifest)
    counts = Counter((r['category_key'], r['partition'] or 'excluded') for r in rows)
    summary = {'manifest_path': str(root / 'manifest.json'), 'manifest_sha256': sha(root / 'manifest.json'),
               'cohort_sha256': COHORT_SHA, 'split': SPLIT.metadata(), 'legacy': old,
               'instrument_counts': {f'{k[0]}/{k[1]}': v for k,v in sorted(counts.items())},
               'excluded_contracts': {r['contract']: r['exclusions'] for r in rows if r['exclusions']}}
    immutable_json(root / 'preparation.json', summary)
    return summary


def load_manifest(root=ROOT):
    summary = json.loads((root / 'preparation.json').read_text())
    if sha(root / 'manifest.json') != summary['manifest_sha256']:
        raise HoldoutViolation('manifest changed after preparation')
    manifest = json.loads((root / 'manifest.json').read_text())
    if manifest['capture_audit_sha256'] != sha(AUDIT) or manifest['preregistration_sha256'] != sha(PLAN):
        raise HoldoutViolation('source audit or preregistration changed')
    return manifest, summary['manifest_sha256']


def category_rows(manifest, category, partition=None):
    return [r for r in manifest['rows'] if r['category_key'] == category and r['partition'] is not None
            and (partition is None or r['partition'] == partition)]


def reference_maps(rows):
    pairs = defaultdict(list)
    for row in rows:
        pairs[row['contract']].append(row['instrument_id'])
    return {'market_of': {str(r['instrument_id']): r['contract'] for r in rows},
            'siblings': {str(r['instrument_id']): [i for i in pairs[r['contract']] if i != r['instrument_id']] for r in rows},
            'event_ts': {str(r['instrument_id']): r['close_ts'] for r in rows},
            # Mapping membership is O(1) on the large frozen instrument universe.
            'instruments': {str(r['instrument_id']): True for r in rows}}


def slug(category):
    return category.replace(':', '_').replace('/', '_')


def cache_tape(rows, category, partition, manifest_sha, root=ROOT):
    """Called lazily by feed(), after final admission. Exact decimals stay strings."""
    path = root / (slug(category) + '-' + partition + '.parquet')
    receipt = path.with_suffix('.json')
    identity = {'schema': 1, 'category': category, 'partition': partition, 'manifest_sha256': manifest_sha}
    if path.exists() or receipt.exists():
        info = json.loads(receipt.read_text())
        if any(info.get(k) != v for k,v in identity.items()) or sha(path) != info['sha256']:
            raise HoldoutViolation('tape cache identity/content mismatch')
        return path, info
    BUDGET.check()
    schema = pa.schema([('time', pa.timestamp('us', tz='UTC')), ('id', pa.int64()),
                        ('instrument_id', pa.int64()), ('price', pa.string()), ('size', pa.string()),
                        ('external_trade_id', pa.string()), ('aggressor_side', pa.string())])
    temporary = path.with_suffix('.parquet.tmp')
    if temporary.exists():
        raise HoldoutViolation(f'interrupted tape cache requires audit: {temporary}')
    count = 0
    instruments = set()
    with get_engine().connect() as connection:
        connection.execute(text('CREATE TEMP TABLE replay_windows (instrument_id bigint PRIMARY KEY, lo timestamptz, hi timestamptz) ON COMMIT DROP'))
        windows = [(r['instrument_id'], instant(r['window_start']), instant(r['resolve_ts'])) for r in rows
                   if instant(r['window_start']) < instant(r['resolve_ts'])]
        with connection.connection.driver_connection.cursor() as cursor:
            with cursor.copy('COPY replay_windows (instrument_id,lo,hi) FROM STDIN') as copy:
                for row in windows:
                    copy.write_row(row)
        connection.execute(text('ANALYZE replay_windows'))
        lower, upper = ((SPLIT.holdout_start, SPLIT.data_end) if partition == 'final' else
                        (SPLIT.data_start, SPLIT.holdout_start))
        stream = connection.execution_options(stream_results=True).execute(text("""
            SELECT t.time,t.id,t.instrument_id,t.price::text AS price,t.size::text AS size,
                   t.external_trade_id,t.aggressor_side
            FROM trades t JOIN replay_windows w ON w.instrument_id=t.instrument_id
            WHERE t.time>=:lower AND t.time<:upper AND t.time>=w.lo AND t.time<w.hi
              AND t.metadata->'historical'->>'maker_fill_eligible'='true'
            ORDER BY t.time,t.id
        """), {'lower': lower, 'upper': upper}).mappings()
        with BUDGET.reserve(65536):
            root.mkdir(parents=True, exist_ok=True)
            writer = pq.ParquetWriter(temporary, schema, compression='zstd')
        try:
            for batch in stream.partitions(25000):
                values = [dict(r) for r in batch]
                if any(r['external_trade_id'] is None or D(r['size']) < 0 or not 0 <= D(r['price']) <= 1 for r in values):
                    raise ValueError('invalid source execution evidence')
                table = pa.Table.from_pylist(values, schema=schema)
                with BUDGET.reserve(table.nbytes * 3):
                    writer.write_table(table)
                count += len(values)
                instruments.update(r['instrument_id'] for r in values)
        finally:
            writer.close()
    os.link(temporary, path); temporary.unlink()
    info = {**identity, 'sha256': sha(path), 'rows': count, 'bytes': path.stat().st_size,
            'instruments_with_observations': len(instruments), 'eligible_instruments': len(rows)}
    immutable_json(receipt, info)
    return path, info


def feed(rows, category, partition, manifest_sha, root=ROOT, *, on_cache=None):
    # Generator body deliberately does not run until Backtester.run has admitted.
    path, info = cache_tape(rows, category, partition, manifest_sha, root)
    if on_cache:
        on_cache(info)
    lookup = {r['instrument_id']: r for r in rows}
    def trades():
        for batch in pq.ParquetFile(path).iter_batches(batch_size=25000):
            for r in batch.to_pylist():
                ref = lookup[r['instrument_id']]
                yield MarketEvent.trade(r['instrument_id'], r['time'], price=D(r['price']), size=D(r['size']),
                    maker_fill_eligible=True, meta={'trade_id': r['id'], 'sequence': r['id'],
                    'execution_identity': ref['contract'] + ':' + r['external_trade_id']})
    timers = []
    for r in rows:
        deadline = instant(r['entry_end'])
        if instant(r['window_start']) <= deadline < instant(r['resolve_ts']):
            timers.append(MarketEvent.quote(r['instrument_id'], deadline, meta={'timer': True, 'sequence': r['instrument_id']}))
    key = lambda e: (utc(e.time), 0 if e.meta.get('timer') else 1, e.meta['sequence'])
    yield from heapq.merge(trades(), sorted(timers, key=key), key=key)


def run_parameters(rows, category, side, offset):
    return {**reference_maps(rows), 'category': category, 'side_rule': side, 'offset': offset,
            'size': '10', 'threshold': '0.5', 'min_price': '0.03', 'max_price': '0.97', 'tick': '0.01',
            'max_fills_per_market': 3, 'entry_blackout_seconds': 300, 'within_days': 7}


def version_parameters(manifest_sha):
    return {'manifest_sha256': manifest_sha, 'driver_sha256': sha(__file__),
            'legacy_fee_adapter_sha256': sha(Path(__file__).with_name('favourite_longshot.py')),
            'preregistration_sha256': sha(PLAN), 'fee_scenario': 'current PM US coefficients counterfactual on native history'}


def identity_for(runtime, version_params):
    return strategy_identity(runtime.version_strategy, type(runtime),
        {'runtime': runtime.version_context, 'run': version_params}, (type(runtime.ledger), type(runtime.risk)))


def create_research_strategy(session, category):
    key = 'longshot-full-' + hashlib.sha256(category.encode()).hexdigest()[:16]
    row = session.scalar(select(StrategyRow).where(StrategyRow.key == key))
    if row is None:
        row = StrategyRow(key=key, name='Longshot history: ' + category, status='backtest', allocation_usd=D(140),
                          description='Isolated virtual research collateral; no live funding or venue authorization.')
        session.add(row); session.commit()
    if row.status != 'backtest' or row.allocation_usd != 140:
        raise ValueError('research strategy state changed')
    return row.id


def band(price):
    edges = ('0.03', '0.30', '0.50', '0.70', '0.90', '0.97')
    for lo, hi in zip(edges, edges[1:]):
        if D(lo) <= price < D(hi) or price == D(hi) == D('.97'):
            return lo + '–' + hi
    return 'outside-reference-band (order offset)'


def execution_metrics(session, runtime, result, rows):
    """Capture all receipts before rollback; rolled-back fill IDs aren't evidence."""
    lookup = {r['instrument_id']: r for r in rows}
    fills = list(session.scalars(select(Fill).where(Fill.trial_id == result.trial_id).order_by(Fill.fill_ts, Fill.id)))
    grouped = defaultdict(list)
    receipts = []
    for f in fills:
        grouped[f.instrument_id].append(f)
        order = f.order
        receipts.append({'instrument_id': f.instrument_id, 'contract': lookup[f.instrument_id]['contract'],
                         'event_id': lookup[f.instrument_id]['event_id'], 'time': f.fill_ts,
                         'side': f.side, 'price': f.price, 'size': f.size, 'fee': f.fee,
                         'liquidity': f.liquidity, 'metadata': f.metadata_,
                         'order_created_ts': order.created_ts, 'order_limit_price': order.limit_price})
    trips = []
    for iid, fs in grouped.items():
        for t in iter_round_trips([FillEvent(f.side, f.price, f.size, f.fee, f.fill_ts) for f in fs], D(1)):
            trips.append({'instrument_id': iid, 'contract': lookup[iid]['contract'], 'event_id': lookup[iid]['event_id'],
                          'entry_ts': t.entry_ts, 'exit_ts': t.exit_ts, 'gross_pnl': t.gross_pnl,
                          'fees': t.fees, 'net_pnl': t.net_pnl, 'entry_price': runtime.entry_prices[iid]})
    trips.sort(key=lambda t: (t['exit_ts'], t['instrument_id']))
    buckets = {'month': defaultdict(list), 'quarter': defaultdict(list), 'entry_price': defaultdict(list)}
    days = defaultdict(lambda: D(0))
    for t in trips:
        dt = utc(t['exit_ts'])
        days[dt.date().isoformat()] += t['net_pnl']
        buckets['month'][dt.strftime('%Y-%m')].append(t)
        buckets['quarter'][f'{dt.year}-Q{(dt.month-1)//3+1}'].append(t)
        buckets['entry_price'][band(t['entry_price'])].append(t)
    for month in runtime.monthly:
        buckets['month'][month]  # Preserve observed calendar months with zero fills.
        year, number = map(int, month.split('-'))
        buckets['quarter'][f'{year}-Q{(number-1)//3+1}']
    for label in ('0.03–0.30', '0.30–0.50', '0.50–0.70', '0.70–0.90', '0.90–0.97'):
        buckets['entry_price'][label]
    regimes = {kind: {key: {'trades': len(v), 'net_pnl': sum((t['net_pnl'] for t in v),D(0)),
                           'gross_pnl': sum((t['gross_pnl'] for t in v),D(0)),
                           'fees': sum((t['fees'] for t in v),D(0)),
                           'realized_drawdown': max_drawdown([t['net_pnl'] for t in v])}
                      for key,v in sorted(values.items())} for kind,values in buckets.items()}
    open_positions = session.scalar(select(text('count(*)')).select_from(Position).where(
        Position.strategy_id == runtime.strategy_id, Position.mode == 'backtest', Position.quantity != 0))
    active_orders = session.scalar(select(text('count(*)')).select_from(Order).where(
        Order.trial_id == result.trial_id, Order.status.in_(['open','partially_filled','pending'])))
    residual = runtime.cash - runtime.initial_cash - result.report['pnl_after_fees']
    tolerance = D('0.000002') * len(fills)
    if open_positions or active_orders or any(runtime.quantities.values()) or abs(runtime.inventory_value) > D('1e-40'):
        raise ValueError('replay did not finish terminal and flat')
    if abs(residual) > tolerance:
        raise ValueError(f'cash/ledger reconciliation outside accounting precision: {residual}')
    metrics = {**result.report, 'marked_drawdown': runtime.max_drawdown,
               'marked_drawdown_fraction': runtime.max_drawdown / runtime.initial_cash,
               'cash_net_pnl': runtime.cash - runtime.initial_cash, 'cash_ledger_residual': residual,
               'accounting_tolerance': tolerance, 'maximum_collateral': runtime.max_collateral,
               'orders_placed': result.orders_placed, 'orders_rejected': result.orders_rejected,
               'maker_fills': result.fills, 'rejection_reasons': dict(runtime.rejection_reasons),
               'halt_events': runtime.halt_events, 'holding_breaches': runtime.holding_breaches,
               'open_positions': open_positions, 'active_orders': active_orders,
               'unique_contracts': len({t['contract'] for t in trips}), 'unique_events': len({t['event_id'] for t in trips}),
               'unique_entry_dates': len({utc(t['entry_ts']).date() for t in trips}),
               'maximum_holding_seconds': max(((utc(t['exit_ts'])-utc(t['entry_ts'])).total_seconds() for t in trips), default=0),
               'unique_exit_dates': len(days), 'date_aggregate_p_value': luck_probability(list(days.values())),
               'date_aggregate_net': days, 'regimes': regimes, 'monthly_marks': runtime.monthly,
               'daily_equity': runtime.daily, 'initial_cash': runtime.initial_cash}
    return json_value(metrics), json_value({'fills': receipts, 'trips': trips})


def trial_summary(trial):
    return json_value({k: getattr(trial,k) for k in ('id','status','strategy_version','final_holdout',
            'pnl','pnl_after_fees','fees_total','trade_count','max_drawdown','luck_p_value','metrics','notes')})


def run_variant(manifest, manifest_sha, category, side, offset, *, final=False, expected_version=None, root=ROOT):
    partition = 'final' if final else 'training'
    full_rows = category_rows(manifest, category)
    rows = category_rows(manifest, category, partition)
    params = run_parameters(full_rows, category, side, offset)
    vp = version_parameters(manifest_sha)
    with SessionLocal() as session, localcontext() as context:
        context.prec = 60
        if legacy_receipt(session) != manifest['legacy']:
            raise HoldoutViolation('legacy trials changed')
        sid = create_research_strategy(session, category)
        runtime = PredictionBacktester(session, strategy=FavouriteLongshotBias(params), strategy_id=sid, instruments=full_rows)
        version, identity = identity_for(runtime, vp)
        if expected_version is not None and version != expected_version:
            raise HoldoutViolation('final implementation/reference identity differs from selected training')
        if not final:
            # Serialize first admission too; two CLI invocations cannot duplicate
            # a training attempt while its durable RUNNING row is being created.
            session.execute(text('SELECT pg_advisory_xact_lock(:key)'),
                            {'key': int.from_bytes(bytes.fromhex(version)[:8], signed=True)})
        previous = session.scalar(select(Trial).where(Trial.strategy_version == version, Trial.final_holdout == final))
        if previous is not None:
            return trial_summary(previous)  # Never reread prices on reuse, even failed/running attempts.
        register_split(session, SPLIT)
        durable_id = None
        trial_params = {**json_value(params), '_holdout': {**SPLIT.metadata(), 'final_holdout': final,
                                      'strategy_version': version, 'identity': identity}}
        if not final:
            durable = Trial(strategy_id=sid, mode='backtest', status='running', params=trial_params,
                            dataset_key=SPLIT.dataset_key, holdout_start=SPLIT.holdout_start,
                            strategy_version=version, final_holdout=False,
                            notes=f'Full-cohort {category} {side} {offset}; training admitted before feed access.')
            session.add(durable); session.flush(); durable_id = durable.id
        session.commit()
        sp = session.begin_nested()
        cache = {}
        try:
            result = runtime.run(feed(rows, category, partition, manifest_sha, root, on_cache=cache.update),
                split=SPLIT, final_holdout=final, version_params=vp, params=params,
                settlements=[Settlement(r['instrument_id'],D(r['payout']),instant(r['resolve_ts'])) for r in rows],
                notes=f'Full-cohort {category} {side} {offset}; exact native trade-through/PM US fees counterfactual.')
            if final:
                durable_id = result.trial_id
            metrics, executions = execution_metrics(session, runtime, result, full_rows)
            metrics['trial_id'] = durable_id  # The training replay row rolls back.
            executions.update({'durable_trial_id': durable_id, 'strategy_version': version, 'tape': cache})
            artifact = root / f'trial-{durable_id}-executions.json'
            immutable_json(artifact, executions)
            fields = {k: result.report[k] for k in ('pnl','pnl_after_fees','fees_total','trade_count','luck_p_value')}
            fields.update(status='complete', max_drawdown=runtime.max_drawdown,
                          completed_ts=datetime.now(UTC), metrics={**metrics, 'execution_receipt': str(artifact),
                          'execution_sha256': sha(artifact), 'tape': cache, 'category': category,
                          'side_rule': side, 'offset': offset},
                          data_start=SPLIT.holdout_start if final else SPLIT.data_start,
                          data_end=(SPLIT.data_end if final else SPLIT.holdout_start) - timedelta(microseconds=1))
        except BaseException as error:
            durable_id = durable_id or runtime.last_trial_id
            sp.rollback(); session.expunge_all()
            if durable_id is not None:
                durable = session.get(Trial, durable_id)
                if durable:
                    durable.status = 'failed'
                    durable.notes = (durable.notes or '') + f'\nFailed without retry: {type(error).__name__}: {error}'
                    session.commit()
            raise
        else:
            sp.rollback(); session.expunge_all()
            durable = session.get(Trial, durable_id)
            for key,value in fields.items():
                setattr(durable,key,value)
            session.commit()
            if legacy_receipt(session) != manifest['legacy']:
                raise HoldoutViolation('legacy trials changed during replay')
            summary = trial_summary(durable)
            immutable_json(root / f'trial-{durable_id}.json', summary)
            return summary


def categories(manifest):
    return sorted({r['category_key'] for r in manifest['rows']})


def train(root=ROOT):
    manifest, digest = load_manifest(root)
    summaries = []
    for category in categories(manifest):
        for side in SIDE_RULES:
            for offset in OFFSETS:
                print(f'TRAIN {category} {side} {offset}', flush=True)
                result = run_variant(manifest, digest, category, side, offset, root=root)
                summaries.append({'category':category, 'side_rule':side, 'offset':offset, **result})
                print(json.dumps({k:result[k] for k in ('id','status','pnl_after_fees','trade_count')},sort_keys=True),flush=True)
    immutable_json(root / 'training.json', summaries)
    return summaries


def select_training(training):
    choices = {}
    for category in sorted({r['category'] for r in training}):
        variants = [r for r in training if r['category'] == category]
        if len(variants) != 6 or {(r['side_rule'],r['offset']) for r in variants} != {(s,o) for s in SIDE_RULES for o in OFFSETS}:
            raise HoldoutViolation('selection requires all six frozen variants')
        if any(r['status'] == 'running' for r in variants):
            raise HoldoutViolation('interrupted training requires a failure audit')
        eligible = [r for r in variants if r['status'] == 'complete' and r['trade_count'] > 0 and D(r['pnl_after_fees']) > 0]
        choices[category] = min(eligible, key=lambda r: (-D(r['pnl_after_fees']), SIDE_RULES.index(r['side_rule']), D(r['offset']))) if eligible else None
    return choices


def freeze_selection(root=ROOT):
    manifest, digest = load_manifest(root)
    training = json.loads((root / 'training.json').read_text())
    choices = select_training(training)
    if set(choices) != set(categories(manifest)):
        raise HoldoutViolation('training category set changed')
    selection = {'manifest_sha256': digest, 'driver_sha256': sha(__file__),
                 'training_sha256': sha(root / 'training.json'), 'choices': choices,
                 'rule': 'positive-net completed training trades; largest net; buy before sell then ascending offset'}
    immutable_json(root / 'selection.json', selection)
    return selection


def evaluate_final(root=ROOT):
    manifest, digest = load_manifest(root)
    selected_path = Path('docs/research/20-longshot-selection.json')
    # Require the exact selection in committed history before opening any final.
    committed = subprocess.check_output(['git','show','HEAD:' + str(selected_path)])
    if committed != selected_path.read_bytes() or committed != (root / 'selection.json').read_bytes():
        raise HoldoutViolation('frozen selection must be committed before final evaluation')
    if subprocess.check_output(['git','show','origin/main:' + str(selected_path)]) != committed:
        raise HoldoutViolation('frozen selection must be pushed before final evaluation')
    selected = json.loads(committed)
    if selected['manifest_sha256'] != digest or selected['driver_sha256'] != sha(__file__):
        raise HoldoutViolation('selected source or driver identity changed')
    summaries = []
    for category, choice in selected['choices'].items():
        if choice is None:
            summaries.append({'category':category,'status':'unconsumed_no_profitable_training_variant'})
            continue
        print(f'FINAL {category}',flush=True)
        result = run_variant(manifest,digest,category,choice['side_rule'],choice['offset'],final=True,
                             expected_version=choice['strategy_version'],root=root)
        summaries.append({'category':category,**result})
        print(json.dumps({k:result[k] for k in ('id','status','pnl_after_fees','trade_count')},sort_keys=True),flush=True)
    immutable_json(root / 'final.json', summaries)
    return summaries


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('prepare','train','select','final'))
    args = parser.parse_args(argv)
    result = {'prepare':prepare,'train':train,'select':freeze_selection,'final':evaluate_final}[args.action]()
    if args.action == 'prepare':
        print(json.dumps(result,indent=2))


if __name__ == '__main__':
    main()
