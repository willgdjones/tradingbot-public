"""C03 re-admission evidence. Never calculate rankings, returns or outcomes."""
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
from html.parser import HTMLParser
import argparse
import json
import subprocess

import pyarrow.parquet as pq
from sqlalchemy import select

from tradingbot.backtest.holdout import HoldoutSplit, register_split
from tradingbot.connectors.cash import NEW_YORK
from tradingbot.data.archive import canonical, SCHEMA
from tradingbot.data.c04_sources import Distribution
from tradingbot.data.disk_budget import CaptureDiskBudget
from tradingbot.data.equity_source_repair import primary_opening_price, primary_closing_price
from tradingbot.data.free_history import parse_yahoo
from tradingbot.db.models import Trial
from tradingbot.db.session import session_scope
from tradingbot.research.c03_source_audit import load_source, inspect_source, UNIVERSE
from tradingbot.research.c03_c04_sources import ROOT, ARCHIVE, START, END, sha
from tradingbot.research.c06_sources import _IssuerPage, ishares_distributions, spy_source
from tradingbot.research.equity_data import load_equities

RUN = 'c03-readmission-20261001'


def document(folder, filename, url):
    metadata = json.loads((folder / 'manifest.json').read_text())
    raw = (folder / filename).read_bytes()
    if metadata['url'] != url or metadata['status'] != 200 or metadata['sha256'] != sha(raw):
        raise ValueError('document identity/status/checksum mismatch')
    return metadata, raw


def efa_distributions(raw):
    """Validate both issuer views; irrelevant pre-2006 missing components stay excluded."""
    page = _IssuerPage(); page.feed(raw)
    if len(page.tables) != 1 or len(page.parallel_tables) != 1:
        raise ValueError('ambiguous EFA issuer views')
    columns = {r['name']: r for r in page.tables[0]}
    names = {'exDate', 'recordDate', 'payableDate', 'totalDistribution', 'incomeAmount',
             'shortTermCapitalGain', 'longTermCapitalGain', 'returnOnCapital'}
    if set(columns) != names or len(columns) != len(page.tables[0]):
        raise ValueError('EFA issuer headers changed')
    lengths = {len(r['value']) for r in columns.values()}
    if len(lengths) != 1 or next(iter(lengths)) == 0:
        raise ValueError('EFA issuer array mismatch')
    for key, column in columns.items():
        parallel = page.parallel_tables[0][key]
        if column['value'] != parallel['value'] or column['label'] != parallel['label']:
            raise ValueError('EFA parallel views disagree')
    out = {}
    for index in range(next(iter(lengths))):
        def day(key):
            value = columns[key]['value'][index]
            if type(value) is not int:
                raise ValueError('EFA date is not integer YYYYMMDD')
            return datetime.strptime(str(value), '%Y%m%d').date()
        ex, record, pay = (day(k) for k in ('exDate', 'recordDate', 'payableDate'))
        if not START.date() <= ex < END.date():
            continue
        parts = [D(str(columns[k]['value'][index])) for k in
                 ('incomeAmount', 'shortTermCapitalGain', 'longTermCapitalGain', 'returnOnCapital')]
        total = D(str(columns['totalDistribution']['value'][index]))
        if (any(not p.is_finite() or p < 0 for p in [*parts, total]) or total <= 0
                or total != sum(parts, D(0)) or not ex <= record <= pay or ex in out):
            raise ValueError('invalid EFA in-interval distribution')
        out[ex] = Distribution(ex, record, pay, total)
    return out


