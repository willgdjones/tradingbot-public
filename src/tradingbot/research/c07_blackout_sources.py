"""C07 Amendment 21 source admission; no ranking or strategy replay."""
from __future__ import annotations

import argparse
from bisect import bisect_right
from datetime import date, datetime, timedelta
from decimal import Decimal as D
import json
import subprocess
from types import SimpleNamespace
from zipfile import ZipFile
import xml.etree.ElementTree as ET

import pyarrow.parquet as pq

from tradingbot.backtest.holdout import HoldoutSplit, json_value
from tradingbot.data.alpaca_history import NY
from tradingbot.data.archive import Request, SCHEMA, canonical
from tradingbot.data.c04_sources import NS
from tradingbot.data.disk_budget import CaptureDiskBudget
from tradingbot.data.equity_source_repair import primary_closing_price, primary_opening_price
from tradingbot.data.free_history import parse_yahoo
from tradingbot.data.xlf_action_amendment import checked_bytes, sha
from tradingbot.research.action_blackout import CorporateAction, plan_blackouts
from tradingbot.research.c05_blackout import actual_share_factor, compare_reference
from tradingbot.research.c06_sources import spy_source
from tradingbot.research.c07_source_audit import ROOT, START, END, UNIVERSE, PROOFS, load_sector
from tradingbot.research.c03_source_audit import inspect_source

ARCHIVE = ROOT / 'data/research/c07-blackout'
RUN = 'c07-amendment21-20261001'
WORKBOOK = 'data/equities/c04/sources/ssga-historical-distributions.xlsx'
WORKBOOK_SHA = '51a16a450298a663b3fa088883a17c75f4464e87c911b0e83902a0ad46877c54'
OPEN_CORRECTIONS = {('XLK', '2017-10-30'): '62.56', ('XLV', '2016-11-09'): '71.31'}
SPLIT_SYMBOLS = ('XLB', 'XLE', 'XLK', 'XLU', 'XLY')
ANNOUNCEMENTS = {
    'xlf-497-edgar-index.html': '529a352809e7331dfb48c7f389a687e7117353aa9b9dd9e2205f3bbfe1e5582f',
    'ssga-split-notice-2025-11-25.pdf': '4175a60cffdf8f1116da2652da5ccfece94cc1ede04bb11b2bb4543320c3a994',
}


def bars_request(symbol, feed, *, in_kind=False):
    if symbol not in (*UNIVERSE, 'XLRE') or feed not in ('sip', 'iex') or in_kind != (symbol == 'XLRE'):
        raise ValueError('unsupported reference scope')
    return Request('https://data.alpaca.markets/v2/stocks/bars', {
        'symbols': symbol, 'timeframe': '1Day',
        'start': '2016-09-19T00:00:00Z' if in_kind else '2006-01-01T00:00:00Z',
        'end': '2016-09-20T00:00:00Z' if in_kind else '2026-10-01T00:00:00Z',
        'adjustment': 'raw', 'feed': feed, 'limit': 10000, 'sort': 'asc', 'asof': '-'})


def action_request():
    return Request('https://data.alpaca.markets/v1/corporate-actions', {
        'symbols': ','.join(sorted(UNIVERSE)), 'start': '2006-01-01',
        'end': '2026-09-30', 'limit': 1000, 'sort': 'asc'})


def auction_request(symbol, session, field):
    if symbol not in (*UNIVERSE, 'XLRE') or field not in ('open', 'close'):
        raise ValueError('unsupported auction scope')
    stamp = datetime.fromisoformat(session['opens_at' if field == 'open' else 'closes_at'])
    if stamp.tzinfo is None:
        raise ValueError('naive auction timestamp')
    return Request(f'https://data.alpaca.markets/v2/stocks/{symbol}/trades', {
        'start': stamp.isoformat(), 'end': (stamp + timedelta(seconds=10)).isoformat(),
        'feed': 'sip', 'limit': 10000, 'sort': 'asc'})


