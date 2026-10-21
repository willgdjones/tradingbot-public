"""C03 source reconciliation only: no rankings, strategy returns or replay."""
from __future__ import annotations

import argparse
from datetime import UTC, date, datetime
from decimal import Decimal as D
from html.parser import HTMLParser
import json
import subprocess

from sqlalchemy import select, text

from tradingbot.backtest.holdout import HoldoutSplit, register_split
from tradingbot.data.archive import canonical
from tradingbot.data.disk_budget import CaptureDiskBudget
from tradingbot.db.models import Strategy, Trial
from tradingbot.db.session import get_engine, session_scope
from tradingbot.research.c03_c04_c03_audit import audit as prior_audit
from tradingbot.research.c03_repair_capture import ROOT, ARCHIVE, SOURCES, load, sha
from tradingbot.research.c03_source_audit import START, END, UNIVERSE, VARIANTS

REPORT = 'docs/research/35-c03-source-repair.json'
PRIOR = 'docs/research/24-c03-c04-c03-source.json'
PLAN = 'docs/research/35-c03-source-repair-plan.md'
KEY = 'sweep_c03_cross_asset_momentum'
CODE = (
    'src/tradingbot/research/c03_repair_audit.py',
    'src/tradingbot/research/c03_repair_capture.py',
    'src/tradingbot/research/c03_c04_c03_audit.py',
    'src/tradingbot/research/c03_source_audit.py',
    'src/tradingbot/research/c06_sources.py',
)
TARGETS = ('2006-03-20', '2006-06-26', '2006-09-25', '2006-12-22')


class Tables(HTMLParser):
    """Keep each table's headers and body separate, including headerless tr markup."""
    def __init__(self):
        super().__init__()
        self.stack, self.tables = [], []

    def handle_starttag(self, tag, attrs):
        if tag == 'table':
            self.stack.append({'headers': [], 'rows': [], 'row': None, 'cell': None, 'attrs': dict(attrs)})
        elif self.stack:
            item = self.stack[-1]
            if tag == 'tr':
                item['row'] = []
            elif tag in ('th', 'td'):
                item['cell'] = (tag, [])

    def handle_data(self, data):
        if self.stack and self.stack[-1]['cell'] is not None:
            self.stack[-1]['cell'][1].append(data)

    def handle_endtag(self, tag):
        if not self.stack:
            return
        item = self.stack[-1]
        if tag in ('th', 'td') and item['cell'] is not None:
            kind, parts = item['cell']
            value = ' '.join(' '.join(parts).split())
            if kind == 'th':
                item['headers'].append(value)
            elif item['row'] is not None:
                item['row'].append(value)
            item['cell'] = None
        elif tag == 'tr':
            if item['row']:
                item['rows'].append(item['row'])
            item['row'] = None
        elif tag == 'table':
            self.tables.append(self.stack.pop())


def table(raw, headers, *, continuation_class=None):
    parser = Tables()
    parser.feed(raw)
    matches = [item for item in parser.tables if item['headers'] == headers]
    if len(matches) != 1 or not matches[0]['rows']:
        raise ValueError('missing or ambiguous source table headers')
    rows = list(matches[0]['rows'])
    if continuation_class is not None:
        if matches[0]['attrs'].get('class') != continuation_class:
            raise ValueError('source continuation table class changed')
        # Stock Screener splits its one chronology into adjacent identically
        # styled tables around an advertisement, omitting repeated headings.
        index = parser.tables.index(matches[0]) + 1
        while index < len(parser.tables):
            following = parser.tables[index]
            if following['headers'] or following['attrs'].get('class') != continuation_class:
                break
            rows.extend(following['rows'])
            index += 1
    if any(len(row) != len(headers) for row in rows):
        raise ValueError('source table row width changed')
    return rows


def day(value, fmt):
    return datetime.strptime(value, fmt).date()