def vanguard_distributions(raw):
    """Sum separate INC/ROC/capital-gain/1250 cash components once per ex-date."""
    groups, seen = {}, set()
    for row in json.loads(raw, parse_float=D):
        ex, record, pay = (date.fromisoformat(row[k]) for k in ('exDividendDate', 'recordDate', 'payableDate'))
        kind, amount = row['typeCode'], D(row['amount'])
        if (kind not in {'INC', 'ROC', 'CGST', 'CGLT', '1250'} or not amount.is_finite()
                or amount < 0 or (ex, kind) in seen or not ex <= record <= pay):
            raise ValueError('invalid/duplicate Vanguard distribution component')
        seen.add((ex, kind))
        old = groups.get(ex, Distribution(ex, record, pay, D(0)))
        if (old.record_date, old.pay_date) != (record, pay):
            raise ValueError('Vanguard cash components disagree on dates')
        groups[ex] = Distribution(ex, record, pay, old.amount + amount)
    if not groups or any(v.amount <= 0 for v in groups.values()):
        raise ValueError('empty/nonpositive Vanguard distribution inventory')
    return groups


class TableRows(HTMLParser):
    def __init__(self):
        super().__init__(); self.rows, self.row, self.cell = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == 'tr': self.row = []
        if tag in ('th', 'td'): self.cell = []

    def handle_data(self, value):
        if self.cell is not None: self.cell.append(value)

    def handle_endtag(self, tag):
        if tag in ('th', 'td') and self.cell is not None:
            if self.row is not None: self.row.append(' '.join(' '.join(self.cell).split()))
            self.cell = None
        if tag == 'tr' and self.row is not None:
            self.rows.append(self.row); self.row = None


def secondary_distributions(raw, kind):
    table = TableRows(); table.feed(raw)
    if kind == 'dividendhistory':
        expected = ['Ex-Dividend Date', 'Payout Date', 'Cash Amount', 'Change / Status']
        fmt, pay_index = '%Y-%m-%d', 1
    elif kind == 'stockscan':
        expected = ['Ex/EFF Date', 'Type', 'Cash amount', 'Declaration date', 'Record date', 'Payment date']
        fmt, pay_index = '%m/%d/%Y', 5
    else:
        raise ValueError('unknown secondary distribution source')
    if not table.rows or table.rows[0] != expected:
        raise ValueError('secondary table headers changed')
    out = {}
    for row in table.rows[1:]:
        if len(row) != len(expected):
            continue
        ex = datetime.strptime(row[0], fmt).date()
        if not START.date() <= ex < END.date():
            continue  # never admit future estimated rows from these pages
        pay, amount = datetime.strptime(row[pay_index], fmt).date(), D(row[2].removeprefix('$'))
        if ex in out or pay < ex or not amount.is_finite() or amount <= 0:
            raise ValueError('invalid/duplicate secondary dividend')
        out[ex] = {'pay_date': str(pay), 'amount': str(amount)}
    return out


def reference(dataset, url, params, kind, symbol=None):
    """Verify the exact one-page exhausted request and original response bytes."""
    folder = ARCHIVE / 'raw/raw/alpaca' / dataset / RUN
    manifests = list(folder.glob('*/manifest.json'))
    if len(manifests) != 1:
        raise ValueError('missing/ambiguous reference archive')
    path = manifests[0]; manifest = json.loads(path.read_text())
    request = {'url': url, 'params': params}
    if manifest['request'] != request or sha(canonical(manifest).encode())[:24] != path.parent.name:
        raise ValueError('reference request identity changed')
    files = sorted(path.parent.glob('page-*.parquet'))
    if [p.name for p in files] != ['page-00000000.parquet']:
        raise ValueError('reference must have exactly one exhausted page')
    table = pq.ParquetFile(files[0]).read()
    if table.num_rows != 1 or not table.schema.equals(SCHEMA):
        raise ValueError('reference schema changed')
    row = table.to_pylist()[0]; payload = json.loads(row['response_json'], parse_float=D)
    if (row['request_json'] != canonical(request) or row['response_sha256'] != sha(row['response_json'].encode())
            or row['next_request_json'] is not None or payload['next_page_token'] is not None):
        raise ValueError('reference checksum/cursor changed')
    if kind == 'bars':
        if set(payload['bars']) != {symbol}: raise ValueError('reference symbol mismatch')
        values = payload['bars'][symbol]
    elif kind == 'trades': values = payload['trades']
    else: values = [r for rows in payload['corporate_actions'].values() for r in rows]
    if len(values) != row['record_count']:
        raise ValueError('reference row count mismatch')
    return {'path': str(files[0].relative_to(ROOT)), 'request': request,
        'response_sha256': row['response_sha256'], 'records': len(values)}, payload