def read_pages(archive, dataset, request, count):
    """Validate request, immutable bytes, schema, counts and exhausted cursor."""
    manifests = list((archive / 'raw/alpaca' / dataset / RUN).glob('*/manifest.json'))
    if len(manifests) != 1:
        raise ValueError('missing or ambiguous reference archive')
    path = manifests[0]
    manifest = json.loads(path.read_text())
    if (sha(canonical(manifest).encode())[:24] != path.parent.name
            or manifest['request'] != json.loads(request.to_json())
            or manifest['venue'] != 'alpaca' or manifest['dataset'] != dataset):
        raise ValueError('reference manifest identity mismatch')
    files = sorted(path.parent.glob('page-*.parquet'))
    if not files:
        raise ValueError('reference has no pages')
    output, receipts, seen = [], [], set()
    current = request
    for index, file in enumerate(files):
        if file.name != f'page-{index:08d}.parquet' or current is None:
            raise ValueError('reference has a gap or page after exhaustion')
        table = pq.ParquetFile(file).read()
        if table.num_rows != 1 or not table.schema.equals(SCHEMA):
            raise ValueError('reference page schema mismatch')
        row = table.to_pylist()[0]
        if (row['format_version'] != 1 or row['venue'] != 'alpaca' or row['dataset'] != dataset
                or row['page'] != index or row['request_json'] != current.to_json()
                or row['request_json'] in seen
                or row['response_sha256'] != sha(row['response_json'].encode())):
            raise ValueError('reference page identity or checksum mismatch')
        seen.add(row['request_json'])
        payload = json.loads(row['response_json'], parse_float=D)
        if 'next_page_token' not in payload or row['record_count'] != count(payload):
            raise ValueError('reference cursor or record count mismatch')
        token = payload['next_page_token']
        if token is not None and (not isinstance(token, str) or not token or not row['record_count']):
            raise ValueError('invalid reference continuation')
        following = Request(current.url, {**current.params, 'page_token': token}) if token else None
        if row['next_request_json'] != (following.to_json() if following else None):
            raise ValueError('reference pagination receipt disagrees with payload')
        receipts.append({'path': str(file.relative_to(archive)), 'response_sha256': row['response_sha256'],
                         'record_count': row['record_count'], 'retrieved_at': row['retrieved_at'].isoformat()})
        output.append(payload)
        current = following
    if current is not None:
        raise ValueError('reference pagination is incomplete')
    return {'manifest': manifest, 'pages': receipts}, output


def issuer_rows(path):
    """Read only relevant rows, with explicit zero and in-kind classifications."""
    with ZipFile(path) as z:
        strings = [''.join(n.text or '' for n in si.findall('.//s:t', NS)).strip()
                   for si in ET.fromstring(z.read('xl/sharedStrings.xml'))]
        records = []
        for row in ET.fromstring(z.read('xl/worksheets/sheet1.xml')).findall('.//s:row', NS):
            values = {}
            for cell in row.findall('s:c', NS):
                value = cell.find('s:v', NS)
                if value is not None:
                    col = ''.join(c for c in cell.attrib['r'] if c.isalpha())
                    values[col] = strings[int(value.text)] if cell.attrib.get('t') == 's' else value.text
            records.append((row, values))
    required = {'B': 'TICKER', 'D': 'EX-DATE', 'E': 'RECORD DATE', 'F': 'PAYABLE DATE',
                'G': 'DIVIDEND ($)', 'H': 'SHORT TERM CAPITAL GAIN ($)', 'I': 'LONG TERM CAPITAL GAIN ($)'}
    if any(' '.join(records[0][1].get(k, '').split()) != v for k, v in required.items()):
        raise ValueError('issuer worksheet headers changed')
    output, classified, seen = [], [], set()
    for row, values in records[1:]:
        symbol = values.get('B')
        if symbol not in UNIVERSE:
            continue
        ex = datetime.strptime(values['D'], '%m/%d/%Y').date()
        if not START.date() <= ex < END.date():
            continue
        record, pay = (datetime.strptime(values[k], '%m/%d/%Y').date() for k in ('E', 'F'))
        amount = sum((D(values.get(k, '0').replace(',', '').strip() or '0') for k in ('G', 'H', 'I')), D(0))
        if ((symbol, ex) in seen or row.findall('.//s:f', NS) or not ex <= record <= pay
                or not amount.is_finite() or amount < 0):
            raise ValueError('invalid, formula or duplicate issuer row')
        seen.add((symbol, ex))
        item = {'symbol': symbol, 'ex_date': str(ex), 'record_date': str(record),
                'pay_date': str(pay), 'amount': str(amount)}
        if amount == 0:
            if symbol != 'XLK' or str(ex) not in ('2006-06-16', '2007-03-16'):
                raise ValueError('unexpected zero distribution')
            classified.append({**item, 'kind': 'zero_distribution'})
        elif symbol == 'XLF' and str(ex) == '2016-09-19':
            if amount != D('.139146') or str(record) != '2016-09-21' or str(pay) != '2016-09-22':
                raise ValueError('XLF in-kind issuer units/dates changed')
            classified.append({**item, 'kind': 'XLRE_units_not_cash'})
        else:
            output.append(item)
    if len(classified) != 3 or {r['symbol'] for r in output} != set(UNIVERSE):
        raise ValueError('issuer inventory changed')
    return sorted(output, key=lambda r: (r['ex_date'], r['symbol'])), classified


