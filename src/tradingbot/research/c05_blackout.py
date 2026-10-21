"""Source-only C05 Amendment 21 re-attempt. Never computes strategy returns."""
from __future__ import annotations

import argparse
from bisect import bisect_left, bisect_right
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
import json
from pathlib import Path
import re

import pyarrow.parquet as pq

from tradingbot.backtest.holdout import HoldoutSplit, json_value
from tradingbot.data.alpaca_history import NY
from tradingbot.data.archive import Request, SCHEMA, canonical
from tradingbot.data.disk_budget import CaptureDiskBudget
from tradingbot.data.equity_source_repair import primary_closing_price, primary_opening_price
from tradingbot.data.free_history import parse_yahoo
from tradingbot.research.c05_commodity_trend import (
    ARCHIVE as ORIGINAL, END, ROOT, START, UNIVERSE, VARIANTS, inspect_source,
    load_source, load_document, document_text, sha,
)
from tradingbot.research.c06_sources import spy_source
from tradingbot.research.equity_data import load_equities

ARCHIVE = ROOT / 'data/research/c05-blackout'
RUN = 'c05-amendment21-20261001'
DATA_URL = 'https://data.alpaca.markets/v2/stocks/bars'
ACTION_URL = 'https://data.alpaca.markets/v1/corporate-actions'
REFERENCE_BOUND = D('.01')
PRIMARY_MATCH = D('.000001')

# C05-local, written in report 23 before outcomes. Raw captures never change.
OPEN_CORRECTIONS = {
    ('GLD', '2016-08-12'): '129.10', ('USO', '2016-11-30'): '10.68',
    ('USO', '2017-01-12'): '11.61', ('USO', '2017-02-09'): '11.38',
    ('USO', '2017-10-30'): '10.90', ('UNG', '2017-02-09'): '7.96',
}
EXTRACTS = {
    'slv-2008-dba-2025': 'f2b4328a2fb07c444e634eeae036eb987101f8c107bd864e75c32499ba212641',
    'qualified-2022-2024': 'e9a795af41129f306f58c890495b31ad6297c52ec92ec9d03620968fc98eebc3',
    'annual-2008-2018-2019': '2353f47f3690ecefde68f4ad451f24d5f4aec32cebaa2a0525e2ebd46a4c1eec',
    'qualified-2023': '4053a57e108bd2103e18127ef3a276502e9fae5c1830ea6b8592b56440c0aec3',
    'nyse-ex-date-rule': '9556f41ea8690621657b0a33842742bf6a3fb3dc686d955e5f33455edcf70130',
}
ACTION_SPECS = (
    ('SLV', '2008-07-11', '2008-07-24', '2008-07-23', '2008-07-23', '2008-07-28', '10', None, None),
    ('UNG', '2011-02-16', '2011-03-09', '2011-03-08', None, None, '.5',
     'ung-2011-issuer-release', '064da32cd64db348570cc9f57789373df4629d5342bb78a50bf38ac59770e0d0'),
    ('UNG', '2012-02-01', '2012-02-22', '2012-02-21', None, None, '.25',
     'ung-2012-split', '15f1a0b2140820bdfb3df689e2e0b11226811f8019c523c3259fbe4981dc8ed5'),
    ('UNG', '2017-12-22', '2018-01-05', '2018-01-04', None, None, '.25',
     'ung-2018-issuer-release', 'f87ab9b9823b263a7ba87a2296be5222699f03c6afbd108baf018ec2064f1385'),
    ('USO', '2020-04-22', '2020-04-29', '2020-04-28', '2020-04-29', None, '.125',
     'uso-2020-issuer-release', 'f6c45b79216bc0139f6819482a127bc68eb310915b4932ce2cee79cd0ec34364'),
    ('UNG', '2024-01-05', '2024-01-24', '2024-01-23', '2024-01-24', None, '.25',
     'ung-2024-issuer-release', '0de166188d2f4dbb62c72812094c21bb3ae89337c04f26641f9a67ba417b9238'),
)
DIVIDENDS = (
    ('2008-12-15', '2008-12-17', '2008-12-30', '.45'),
    ('2018-12-24', '2018-12-26', '2018-12-31', '.17994'),
    ('2019-12-23', '2019-12-24', '2019-12-31', '.25717'),
    ('2022-12-19', '2022-12-20', '2022-12-23', '.09643'),
    ('2023-12-18', '2023-12-19', '2023-12-22', '.96045'),
    ('2024-12-23', '2024-12-23', '2024-12-27', '1.08408'),
    ('2025-12-22', '2025-12-22', '2025-12-26', '.91237'),
)