def reconcile(bars, distributions):
    vendor = {b.date: b.dividend for b in bars if b.dividend}
    issuer = {k:v for k,v in distributions.items() if START.date() <= k < END.date()}
    conflicts = [{'ex_date': str(k), 'vendor': str(vendor[k]), 'issuer': str(issuer[k].amount)}
                 for k in sorted(vendor.keys() & issuer.keys()) if abs(vendor[k]-issuer[k].amount) > D('.0005')]
    return {'vendor_count': len(vendor), 'issuer_count': len(issuer),
        'missing_issuer_dates': list(map(str, sorted(vendor.keys()-issuer.keys()))),
        'issuer_only_dates': list(map(str, sorted(issuer.keys()-vendor.keys()))), 'amount_conflicts': conflicts,
        'rows': [{'ex_date': str(k), 'record_date': str(v.record_date), 'pay_date': str(v.pay_date), 'amount': str(v.amount)}
                 for k,v in sorted(issuer.items())]}


def audit():
    spy_receipt, spy = spy_source()
    calendar = load_equities(ROOT / 'data/equities/c04', 'c04-20261001')
    sources, bars, coverage = {}, {}, {}
    for symbol in UNIVERSE:
        sources[symbol], raw = load_source(ROOT / 'data/research/c03' / symbol, symbol)
        coverage[symbol] = inspect_source(raw, symbol, calendar.sessions)
        if not coverage[symbol]['coverage_ok']:
            raise ValueError('original source coverage no longer passes')
        _, bars[symbol] = parse_yahoo(raw.decode())
    evidence = {}
    m, raw = document(ROOT/'data/research/c06/ief-issuer-page', 'raw.html',
        'https://www.ishares.com/us/products/239456/ishares-7-10-year-treasury-bond-etf')
    evidence['IEF'] = m; ief = reconcile(bars['IEF'], ishares_distributions(raw.decode()))
    m, raw = document(ARCHIVE/'efa-issuer', 'raw.html', 'https://www.ishares.com/us/products/239623/ishares-msci-eafe-etf')
    evidence['EFA'] = m; efa = reconcile(bars['EFA'], efa_distributions(raw.decode()))
    m, raw = document(ARCHIVE/'vnq-distributions', 'raw.json',
        'https://advisors.vanguard.com/investments/products/api/funds/0986/pricing/distributions')
    evidence['VNQ'] = m; vnq = reconcile(bars['VNQ'], vanguard_distributions(raw.decode()))
    secondaries = {}
    for kind,url in [('dividendhistory','https://dividendhistory.org/payout/VNQ/'),
                     ('stockscan','https://stockscan.io/stocks/VNQ/dividend-history')]:
        meta, raw = document(ARCHIVE/('vnq-'+kind), 'raw.html', url)
        parsed = secondary_distributions(raw.decode(), kind)
        vendor = {b.date: b.dividend for b in bars['VNQ'] if b.dividend}
        secondaries[kind] = {'source': meta, 'rows': {str(k):v for k,v in parsed.items()},
            'missing_dates': list(map(str, sorted(vendor.keys()-parsed.keys()))),
            'amount_conflicts': [{'ex_date': str(k), 'vendor': str(v), 'secondary': parsed[k]['amount']}
                for k,v in vendor.items() if k in parsed and abs(v-D(parsed[k]['amount'])) > D('.0005')]}
    overlaps = {}
    for symbol in ('IEF', 'EFA', 'VNQ'):
        by_day = {b.date: b for b in bars[symbol]}
        overlaps[symbol] = {}
        for feed in ('sip', 'iex'):
            params = {'symbols': symbol, 'timeframe':'1Day','start':'2016-01-01T00:00:00Z',
                'end':'2026-10-01T00:00:00Z','adjustment':'raw','feed':feed,'limit':10000,'sort':'asc','asof':'-'}
            ref,payload = reference('bars_'+symbol+'_'+feed, 'https://data.alpaca.markets/v2/stocks/bars',params,'bars',symbol)
            seen, differences = set(), []
            for row in payload['bars'][symbol]:
                day = datetime.fromisoformat(row['t'].replace('Z','+00:00')).astimezone(NEW_YORK).date()
                if day in seen or day not in by_day: raise ValueError('invalid/duplicate reference date')
                seen.add(day)
                for field in ('open','close'):
                    value = D(row[field[0]])
                    if not value.is_finite() or value <= 0: raise ValueError('invalid independent price')
                    vendor = getattr(by_day[day],field)
                    if abs(vendor/value-1) <= D('.01'): continue
                    session = calendar.sessions[day]
                    at = session.opens_at if field == 'open' else session.closes_at
                    at = at.astimezone(NEW_YORK)
                    request = {'start':at.isoformat(),'end':(at+timedelta(seconds=10)).isoformat(),
                        'feed':'sip','asof':'-','sort':'asc','limit':10000}
                    proof,p = reference(f'auction_{symbol}_{day}_{field}',
                        f'https://data.alpaca.markets/v2/stocks/{symbol}/trades',request,'trades')
                    function = primary_opening_price if field == 'open' else primary_closing_price
                    primary = function(p['trades'],at,'P')
                    if abs(primary-vendor) > D('.005'): raise ValueError('unresolved primary price disagreement')
                    differences.append({'date':str(day),'field':field,'vendor':str(vendor),
                        'independent':str(value),'primary_arca':str(primary),'proof':proof,'resolved':True})
            missing = sorted(d for d in calendar.sessions if min(seen)<=d<=max(seen) and d not in seen)
            if feed == 'sip' and missing: raise ValueError('missing consolidated overlap sessions')
            overlaps[symbol][feed] = {'source':ref,'sessions':len(seen), 'first':str(min(seen)),
                'last':str(max(seen)), 'missing_overlap_sessions':list(map(str,missing)),
                'threshold':'0.01 unchanged','breaches':differences}
    action_ref, payload = reference('corporate_actions', 'https://data.alpaca.markets/v1/corporate-actions',
        {'symbols':'EFA,GLD,IEF,SPY,VNQ','start':'2006-01-01','end':'2026-09-30','limit':1000,'sort':'asc'},'actions')
    actions = payload['corporate_actions']
    if set(actions) != {'cash_dividends'}: raise ValueError('new noncash corporate action requires Amendment21 audit')
    failures = []
    for symbol, result in [('IEF',ief),('EFA',efa),('VNQ',vnq)]:
        if any(result[k] for k in ('missing_issuer_dates','issuer_only_dates','amount_conflicts')):
            failures.append({'symbol':symbol,'kind':'incomplete_issuer_distribution_inventory',
                'missing_dates':result['missing_issuer_dates'],'amount_conflicts':result['amount_conflicts']})
    if vnq['missing_issuer_dates']:
        failures.append({'symbol':'VNQ','kind':'secondary_evidence_insufficient_for_missing_issuer_rows',
            'reason':'DividendHistory 2006-12-22 amount 1.133 conflicts with Yahoo total 1.494; StockScan lacks all four 2006 payments and 2009-06-24. No documented complete-component cash/pay reconciliation for these rows. A latest-date rule cannot invent missing component evidence.'})
    identity = {'candidate':'C03-readmission-v1','original_sources':sources,
        'spy_source_receipt':spy_receipt['receipt_sha256'],'issuer_evidence':evidence,
        'overlaps':overlaps,'broker_action_source':action_ref,
        'secondary_sources':{k:v['source'] for k,v in secondaries.items()},
        'policy_sha256':sha((ROOT/'docs/research/24-c03-c04-readmission-plan.md').read_bytes()),
        'audit_code_sha256':sha(__import__('pathlib').Path(__file__).read_bytes())}
    split = HoldoutSplit('c03-readmission-v1:'+sha(canonical(identity).encode()), START, END)
    return {'status':'DATA_FAIL' if failures else 'SOURCE_INCOMPLETE_NOT_ADMITTED', 'identity':identity,
        'split':split.metadata(),'coverage':coverage,'distributions':{'IEF':ief,'EFA':efa,'VNQ':vnq},
        'secondary_evidence':secondaries,'failed_prerequisites':failures,
        'broker_actions':{'source':action_ref,'cash_count':len(actions['cash_dividends']),
            'noncash_events':0,'first_cash_ex_date':min(r['ex_date'] for r in actions['cash_dividends']),
            'coverage_caveat':'Request begins 2006; returned actions begin 2016. Not proof of complete pre-2016 action coverage.'},
        'gld_scope':'Original Yahoo has no distributions or splits; C05 independently repaired GLD 2008+ source remains reusable, but full C03 admission/action inventory is not claimed while VNQ fails.',
        'strategy_outcomes_inspected':False,'training_cases_attempted':0,'final_holdout_attempts':0,
        'original_failed_trial':3516,'pnl':None,'drawdown':None,'luck_p_value':None,'promotion':'none'}


