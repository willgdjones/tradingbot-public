"""C10 TLT source admission receipt; never computes a strategy return."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import UTC, date, datetime
from decimal import Decimal as D
import json
from pathlib import Path
import subprocess
from zoneinfo import ZoneInfo

import pyarrow.parquet as pq
from sqlalchemy import select, text

from tradingbot.backtest.holdout import HoldoutSplit, register_split
from tradingbot.data.archive import canonical, SCHEMA
from tradingbot.data.disk_budget import CaptureDiskBudget
from tradingbot.data.free_history import parse_yahoo
from tradingbot.db.models import Strategy, Trial
from tradingbot.db.session import session_scope
from tradingbot.research.c03_source_audit import inspect_source
from tradingbot.research.c06_sources import ishares_distributions
from tradingbot.research.c10_capture import ROOT, ARCHIVE, RUN, START, END, PUBLIC, EVIDENCE, read, sha
from tradingbot.research.equity_data import load_equities

KEY = 'batch2_c10_tlt_month_end'
VARIANTS = ({'entry_sessions_from_month_end': 3}, {'entry_sessions_from_month_end': 5})
REPORT = 'docs/research/30-c10-source-audit.json'
PINNED = {
    'yahoo-tlt': 'afe749c182e8f7dcd1502e7bb51c62e88b9210e3c813618cd5bfa3d176130526',
    'stooq-tlt': '4089ac0546423d932589c1c7d30362ab8052538de4e9ec77e26c6d47c55d1fbb',
    'tlt-issuer': 'e735bb0e72ecaf45f5d6a5dd522f0d65391823532b47962ba9115fb1fdd1231d',
    'bars_1Day_raw_iex': 'e9f6a615dc460ca48d778798c4d747c081f121f3fec50fe365ab5308b5aaab64',
    'corporate_actions': '0f3c30aa4d871423bfceede1f212e0eeb1b56c6c3a175abee38387931eb39ac2',
}
POLICY = {
    'universe': ['TLT'], 'ordered_variants': list(VARIANTS), 'costs_bp_per_side': [5, 10],
    'entry': 'Third-to-last or fifth-to-last announced regular open; decide at preceding actual close.',
    'exit': 'First announced regular open next month. Preserve originally scheduled dates through unexpected closures; roll execution forward, skip entry reaching fixed exit.',
    'sizing': '140 virtual USD; min(95% decision equity, 140) frozen target, 5% reserve and common fee reserve. Clip at rounded adverse limit to settled cash, frozen target and hard slot; floor fractional quantity; no sub-dollar orders.',
    'cash': 'Issuer ordinary distributions entitled from pre-ex-open ownership; spend only at first regular open after documented payable date. Sale proceeds after documented settlement completion under the published T+1 counterfactual.',
    'actions': 'Amendment 21: causal primary notice, exit last pre-action regular open, stay flat through payable; cancel event, no late restart. Complete share-action inventory required.',
    'selection': 'Only complete positive 10bp training candidates eligible; largest net dollars, variant-order ties. Freeze before sole higher-cost final in canonical c10 family; failed finals consumed.',
    'fees': 'EquityFeeBook 2026-09-17 current-account historical counterfactual; shared risk and ledger unchanged.',
    'exposure': 'Source checks only; issuer fund-performance/NAV search previews seen. C09/C06 and prior calendar research are dependent evidence. No strategy outcomes or final inspection.',
}


def public_sources(archive):
    sources, bodies = {}, {}
    for key, (url, params) in (PUBLIC | EVIDENCE).items():
        folder = archive / key
        meta, raw = read(folder, url, params)
        if key in PINNED and sha(raw) != PINNED[key]:
            raise ValueError('C10 frozen public source changed')
        sources[key] = {**meta, 'path': str(folder.relative_to(ROOT) / 'raw'),
                        'manifest_sha256': sha((folder / 'manifest.json').read_bytes())}
        bodies[key] = raw
    if any(sources[key]['status'] != 200 for key in ('yahoo-tlt', 'tlt-issuer')):
        raise ValueError('required source did not return success')
    return sources, bodies


def api_page(archive, dataset, expected_request):
    """Admit this frozen one-page capture only with exhausted, exact identity."""
    paths = list((archive / 'raw/alpaca' / dataset / RUN).glob('*/manifest.json'))
    if len(paths) != 1:
        raise ValueError('missing or ambiguous C10 API capture')
    path = paths[0]
    manifest = json.loads(path.read_bytes())
    if (sha(canonical(manifest).encode())[:24] != path.parent.name
            or manifest['request'] != expected_request or manifest['venue'] != 'alpaca'
            or manifest['dataset'] != dataset or manifest['format_version'] != 1):
        raise ValueError('C10 API request identity mismatch')
    files = list(path.parent.glob('page-*.parquet'))
    if len(files) != 1 or files[0].name != 'page-00000000.parquet':
        raise ValueError('C10 frozen API capture requires one exhausted page')
    table = pq.read_table(files[0])
    if table.num_rows != 1 or not table.schema.equals(SCHEMA):
        raise ValueError('C10 API page schema mismatch')
    row = table.to_pylist()[0]
    payload = json.loads(row['response_json'], parse_float=D)
    if (row['format_version'] != 1 or row['venue'] != 'alpaca' or row['dataset'] != dataset
            or row['page'] != 0 or row['request_json'] != canonical(expected_request)
            or row['response_sha256'] != sha(row['response_json'].encode())
            or row['response_sha256'] != PINNED[dataset]
            or row['next_request_json'] is not None or payload['next_page_token'] is not None):
        raise ValueError('C10 API checksum, identity or cursor mismatch')
    key = 'bars' if dataset.startswith('bars_') else 'corporate_actions'
    groups = payload[key]
    if (not isinstance(groups, dict) or any(not isinstance(v, list) for v in groups.values())
            or sum(map(len, groups.values())) != row['record_count']):
        raise ValueError('C10 API record count mismatch')
    return {'request': expected_request, 'path': str(files[0].relative_to(ROOT)),
            'response_sha256': row['response_sha256'], 'exhausted': True,
            'records': row['record_count'], 'retrieved_at': row['retrieved_at'].isoformat()}, groups


def distributions_audit(bars, issuer):
    issuer = {day: value for day, value in issuer.items() if START.date() <= day < END.date()}
    vendor = {bar.date: bar.dividend for bar in bars if bar.dividend}
    mismatches = [{'ex_date': str(day), 'vendor': str(vendor[day]), 'issuer': str(issuer[day].amount)}
                  for day in sorted(issuer.keys() & vendor.keys())
                  if abs(vendor[day] - issuer[day].amount) > D('.0005')]
    return {'issuer_count': len(issuer), 'yahoo_count': len(vendor),
            'issuer_only': [dict((k, str(v)) for k, v in asdict(issuer[d]).items())
                            for d in sorted(issuer.keys() - vendor.keys())],
            'vendor_only': [str(d) for d in sorted(vendor.keys() - issuer.keys())],
            'amount_disagreements_beyond_0.0005': mismatches,
            'issuer_distributions': [{k: str(v) for k, v in asdict(v).items()}
                                     for _, v in sorted(issuer.items())],
            'source_amendment_applied': False}, issuer


def reference_audit(groups, bars, sessions):
    if set(groups) != {'TLT'}:
        raise ValueError('unexpected reference symbol')
    yahoo = {b.date: b for b in bars}
    seen, worst, breaches = set(), {'open': D(0), 'close': D(0)}, []
    for other in groups['TLT']:
        stamp = datetime.fromisoformat(other['t'].replace('Z', '+00:00'))
        day = stamp.astimezone(ZoneInfo('America/New_York')).date()
        if stamp.tzinfo is None or day not in yahoo or day in seen:
            raise ValueError('invalid or duplicate reference session')
        seen.add(day)
        for field, name in (('o', 'open'), ('c', 'close')):
            price = D(str(other[field]))
            if not price.is_finite() or price <= 0:
                raise ValueError('invalid reference price')
            distance = abs(getattr(yahoo[day], name) / price - 1)
            worst[name] = max(worst[name], distance)
            if distance > D('.01'):
                breaches.append({'date': str(day), 'field': name, 'relative_distance': str(distance)})
    if not seen:
        raise ValueError('empty reference prices')
    return {'sessions': len(seen), 'first': str(min(seen)), 'last': str(max(seen)),
            'missing_overlap_sessions': [str(d) for d in sorted(sessions)
                                         if min(seen) <= d <= max(seen) and d not in seen],
            'worst_relative_difference': {k: str(v) for k, v in worst.items()},
            'breaches': breaches, 'fixed_threshold': '0.01',
            'pre_overlap_validation_claimed': False, 'execution_BBO': False}


def actions_audit(groups, issuer):
    rows = groups.get('cash_dividends', [])
    dates, ids, mismatches = set(), set(), []
    for row in rows:
        day, amount = date.fromisoformat(row['ex_date']), D(str(row['rate']))
        if (row['symbol'] != 'TLT' or day in dates or row['id'] in ids
                or not START.date() <= day < END.date() or not amount.is_finite() or amount <= 0):
            raise ValueError('invalid or duplicate corporate action')
        dates.add(day)
        ids.add(row['id'])
        if day not in issuer or abs(amount - issuer[day].amount) > D('.0005'):
            mismatches.append({'ex_date': str(day), 'vendor_amount': str(amount)})
    if not dates:
        raise ValueError('empty action inventory')
    return {'groups': {k: len(v) for k, v in groups.items()},
            'first_cash_ex_date': str(min(dates)), 'last_cash_ex_date': str(max(dates)),
            'issuer_amount_or_date_disagreements': mismatches,
            'issuer_dates_missing_within_observed_bounds': [str(d) for d in sorted(issuer)
                                                          if min(dates) <= d <= max(dates) and d not in dates],
            'full_interval_share_action_completeness_proven': False,
            'scope': 'Exhausted all-type query is not evidence of full historical vendor coverage; no primary exhaustive share-action inventory established.'}


def calendar_evidence(root):
    path = root / 'docs/research/13-equity-data-repair-calendar.json'
    raw = path.read_bytes()
    if sha(raw) != '11b791a4edf1af2ba3d1d78d37c9d1de4cdaa00116c755ce198674c1bdd693c7':
        raise ValueError('published settlement calendar proof changed')
    proof = json.loads(raw)
    sources = [s for year in proof['years'] if year['year'] <= 2023 for s in year['sources']]
    sources += [v['source'] for v in proof['exceptional_open_days']]
    unique = {s['name']: s for s in sources}
    for s in unique.values():
        if sha((root / s['path']).read_bytes()) != s['sha256']:
            raise ValueError('primary calendar source bytes changed')
    return {'settlement_proof_sha256': sha(raw), 'primary_sources': list(unique.values()),
            'planned_exchange_calendar_admitted': False,
            'scope': 'Annual FINRA PDFs have separate exchange-closure sections. Settlement-eligible dates cannot be used as an announced exchange session calendar. Full as-of extraction/availability audit remains incomplete.',
            'sandy_2012': {'fifth_last_planned_entry': '2012-10-25', 'third_last_planned_entry': '2012-10-29',
                           'third_last_delayed_entry': '2012-10-31', 'fixed_exit': '2012-11-01',
                           'rejected_hindsight_entries': ['2012-10-23', '2012-10-25']},
            'ford_2007': {'planned_exit': '2007-01-02', 'closure_notice_date': '2006-12-29',
                          'delayed_exit': '2007-01-03', 'settlement_open_on_closed_exchange_day': True}}


def audit(root=ROOT, archive=ARCHIVE):
    sources, bodies = public_sources(archive)
    original = load_equities(root / 'data/equities/c04', 'c04-20261001')
    coverage = inspect_source(bodies['yahoo-tlt'], 'TLT', original.sessions)
    _, bars = parse_yahoo(bodies['yahoo-tlt'].decode())
    distributions, issuer = distributions_audit(bars, ishares_distributions(bodies['tlt-issuer'].decode()))
    reference_source, reference = api_page(archive, 'bars_1Day_raw_iex', {
        'url': 'https://data.alpaca.markets/v2/stocks/bars', 'params': {'symbols': 'TLT',
        'timeframe': '1Day', 'start': '2016-01-01T00:00:00Z', 'end': '2026-10-01T00:00:00Z',
        'adjustment': 'raw', 'feed': 'iex', 'limit': 10000, 'sort': 'asc', 'asof': '-'}})
    action_source, actions = api_page(archive, 'corporate_actions', {
        'url': 'https://data.alpaca.markets/v1/corporate-actions', 'params': {'symbols': 'TLT',
        'start': '2006-01-01', 'end': '2026-09-30', 'data_quality': 'all', 'limit': 1000, 'sort': 'asc'}})
    overlap = reference_audit(reference, bars, original.sessions)
    action_check = actions_audit(actions, issuer)
    calendar = calendar_evidence(root)
    failures = ['Complete primary share-action inventory for 2006-2026 is unproven; no-action vendor omissions cannot establish actual-share basis or Amendment 21 completeness.',
                'Issuer/Yahoo distribution mismatch has no reviewed source amendment; preserve the issuer-recorded 2012-11-01 cash event, do not silently delete or shift it.',
                'Causal announced exchange-calendar extraction and publication-time availability have not been fully admitted; realized and settlement calendars are insufficient substitutes.']
    if not coverage['coverage_ok'] or coverage['split_events']:
        failures.append('Yahoo coverage or split events need additional admission.')
    if overlap['breaches'] or overlap['missing_overlap_sessions']:
        failures.append('Independent raw price overlap requires reconciliation.')
    if action_check['issuer_amount_or_date_disagreements']:
        failures.append('Alpaca cash actions disagree with issuer dates/amounts.')
    code_paths = ('src/tradingbot/research/c10_source_audit.py', 'src/tradingbot/research/c10_capture.py',
                  'src/tradingbot/research/c03_source_audit.py', 'src/tradingbot/research/c06_sources.py',
                  'src/tradingbot/research/equity_data.py', 'src/tradingbot/data/free_history.py')
    code = {p: sha((root / p).read_bytes()) for p in code_paths}
    proofs = {p: sha((root / p).read_bytes()) for p in ('docs/research/25-candidate-shortlist.md',
              'docs/research/30-c10-source-plan.md', 'docs/research/21-corporate-action-blackout.md')}
    identity = {'source_sha256': {k: v['sha256'] for k, v in sources.items()},
                'api_sha256': [reference_source['response_sha256'], action_source['response_sha256']],
                'source_manifest_sha256': {k: v['manifest_sha256'] for k, v in sources.items()},
                'calendar_source_hash': original.source_hash, 'calendar_evidence': calendar,
                'proofs_sha256': proofs, 'policy': POLICY, 'data_start': START.isoformat(), 'data_end': END.isoformat()}
    split = HoldoutSplit('batch2-c10-v1:' + sha(canonical(identity).encode()), START, END)
    return {'candidate': 'C10', 'bead': 'tradingbot-eu4', 'status': 'DATA_FAIL',
            'dataset_admitted': False, 'identity': identity, 'split': split.metadata(),
            'sources': sources, 'coverage': coverage, 'distributions': distributions,
            'independent_reference': {'source': reference_source, **overlap},
            'vendor_actions': {'source': action_source, **action_check}, 'calendar_evidence': calendar,
            'stooq_status': 'HTTP 200 browser-verification HTML; no CSV admitted; no challenge bypass.',
            'failed_prerequisites': failures,
            'not_completed_after_failed_gate': ['Full source amendment and actual-share admission',
                'Pure strategy reactor and shared risk/ledger replay', 'Training, winner selection, final holdout and dependence-aware inference'],
            'planned_variants': list(VARIANTS), 'planned_training_costs_bp': [5, 10],
            'planned_configurations': [{**v, 'costs_bp_per_side': cost, 'state': 'unattempted_source_gate_failed'}
                                       for v in VARIANTS for cost in (5, 10)],
            'strategy_outcomes_inspected': False, 'training_cases_attempted': 0, 'final_holdout_attempts': 0,
            'pnl': None, 'fees': None, 'drawdown': None, 'regimes': None, 'trade_count': None,
            'luck_p_value': None, 'promotion': 'none', 'code_sha256': code}


def record_failure(session, result, commit):
    if (result['status'] != 'DATA_FAIL' or not result['failed_prerequisites']
            or result['dataset_admitted'] or result['strategy_outcomes_inspected']
            or result['training_cases_attempted'] != 0 or result['final_holdout_attempts'] != 0
            or any(result[k] is not None for k in ('pnl', 'fees', 'drawdown', 'regimes', 'trade_count', 'luck_p_value'))):
        raise ValueError('only failed source admission without performance can be recorded')
    split = HoldoutSplit(result['split']['dataset_key'], START, END)
    if split.metadata() != result['split']:
        raise ValueError('fixed C10 bounds changed')
    version = sha(canonical({'identity': result['identity'], 'code': result['code_sha256']}).encode())
    session.execute(text('SELECT pg_advisory_xact_lock(703101)'))
    strategy = session.scalar(select(Strategy).where(Strategy.key == KEY))
    if strategy is None:
        strategy = Strategy(key=KEY, name='C10 TLT month-end institutional demand', status='idea',
                            config={'research_only': True, 'source_audit_only': True, 'policy': POLICY})
        session.add(strategy)
        session.flush()
    old = session.scalar(select(Trial).where(Trial.strategy_id == strategy.id,
                          Trial.params['source_audit_version'].astext == version))
    if old is not None:
        return old
    register_split(session, split)
    trial = Trial(strategy_id=strategy.id, mode='backtest', status='failed', final_holdout=False,
                  dataset_key=split.dataset_key, holdout_start=split.holdout_start,
                  data_start=START, data_end=END, git_commit=commit, code_version='c10-source-audit-v1',
                  completed_ts=datetime.now(UTC),
                  params={'stage': 'data_quality_only_no_strategy_replay', '_holdout': split.metadata(),
                          'source_audit_version': version, 'policy': POLICY, 'identity': result['identity'],
                          'planned_configurations': result['planned_configurations']},
                  metrics={'audit_result': 'DATA_FAIL', 'failures': result['failed_prerequisites'],
                           'training_cases_attempted': 0, 'final_holdout_attempts': 0},
                  notes='Source admission failed. Both variants and four training cases remain unattempted. '
                        'Return metrics null; no holdout consumption, allocation or promotion. '
                        'Decision and account-risk review: docs/research/30-c10-source-audit.md.')
    session.add(trial)
    session.flush()
    return trial


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record-ledger', action='store_true')
    args = parser.parse_args()
    result = audit()
    path = ROOT / REPORT
    ledger_fields = ('data_failure_trial_id', 'strategy_id', 'audit_git_commit')
    if path.exists():
        saved = json.loads(path.read_bytes())
        if {k: v for k, v in saved.items() if k not in ledger_fields} == result:
            result.update({k: saved[k] for k in ledger_fields if k in saved})
    if args.record_ledger:
        tracked = list(result['code_sha256']) + list(result['identity']['proofs_sha256'])
        if subprocess.check_output(['git', 'status', '--porcelain', '--', *tracked], cwd=ROOT).strip():
            raise ValueError('commit source audit code and evidence before ledger recording')
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        with session_scope() as session:
            trial = record_failure(session, result, commit)
            result.update(data_failure_trial_id=trial.id, strategy_id=trial.strategy_id, audit_git_commit=trial.git_commit)
    encoded = json.dumps(result, indent=2, sort_keys=True) + '\n'
    with CaptureDiskBudget(ROOT / 'data').reserve(3 * len(encoded.encode()) + 65536):
        (ARCHIVE / 'audit.json').write_text(encoded)
    path.write_text(encoded)
    print(json.dumps({'status': result['status'], 'trial': result.get('data_failure_trial_id'),
                      'sessions': result['coverage']['sessions'], 'training_cases_attempted': 0,
                      'final_holdout_attempts': 0}))


if __name__ == '__main__':
    main()