def cash_audit(allbars, broker, sessions, root=ROOT):
    checked_bytes(root / WORKBOOK, WORKBOOK_SHA)
    distributions, classified = issuer_rows(root / WORKBOOK)
    lookup = {(r['symbol'], r['ex_date']): r for r in distributions}
    expected = {(s, str(b.date)) for s, bars in allbars.items() for b in bars if b.dividend}
    if set(lookup) != expected:
        raise ValueError('ordinary issuer and Yahoo ex-date inventory differs')
    differences = []
    for s, bars in allbars.items():
        splits = [(b.date, b.split_ratio) for b in bars if b.split_ratio != 1]
        for b in bars:
            if not b.dividend:
                continue
            actual = b.dividend * actual_share_factor(b.date, splits)
            issuer = D(lookup[s, str(b.date)]['amount'])
            if actual != issuer:
                differences.append({'symbol': s, 'ex_date': str(b.date), 'yahoo_actual': str(actual),
                                    'issuer': str(issuer), 'material_over_001': abs(actual-issuer) > D('.001')})
    broker_issues, broker_rounding, unique, duplicate_count = [], [], {}, 0
    for row in broker['cash_dividends']:
        key = (row['symbol'], row['ex_date'])
        if key == ('XLF', '2016-09-19'):
            if D(row['rate']) != D('.139146'):
                raise ValueError('unexpected broker XLF action')
            continue
        if key not in lookup:
            raise ValueError('broker ordinary ex-date absent from issuer source')
        issuer = lookup[key]
        if D(row['rate']).quantize(D('.000001')) != D(issuer['amount']):
            raise ValueError('broker and issuer ordinary cash amount conflict')
        if D(row['rate']) != D(issuer['amount']):
            broker_rounding.append({'symbol': key[0], 'ex_date': key[1],
                'broker_rate': str(row['rate']), 'issuer_amount': issuer['amount']})
        if key in unique:
            duplicate_count += 1
        unique.setdefault(key, []).append(row)
        if row.get('payable_date') != issuer['pay_date'] or row.get('record_date') != issuer['record_date']:
            broker_issues.append({'symbol': key[0], 'ex_date': key[1],
                'broker_id': row['id'], 'broker_record': row.get('record_date'),
                'broker_payable': row.get('payable_date'), 'issuer_record': issuer['record_date'],
                'issuer_payable': issuer['pay_date']})
    days = [date.fromisoformat(r['date']) for r in sessions]
    for r in distributions:
        # Conservative written amendment: latest documented payment, then next open.
        documented = [r['pay_date']] + [v['payable_date'] for v in unique.get((r['symbol'], r['ex_date']), []) if v.get('payable_date')]
        endpoint = max(documented)
        index = bisect_right(days, date.fromisoformat(endpoint))
        r['cash_endpoint'] = endpoint
        r['cash_release'] = sessions[index]['opens_at'] if index < len(sessions) else None
    return {'workbook': {'path': WORKBOOK, 'sha256': WORKBOOK_SHA}, 'distributions': distributions,
        'classified_non_cash_rows': classified, 'yahoo_amount_reconciliations': differences,
        'broker_date_disagreements_or_missing': broker_issues,
        'broker_six_decimal_rounding': broker_rounding,
        'broker_ordinary_unique': len(unique), 'broker_duplicate_ordinary_rows': duplicate_count,
        'policy': 'Issuer amounts/dates govern ordinary cash; latest documented pay date then next regular open. No process-date proxy or double credit.'}


