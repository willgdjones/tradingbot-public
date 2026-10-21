"""C03 source-only admission audit. No ranking, return replay or holdout admission.

The fixed five-ETF source bundle is useful even when a shared cash/action
prerequisite fails. A data failure is logged once with unmeasured performance.
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import subprocess

import requests
from sqlalchemy import select, text

from tradingbot.backtest.holdout import HoldoutSplit, register_split
from tradingbot.data.archive import canonical
from tradingbot.data.c04_sources import issuer_distributions
from tradingbot.data.disk_budget import CaptureDiskBudget
from tradingbot.data.free_history import parse_yahoo, USER_AGENT, YAHOO_CHART
from tradingbot.db.models import Strategy, Trial
from tradingbot.db.session import session_scope
from tradingbot.research.equity_data import load_equities

START = datetime(2006, 1, 1, tzinfo=UTC)
END = datetime(2026, 10, 1, tzinfo=UTC)
UNIVERSE = ('SPY', 'IEF', 'GLD', 'EFA', 'VNQ')
VARIANTS = ('top_one_95pct', 'top_two_equal_47.5pct', 'top_two_each_filtered_10_month_sma')
ROOT = Path(__file__).resolve().parents[3]
ARCHIVE = ROOT / 'data/research/c03'
POLICY = {
    'universe': list(UNIVERSE), 'variants': list(VARIANTS),
    'score': 'mean of 1/3/6/9/12-month total returns, alphabetical ties',
    'decisions': 'month-end after actual session close; next eligible session open',
    'cash': '140 USD initial; 95% aggregate ceiling; settled cash and actual payment dates required',
    'price_basis': 'Yahoo quote OHLC split-adjusted, not dividend-adjusted; actual-share execution basis not yet admitted',
    'dividends': 'No ex-date cash or payment-date proxy; reconcile issuer cash dates before replay',
    'costs_bp': [5, 10], 'training_selection': 'highest net P&L at 10 bp; preregistered variant order breaks ties',
    'prior_inspection': 'SPY overlaps inspected #5/#6/C01; published issuer pages contain fund performance. No candidate outcomes or rankings calculated.',
}


def sha(body):
    return hashlib.sha256(body).hexdigest()


def load_source(directory, symbol):
    receipt = json.loads((directory / 'manifest.json').read_text())
    raw = (directory / 'raw.json').read_bytes()
    if receipt['sha256'] != sha(raw) or receipt['symbol'] != symbol:
        raise ValueError('source checksum or symbol identity mismatch')
    if receipt['start'] != START.isoformat() or receipt['end_exclusive'] != END.isoformat():
        raise ValueError('source bounds differ from preregistration')
    return receipt, raw


def capture(symbol, archive=ARCHIVE):
    if symbol not in UNIVERSE:
        raise ValueError('symbol outside fixed C03 universe')
    directory = archive / symbol
    if directory.exists():
        return load_source(directory, symbol)[0]
    budget = CaptureDiskBudget(ROOT / 'data')
    budget.check()
    params = {'period1': int(START.timestamp()), 'period2': int(END.timestamp()),
              'interval': '1d', 'events': 'div,split', 'includeAdjustedClose': 'true'}
    response = requests.get(YAHOO_CHART.format(symbol=symbol), params=params,
                            headers={'User-Agent': USER_AGENT}, timeout=60)
    raw = response.content
    receipt = {'symbol': symbol, 'url': response.url, 'status_code': response.status_code,
               'retrieved_at': datetime.now(UTC).isoformat(), 'sha256': sha(raw),
               'bytes': len(raw), 'start': START.isoformat(), 'end_exclusive': END.isoformat(),
               'adjustments': POLICY['price_basis'], 'cash_dates': 'not established by vendor ex-date events'}
    with budget.reserve(3 * len(raw) + 65536):
        directory.mkdir(parents=True, exist_ok=False)
        (directory / 'raw.json').write_bytes(raw)
        (directory / 'manifest.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt


def inspect_source(raw, symbol, sessions):
    """Coverage, field integrity and actions only; never calculates returns."""
    doc = json.loads(raw)
    result = doc['chart']['result'][0]
    if result['meta'].get('symbol') != symbol:
        raise ValueError('response symbol differs from requested symbol')
    stamps = result.get('timestamp', [])
    if not stamps or stamps != sorted(set(stamps)):
        raise ValueError('empty, duplicated or unordered source timestamps')
    quote = result['indicators']['quote'][0]
    adj = result['indicators']['adjclose'][0]['adjclose']
    if any(len(quote.get(k, [])) != len(stamps) for k in ('open', 'high', 'low', 'close', 'volume')) or len(adj) != len(stamps):
        raise ValueError('source field lengths differ')
    meta, bars = parse_yahoo(raw.decode('utf-8'))
    expected = {d for d, session in sessions.items() if START <= session.closes_at < END}
    actual = {bar.date for bar in bars}
    invalid = []
    for bar in bars:
        prices = (bar.open, bar.high, bar.low, bar.close, bar.adj_close)
        if (any(not p.is_finite() or p <= 0 for p in prices) or
                not bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high or
                bar.volume < 0 or not bar.dividend.is_finite() or bar.dividend < 0 or
                not bar.split_ratio.is_finite() or bar.split_ratio <= 0):
            invalid.append(str(bar.date))
    missing, extra = sorted(expected - actual), sorted(actual - expected)
    action_groups = result.get('events', {})
    unsupported = sorted(k for k, v in action_groups.items() if v and k not in ('dividends', 'splits'))
    from tradingbot.data.alpaca_history import NY
    orphan_events = sorted({str(datetime.fromtimestamp(event['date'], NY).date())
                            for kind in ('dividends', 'splits')
                            for event in action_groups.get(kind, {}).values()
                            if datetime.fromtimestamp(event['date'], NY).date() not in actual})
    coverage_ok = not (missing or extra or invalid or meta['null_rows'] or len(actual) != len(bars)
                       or unsupported or orphan_events)
    return {
        'coverage_ok': coverage_ok, 'sessions': len(bars), 'expected_sessions': len(expected),
        'null_rows': meta['null_rows'], 'missing_sessions': list(map(str, missing)),
        'extra_sessions': list(map(str, extra)), 'invalid_sessions': invalid,
        'duplicate_dates': len(bars) - len(actual), 'unsupported_event_groups': unsupported,
        'orphan_event_dates': orphan_events,
        'first_session': str(bars[0].date) if bars else None,
        'last_session': str(bars[-1].date) if bars else None,
        'dividend_events': [{'ex_date': str(b.date), 'amount': str(b.dividend)} for b in bars if b.dividend],
        'split_events': [{'date': str(b.date), 'ratio': str(b.split_ratio)} for b in bars if b.split_ratio != 1],
        'vendor_dividend_field_names': sorted({k for event in action_groups.get('dividends', {}).values() for k in event}),
    }


def audit(archive=ARCHIVE):
    data = load_equities(ROOT / 'data/equities/c04', 'c04-20261001')
    sources, coverage, failures = {}, {}, []
    for symbol in UNIVERSE:
        receipt, raw = load_source(archive / symbol, symbol)
        sources[symbol] = receipt
        try:
            if receipt['status_code'] != 200:
                raise ValueError(f'HTTP {receipt["status_code"]}')
            coverage[symbol] = inspect_source(raw, symbol, data.sessions)
            if not coverage[symbol]['coverage_ok']:
                failures.append(f'{symbol}: source coverage or field-integrity failure')
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            coverage[symbol] = {'coverage_ok': False, 'error': str(exc)}
            failures.append(f'{symbol}: source parsing/identity failure')

    # Recheck the immutable primary workbook, not just another candidate's verdict.
    issuer = ROOT / 'data/equities/c04/sources/ssga-historical-distributions.xlsx'
    issuer_receipt = json.loads(issuer.with_suffix('.json').read_text())
    if sha(issuer.read_bytes()) != issuer_receipt['sha256']:
        raise ValueError('issuer source checksum mismatch')
    try:
        issuer_distributions(issuer, 'SPY')
    except ValueError as exc:
        failures.append(str(exc))

    evidence = {}
    source_commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    for name in ('13-equity-data-repair.json', '13-equity-data-repair-calendar.json'):
        path = ROOT / 'docs/research' / name
        raw = path.read_bytes()
        committed = subprocess.check_output(['git', 'show', source_commit + ':docs/research/' + name], cwd=ROOT)
        if raw != committed:
            raise ValueError('shared source evidence has uncommitted changes; wait for its source slice')
        original = json.loads(raw)
        evidence[name] = {'sha256': sha(raw), 'path': 'docs/research/' + name,
                          'git_commit': source_commit,
                          'receipt': {k: original[k] for k in ('status', 'remaining_gates',
                                      'proposed_spy_payment_amendment', 'cash_policy_proposal',
                                      'source_amendment_applied_to_replay') if k in original}}
    repair = evidence['13-equity-data-repair.json']['receipt']
    if repair['status'] != 'PARTIAL_SOURCE_REPAIR_NOT_ADMITTED':
        raise ValueError('shared source-repair state changed; review admission before rerunning this audit')
    failures.append('Amended SPY dividend/price basis and cash-release convention remain unadmitted under shared repair 900')
    identity = {'yahoo_sha256': {s: sources[s]['sha256'] for s in UNIVERSE},
                'issuer_sha256': issuer_receipt['sha256'], 'calendar_archive_sha256': data.source_hash,
                'shared_evidence_sha256': {k: v['sha256'] for k, v in evidence.items()},
                'policy': POLICY, 'start': START.isoformat(), 'end_exclusive': END.isoformat()}
    split = HoldoutSplit('sweep-c03-v1:' + sha(canonical(identity).encode()), START, END)
    return {'candidate': 'C03', 'bead': 'tradingbot-wn9', 'status': 'DATA_FAIL',
            'generated_at': datetime.now(UTC).isoformat(), 'identity': identity, 'split': split.metadata(),
            'sources': sources, 'coverage': coverage, 'failed_prerequisites': failures,
            'shared_evidence': evidence, 'issuer_source': issuer_receipt,
            'not_completed_after_failed_gate': ['IEF/EFA/VNQ full issuer payment-date reconciliation',
                'GLD complete action inventory validation', 'five-ETF independent same-basis price cross-check',
                'all actual-share conversions and frozen cash-release/source amendment'],
            'strategy_outcomes_inspected': False, 'training_cases_attempted': 0, 'final_holdout_attempts': 0,
            'planned_variants': list(VARIANTS), 'planned_training_costs_bp': [5, 10],
            'pnl': None, 'fees': None, 'drawdown': None, 'regimes': None, 'luck_p_value': None,
            'promotion': 'none', 'audit_code_sha256': sha(Path(__file__).read_bytes())}


def record_failure(session, result, commit):
    if result['status'] != 'DATA_FAIL' or not result['failed_prerequisites']:
        raise ValueError('a concrete data failure is required')
    version = sha(canonical({'identity': result['identity'], 'audit_code': result['audit_code_sha256']}).encode())
    session.execute(text('SELECT pg_advisory_xact_lock(703031)'))
    strategy = session.scalar(select(Strategy).where(Strategy.key == 'sweep_c03_cross_asset_momentum'))
    if strategy is None:
        strategy = Strategy(key='sweep_c03_cross_asset_momentum', name='C03 cross-asset relative momentum',
                            status='idea', config={'research_only': True, 'source_audit_only': True})
        session.add(strategy)
        session.flush()
    old = session.scalar(select(Trial).where(Trial.strategy_id == strategy.id,
                          Trial.params['source_audit_version'].astext == version))
    if old:
        return old
    split = HoldoutSplit(result['split']['dataset_key'], START, END)
    register_split(session, split)
    trial = Trial(strategy_id=strategy.id, mode='backtest', status='failed', final_holdout=False,
                  dataset_key=split.dataset_key, holdout_start=split.holdout_start,
                  data_start=START, data_end=END, git_commit=commit, code_version='c03-source-audit-v1',
                  completed_ts=datetime.now(UTC),
                  params={'stage': 'data_quality_only_no_strategy_replay', '_holdout': split.metadata(),
                          'source_audit_version': version, 'policy': POLICY, 'identity': result['identity']},
                  metrics={'audit_result': 'DATA_FAIL', 'failures': result['failed_prerequisites'],
                           'training_cases_attempted': 0, 'final_holdout_attempts': 0},
                  notes='Source audit failed before any ranking or replay; planned variants remain unattempted. '
                        'No P&L, fees, trades, drawdown, regime results or luck p-value measured. Shared repair 900 remains separate.')
    session.add(trial)
    session.flush()
    return trial


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', action='store_true')
    parser.add_argument('--record-ledger', action='store_true')
    args = parser.parse_args()
    if args.capture:
        for symbol in UNIVERSE:
            receipt = capture(symbol)
            print(json.dumps({'captured': symbol, 'http': receipt['status_code'], 'sha256': receipt['sha256']}), flush=True)
    result = audit()
    if args.record_ledger:
        relative = str(Path(__file__).relative_to(ROOT))
        if subprocess.check_output(['git', 'status', '--porcelain', '--', relative], cwd=ROOT).strip():
            raise ValueError('commit the audit source before recording its ledger receipt')
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        with session_scope() as session:
            trial = record_failure(session, result, commit)
            result.update({'data_failure_trial_id': trial.id, 'strategy_id': trial.strategy_id,
                           'audit_git_commit': commit})
    encoded = json.dumps(result, indent=2, sort_keys=True) + '\n'
    with CaptureDiskBudget(ROOT / 'data').reserve(len(encoded.encode()) * 2 + 65536):
        (ARCHIVE / 'audit.json').write_text(encoded)
    (ROOT / 'docs/research/14-c03-source-audit.json').write_text(encoded)
    print(json.dumps({'status': result['status'], 'coverage': {s:r.get('sessions') for s,r in result['coverage'].items()},
                      'trial': result.get('data_failure_trial_id'), 'holdout_attempts': 0}))


if __name__ == '__main__':
    main()