def amount(value):
    value = D(value.removeprefix('$'))
    if not value.is_finite() or value <= 0:
        raise ValueError('invalid cash amount')
    return value


def components(raw):
    output, seen = {}, set()
    for ex, value, kind in table(raw, ['Date', 'Amount', 'Type']):
        ex = day(ex, '%b %d, %Y')
        if not START.date() <= ex < END.date():
            continue
        if kind not in ('OrdinaryDividend', 'CapitalGainLongTerm', 'CapitalGainShortTerm', 'ReturnOfCapital'):
            raise ValueError('unknown cash component')
        if (ex, kind) in seen:
            raise ValueError('duplicate cash component')
        seen.add((ex, kind))
        output.setdefault(str(ex), []).append({'kind': kind, 'amount': str(amount(value))})
    return output


def full_cash(raw):
    headers = ['Ex-Dividend Date', 'Period', 'Dividend', 'Change', 'Declaration Date', 'Record Date', 'Payout Date']
    output = {}
    prior_date = None
    for ex, period, value, _, declared, record, pay in table(raw, headers, continuation_class='table table-bordered'):
        ex = day(ex, '%m/%d/%Y')
        if prior_date is not None and ex >= prior_date:
            raise ValueError('duplicate or unordered full cash chronology')
        prior_date = ex
        if not START.date() <= ex < END.date():
            continue
        record, pay = day(record, '%m/%d/%Y'), day(pay, '%m/%d/%Y')
        if str(ex) in output or not ex <= record <= pay or period != 'Quarterly':
            raise ValueError('invalid or duplicate full cash row')
        output[str(ex)] = {'amount': str(amount(value)), 'record_date': str(record),
                          'pay_date': str(pay), 'declared_as_reported': declared or None}
    return output


def marketlog(raw):
    headers = ['Name', 'Ex-Dividend Date', 'Dividend', 'Payment Date', 'Record Date', 'Declaration Date', 'Frequency']
    output = {}
    for name, ex, value, pay, record, _, frequency in table(raw, headers):
        ex = day(ex, '%d %b %Y')
        if not START.date() <= ex < END.date():
            continue
        record = None if record == '-' else day(record, '%d %b %Y')
        pay = None if pay == '-' else day(pay, '%d %b %Y')
        if (not name.startswith('VNQ Paid Vanguard Real Estate ETF ') or frequency not in ('Quarterly', 'Other')
                or str(ex) in output or (record is not None and record < ex)
                or (pay is not None and pay < (record or ex))):
            raise ValueError('invalid or duplicate rounded cash row')
        output[str(ex)] = {'rounded_amount': str(amount(value)),
                          'record_date': str(record) if record else None,
                          'pay_date': str(pay) if pay else None, 'frequency_as_reported': frequency}
    return output


def labeled_payments(raw):
    output = []
    seen = set()
    for kind, data_com, pay, value in table(raw, ['tipo', 'data com', 'pagamento', 'valor']):
        label, pay = day(data_com, '%d/%m/%Y'), day(pay, '%d/%m/%Y')
        if not START.date() <= label < END.date():
            continue
        value = amount(value.replace(',', '.'))
        identity = (label, pay, value)
        if identity in seen or kind != 'Dividendos' or pay < label:
            raise ValueError('invalid or duplicate labeled payment row')
        seen.add(identity)
        # The source labels this "data com". Do not silently relabel it ex-date
        # or infer entitlement from what resembles a US record date.
        output.append({'data_com_as_labeled': str(label), 'pay_date': str(pay), 'amount': str(value)})
    return output


def calendar_row(raw):
    rows = table(raw, ['Security', 'Ex-Date', 'Pay Date', 'Div.%', 'Amount'])
    matches = [r for r in rows if r[0] == 'Vanguard Real Estate Index Fund ETF Shares']
    if len(matches) != 1:
        raise ValueError('ambiguous VNQ calendar row')
    _, ex, pay, _, value = matches[0]
    return {'ex_date': str(day(ex, '%d/%m/%Y')), 'pay_date': str(day(pay, '%d/%m/%Y')),
            'rounded_amount': str(amount(value))}