def action_audit(allbars, broker, sessions, root=ROOT):
    expected = {('XLF', '2016-09-19'): D('1.231'), **{(s, '2025-12-05'): D(2) for s in SPLIT_SYMBOLS}}
    actual = {(s, str(b.date)): b.split_ratio for s, bars in allbars.items() for b in bars if b.split_ratio != 1}
    if actual != expected or set(broker) != {'cash_dividends', 'forward_splits'}:
        raise ValueError('noncash action inventory changed')
    if {(r['symbol'], r['ex_date'], D(r['new_rate']) / D(r['old_rate'])) for r in broker['forward_splits']} != {(s, '2025-12-05', D(2)) for s in SPLIT_SYMBOLS}:
        raise ValueError('broker split inventory changed')
    sources = {}
    for name, digest in ANNOUNCEMENTS.items():
        path = root / 'data/equities/c02/amendment21-evidence' / name
        raw = checked_bytes(path, digest)
        sources[name] = {'path': str(path.relative_to(root)), 'sha256': digest}
        if name.endswith('.html') and b'2016-09-01' not in raw:
            raise ValueError('XLF filing date absent')
    pdf = root / sources['ssga-split-notice-2025-11-25.pdf']['path']
    text = subprocess.check_output(['pdftotext', '-layout', str(pdf), '-'], text=True)
    if any(t not in text for t in ('November 20, 2025', 'December 2, 2025', 'December 4, 2025', 'December 5, 2025', *SPLIT_SYMBOLS)):
        raise ValueError('issuer split announcement anchors absent')
    # Preserve and verify the earlier primary in-kind terms; only its fraction gate is superseded.
    proof = json.loads(checked_bytes(root / 'docs/research/17-xlf-action-amendment.json', PROOFS['docs/research/17-xlf-action-amendment.json']))
    for source in proof['sources'].values():
        checked_bytes(root / source['path'], source['sha256'])
    actions = [CorporateAction('XLF', 'in_kind_distribution', date(2016, 9, 1), date(2016, 9, 19), date(2016, 9, 22), 'issuer497_and_annual')]
    actions += [CorporateAction(s, 'split', date(2025, 11, 20), date(2025, 12, 5), date(2025, 12, 5), 'issuerFAQ_effective_endpoint') for s in SPLIT_SYMBOLS]
    plans = []
    for plan in plan_blackouts(actions, sessions):
        a = plan.action
        plans.append({'symbol': a.symbol, 'kind': a.kind, 'announced': str(a.announced),
            'ex_date': str(a.ex_date), 'actual_payable': '2025-12-04' if a.kind == 'split' else str(a.payable),
            'research_end': str(a.payable), 'decision': str(plan.decision), 'exit': str(plan.exit),
            'reentry': str(plan.reentry), 'source': a.source, 'endpoint_is_broker_credit': False,
            'blackout_sessions': [str(d) for d in sessions if plan.exit <= d < plan.reentry]})
    return {'sources': sources, 'plans': plans,
        'xlf_treatment': 'Undo vendor 1.231 normalization for actual-share prices only; XLF share count does not change. Flat through distribution.'}


def price_audit(archive=ARCHIVE, root=ROOT):
    source_proof = json.loads(checked_bytes(root / 'docs/research/12-c02-source-audit.json', PROOFS['docs/research/12-c02-source-audit.json']))
    spy_receipt, spy = spy_source(root)
    sessions = {r['date']: r for r in spy['prices']}
    calendar = {date.fromisoformat(r['date']): SimpleNamespace(closes_at=datetime.fromisoformat(r['closes_at'])) for r in spy['prices']}
    output, allbars, failures = {}, {}, []
    for symbol in UNIVERSE:
        source, raw = load_sector(root / 'data/equities/c02/sources' / symbol, symbol, source_proof['identity']['yahoo_sha256'][symbol])
        coverage = inspect_source(raw, symbol, calendar)
        if not coverage['coverage_ok']:
            raise ValueError('original sector coverage no longer passes')
        _, bars = parse_yahoo(raw.decode())
        refs, required = {}, set()
        for feed in ('sip', 'iex'):
            def count(p):
                if set(p['bars']) != {symbol}:
                    raise ValueError('reference symbol mismatch')
                return len(p['bars'][symbol])
            ref, pages = read_pages(archive, f'bars_{symbol}_{feed}', bars_request(symbol, feed), count)
            rows = [r for p in pages for r in p['bars'][symbol]]
            diag = compare_reference(bars, rows, feed=feed)
            required.update((r['date'], r['field']) for r in diag['differences_over_1pct'] if not r['diagnostic_only'])
            refs[feed] = ref, rows
        proofs, auctions = {}, []
        for day, field in sorted(required):
            req = auction_request(symbol, sessions[day], field)
            ref, pages = read_pages(archive, f'auction_{symbol}_{day}_{field}', req, lambda p: len(p['trades']))
            trades = [r for p in pages for r in p['trades']]
            parser = primary_opening_price if field == 'open' else primary_closing_price
            proof = parser(trades, datetime.fromisoformat(req.params['start']), 'P')
            proofs[date.fromisoformat(day), field] = proof
            auctions.append({'date': day, 'field': field, 'primary': str(proof), 'source': ref})
        comparisons = {}
        for feed, (ref, rows) in refs.items():
            comparison = compare_reference(bars, rows, feed=feed, primary=proofs)
            comparisons[feed] = {'source': ref, **comparison}
            failures += [{'symbol': symbol, 'feed': feed, **r} for r in comparison['failures']]
        output[symbol] = {'source': source, 'coverage': coverage, 'references': comparisons, 'auctions': auctions}
        allbars[symbol] = bars
    if len(failures) != 2 or {(r['symbol'], r['date']) for r in failures} != set(OPEN_CORRECTIONS):
        raise ValueError('price conflicts differ from exact source amendment')
    for r in failures:
        if r['field'] != 'open' or r['feed'] != 'sip' or D(r['primary']) != D(OPEN_CORRECTIONS[r['symbol'], r['date']]):
            raise ValueError('correction lacks primary auction evidence')
    return {'sources': output, 'amended_conflicts': failures}, allbars, spy_receipt, spy