def bars_request(symbol, feed):
    if symbol not in UNIVERSE or feed not in ('sip', 'iex'):
        raise ValueError('outside the fixed source universe or feeds')
    return Request(DATA_URL, {'symbols': symbol, 'timeframe': '1Day',
        'start': '2008-01-01T00:00:00Z', 'end': '2026-10-01T00:00:00Z',
        'adjustment': 'raw', 'feed': feed, 'limit': 10000, 'sort': 'asc', 'asof': '-'})


def action_request():
    return Request(ACTION_URL, {'symbols': ','.join(sorted(UNIVERSE)),
        'start': '2008-01-01', 'end': '2026-09-30', 'limit': 1000, 'sort': 'asc'})


def read_pages(archive, dataset, request, count):
    """Verify schema, request chain, bytes, counts and exhausted pagination."""
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


def actual_share_factor(day, splits):
    """Undo every *later* Yahoo split adjustment; never convert ex-date twice."""
    seen, factor = set(), D(1)
    for ex, ratio in splits:
        if ex in seen or not ratio.is_finite() or ratio <= 0 or ratio == 1:
            raise ValueError('invalid or duplicate split conversion')
        seen.add(ex)
        if day < ex:
            factor *= ratio
    return factor


def compare_reference(bars, reference, *, feed, primary=None):
    """Report all source differences. Confirmed bad opens remain unresolved here."""
    if feed not in ('sip', 'iex') or not reference:
        raise ValueError('missing or unsupported reference feed')
    primary = primary or {}
    by_date = {b.date: b for b in bars}
    if len(by_date) != len(bars):
        raise ValueError('duplicate vendor bar dates')
    splits = [(b.date, b.split_ratio) for b in bars if b.split_ratio != 1]
    seen, differences, failures = set(), [], []
    worst = {'open': D(0), 'close': D(0)}
    for other in reference:
        stamp = datetime.fromisoformat(other['t'].replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            raise ValueError('reference timestamp must be aware')
        day = stamp.astimezone(NY).date()
        if day not in by_date or day in seen:
            raise ValueError('unexpected or duplicate reference date')
        seen.add(day)
        factor = actual_share_factor(day, splits)
        for field in ('open', 'close'):
            other_price = D(str(other[field[0]]))
            if not other_price.is_finite() or other_price <= 0:
                raise ValueError('invalid reference price')
            actual = getattr(by_date[day], field) * factor
            gap = abs(actual / other_price - 1)
            worst[field] = max(worst[field], gap)
            if gap <= REFERENCE_BOUND:
                continue
            proof = primary.get((day, field))
            if proof is not None and (not proof.is_finite() or proof <= 0):
                raise ValueError('invalid primary auction proof')
            resolved = proof is not None and abs(actual / proof - 1) <= PRIMARY_MATCH
            diagnostic = feed == 'iex' and field == 'open'
            record = {'date': str(day), 'field': field, 'yahoo_actual_share': str(actual),
                'reference': str(other_price), 'relative_difference': str(gap),
                'primary': str(proof) if proof is not None else None,
                'primary_confirms_yahoo': resolved, 'diagnostic_only': diagnostic}
            differences.append(record)
            if not diagnostic and not resolved:
                failures.append(record)
    inside_missing = sorted(d for d in by_date if min(seen) <= d <= max(seen) and d not in seen)
    if feed == 'sip' and inside_missing:
        failures.append({'missing_overlap_sessions': list(map(str, inside_missing))})
    return {'sessions': len(seen), 'first': str(min(seen)), 'last': str(max(seen)),
        'missing_overlap_sessions': list(map(str, inside_missing)),
        'uncovered_source_sessions': len(by_date.keys() - seen),
        'worst_relative_difference': {k: str(v) for k, v in worst.items()},
        'differences_over_1pct': differences, 'failures': failures}


def auction_request(symbol, row, field):
    if symbol not in UNIVERSE or field not in ('open', 'close'):
        raise ValueError('invalid auction reference')
    stamp = datetime.fromisoformat(row['opens_at' if field == 'open' else 'closes_at'])
    if stamp.tzinfo is None:
        raise ValueError('auction boundary must be aware')
    return Request(f'https://data.alpaca.markets/v2/stocks/{symbol}/trades', {
        'start': stamp.isoformat(), 'end': (stamp + timedelta(seconds=10)).isoformat(),
        'feed': 'sip', 'limit': 10000, 'sort': 'asc'})


def price_audit(archive=ARCHIVE):
    calendar = load_equities(ROOT / 'data/equities/c04', 'c04-20261001')
    spy_receipt, spy_data = spy_source()
    sessions = {r['date']: r for r in spy_data['prices'] if START.date().isoformat() <= r['date'] < END.date().isoformat()}
    output, failures = {}, []
    for symbol in UNIVERSE:
        receipt, raw = load_source(ORIGINAL / symbol, symbol)
        if receipt['status_code'] != 200:
            raise ValueError('original source is not a successful response')
        coverage = inspect_source(raw, symbol, calendar.sessions)
        if not coverage['coverage_ok']:
            raise ValueError('original source coverage no longer passes')
        _, bars = parse_yahoo(raw.decode())
        refs, required = {}, set()
        for feed in ('sip', 'iex'):
            def count(payload):
                if set(payload['bars']) != {symbol}:
                    raise ValueError('reference symbol mismatch')
                return len(payload['bars'][symbol])
            ref, pages = read_pages(archive, f'bars_{symbol}_{feed}', bars_request(symbol, feed), count)
            rows = [row for page in pages for row in page['bars'][symbol]]
            diagnostic = compare_reference(bars, rows, feed=feed)
            required.update((date.fromisoformat(d['date']), d['field']) for d in
                            diagnostic['differences_over_1pct'] if not d['diagnostic_only'])
            refs[feed] = (ref, rows)
        proofs, auctions = {}, []
        for day, field in sorted(required):
            dataset = f'auction_{symbol}_{day}_{field}'
            request = auction_request(symbol, sessions[str(day)], field)
            ref, pages = read_pages(archive, dataset, request, lambda p: len(p['trades']))
            trades = [row for p in pages for row in p['trades']]
            stamp = datetime.fromisoformat(request.params['start'])
            parser = primary_opening_price if field == 'open' else primary_closing_price
            proof = parser(trades, stamp, 'P')
            proofs[(day, field)] = proof
            auctions.append({'date': str(day), 'field': field, 'primary_exchange': 'P / NYSE Arca',
                             'price': str(proof), 'source': ref})
        comparisons = {}
        for feed, (ref, rows) in refs.items():
            comparison = compare_reference(bars, rows, feed=feed, primary=proofs)
            comparisons[feed] = {'source': ref, **comparison}
            failures.extend({'symbol': symbol, 'feed': feed, **failure} for failure in comparison['failures'])
        output[symbol] = {'source': receipt, 'coverage': coverage, 'references': comparisons,
                          'primary_auctions': auctions}
    return {'sources': output, 'failures': failures, 'price_corrections': [],
        'calendar_receipt': spy_receipt['receipt_sha256'],
        'policy': 'Undo later splits for actual-share prices. SIP open/close and IEX close bound 1%; '
                  'IEX opens diagnostic only. Primary Arca O/Q and 6/M prints in fixed ten seconds '
                  'may confirm Yahoo. Conflicts require a written source amendment before outcomes.'}


def broker_action_audit(archive=ARCHIVE):
    ref, pages = read_pages(archive, 'corporate_actions', action_request(),
                           lambda p: sum(len(rows) for rows in p['corporate_actions'].values()))
    groups = {}
    for page in pages:
        for kind, rows in page['corporate_actions'].items():
            groups.setdefault(kind, []).extend(rows)
    ids = [r['id'] for rows in groups.values() for r in rows]
    if len(set(ids)) != len(ids) or any(r['symbol'] not in UNIVERSE for rows in groups.values() for r in rows):
        raise ValueError('duplicate or out-of-universe broker action')
    return {'source': ref, 'actions': groups,
        'limitations': 'Missing action/payable fields are not inferred from process or ex dates; '
                       'the 2018 DBA duplicate ex-date requires issuer reconciliation.'}


def audit(archive=ARCHIVE):
    prices = price_audit(archive)
    actions = broker_action_audit(archive)
    identity = {'candidate': 'C05-amendment21', 'start': START.isoformat(),
                'end_exclusive': END.isoformat(), 'universe': list(UNIVERSE), 'variants': list(VARIANTS),
                'source_sha256': {s: v['source']['sha256'] for s, v in prices['sources'].items()}}
    split = HoldoutSplit('c05-amendment21-source:' + sha(canonical(identity).encode()), START, END)
    return {'candidate': 'C05', 'bead': 'tradingbot-qdd', 'stage': 'source-review-in-progress',
        'generated_at': datetime.now(UTC).isoformat(), 'identity': identity, 'split': split.metadata(),
        'prices': prices, 'broker_actions': actions, 'source_admitted': False,
        'training_cases_attempted': 0, 'final_holdout_attempts': 0,
        'strategy_outcomes_inspected': False, 'prior_failure': {'trial': 3518, 'strategy': 6032},
        'promotion': 'none'}


def extracted_evidence(archive=ARCHIVE):
    receipts, texts = {}, {}
    for key, expected in EXTRACTS.items():
        directory = archive / 'provider-evidence' / key
        receipt = json.loads((directory / 'manifest.json').read_text())
        raw = (directory / 'retrieved-text.txt').read_bytes()
        if sha(raw) != expected or receipt['sha256'] != expected or receipt['bytes'] != len(raw):
            raise ValueError('primary extracted evidence changed')
        receipts[key], texts[key] = receipt, ' '.join(raw.decode().split())
    return receipts, texts


def local_blackout(*, symbol, announced, ex_date, effective, payable, delivery, sessions):
    """Keep the research endpoint separate from the nullable actual payable."""
    if sessions != sorted(set(sessions)) or announced > ex_date or effective > ex_date:
        raise ValueError('invalid action or calendar')
    end = max(d for d in (ex_date, effective, payable, delivery) if d is not None)
    before, after = bisect_left(sessions, ex_date), bisect_right(sessions, end)
    if before < 2 or after >= len(sessions) or announced > sessions[before - 2]:
        raise ValueError('action cannot be avoided with a prior-close decision')
    return {'symbol': symbol, 'announced': str(announced), 'ex_date': str(ex_date),
        'effective': str(effective), 'actual_payable': str(payable) if payable else None,
        'expected_delivery': str(delivery) if delivery else None, 'research_end': str(end),
        'decision': str(sessions[before-2]), 'exit': str(sessions[before-1]),
        'reentry': str(sessions[after]), 'endpoint_is_broker_credit': False,
        'blackout_sessions': [str(d) for d in sessions if sessions[before-1] <= d < sessions[after]]}


def reconcile_actions(prices, broker, sessions, texts):
    sources, plans = {}, []
    expected_splits = {(s, ex): D(ratio) for s, _, ex, _, _, _, ratio, _, _ in ACTION_SPECS}
    actual_splits = {(s, r['date']): D(r['ratio']) for s, v in prices['sources'].items()
                     for r in v['coverage']['split_events']}
    if actual_splits != expected_splits:
        raise ValueError('split inventory differs from reviewed primary events')
    groups = broker['actions']
    if set(groups) != {'cash_dividends', 'reverse_splits'}:
        raise ValueError('unexpected broker action kind')
    expected_broker = {('UNG', '2018-01-05'), ('UNG', '2024-01-24'), ('USO', '2020-04-29')}
    if {(r['symbol'], r['ex_date']) for r in groups['reverse_splits']} != expected_broker:
        raise ValueError('broker split inventory changed')
    for row in groups['reverse_splits']:
        if D(row['new_rate']) / D(row['old_rate']) != expected_splits[(row['symbol'], row['ex_date'])]:
            raise ValueError('broker split ratio differs from issuer')
        if row.get('payable_date') != (None if row['ex_date'] == '2018-01-05' else row['ex_date']):
            raise ValueError('broker split payable changed')
    for symbol, ann, ex, effective, pay, delivery, ratio, key, expected in ACTION_SPECS:
        if key:
            receipt, raw = load_document(ORIGINAL / 'documents' / key, key)
            published = re.findall(r'"datePublished"\s*:\s*"([^"]+)"', raw.decode())
            if receipt['status_code'] != 200 or receipt['sha256'] != expected or len(published) != 1:
                raise ValueError('issuer announcement identity changed')
            if datetime.fromisoformat(published[0]).date().isoformat() != ann:
                raise ValueError('issuer publication date changed')
            text = document_text(raw)
            formatted = date.fromisoformat(ex).strftime('%B %-d, %Y')
            if formatted not in text or 'cash in lieu' not in text:
                raise ValueError('issuer split terms absent')
            sources[key] = receipt
        else:
            text = texts['slv-2008-dba-2025']
            if any(t not in text for t in ('July 11, 2008', 'July 23, 2008', 'July 24th', 'July 28, 2008', '10 for 1')):
                raise ValueError('SLV primary split terms absent')
        plan = local_blackout(symbol=symbol, announced=date.fromisoformat(ann),
            ex_date=date.fromisoformat(ex), effective=date.fromisoformat(effective),
            payable=date.fromisoformat(pay) if pay else None,
            delivery=date.fromisoformat(delivery) if delivery else None, sessions=sessions)
        plans.append({**plan, 'ratio': ratio, 'issuer_evidence': key or 'slv-2008-dba-2025'})
    return {'sources': sources, 'plans': plans}


def reconcile_cash_dividends(prices, broker, sessions, texts):
    vendor = {r['ex_date']: D(r['amount']) for r in prices['sources']['DBA']['coverage']['dividend_events']}
    if set(vendor) != {r[0] for r in DIVIDENDS} or any(
            v['coverage']['dividend_events'] for s, v in prices['sources'].items() if s != 'DBA'):
        raise ValueError('vendor dividend inventory changed')
    extra = '8e4b54c3-f147-45e0-90fa-e96ce52fe198'
    rows = broker['actions']['cash_dividends']
    duplicate = [r for r in rows if r['id'] == extra]
    if len(duplicate) != 1 or duplicate[0]['ex_date'] != '2018-12-26' or D(duplicate[0]['rate']) != D('.17994'):
        raise ValueError('reviewed record-date duplicate changed')
    good = [r for r in rows if r['id'] != extra]
    if len(good) != 6 or {r['ex_date'] for r in good} != {r[0] for r in DIVIDENDS[1:]}:
        raise ValueError('broker dividend inventory changed')
    annual = texts['annual-2008-2018-2019']
    for term in ('December 17, 2008', 'December 30, 2008', 'December 26, 2018',
                 'December 31, 2018', 'December 24, 2019', 'December 31, 2019'):
        if term not in annual:
            raise ValueError('annual report record/payment evidence absent: ' + term)
    rules = texts['nyse-ex-date-rule']
    if 'two trading days before' not in rules or 'one trading day before' not in rules:
        raise ValueError('historical ex-date rule evidence absent')
    output = []
    for ex, record, pay, amount in DIVIDENDS:
        if abs(vendor[ex] - D(amount)) > D('.0005'):
            raise ValueError('dividend amount exceeds vendor rounding tolerance')
        if ex != '2008-12-15':
            [row] = [r for r in good if r['ex_date'] == ex]
            if row['symbol'] != 'DBA' or D(row['rate']) != D(amount):
                raise ValueError('broker dividend amount differs from reviewed value')
            if ex >= '2022' and (row['payable_date'] != pay or row['record_date'] != record):
                raise ValueError('broker dividend record/payable disagreement')
        if ex < '2020':
            offset = 2 if ex < '2017-09-05' else 1
            index = sessions.index(date.fromisoformat(record))
            if str(sessions[index-offset]) != ex:
                raise ValueError('historical ex-date rule conflicts with source event')
        else:
            key = ('qualified-2022-2024' if ex[:4] in ('2022', '2024') else
                   'qualified-2023' if ex[:4] == '2023' else 'slv-2008-dba-2025')
            for term in (date.fromisoformat(ex).strftime('%-m/%-d/%Y'),
                         date.fromisoformat(pay).strftime('%-m/%-d/%Y'), str(D(amount))):
                if term not in texts[key]:
                    raise ValueError('qualified-notice dividend evidence absent')
        after = bisect_right(sessions, date.fromisoformat(pay))
        if after >= len(sessions):
            raise ValueError('cash-credit session outside source')
        output.append({'symbol': 'DBA', 'ex_date': ex, 'record_date': record, 'payable_date': pay,
                       'amount': str(D(amount)), 'cash_available_session': str(sessions[after])})
    return {'distributions': output, 'excluded_record_date_duplicate': duplicate[0],
            'cash_policy': 'prior-owned ex-open entitlement; spendable first regular open strictly after issuer pay date'}


def freeze_source(archive=ARCHIVE):
    """Admit only the written exact corrections and verified action inventory."""
    prices, broker = price_audit(archive), broker_action_audit(archive)
    actual = {(r['symbol'], r['date']): r for r in prices['failures']}
    if len(prices['failures']) != 6 or set(actual) != set(OPEN_CORRECTIONS):
        raise ValueError('price conflicts differ from exact pre-outcome amendment')
    for key, corrected in OPEN_CORRECTIONS.items():
        row = actual[key]
        if row['field'] != 'open' or row['feed'] != 'sip' or D(row['primary']) != D(corrected):
            raise ValueError('source correction lacks exact primary opening proof')
    receipts, texts = extracted_evidence(archive)
    spy_receipt, spy = spy_source()
    refs = [r for r in spy['prices'] if START.date().isoformat() <= r['date'] < END.date().isoformat()]
    sessions = [date.fromisoformat(r['date']) for r in refs]
    actions = reconcile_actions(prices, broker, sessions, texts)
    cash = reconcile_cash_dividends(prices, broker, sessions, texts)
    by_symbol, split_events = {}, {}
    for symbol in UNIVERSE:
        _, raw = load_source(ORIGINAL / symbol, symbol)
        _, bars = parse_yahoo(raw.decode())
        by_symbol[symbol] = {b.date: b for b in bars}
        split_events[symbol] = [(b.date, b.split_ratio) for b in bars if b.split_ratio != 1]
    spy_divs = {r['ex_date']: r['amount'] for r in spy['distributions']}
    rows, corrections = [], []
    for ref in refs:
        day, quotes = date.fromisoformat(ref['date']), {}
        for symbol in UNIVERSE:
            bars = by_symbol[symbol]
            bar = bars[day]
            factor = actual_share_factor(day, split_events[symbol])
            prices_row = {field: str(getattr(bar, field) * factor) for field in ('open', 'high', 'low', 'close')}
            corrected = OPEN_CORRECTIONS.get((symbol, str(day)))
            if corrected:
                if not D(prices_row['low']) <= D(corrected) <= D(prices_row['high']):
                    raise ValueError('corrected primary open outside source range')
                corrections.append({'symbol': symbol, 'date': str(day), 'field': 'open',
                    'original_actual_share': prices_row['open'], 'corrected': corrected,
                    'evidence': actual[(symbol, str(day))]})
                prices_row['open'] = corrected
            quotes[symbol] = {**prices_row, 'adjusted_close': str(bar.adj_close),
                             'split_continuous_close': str(bar.close), 'split_ratio': str(bar.split_ratio)}
        rows.append({**ref, 'spy_close': ref['close'], 'spy_distribution': spy_divs.get(ref['date'], '0'),
                     'quotes': quotes})
    data = {'prices': rows, 'blackouts': actions['plans'], 'distributions': cash['distributions']}
    raw_data = (json.dumps(data, sort_keys=True, indent=2) + '\n').encode()
    amendment = (ROOT / 'docs/research/23-c05-blackout.md').read_bytes()
    identity = {'data_sha256': sha(raw_data), 'amendment_sha256': sha(amendment),
        'spy_calendar_benchmark_receipt': spy_receipt['receipt_sha256'],
        'source_start': START.isoformat(), 'source_end_exclusive': END.isoformat(),
        'policy': 'C05 report23 pre-outcome corrections and local split timing; Amendment21; unchanged signals and risk'}
    split = HoldoutSplit('c05-amendment21-' + sha(canonical(identity).encode())[:40], START, END)
    paths = ['research/c05_blackout.py', 'research/c05_commodity_trend.py', 'research/c06_sources.py',
             'research/equity_data.py', 'data/free_history.py', 'data/equity_source_repair.py']
    receipt = {'candidate': 'C05-amendment21', 'status': 'SOURCE_ADMITTED_NO_STRATEGY_OUTCOMES',
        'identity': identity, 'split': split.metadata(), 'prices': prices, 'price_corrections': corrections,
        'broker_actions': broker, 'action_audit': actions, 'cash_audit': cash, 'extracted_evidence': receipts,
        'source_code_sha256': {'src/tradingbot/' + p: sha((ROOT / 'src/tradingbot' / p).read_bytes()) for p in paths},
        'sessions': len(rows), 'strategy_outcomes_inspected': False, 'training_cases_attempted': 0,
        'final_holdout_attempts': 0, 'original_failed_rows_sha256': '8b9696d0de5dc85d159e7eec01a75512f216486b2e753e54aa207a2f07630f5e',
        'limitations': ['SIP independently checks 2016 onward only; IEX coverage later and sparse.',
            'Provider-extracted SEC/Invesco primary text where direct HTTP blocked; no PDF visual verification.',
            'Missing split payable stays null; model boundary is not broker credit.',
            'C08 previously inspected overlapping USO outcomes; earlier GLD sources and fund annual performance visible.',
            'Action inventory reconciles full Yahoo and available broker snapshots, not proof of no unknown omissions.']}
    receipt = json_value(receipt)
    receipt['receipt_sha256'] = sha(canonical(receipt).encode())
    encoded = (json.dumps(receipt, sort_keys=True, indent=2, default=str) + '\n').encode()
    directory = archive / 'frozen-source-v1'
    with CaptureDiskBudget(ROOT / 'data').reserve(3 * (len(raw_data) + len(encoded)) + 65536):
        directory.mkdir(exist_ok=False)
        (directory / 'data.json').write_bytes(raw_data)
        (directory / 'manifest.json').write_bytes(encoded)
        (directory / 'source-amendment.md').write_bytes(amendment)
    (ROOT / 'docs/research/23-c05-source.json').write_bytes(encoded)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--freeze', action='store_true')
    args = parser.parse_args()
    if args.freeze:
        receipt = freeze_source()
        print(json.dumps({'source_admitted': True, 'receipt_sha256': receipt['receipt_sha256'], 'sessions': receipt['sessions']}))
        return
    result = audit()
    encoded = json.dumps(result, indent=2, sort_keys=True, default=str) + '\n'
    with CaptureDiskBudget(ROOT / 'data').reserve(3 * len(encoded.encode()) + 65536):
        ARCHIVE.mkdir(parents=True, exist_ok=True)
        (ARCHIVE / 'source-progress.json').write_text(encoded)
    (ROOT / 'docs/research/23-c05-blackout.json').write_text(encoded)
    print(json.dumps({'stage': result['stage'], 'price_conflicts': len(result['prices']['failures']),
                      'training_cases_attempted': 0, 'final_holdout_attempts': 0}))


if __name__ == '__main__':
    main()
