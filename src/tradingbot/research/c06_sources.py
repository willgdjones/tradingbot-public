"""C06 source-only checks. No strategy signals, returns or holdout admission."""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal as D
from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path
from dataclasses import asdict
from zoneinfo import ZoneInfo

import pyarrow.parquet as pq

from tradingbot.backtest.holdout import HoldoutSplit
from tradingbot.data.archive import canonical, SCHEMA
from tradingbot.data.c04_sources import Distribution
from tradingbot.data.disk_budget import CaptureDiskBudget
from tradingbot.data.free_history import parse_yahoo

START = datetime(2006, 1, 1, tzinfo=UTC)
END = datetime(2026, 10, 1, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[3]
ARCHIVE = ROOT / 'data/research/c06'
SPY_RECEIPT_SHA = '3726951207c75d417a45d4264e414178eb5d4234e7f6328e4cf363474dbe9040'
SPY_DATA_SHA = 'cab4b01dd76d2603b9e94d20890579fd63d1e1e6dc6030e77838f18a99ea86a5'


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def spy_source(root=ROOT):
    """Read the opt-in, reviewed source amendment; never rebuild or overwrite it."""
    manifest = json.loads((root / 'docs/research/13-equity-data-repair-spy-amendment.json').read_text())
    receipt_sha = manifest.pop('receipt_sha256')
    if sha(canonical(manifest).encode()) != receipt_sha or receipt_sha != SPY_RECEIPT_SHA:
        raise ValueError('SPY source amendment receipt changed')
    raw = (root / manifest['data_path']).read_bytes()
    if sha(raw) != manifest['identity']['data_sha256'] or sha(raw) != SPY_DATA_SHA:
        raise ValueError('SPY source amendment data changed')
    split = manifest['split']
    if (split['data_start'] != START.isoformat() or split['data_end'] != END.isoformat()
            or split['holdout_start'] != '2020-07-10T14:24:00+00:00'):
        raise ValueError('SPY source bounds changed')
    manifest['receipt_sha256'] = receipt_sha
    return manifest, json.loads(raw)


class _IssuerPage(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables = []
        self.parallel_tables = []

    def handle_starttag(self, tag, attrs):
        props = dict(attrs).get('componentprops')
        if tag != 'walrus-render-on-client' or not props or 'Payable Date' not in props:
            return
        data = json.loads(props)
        if 'distributionTableData' in data:
            self.tables.append(data['distributionTableData'])
        containers = data.get('containersByNameMap', {})
        if 'distributions' in containers:
            self.parallel_tables.append(containers['distributions']['subContainersByNameMap']['table']['dataPointsByNameMap'])


def ishares_distributions(raw: str) -> dict[date, Distribution]:
    """Parse exact typed issuer arrays; require agreement between embedded views."""
    page = _IssuerPage()
    page.feed(raw)
    if len(page.tables) != 1 or len(page.parallel_tables) != 1:
        raise ValueError('missing or ambiguous issuer distribution tables')
    records = page.tables[0]
    columns = {c['name']: c for c in records}
    expected = {'recordDate': 'Record Date', 'exDate': 'Ex-Date', 'payableDate': 'Payable Date',
                'totalDistribution': 'Total Distribution', 'incomeAmount': 'Income',
                'shortTermCapitalGain': 'ST Cap Gains', 'longTermCapitalGain': 'LT Cap Gains',
                'returnOnCapital': 'Return of Capital'}
    if len(columns) != len(records) or set(columns) != expected.keys():
        raise ValueError('issuer distribution columns changed')
    lengths = {len(c.get('value', [])) for c in columns.values()}
    if len(lengths) != 1 or not next(iter(lengths)):
        raise ValueError('issuer distribution array lengths differ or are empty')
    for key, label in expected.items():
        column = columns[key]
        parallel = page.parallel_tables[0][key]
        if (column['label'] != label or parallel['label'] != label
                or column['value'] != parallel['value']):
            raise ValueError('issuer distribution views or headers disagree')
    output = {}
    for i in range(next(iter(lengths))):
        def day(key):
            value = columns[key]['value'][i]
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError('issuer date must be an integer YYYYMMDD')
            return datetime.strptime(str(value), '%Y%m%d').date()
        ex, record, pay = (day(k) for k in ('exDate', 'recordDate', 'payableDate'))
        parts = [D(str(columns[k]['value'][i])) for k in
                 ('incomeAmount', 'shortTermCapitalGain', 'longTermCapitalGain', 'returnOnCapital')]
        amount = D(str(columns['totalDistribution']['value'][i]))
        if (any(not x.is_finite() or x < 0 for x in [amount, *parts])
                or amount <= 0 or amount != sum(parts, D(0))
                or not ex <= record <= pay or ex in output):
            raise ValueError(f'invalid or duplicated issuer distribution: {ex}')
        output[ex] = Distribution(ex, record, pay, amount)
    return output


def reconcile_distributions(bars, distributions):
    """Require exact ex-dates and only the preregistered three-decimal rounding."""
    issuer = {d: v for d, v in distributions.items() if START.date() <= d < END.date()}
    vendor = {b.date: b.dividend for b in bars if b.dividend}
    if vendor.keys() != issuer.keys():
        raise ValueError(f'IEF ex-date disagreement: vendor_only={sorted(vendor.keys()-issuer.keys())}, issuer_only={sorted(issuer.keys()-vendor.keys())}')
    differences = []
    for day, amount in vendor.items():
        true = issuer[day].amount
        if abs(amount - true) > D('.0005'):
            raise ValueError(f'IEF amount disagreement beyond rounding: {day}: vendor={amount}, issuer={true}')
        if amount != true:
            differences.append({'ex_date': str(day), 'vendor': str(amount), 'issuer': str(true)})
    return issuer, differences


def reference_overlap(archive, bars, sessions):
    """Audit both fixed raw feeds and all closes, never splice price histories."""
    output = []
    by_date = {b.date: b for b in bars}
    for feed in ('iex', 'sip'):
        directories = list((archive / 'raw/alpaca' / ('bars_1Day_raw_' + feed)
                            / 'c06-source-20261001').glob('*/manifest.json'))
        if len(directories) != 1:
            raise ValueError('missing or ambiguous IEF overlap archive')
        path = directories[0]
        manifest = json.loads(path.read_text())
        if sha(canonical(manifest).encode())[:24] != path.parent.name:
            raise ValueError('IEF overlap archive identity changed')
        request = manifest['request']
        expected_params = {'symbols': 'IEF', 'timeframe': '1Day',
            'start': '2016-01-01T00:00:00Z', 'end': '2026-10-01T00:00:00Z',
            'adjustment': 'raw', 'feed': feed, 'limit': 10000, 'sort': 'asc', 'asof': '-'}
        if request != {'url': 'https://data.alpaca.markets/v2/stocks/bars', 'params': expected_params}:
            raise ValueError('IEF overlap request differs from fixed capture')
        files = sorted(path.parent.glob('page-*.parquet'))
        if len(files) != 1 or files[0].name != 'page-00000000.parquet':
            raise ValueError('IEF overlap expects its one exhausted page')
        table = pq.read_table(files[0])
        if table.num_rows != 1 or not table.schema.equals(SCHEMA):
            raise ValueError('IEF overlap page schema mismatch')
        row = table.to_pylist()[0]
        payload = json.loads(row['response_json'], parse_float=D)
        if (row['request_json'] != canonical(request) or row['page'] != 0
                or row['response_sha256'] != sha(row['response_json'].encode())
                or row['next_request_json'] is not None or payload['next_page_token'] is not None
                or set(payload['bars']) != {'IEF'} or row['record_count'] != len(payload['bars']['IEF'])):
            raise ValueError('IEF overlap page checksum, cursor or count mismatch')
        compared = {}
        worst = D(0)
        for other in payload['bars']['IEF']:
            stamp = datetime.fromisoformat(other['t'].replace('Z', '+00:00'))
            if stamp.tzinfo is None:
                raise ValueError('IEF overlap timestamp must be aware')
            day = stamp.astimezone(ZoneInfo('America/New_York')).date()
            close = D(str(other['c']))
            if day not in by_date or day in compared or not close.is_finite() or close <= 0:
                raise ValueError('invalid or duplicate IEF overlap price/session')
            distance = abs(by_date[day].close / close - 1)
            if distance > D('.01'):
                raise ValueError(f'IEF raw close disagreement beyond fixed 1%: {feed} {day}')
            compared[day] = close
            worst = max(worst, distance)
        if not compared:
            raise ValueError('IEF independent overlap is empty')
        missing = sorted(d for d in sessions if min(compared) <= d <= max(compared) and d not in compared)
        output.append({'feed': feed, 'response_sha256': row['response_sha256'],
            'path': str(files[0].relative_to(ROOT)), 'request': request, 'sessions': len(compared),
            'first': str(min(compared)), 'last': str(max(compared)),
            'missing_overlap_sessions': list(map(str, missing)),
            'worst_relative_close_difference': str(worst), 'threshold': '0.01', 'breaches': []})
    return output


def calendar_windows(prices):
    """Calendar only: previous month end, decision, entry, next-month exit."""
    groups = {}
    for row in prices:
        groups.setdefault(row['date'][:7], []).append(row['date'])
    months = sorted(groups)
    windows = []
    for previous, current, following in zip(months, months[1:], months[2:]):
        days = groups[current]
        windows.append({'month': current, 'base': groups[previous][-1],
                        'decision': days[-2], 'entry': days[-1], 'exit': groups[following][0]})
    return windows


def build_sources(archive=ARCHIVE):
    from tradingbot.research.c03_source_audit import load_source, inspect_source
    from tradingbot.research.equity_data import load_equities
    spy_manifest, spy = spy_source()
    yahoo_receipt, raw = load_source(ROOT / 'data/research/c03/IEF', 'IEF')
    if yahoo_receipt['status_code'] != 200:
        raise ValueError('IEF Yahoo archive was not successful')
    _, bars = parse_yahoo(raw.decode())
    original = load_equities(ROOT / 'data/equities/c04', 'c04-20261001')
    coverage = inspect_source(raw, 'IEF', original.sessions)
    if not coverage['coverage_ok'] or coverage['split_events']:
        raise ValueError('IEF session/action source integrity failure')
    issuer_path = archive / 'ief-issuer-page/raw.html'
    issuer_meta = json.loads(issuer_path.with_name('manifest.json').read_text())
    issuer_raw = issuer_path.read_bytes()
    if issuer_meta['status'] != 200 or issuer_meta['sha256'] != sha(issuer_raw):
        raise ValueError('IEF issuer page checksum or status mismatch')
    distributions, differences = reconcile_distributions(bars, ishares_distributions(issuer_raw.decode()))
    overlap = reference_overlap(archive, bars, original.sessions)
    windows = calendar_windows(spy['prices'])
    # This is only a calendar/action check, independent of signal selection.
    # If a future source has an entitled SPY distribution during ANY eligible
    # window, require dividend-aware execution accounting before admission.
    collisions = [(w['month'], d['ex_date']) for w in windows for d in spy['distributions']
                  if w['entry'] < d['ex_date'] <= w['exit']]
    if collisions:
        raise ValueError(f'SPY dividend entitlement in C06 window needs cash ledger support: {collisions}')
    stooq_path = archive / 'stooq-ief/raw.txt'
    stooq = json.loads(stooq_path.with_name('manifest.json').read_text())
    if sha(stooq_path.read_bytes()) != stooq['sha256']:
        raise ValueError('Stooq response checksum mismatch')
    body = {'SPY': spy, 'IEF': {'prices': [{'date': str(b.date), 'close': str(b.close)} for b in bars],
            'distributions': [{k: str(v) for k, v in asdict(d).items()} for _, d in sorted(distributions.items())]}}
    encoded = (canonical(body) + '\n').encode()
    policy = {'scope': 'SPY execution open/close; IEF signal close only; no high/low/adjusted close execution',
        'spy_amendment': spy_manifest['receipt_sha256'],
        'signal': 'causal compounded (close + issuer ex-date distribution)/prior close; no double counting',
        'cash': spy_manifest['identity']['policies']['cash'],
        'ief_distributions': 'Issuer exact amounts replace vendor three-decimal rounding; IEF is reference only, never owned',
        'price_overlap': 'IEX and SIP raw closes, existing fixed 1% bound, no substitutions or enlarged tolerance; no independent coverage claimed before 2016',
        'stooq': 'Archived HTTP404 response; no data or total-return validation claimed',
        'dividend_execution': 'All calendar-eligible SPY round trips have zero ex-date entitlement; otherwise stop before replay',
        'contamination': 'Prior #5/#6/C01 SPY inspection and issuer-page fund performance; historical results diagnostic, never fresh proof',
        'fees': 'EquityFeeBook 2026-09-17 current-account counterfactual; 5 and 10 bp per side fixed training cases',
        'risk': '140 virtual USD; 95% target with cash buffer and unchanged PRD6 hard slot/loss limits'}
    identity = {'spy_data_sha256': SPY_DATA_SHA, 'spy_receipt_sha256': SPY_RECEIPT_SHA,
        'ief_yahoo_sha256': yahoo_receipt['sha256'], 'ief_issuer_sha256': issuer_meta['sha256'],
        'ief_overlap_sha256': [v['response_sha256'] for v in overlap], 'stooq_sha256': stooq['sha256'],
        'data_sha256': sha(encoded), 'policy': policy, 'data_start': START.isoformat(), 'data_end': END.isoformat()}
    split = HoldoutSplit('sweep-c06-v1:' + sha(canonical(identity).encode()), START, END)
    receipt = {'status': 'SOURCE_VALIDATED_NOT_STRATEGY_ADMITTED', 'candidate': 'C06', 'identity': identity,
        'split': split.metadata(), 'ief_yahoo_source': yahoo_receipt, 'ief_issuer_source': issuer_meta,
        'ief_coverage': coverage, 'ief_distribution_reconciliations': differences, 'ief_overlap': overlap,
        'stooq': stooq, 'calendar_eligible_windows': len(windows), 'spy_dividend_entitlement_collisions': collisions,
        'strategy_outcomes_inspected': False, 'training_cases_attempted': 0, 'final_holdout_attempts': 0,
        'source_code_sha256': {str(p.relative_to(ROOT)): sha(p.read_bytes()) for p in
            [Path(__file__), ROOT / 'src/tradingbot/research/c03_source_audit.py',
             ROOT / 'src/tradingbot/data/free_history.py']}}
    receipt['receipt_sha256'] = sha(canonical(receipt).encode())
    directory = archive / 'frozen-source-v1'
    rendered = (json.dumps(receipt, indent=2, sort_keys=True) + '\n').encode()
    with CaptureDiskBudget(ROOT / 'data').reserve(3 * (len(encoded) + len(rendered)) + 65536):
        directory.mkdir(exist_ok=True)
        for target, value in [(directory / 'data.json', encoded), (directory / 'manifest.json', rendered)]:
            if target.exists() and target.read_bytes() != value:
                raise ValueError('refuse overwrite of frozen C06 source')
            if not target.exists():
                target.write_bytes(value)
    (ROOT / 'docs/research/16-c06-source-audit.json').write_bytes(rendered)
    return receipt


if __name__ == '__main__':
    receipt = build_sources()
    print(json.dumps({k: receipt[k] for k in ('status', 'split', 'receipt_sha256', 'calendar_eligible_windows')}))