def in_kind_valuation(archive, session):
    raw = (archive / 'xlre-exdate/raw.json').read_bytes()
    receipt = json.loads((archive / 'xlre-exdate/manifest.json').read_text())
    if sha(raw) != receipt['sha256'] or receipt['symbol'] != 'XLRE':
        raise ValueError('XLRE source identity mismatch')
    meta, bars = parse_yahoo(raw.decode())
    if meta['null_rows'] or len(bars) != 1 or bars[0].date != date(2016, 9, 19) or bars[0].split_ratio != 1:
        raise ValueError('XLRE ex-date valuation source changed')
    req = auction_request('XLRE', session, 'close')
    proof, pages = read_pages(archive, 'inkind_XLRE_primary_close', req, lambda p: len(p['trades']))
    primary = primary_closing_price([r for p in pages for r in p['trades']], datetime.fromisoformat(req.params['start']), 'P')
    daily, pages = read_pages(archive, 'inkind_XLRE_sip', bars_request('XLRE', 'sip', in_kind=True), lambda p: len(p['bars']['XLRE']))
    daily_rows = [r for p in pages for r in p['bars']['XLRE']]
    if len(daily_rows) != 1 or abs(bars[0].close / primary - 1) > D('.000001') or D(daily_rows[0]['c']) != primary:
        raise ValueError('XLRE ex-close does not reconcile')
    return {'symbol': 'XLRE', 'date': '2016-09-19', 'close': str(primary), 'ratio': '0.139146',
        'economic_value_per_xlf_share': str(primary * D('.139146')), 'yahoo': receipt,
        'primary_auction': proof, 'daily_reference': daily,
        'use': 'Economic total-return signal only, no cash credit, position or ranked asset.'}


def audit(archive=ARCHIVE, root=ROOT):
    prices, bars, spy_receipt, spy = price_audit(archive, root)
    broker_ref, pages = read_pages(archive, 'corporate_actions', action_request(), lambda p: sum(len(v) for v in p['corporate_actions'].values()))
    broker = {}
    for page in pages:
        for kind, rows in page['corporate_actions'].items():
            broker.setdefault(kind, []).extend(rows)
    cash = cash_audit(bars, broker, spy['prices'], root)
    days = [date.fromisoformat(r['date']) for r in spy['prices']]
    actions = action_audit(bars, broker, days, root)
    ink = in_kind_valuation(archive, next(r for r in spy['prices'] if r['date'] == '2016-09-19'))
    return json_value({'candidate': 'C07-amendment21', 'status': 'SOURCE_CHECKS_PASSED_NOT_FROZEN',
        'prices': prices, 'cash': cash, 'actions': actions, 'in_kind_signal': ink,
        'broker_reference': broker_ref, 'spy_receipt': spy_receipt['receipt_sha256'],
        'sessions': len(days), 'strategy_outcomes_inspected': False,
        'training_cases_attempted': 0, 'final_holdout_attempts': 0})