def record_failure(result, commit):
    if result['status'] != 'DATA_FAIL': raise ValueError('not a failed source attempt')
    version = sha(canonical(result['identity']).encode())
    with session_scope() as session:
        prior = session.scalar(select(Trial).where(Trial.strategy_id==6030,
            Trial.params['source_audit_version'].astext==version))
        if prior is not None: return prior.id
        split = HoldoutSplit(result['split']['dataset_key'],START,END);register_split(session,split)
        row = Trial(strategy_id=6030,mode='backtest',status='failed',final_holdout=False,
            dataset_key=split.dataset_key,holdout_start=split.holdout_start,data_start=START,data_end=END,
            git_commit=commit,code_version='c03-source-readmission-v1',completed_ts=datetime.now(UTC),
            params={'stage':'data_quality_only_no_strategy_replay','source_audit_version':version,
                '_holdout':split.metadata(),'identity':result['identity']},
            metrics={'audit_result':'DATA_FAIL','failures':result['failed_prerequisites'],
                'training_cases_attempted':0,'final_holdout_attempts':0},
            notes='SPY amendment and IEF/EFA payments validated; seven EFA/VNQ price breaches reconciled. Older VNQ complete distribution/payment evidence unresolved. No rankings, signals, returns or holdout replay.')
        session.add(row);session.flush();return row.id


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--record-ledger',action='store_true');args=parser.parse_args()
    result=audit()
    if args.record_ledger:
        name=str(__import__('pathlib').Path(__file__).relative_to(ROOT))
        if subprocess.check_output(['git','status','--porcelain','--',name],cwd=ROOT).strip():
            raise ValueError('commit source audit before ledger receipt')
        commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
        result.update(data_failure_trial_id=record_failure(result,commit),audit_git_commit=commit)
    encoded=json.dumps(result,indent=2,sort_keys=True)+'\n'
    with CaptureDiskBudget(ROOT/'data').reserve(len(encoded.encode())*3+65536):
        (ARCHIVE/'c03-readmission-audit.json').write_text(encoded)
    (ROOT/'docs/research/24-c03-c04-c03-source.json').write_text(encoded)
    print(json.dumps({'status':result['status'],'trial':result.get('data_failure_trial_id'),
        'missing_vnq_issuer_dates':len(result['distributions']['VNQ']['missing_issuer_dates']),
        'training_cases_attempted':0,'final_holdout_attempts':0}))


if __name__ == '__main__': main()