def reconcile_2006(vendor, ordinary, parts, totals, rounded, payments):
    output = []
    for ex in TARGETS:
        total = totals[ex]
        component_total = sum((D(row['amount']) for row in parts[ex]), D(0))
        payment_matches = [r for r in payments if D(r['amount']) == D(total['amount'])
                           and r['pay_date'] == total['pay_date']]
        ordinary_parts = [D(r['amount']) for r in parts[ex] if r['kind'] == 'OrdinaryDividend']
        checks = {
            'components_equal_full_total': component_total == D(total['amount']),
            'original_yahoo_total_agrees': D(vendor[ex]) == D(total['amount']),
            'old_cash_row_matches_ordinary_component': ordinary_parts == [D(ordinary[ex]['amount'])],
            'ordinary_and_full_total_pay_dates_agree': ordinary[ex]['pay_date'] == total['pay_date'],
            'independent_page_full_total_and_payment_match': len(payment_matches) == 1,
            'rounded_reference_amount_consistent': abs(D(rounded[ex]['rounded_amount']) - component_total) <= D('.005'),
            'rounded_reference_dates_agree': all(rounded[ex][key] == total[key] for key in ('record_date', 'pay_date')),
        }
        output.append({'ex_date': ex, 'components': parts[ex], 'full_total': total,
                       'payment_matches': payment_matches, 'rounded_reference': rounded[ex],
                       'checks': checks, 'secondary_corroboration': all(checks.values()),
                       'issuer_event_notice_recovered': False,
                       'independent_upstream_providers_proven': False})
    return output


def configurations():
    return [{'variant': variant, 'costs_bp_per_side': cost, 'state': 'unattempted_source_gate_failed'}
            for variant in VARIANTS for cost in (5, 10)]