def freeze_source(archive=ARCHIVE, root=ROOT):
    result = audit(archive, root)
    _, spy = spy_source(root)
    by_symbol, normalizations = {}, {}
    for symbol in UNIVERSE:
        source = result['prices']['sources'][symbol]['source']
        raw_source = checked_bytes(root / f'data/equities/c02/sources/{symbol}/raw.json', source['sha256'])
        _, bars = parse_yahoo(raw_source.decode())
        by_symbol[symbol] = {b.date: b for b in bars}
        normalizations[symbol] = [(b.date, b.split_ratio) for b in bars if b.split_ratio != 1]
    distributions = result['cash']['distributions']
    cash = {(r['symbol'], r['ex_date']): r['amount'] for r in distributions}
    spy_cash = {r['ex_date']: r['amount'] for r in spy['distributions']}
    prices = []
    for ref in spy['prices']:
        day, quotes = date.fromisoformat(ref['date']), {}
        for symbol in UNIVERSE:
            bar = by_symbol[symbol][day]
            factor = actual_share_factor(day, normalizations[symbol])
            spin = symbol == 'XLF' and ref['date'] == '2016-09-19'
            quotes[symbol] = {
                'open': OPEN_CORRECTIONS.get((symbol, ref['date']), str(bar.open * factor)),
                'close': str(bar.close * factor),
                'split_ratio': '1' if spin else str(bar.split_ratio),
                'signal_distribution': cash.get((symbol, ref['date']), '0'),
                'in_kind_signal_value': result['in_kind_signal']['economic_value_per_xlf_share'] if spin else '0',
            }
        prices.append({**ref, 'spy_close': ref['close'],
                       'spy_distribution': spy_cash.get(ref['date'], '0'), 'quotes': quotes})
    data = {'prices': prices, 'distributions': distributions, 'blackouts': result['actions']['plans']}
    raw = (json.dumps(data, sort_keys=True, indent=2) + '\n').encode()
    amendment = (root / 'docs/research/24-c07-blackout.md').read_bytes()
    identity = {'source_audit_sha256': sha(canonical(result).encode()), 'data_sha256': sha(raw),
        'amendment_sha256': sha(amendment), 'source_start': START.isoformat(), 'source_end_exclusive': END.isoformat(),
        'policy': 'C07 report24 pre-outcome source precedence, exact opening corrections, economic in-kind signal and conservative cash; Amendment21'}
    paths = ['research/c07_blackout_sources.py', 'research/c07_source_audit.py', 'research/c03_source_audit.py',
             'research/c05_blackout.py', 'research/c06_sources.py', 'research/action_blackout.py',
             'data/free_history.py', 'data/equity_source_repair.py', 'data/c04_sources.py']
    split = HoldoutSplit('c07-amendment21-' + sha(canonical(identity).encode())[:40], START, END)
    receipt = {**result, 'status': 'SOURCE_ADMITTED_NO_STRATEGY_OUTCOMES', 'identity': identity,
        'split': split.metadata(), 'source_code_sha256': {'src/tradingbot/' + p: sha((root / 'src/tradingbot' / p).read_bytes()) for p in paths}}
    receipt['receipt_sha256'] = sha(canonical(receipt).encode())
    encoded = (json.dumps(receipt, sort_keys=True, indent=2) + '\n').encode()
    with CaptureDiskBudget(root / 'data').reserve(3 * (len(raw) + len(encoded)) + 65536):
        directory = archive / 'frozen-source-v1'
        directory.mkdir(exist_ok=False)
        (directory / 'data.json').write_bytes(raw)
        (directory / 'manifest.json').write_bytes(encoded)
        (directory / 'source-amendment.md').write_bytes(amendment)
    (root / 'docs/research/24-c07-blackout-source.json').write_bytes(encoded)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--freeze', action='store_true')
    args = parser.parse_args()
    result = freeze_source() if args.freeze else audit()
    raw = json.dumps(result, indent=2, sort_keys=True) + '\n'
    with CaptureDiskBudget(ROOT / 'data').reserve(3 * len(raw.encode()) + 65536):
        (ARCHIVE / 'source-progress.json').write_text(raw)
    (ROOT / 'docs/research/24-c07-blackout-source-progress.json').write_text(raw)
    print(json.dumps({'status': result['status'], 'sessions': result['sessions'],
        'ordinary_dividends': len(result['cash']['distributions']),
        'price_corrections': len(result['prices']['amended_conflicts'])}))


if __name__ == '__main__':
    main()
