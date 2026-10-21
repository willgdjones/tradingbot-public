"""Fixed C05 commodity ETF sources. Source inspection never computes returns."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
from decimal import Decimal
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import subprocess

import requests
from sqlalchemy import select, text

from tradingbot.backtest.holdout import HoldoutSplit, register_split
from tradingbot.data.archive import canonical
from tradingbot.data.alpaca_history import NY
from tradingbot.data.disk_budget import CaptureDiskBudget
from tradingbot.data.free_history import parse_yahoo, USER_AGENT, YAHOO_CHART
from tradingbot.db.models import Strategy, Trial
from tradingbot.db.session import session_scope
from tradingbot.research.equity_data import load_equities

ROOT = Path(__file__).resolve().parents[3]
ARCHIVE = ROOT / 'data/research/c05'
START = datetime(2008, 1, 1, tzinfo=UTC)
END = datetime(2026, 10, 1, tzinfo=UTC)
UNIVERSE = ('GLD', 'SLV', 'USO', 'UNG', 'DBA')
VARIANTS = ('total_return_252_positive', 'total_return_126_positive', 'above_sma_200')
POLICY = {
    'universe': list(UNIVERSE), 'variants': list(VARIANTS),
    'sizing': 'Five 19% sleeves, inactive sleeves cash; 95% aggregate maximum; $140 initial cash',
    'signal': 'Month-end completed total-return observations; equality is cash; warm-up inside partition',
    'execution': 'Next eligible regular-session open; frozen targets; settled cash; actual-share price basis',
    'price_basis': 'Yahoo OHLC split-adjusted, not dividend-adjusted; requires validated actual-share conversion',
    'actions': 'Issuer-reconciled splits, fractional cash-in-lieu and actual distribution pay dates required',
    'costs_bp': [5, 10], 'selection': 'Best net training P&L at 10 bp; fixed variant order for ties; one final at 10 bp',
    'settlement': 'T+1 current-account counterfactual; no ex-date dividend cash or invented cash-in-lieu',
}
DOCUMENTS = {
    'slv-2008-split': 'https://www.sec.gov/Archives/edgar/data/1330568/000119312508149627/dex991.htm',
    'uso-2020-split': 'https://www.sec.gov/Archives/edgar/data/1327068/000117120020000271/i20263_ex99-1.htm',
    'ung-2011-split': 'https://www.sec.gov/Archives/edgar/data/1376227/000114420411009344/v211742_ex99-1.htm',
    'ung-2012-split': 'https://www.prnewswire.com/news-releases/notice-of-reverse-unit-split-138526579.html',
    'ung-2018-split': 'https://www.sec.gov/Archives/edgar/data/1376227/000117120017000526/i17565_ex99-1.htm',
    'ung-2024-split': 'https://www.sec.gov/Archives/edgar/data/1376227/000117120024000010/i24014_ung-8k.htm',
    'alpaca-corporate-actions': 'https://docs.alpaca.markets/us/docs/daily-processes-and-reconcilations.md',
    'alpaca-2021-fractionals': 'https://alpaca.markets/blog/updated-terms-for-payments-in-fractional-shares/',
    'dba-product': 'https://www.invesco.com/us/en/financial-products/etfs/invesco-db-agriculture-fund.html',
    'dba-2008-annual': 'https://www.sec.gov/Archives/edgar/data/1383082/000119312509035862/d10k.htm',
    'uso-2020-issuer-release': 'https://www.prnewswire.com/news-releases/uscf-announces-one-for-eight-reverse-share-split-for-the-united-states-oil-fund-nyse-arca-uso-301045001.html',
    'ung-2011-issuer-release': 'https://www.prnewswire.com/news-releases/notice-of-reverse-unit-split-116350854.html',
    'ung-2018-issuer-release': 'https://www.prnewswire.com/news-releases/notice-of-reverse-share-split-300574185.html',
    'ung-2024-issuer-release': 'https://www.prnewswire.com/news-releases/notice-of-reverse-share-split-302026652.html',
    'dba-2024-qualified-notice': 'https://www.invesco.com/us-rest/contentdetail?contentId=083ba7fa-a1de-4f70-9b8e-e77ff1228dac&dnsName=us',
    'uscf-disclosures': 'https://www.uscfinvestments.com/disclosures',
    'uso-occ-cash-settlement': 'https://infomemo.theocc.com/infomemos?number=46961',
    'uso-occ-split': 'https://infomemo.theocc.com/infomemos?number=46881',
}


def capture_document(key, archive=ARCHIVE):
    url = DOCUMENTS[key]
    directory = archive / 'documents' / key
    if directory.exists():
        return load_document(directory, key)[0]
    budget = CaptureDiskBudget(ROOT / 'data')
    budget.check()
    response = requests.get(url, headers={'User-Agent': USER_AGENT}, timeout=60)
    raw = response.content
    receipt = {'key': key, 'request_url': url, 'response_url': response.url,
               'status_code': response.status_code, 'retrieved_at': datetime.now(UTC).isoformat(),
               'sha256': sha(raw), 'bytes': len(raw), 'content_type': response.headers.get('content-type')}
    with budget.reserve(3 * len(raw) + 65536):
        directory.mkdir(parents=True, exist_ok=False)
        (directory / 'raw').write_bytes(raw)
        (directory / 'manifest.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt


def load_document(directory, key):
    receipt = json.loads((directory / 'manifest.json').read_text())
    raw = (directory / 'raw').read_bytes()
    if receipt['key'] != key or receipt['request_url'] != DOCUMENTS[key] or receipt['sha256'] != sha(raw):
        raise ValueError('document checksum or identity mismatch')
    return receipt, raw


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


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
        raise ValueError('symbol outside fixed C05 universe')
    directory = archive / symbol
    if directory.exists():
        return load_source(directory, symbol)[0]
    budget = CaptureDiskBudget(ROOT / 'data')
    budget.check()
    response = requests.get(YAHOO_CHART.format(symbol=symbol), params={
        'period1': int(START.timestamp()), 'period2': int(END.timestamp()),
        'interval': '1d', 'events': 'div,split', 'includeAdjustedClose': 'true',
    }, headers={'User-Agent': USER_AGENT}, timeout=60)
    raw = response.content
    receipt = {'symbol': symbol, 'url': response.url, 'status_code': response.status_code,
               'retrieved_at': datetime.now(UTC).isoformat(), 'sha256': sha(raw),
               'bytes': len(raw), 'start': START.isoformat(), 'end_exclusive': END.isoformat(),
               'price_basis': POLICY['price_basis']}
    with budget.reserve(3 * len(raw) + 65536):
        directory.mkdir(parents=True, exist_ok=False)
        (directory / 'raw.json').write_bytes(raw)
        (directory / 'manifest.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt


def inspect_source(raw, symbol, sessions):
    doc = json.loads(raw)
    result = doc['chart']['result'][0]
    if result['meta'].get('symbol') != symbol:
        raise ValueError('response symbol differs from requested symbol')
    stamps = result.get('timestamp', [])
    if not stamps or stamps != sorted(set(stamps)):
        raise ValueError('empty, duplicated or unordered source timestamps')
    quote = result['indicators']['quote'][0]
    adj = result['indicators']['adjclose'][0]['adjclose']
    fields = ('open', 'high', 'low', 'close', 'volume')
    if any(len(quote.get(k, [])) != len(stamps) for k in fields) or len(adj) != len(stamps):
        raise ValueError('source field lengths differ')
    events = result.get('events', {})
    # The generic reader defaults a zero split denominator to one; reject it here.
    split_dates = set()
    for event in events.get('splits', {}).values():
        num, den = Decimal(str(event['numerator'])), Decimal(str(event['denominator']))
        day = datetime.fromtimestamp(event['date'], NY).date()
        if not num.is_finite() or not den.is_finite() or min(num, den) <= 0 or day in split_dates:
            raise ValueError('invalid or duplicated split event')
        text_num, text_den = map(Decimal, event['splitRatio'].split(':'))
        if (not text_num.is_finite() or not text_den.is_finite() or min(text_num, text_den) <= 0 or
                text_num / text_den != num / den):
            raise ValueError('inconsistent vendor split ratio')
        split_dates.add(day)
    meta, bars = parse_yahoo(raw.decode('utf-8'))
    expected = {d for d, session in sessions.items() if START <= session.closes_at < END}
    actual = {bar.date for bar in bars}
    invalid = []
    for bar in bars:
        prices = (bar.open, bar.high, bar.low, bar.close, bar.adj_close)
        if (any(not p.is_finite() or p <= 0 for p in prices) or
                not bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high or
                bar.volume < 0 or not bar.dividend.is_finite() or bar.dividend < 0):
            invalid.append(str(bar.date))
    null_volume = [str(datetime.fromtimestamp(ts, NY).date()) for ts, v in zip(stamps, quote['volume']) if v is None]
    missing, extra = sorted(expected - actual), sorted(actual - expected)
    unsupported = sorted(k for k, v in events.items() if v and k not in ('dividends', 'splits'))
    orphan = sorted({str(datetime.fromtimestamp(ev['date'], NY).date())
                     for kind in ('dividends', 'splits') for ev in events.get(kind, {}).values()
                     if datetime.fromtimestamp(ev['date'], NY).date() not in actual})
    return {'coverage_ok': not (missing or extra or invalid or meta['null_rows'] or null_volume or
                               len(actual) != len(bars) or unsupported or orphan),
            'sessions': len(bars), 'expected_sessions': len(expected), 'null_rows': meta['null_rows'],
            'missing_sessions': list(map(str, missing)), 'extra_sessions': list(map(str, extra)),
            'invalid_sessions': invalid, 'null_volume': null_volume, 'duplicate_dates': len(bars) - len(actual),
            'unsupported_event_groups': unsupported, 'orphan_event_dates': orphan,
            'first_session': str(bars[0].date) if bars else None, 'last_session': str(bars[-1].date) if bars else None,
            'dividend_events': [{'ex_date': str(b.date), 'amount': str(b.dividend)} for b in bars if b.dividend],
            'split_events': [{'date': str(b.date), 'ratio': str(b.split_ratio)} for b in bars if b.split_ratio != 1],
            'vendor_dividend_field_names': sorted({k for ev in events.get('dividends', {}).values() for k in ev})}


def document_text(raw):
    class Reader(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts = []

        def handle_data(self, value):
            self.parts.append(value)

    reader = Reader()
    reader.feed(raw.decode('utf-8'))
    return ' '.join(' '.join(reader.parts).split())


def verify_fractional_evidence(documents):
    """Verify the frozen source-review anchors, not an executable action policy."""
    anchors = {
        'uso-2020-issuer-release': ('April 29, 2020', 'cash in lieu'),
        'ung-2011-issuer-release': ('March 9, 2011', 'cash in lieu'),
        'ung-2012-split': ('February 22, 2012', 'cash in lieu'),
        'ung-2018-issuer-release': ('January 5, 2018', 'cash in lieu'),
        'ung-2024-issuer-release': ('January 24, 2024', 'cash in lieu'),
        'alpaca-corporate-actions': ('reverse splits', 'cash from DTC'),
        'alpaca-2021-fractionals': ('August 2nd, 2021', 'removing cash-in-lieu transactions'),
    }
    for key, terms in anchors.items():
        receipt, raw = documents[key]
        body = document_text(raw).lower()
        if receipt['status_code'] != 200 or any(term.lower() not in body for term in terms):
            raise ValueError(f'primary action evidence incomplete: {key}')
    return {'issuer_cash_in_lieu': 'USO 2020 and UNG 2011/2012/2018/2024',
            'broker_sources': ['alpaca-corporate-actions', 'alpaca-2021-fractionals'],
            'account_specific_fractional_treatment': None,
            'cash_credit_dates': None,
            'conclusion': 'Unresolved current-account treatment: retain fractional entitlement or issuer cash-in-lieu; no frozen action/cash amendment'}


def code_hashes():
    paths = ('src/tradingbot/research/c05_commodity_trend.py',
             'src/tradingbot/data/free_history.py', 'src/tradingbot/research/equity_data.py',
             'src/tradingbot/data/alpaca_history.py', 'src/tradingbot/backtest/holdout.py')
    return {p: sha((ROOT / p).read_bytes()) for p in paths}


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
                failures.append(f'{symbol}: source coverage/field integrity failed')
        except (ValueError, KeyError, TypeError, IndexError, ArithmeticError) as exc:
            coverage[symbol] = {'coverage_ok': False, 'error': str(exc)}
            failures.append(f'{symbol}: source parsing/identity failed')
    documents = {key: load_document(archive / 'documents' / key, key) for key in DOCUMENTS}
    try:
        action_gate = verify_fractional_evidence(documents)
        failures.append(action_gate['conclusion'])
    except ValueError as exc:
        action_gate = {'conclusion': str(exc)}
        failures.append(str(exc))
    calendar_path = 'docs/research/13-equity-data-repair-calendar.json'
    calendar_raw = (ROOT / calendar_path).read_bytes()
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    if calendar_raw != subprocess.check_output(['git', 'show', head + ':' + calendar_path], cwd=ROOT):
        raise ValueError('shared calendar evidence must be committed before source audit')
    calendar = json.loads(calendar_raw)
    identity = {'source_sha256': {s: r['sha256'] for s, r in sources.items()},
                'document_sha256': {k: r[0]['sha256'] for k, r in documents.items()},
                'calendar_archive_sha256': data.source_hash, 'calendar_evidence_sha256': sha(calendar_raw),
                'start': START.isoformat(), 'end_exclusive': END.isoformat(), 'policy': POLICY}
    split = HoldoutSplit('sweep-c05-v1:' + sha(canonical(identity).encode()), START, END)
    return {'candidate': 'C05', 'bead': 'tradingbot-9ri', 'status': 'DATA_FAIL',
            'generated_at': datetime.now(UTC).isoformat(), 'sources': sources, 'coverage': coverage,
            'documents': {k: r[0] for k, r in documents.items()}, 'fractional_action_gate': action_gate,
            'failed_prerequisites': failures, 'identity': identity, 'split': split.metadata(),
            'code_sha256': code_hashes(),
            'calendar_evidence': {'path': calendar_path, 'sha256': sha(calendar_raw), 'git_commit': head,
                                  'status': calendar['status'], 'cash_policy_proposal': calendar['cash_policy_proposal']},
            'remaining_checks': ['Full issuer distribution amount/pay-date reconciliation for DBA',
                'Complete five-fund action inventory and actual-share price conversions',
                'Independent same-basis execution price checks for all five ETFs',
                'Frozen settlement/corporate-action cash availability policy'],
            'planned_variants': list(VARIANTS), 'planned_training_costs_bp': [5, 10],
            'training_cases_attempted': 0, 'final_holdout_attempts': 0, 'strategy_outcomes_inspected': False,
            'prior_inspection': 'GLD source overlap with C03; incidental published fund performance in issuer/search pages; no candidate signals or outcomes computed',
            'pnl': None, 'fees': None, 'trades': None, 'drawdown': None, 'regimes': None, 'luck_p_value': None,
            'promotion': 'none'}


def record_failure(session, result, commit):
    if result['status'] != 'DATA_FAIL' or not result['failed_prerequisites']:
        raise ValueError('a concrete data failure is required')
    version = sha(canonical({'identity': result['identity'], 'code': result['code_sha256']}).encode())
    session.execute(text('SELECT pg_advisory_xact_lock(705031)'))
    strategy = session.scalar(select(Strategy).where(Strategy.key == 'sweep_c05_commodity_trend'))
    if strategy is None:
        strategy = Strategy(key='sweep_c05_commodity_trend', name='C05 long/cash commodity ETF trend',
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
                  data_start=START, data_end=END, git_commit=commit, code_version='c05-source-audit-v1',
                  completed_ts=datetime.now(UTC),
                  params={'stage': 'data_quality_only_no_strategy_replay', '_holdout': split.metadata(),
                          'source_audit_version': version, 'policy': POLICY, 'identity': result['identity'],
                          'audit_code_sha256': result['code_sha256']},
                  metrics={'audit_result': 'DATA_FAIL', 'failures': result['failed_prerequisites'],
                           'training_cases_attempted': 0, 'final_holdout_attempts': 0},
                  notes='Source-only failure before signal/replay: unresolved fractional split/cash treatment. '
                        'All six training cases and the final remain unattempted; performance is null, not zero.')
    session.add(trial)
    session.flush()
    return trial


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', action='store_true')
    parser.add_argument('--capture-evidence', action='store_true')
    parser.add_argument('--record-ledger', action='store_true')
    args = parser.parse_args()
    if args.capture:
        for symbol in UNIVERSE:
            receipt = capture(symbol)
            print(json.dumps({'captured': symbol, 'http': receipt['status_code'], 'sha256': receipt['sha256']}), flush=True)
    if args.capture_evidence:
        for key in DOCUMENTS:
            receipt = capture_document(key)
            print(json.dumps({'document': key, 'http': receipt['status_code'], 'sha256': receipt['sha256']}), flush=True)
    result = audit()
    if args.record_ledger:
        paths = list(result['code_sha256'])
        if subprocess.check_output(['git', 'status', '--porcelain', '--', *paths], cwd=ROOT).strip():
            raise ValueError('commit the audit and its dependencies before ledger recording')
        head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        with session_scope() as session:
            trial = record_failure(session, result, head)
            result.update({'data_failure_trial_id': trial.id, 'strategy_id': trial.strategy_id,
                           'audit_git_commit': head})
    encoded = json.dumps(result, indent=2, sort_keys=True) + '\n'
    with CaptureDiskBudget(ROOT / 'data').reserve(2 * len(encoded.encode()) + 65536):
        (ARCHIVE / 'audit.json').write_text(encoded)
    (ROOT / 'docs/research/15-c05-commodity-trend.json').write_text(encoded)
    print(json.dumps({'status': result['status'], 'coverage': {s: r.get('sessions') for s, r in result['coverage'].items()},
                      'failure': result['failed_prerequisites'], 'trial': result.get('data_failure_trial_id'),
                      'holdout_attempts': 0}))


if __name__ == '__main__':
    main()