def audit():
    original = json.loads((ROOT / PRIOR).read_bytes())
    old = prior_audit()  # Revalidates prior immutable source bytes, not outcomes.
    if (original['identity'] != old['identity'] or original['data_failure_trial_id'] != 4067
            or original['original_failed_trial'] != 3516):
        raise ValueError('previous C03 source receipt changed')
    sources, raw = {}, {}
    for key in SOURCES:
        meta, body = load(key)
        capture_code = ARCHIVE / 'capture-code' / (meta['capture_code_sha256'] + '.py')
        if sha(capture_code.read_bytes()) != meta['capture_code_sha256']:
            raise ValueError('historical capture code bytes changed')
        sources[key] = {**meta, 'raw_path': str((ARCHIVE / key / 'raw').relative_to(ROOT)),
                       'capture_code_path': str(capture_code.relative_to(ROOT)),
                       'manifest_sha256': sha((ARCHIVE / key / 'manifest.json').read_bytes())}
        if meta['status'] == 200 and key not in ('vnq-arca-listing-2008',):
            raw[key] = body.decode()
    parts, totals = components(raw['dividend-com']), full_cash(raw['stock-screener'])
    rounded, payments = marketlog(raw['marketlog']), labeled_payments(raw['investidor10'])
    calendar = calendar_row(raw['divvydiary-june-2009'])
    vendor = {r['ex_date']: r['amount'] for r in old['coverage']['VNQ']['dividend_events']}
    ordinary = old['secondary_evidence']['dividendhistory']['rows']
    rows = reconcile_2006(vendor, ordinary, parts, totals, rounded, payments)
    extra = sorted(totals.keys() - vendor.keys())
    missing = sorted(vendor.keys() - totals.keys())
    conflicts = [{'ex_date': ex, 'vendor': vendor[ex], 'secondary': totals[ex]['amount']}
                 for ex in sorted(vendor.keys() & totals.keys())
                 if abs(D(vendor[ex]) - D(totals[ex]['amount'])) > D('.0005')]
    june = {
        'original_yahoo': {'ex_date': '2009-06-24', 'amount': vendor['2009-06-24']},
        'original_dividendhistory': {'ex_date': '2009-06-24', **ordinary['2009-06-24']},
        'dividend_com': {'date_as_reported': '2009-06-25', 'table_header': 'Date', 'components': parts['2009-06-25']},
        'stock_screener': {'ex_date': '2009-06-25', **totals['2009-06-25']},
        'marketlog': {'ex_date': '2009-06-25', **rounded['2009-06-25']},
        'divvydiary': calendar,
        'investidor10': [r for r in payments if r['pay_date'] == '2009-06-30'],
        'primary_event_notice_recovered': False, 'entitlement_date_resolved': False,
        'payment_agreement_does_not_resolve_ex_date': True,
    }
    failures = ['VNQ June 2009 entitlement date remains disputed: June 24 versus June 25. No original issuer/exchange event notice resolves it.']
    if not all(r['secondary_corroboration'] for r in rows):
        failures.append('One or more older cash components/payments still lack secondary corroboration.')
    if missing != ['2009-06-24'] or extra != ['2009-06-25'] or conflicts:
        failures.append('Additional full-period secondary source discrepancy requires review.')
    code = {p: sha((ROOT / p).read_bytes()) for p in CODE}
    proofs = (PRIOR, PLAN, 'docs/research/24-c03-c04-readmission-plan.md',
              'docs/research/07-candidate-shortlist.md', 'docs/research/21-corporate-action-blackout.md')
    identity = {'candidate': 'C03-source-repair-v1', 'prior_identity': old['identity'],
                'sources': sources, 'policy_sha256': {p: sha((ROOT / p).read_bytes()) for p in proofs},
                'universe': list(UNIVERSE), 'variants': list(VARIANTS), 'costs_bp_per_side': [5, 10],
                'cash_rule': 'Pre-ex ownership; first regular open strictly after latest documented payment date of every component; no imputation.',
                'full_period_secondary_missing': missing, 'full_period_secondary_extra': extra,
                'secondary_corroboration_is_not_primary_or_proven_upstream_independence': True}
    split = HoldoutSplit('c03-source-repair-v1:' + sha(canonical(identity).encode()), START, END)
    return {'candidate': 'C03', 'bead': 'tradingbot-2wh', 'status': 'DATA_FAIL',
            'dataset_admitted': False, 'identity': identity, 'code_sha256': code,
            'split': split.metadata(), 'older_cash_reconciliation': rows,
            'june_2009_conflict': june, 'full_period_secondary_amount_conflicts': conflicts,
            'issuer_api_scope': 'Existing issuer endpoint covers 40 ex-dates from 2016-12-22. Current product page says up to ten years; linked distribution store fetches this endpoint with a yield flag, not a historical-date range.',
            'primary_search_limits': 'SEC direct report HTTP403; historical 2010 report mirror HTTP404. Web SEC extraction corroborates 2006 annual total 3.254 only, not event/payment dates; not admitted as original archived bytes. Arca listing notice dated 2008-09-19 establishes listing transfer only.',
            'failed_prerequisites': failures,
            'not_completed_after_failed_gate': ['Full five-fund share-action inventory and timely Amendment21 notices',
                'GLD 2006-2007 independent price/action scope and full actual-share admission',
                'Committed admitted source, pure strategy, six training cases, selection and final'],
            'prior_failed_trials': [3516, 4067], 'planned_configurations': configurations(),
            'strategy_outcomes_inspected': False, 'training_cases_attempted': 0, 'final_holdout_attempts': 0,
            'pnl': None, 'fees': None, 'trade_count': None, 'drawdown': None, 'regimes': None,
            'luck_p_value': None, 'promotion': 'none'}


