"""C08 evidence audit; intentionally contains no inventory signal or return replay."""
from __future__ import annotations

import argparse
from datetime import UTC, date, datetime, timedelta
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import urljoin

import requests
from sqlalchemy import select, text

from tradingbot.backtest.holdout import HoldoutSplit, register_split
from tradingbot.data.archive import canonical
from tradingbot.data.disk_budget import CaptureDiskBudget
from tradingbot.data.free_history import USER_AGENT, YAHOO_CHART
from tradingbot.db.models import Strategy, Trial
from tradingbot.db.session import session_scope
from tradingbot.research.c05_commodity_trend import (
    document_text, inspect_source as inspect_yahoo, load_document,
)
from tradingbot.research.equity_data import load_equities

ROOT = Path(__file__).resolve().parents[3]
ARCHIVE = ROOT / 'data/research/c08'
START = datetime(2018, 1, 1, tzinfo=UTC)
END = datetime(2026, 10, 1, tzinfo=UTC)
ACTION_KEYS = ('uso-2020-issuer-release', 'alpaca-corporate-actions', 'alpaca-2021-fractionals')
EIA_ROOT = 'https://www.eia.gov/petroleum/supply/weekly/archive/'
DOCUMENTS = {
    'eia-index': EIA_ROOT,
    'eia-2020-09-10': EIA_ROOT + '2020/2020_09_10/wpsr_2020_09_10.php',
    'eia-2022-06-17-data': EIA_ROOT + '2022/2022_06_17_data/wpsr_2022_06_17_data.php',
    'eia-2023-11-03-data': EIA_ROOT + '2023/2023_11_03_data/wpsr_2023_11_03_data.php',
    'eia-2026-09-30': EIA_ROOT + '2026/2026_09_30/wpsr_2026_09_30.php',
}
POLICY = {
    'universe': ['USO'], 'thresholds': ['0', '-0.05'],
    'signal': 'Commercial crude stocks excluding SPR / comparable year-ago value - 1; positive denominator; strict below threshold',
    'vintage': 'Original dated release current/year-ago fields; audit corrections; no revised bulk substitution',
    'execution': 'Next regular session after actual publication; date-only waits until next calendar day',
    'sizing': 'Cash-to-long 95% decision-time equity, $140 slot; long-to-cash all; unchanged state retains shares',
    'staleness': 'After 14 calendar days without usable publication, target cash next session',
    'prices': 'Yahoo split-adjusted OHLC requires reconciled actual-share conversion; no adjusted-close fills',
    'cash': 'T+1 current-account counterfactual; proven fractional treatment and cash-credit dates required',
    'costs_bp': [5, 10], 'selection': 'Best positive training net at 10 bp; threshold order breaks ties; one final at 10 bp',
    'risk': 'Existing PRD section 6 vetoes, $140 simulated capital; no live orders or keys',
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def load_capture(directory, key, url):
    receipt = json.loads((directory / 'manifest.json').read_text())
    raw = (directory / 'raw').read_bytes()
    if (receipt['key'] != key or receipt['request_url'] != url
            or receipt['sha256'] != sha(raw) or receipt['bytes'] != len(raw)):
        raise ValueError('capture identity or checksum mismatch')
    return receipt, raw


def capture(key, url, *, params=None, archive=ARCHIVE):
    directory = archive / key
    if directory.exists():
        receipt, _ = load_capture(directory, key, url)
        if receipt['params'] != params:
            raise ValueError('capture request parameters changed')
        return receipt
    budget = CaptureDiskBudget(ROOT / 'data')
    budget.check()
    response = requests.get(url, params=params, headers={'User-Agent': USER_AGENT}, timeout=60)
    raw = response.content
    receipt = {'key': key, 'request_url': url, 'params': params, 'response_url': response.url,
               'status_code': response.status_code, 'retrieved_at': datetime.now(UTC).isoformat(),
               'sha256': sha(raw), 'bytes': len(raw), 'content_type': response.headers.get('content-type')}
    with budget.reserve(3 * len(raw) + 65536):
        directory.mkdir(parents=True, exist_ok=False)
        (directory / 'raw').write_bytes(raw)
        (directory / 'manifest.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt


def uso_params():
    return {'period1': int(START.timestamp()), 'period2': int(END.timestamp()),
            'interval': '1d', 'events': 'div,split', 'includeAdjustedClose': 'true'}


def uso_source(archive, sessions):
    receipt, raw = load_capture(archive / 'USO', 'USO', YAHOO_CHART.format(symbol='USO'))
    if receipt['params'] != uso_params() or receipt['status_code'] != 200:
        raise ValueError('USO capture does not match exact C08 interval/request')
    # The shared structural validator receives only this candidate's calendar.
    selected = {d: s for d, s in sessions.items() if START <= s.closes_at < END}
    return receipt, inspect_yahoo(raw, 'USO', selected)


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a' and dict(attrs).get('href'):
            self.hrefs.append(dict(attrs)['href'])


def eia_layout(raw, url):
    """Only publication metadata and link provenance; not a first-vintage certification."""
    body = document_text(raw)
    pattern = r'Data for week ending (\w+ \d{1,2}, \d{4})\s*\|\s*Release Date:\s*(\w+ \d{1,2}, \d{4})'
    matches = re.findall(pattern, body)
    if len(matches) != 1:
        raise ValueError('missing or ambiguous EIA observation/publication dates')
    observation, release = (datetime.strptime(d, '%B %d, %Y').date() for d in matches[0])
    if release <= observation:
        raise ValueError('EIA publication must follow observation')
    links = Links()
    links.feed(raw.decode('utf-8'))
    urls = {urljoin(url, p) for p in links.hrefs if p.endswith('csv/table1.csv')}
    if len(urls) != 1:
        raise ValueError('missing or ambiguous EIA table 1 CSV')
    return {'observation_date': str(observation), 'release_date': str(release),
            'release_weekday': release.strftime('%A'), 'timestamp_precision': 'date_only',
            'earliest_calendar_date_for_execution': str(release + timedelta(days=1)),
            'table1_url': urls.pop(), 'first_release_vintage_verified': False,
            'notice': 'Production re-benchmarking is not an inventory correction' if 'Crude Oil Production Re-benchmarking Notice' in body else None}


def action_evidence(documents):
    anchors = {
        'uso-2020-issuer-release': ('April 29, 2020', 'cash in lieu', 'one-for-eight'),
        'alpaca-corporate-actions': ('reverse splits', 'cash from DTC'),
        'alpaca-2021-fractionals': ('August 2nd, 2021', 'removing cash-in-lieu transactions'),
    }
    for key, terms in anchors.items():
        receipt, raw = documents[key]
        if receipt['status_code'] != 200 or any(t.lower() not in document_text(raw).lower() for t in terms):
            raise ValueError(f'primary action evidence incomplete: {key}')
    return {'effective_date': '2020-04-29', 'split_ratio': '0.125',
            'issuer_fractional_treatment': 'Cash in lieu of fractional post-split shares',
            'current_account_fractional_treatment': None, 'cash_credit_date': None,
            'conclusion': 'USO reverse-split fractional retention versus cash-in-lieu and usable-cash timing are unresolved for the current-account counterfactual'}


def code_hashes():
    paths = ('src/tradingbot/research/c08_source_audit.py',
             'src/tradingbot/research/c05_commodity_trend.py',
             'src/tradingbot/data/free_history.py', 'src/tradingbot/research/equity_data.py',
             'src/tradingbot/data/alpaca_history.py', 'src/tradingbot/backtest/holdout.py')
    return {p: sha((ROOT / p).read_bytes()) for p in paths}


def audit(archive=ARCHIVE):
    calendar = load_equities(ROOT / 'data/equities/c04', 'c04-20261001')
    receipt, coverage = uso_source(archive, calendar.sessions)
    documents = {k: load_document(ROOT / 'data/research/c05/documents' / k, k) for k in ACTION_KEYS}
    gate = action_evidence(documents)
    failures = [gate['conclusion']]
    if not coverage['coverage_ok']:
        failures.append('USO session coverage or OHLC/action field integrity failed')
    if coverage['split_events'] != [{'date': '2020-04-29', 'ratio': '0.125'}]:
        failures.append('USO split inventory differs from reviewed issuer action')
    sources = {k: load_capture(archive / k, k, url) for k, url in DOCUMENTS.items()}
    probes = {}
    for k, (r, raw) in list(sources.items()):
        if k == 'eia-index':
            continue
        try:
            if r['status_code'] != 200:
                raise ValueError(f'HTTP {r["status_code"]}')
            probes[k] = eia_layout(raw, DOCUMENTS[k])
            table_key, table_url = k + '-table1', probes[k]['table1_url']
            table = load_capture(archive / table_key, table_key, table_url)
            sources[table_key] = table
            probes[k]['table1_http_status'] = table[0]['status_code']
        except (ValueError, FileNotFoundError) as exc:
            probes[k] = {'error': str(exc), 'first_release_vintage_verified': False}
    calendar_path = 'docs/research/13-equity-data-repair-calendar.json'
    calendar_raw = (ROOT / calendar_path).read_bytes()
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    if calendar_raw != subprocess.check_output(['git', 'show', head + ':' + calendar_path], cwd=ROOT):
        raise ValueError('shared calendar evidence must be committed')
    identity = {'uso_sha256': receipt['sha256'], 'action_document_sha256': {k: r[0]['sha256'] for k, r in documents.items()},
                'eia_probe_sha256': {k: r[0]['sha256'] for k, r in sources.items()},
                'calendar_archive_sha256': calendar.source_hash, 'calendar_evidence_sha256': sha(calendar_raw),
                'start': START.isoformat(), 'end_exclusive': END.isoformat(), 'policy': POLICY}
    split = HoldoutSplit('sweep-c08-v1:' + sha(canonical(identity).encode()), START, END)
    return {'candidate': 'C08', 'bead': 'tradingbot-m2d', 'status': 'DATA_FAIL',
            'generated_at': datetime.now(UTC).isoformat(), 'identity': identity, 'split': split.metadata(),
            'uso_source': receipt, 'uso_coverage': coverage,
            'action_sources': {k: r[0] for k, r in documents.items()}, 'action_gate': gate,
            'eia_sources': {k: r[0] for k, r in sources.items()}, 'eia_layout_probes': probes,
            'failed_prerequisites': failures, 'code_sha256': code_hashes(),
            'remaining_checks': [
                'Full original-release EIA current/comparable-year-ago inventory fields, units and exclusion of SPR',
                'Archive correction/errata chronology and first-publication vintage proof for every report',
                'USO actual-share conversion, independent same-basis executable price checks and complete action reconciliation',
                'USO prospectus exposure regimes: pre-2020, changed-2020, September-2023–January-2024 transition, later',
                'Frozen executable source and corporate-action cash/quantity policy before any signal or return'],
            'macro_scope': 'Four dated HTML/table-layout probes only; no complete EIA series or scarcity values computed',
            'planned_variants': ['scarcity_below_0', 'scarcity_below_minus_5pct'], 'planned_training_costs_bp': [5, 10],
            'training_cases_attempted': 0, 'final_holdout_attempts': 0, 'strategy_outcomes_inspected': False,
            'prior_inspection': 'USO source overlaps C05 source audit, which stopped before outcomes; published commodity hypothesis and incidental source-page facts are known',
            'pnl': None, 'fees': None, 'trades': None, 'drawdown': None, 'regimes': None, 'luck_p_value': None,
            'promotion': 'none'}


def record_failure(session, result, commit):
    if result['status'] != 'DATA_FAIL' or not result['failed_prerequisites']:
        raise ValueError('a concrete data failure is required')
    version = sha(canonical({'identity': result['identity'], 'code': result['code_sha256']}).encode())
    session.execute(text('SELECT pg_advisory_xact_lock(708031)'))
    strategy = session.scalar(select(Strategy).where(Strategy.key == 'sweep_c08_inventory_scarcity'))
    if strategy is None:
        strategy = Strategy(key='sweep_c08_inventory_scarcity', name='C08 USO inventory scarcity',
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
                  dataset_key=split.dataset_key, holdout_start=split.holdout_start, data_start=START, data_end=END,
                  git_commit=commit, code_version='c08-source-audit-v1', completed_ts=datetime.now(UTC),
                  params={'stage': 'data_quality_only_no_strategy_replay', '_holdout': split.metadata(),
                          'source_audit_version': version, 'policy': POLICY, 'identity': result['identity'],
                          'audit_code_sha256': result['code_sha256']},
                  metrics={'audit_result': 'DATA_FAIL', 'failures': result['failed_prerequisites'],
                           'training_cases_attempted': 0, 'final_holdout_attempts': 0},
                  notes='Data admission failed on unresolved USO fractional split/cash treatment. '
                        'All four training cases and the final remain unattempted. EIA first-vintage audit incomplete; performance null, not zero.')
    session.add(trial)
    session.flush()
    return trial


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', action='store_true')
    parser.add_argument('--record-ledger', action='store_true')
    args = parser.parse_args()
    if args.capture:
        r = capture('USO', YAHOO_CHART.format(symbol='USO'), params=uso_params())
        print(json.dumps({'captured': 'USO', 'status': r['status_code'], 'sha256': r['sha256']}), flush=True)
        for key, url in DOCUMENTS.items():
            r = capture(key, url)
            print(json.dumps({'captured': key, 'status': r['status_code'], 'sha256': r['sha256']}), flush=True)
            if key != 'eia-index' and r['status_code'] == 200:
                layout = eia_layout(load_capture(ARCHIVE / key, key, url)[1], url)
                r = capture(key + '-table1', layout['table1_url'])
                print(json.dumps({'captured': key + '-table1', 'status': r['status_code'], 'sha256': r['sha256']}), flush=True)
    result = audit()
    if args.record_ledger:
        paths = list(result['code_sha256'])
        if subprocess.check_output(['git', 'status', '--porcelain', '--', *paths], cwd=ROOT).strip():
            raise ValueError('commit audit and dependencies before ledger recording')
        head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        with session_scope() as session:
            trial = record_failure(session, result, head)
            result.update({'data_failure_trial_id': trial.id, 'strategy_id': trial.strategy_id, 'audit_git_commit': head})
    encoded = json.dumps(result, indent=2, sort_keys=True) + '\n'
    with CaptureDiskBudget(ROOT / 'data').reserve(2 * len(encoded.encode()) + 65536):
        (ARCHIVE / 'audit.json').write_text(encoded)
    (ROOT / 'docs/research/19-c08-source-audit.json').write_text(encoded)
    print(json.dumps({'status': result['status'], 'sessions': result['uso_coverage']['sessions'],
                      'failure': result['failed_prerequisites'], 'trial': result.get('data_failure_trial_id'),
                      'holdout_attempts': 0}))


if __name__ == '__main__':
    main()