def record_failure(session, result, commit):
    if (result['status'] != 'DATA_FAIL' or not result['failed_prerequisites']
            or result['dataset_admitted'] or result['strategy_outcomes_inspected']
            or result['training_cases_attempted'] != 0 or result['final_holdout_attempts'] != 0
            or result['planned_configurations'] != configurations()
            or any(result[k] is not None for k in ('pnl', 'fees', 'trade_count', 'drawdown', 'regimes', 'luck_p_value'))):
        raise ValueError('only source failure without performance can be recorded')
    split = HoldoutSplit(result['split']['dataset_key'], START, END)
    if split.metadata() != result['split']:
        raise ValueError('fixed C03 bounds changed')
    version = sha(canonical({'identity': result['identity'], 'code': result['code_sha256']}).encode())
    session.execute(text('SELECT pg_advisory_xact_lock(703031)'))
    strategy = session.scalar(select(Strategy).where(Strategy.key == KEY))
    if strategy is None:
        raise ValueError('existing C03 strategy missing; refuse duplicate family')
    old = session.scalar(select(Trial).where(Trial.strategy_id == strategy.id,
        Trial.params['source_audit_version'].astext == version))
    if old is not None:
        return old
    register_split(session, split)
    trial = Trial(strategy_id=strategy.id, mode='backtest', status='failed', final_holdout=False,
        dataset_key=split.dataset_key, holdout_start=split.holdout_start, data_start=START, data_end=END,
        git_commit=commit, code_version='c03-source-repair-v1', completed_ts=datetime.now(UTC),
        params={'stage': 'data_quality_only_no_strategy_replay', '_holdout': split.metadata(),
                'source_audit_version': version, 'identity': result['identity'], 'code_sha256': result['code_sha256'],
                'planned_configurations': result['planned_configurations']},
        metrics={'audit_result': 'DATA_FAIL', 'failures': result['failed_prerequisites'],
                 'training_cases_attempted': 0, 'final_holdout_attempts': 0},
        notes='Older VNQ 2006 full cash/payment evidence corroborated; June2009 ex-date remains disputed. '
              'No rankings, returns or holdout. Decision/risk review: docs/research/35-c03-source-repair.md.')
    session.add(trial)
    session.flush()
    return trial


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record-ledger', action='store_true')
    args = parser.parse_args()
    result = audit()
    path = ROOT / REPORT
    ledger_keys = ('data_failure_trial_id', 'strategy_id', 'audit_git_commit')
    if path.exists():
        saved = json.loads(path.read_bytes())
        if {k: v for k, v in saved.items() if k not in ledger_keys} == result:
            result.update({k: saved[k] for k in ledger_keys if k in saved})
    if args.record_ledger:
        tracked = list(CODE) + list(result['identity']['policy_sha256'])
        if subprocess.check_output(['git', 'status', '--porcelain', '--', *tracked], cwd=ROOT).strip():
            raise ValueError('commit source code and policy before ledger recording')
        engine = get_engine()
        if engine.url.port != 5433 or engine.url.database != 'tradingbot':
            raise ValueError('designated local database required')
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        with session_scope() as session:
            trial = record_failure(session, result, commit)
            result.update(data_failure_trial_id=trial.id, strategy_id=trial.strategy_id, audit_git_commit=trial.git_commit)
    encoded = (json.dumps(result, indent=2, sort_keys=True) + '\n').encode()
    with CaptureDiskBudget(ROOT / 'data').reserve(3 * len(encoded) + 65536):
        (ARCHIVE / 'audit.json').write_bytes(encoded)
    path.write_bytes(encoded)
    print(json.dumps({'status': result['status'], 'trial': result.get('data_failure_trial_id'),
        'corroborated_2006_rows': sum(r['secondary_corroboration'] for r in result['older_cash_reconciliation']),
        'training_cases_attempted': 0, 'final_holdout_attempts': 0}))


if __name__ == '__main__':
    main()
