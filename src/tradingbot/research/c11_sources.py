"""Recheck C11 raw source evidence without computing event-conditioned prices."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal as D
from html import unescape
import json
import re
import subprocess

import pyarrow.parquet as pq

from tradingbot.data.archive import SCHEMA, canonical
from tradingbot.research.c06_sources import spy_source
from tradingbot.research.c11_capture import ARCHIVE, ROOT, RUN, ACTION_REQUEST, SOURCES, read, sha

ACTION_SHA = 'a2b71bf9c3ebd38db0fe9dce1ac1c559898f8fd5c6ba8aaa3a98a7625213328b'
MONTHLY_TYPE = '6937B1D1-F5D5-46CD-BBE7-041C7BE7B85B'
# Manually read from the colored standard-equity/ETF expiration legend after
# rendering each original PDF. These are observations, NOT as-of admission.
REVIEWED_DAYS = {
    2024: [19, 16, 15, 19, 17, 21, 19, 16, 20, 18, 15, 20],
    2025: [17, 21, 21, 17, 16, 20, 18, 15, 19, 17, 21, 19],
    2026: [16, 20, 20, 17, 15, 18, 17, 21, 18, 16, 20, 18],
}


def public_sources(root=ROOT, archive=ARCHIVE):
    inventory = json.loads((root / 'docs/research/31-c11-evidence.json').read_bytes())['sources']
    if set(inventory) != set(SOURCES):
        raise ValueError('C11 evidence inventory changed')
    bodies = {}
    for key, url in SOURCES.items():
        folder = archive / key
        meta, raw = read(folder, url)
        expected = inventory[key]
        if ({k: v for k, v in expected.items() if k not in ('path', 'manifest_sha256')} != meta
                or expected['path'] != str(folder.relative_to(root))
                or expected['manifest_sha256'] != sha((folder / 'manifest.json').read_bytes())):
            raise ValueError('C11 pinned evidence changed')
        if meta['status'] != (404 if key.startswith('legacy-') else 200):
            raise ValueError('unreviewed source HTTP status')
        bodies[key] = raw
    return inventory, bodies


def occ_dates(raw):
    payload = json.loads(raw)
    legend = [r for r in payload['legend'] if r['type'] == MONTHLY_TYPE]
    if len(legend) != 1 or not legend[0]['title'].startswith('Monthly equity, index,'):
        raise ValueError('OCC monthly calendar legend changed')
    days, all_days = [], set()
    known_types = {r['type'] for r in payload['legend']}
    for row in payload['data']:
        stamp = datetime.fromisoformat(row['date'])
        if stamp.time().isoformat() != '00:00:00' or stamp.date() in all_days:
            raise ValueError('duplicate or non-midnight OCC calendar date')
        all_days.add(stamp.date())
        types = [r['type'] for r in row.get('events', [])]
        if len(types) != len(set(types)) or set(types) - known_types:
            raise ValueError('duplicate or unknown OCC event type')
        if MONTHLY_TYPE in types:
            days.append(stamp.date())
    if not days or len({(d.year, d.month) for d in days}) != len(days):
        raise ValueError('missing or repeated monthly OCC expiry')
    return sorted(days), payload


def fractional_tif(raw):
    text = raw.decode()
    marker = '### Fractional orders (USD)'
    if text.count(marker) != 1:
        raise ValueError('fractional order section missing or ambiguous')
    section = text.split(marker, 1)[1].split('### ', 1)[0]
    rows = {}
    for row in re.findall(r'<tr>.*?</tr>', section, re.S):
        cells = [' '.join(unescape(re.sub('<[^>]+>', '', v)).split())
                 for v in re.findall(r'<td[^>]*>(.*?)</td>', row, re.S)]
        if not cells:
            continue
        if len(cells) != 5 or cells[0] in rows or any(c not in ('Yes', 'No') for c in cells[1:]):
            raise ValueError('fractional order table malformed or duplicated')
        rows[cells[0]] = cells[1:]
    if set(rows) != {'GTC', 'DAY', 'IOC', 'FOK', 'OPG', 'CLS'}:
        raise ValueError('fractional order table incomplete')
    return rows


def calendar_audit(bodies, archive=ARCHIVE):
    dates, occ = occ_dates(bodies['occ-calendar-api'])
    reviewed = [date(y, m, day) for y, days in REVIEWED_DAYS.items() for m, day in enumerate(days, 1)]
    for day in reviewed:
        if day.year >= 2025 and day not in dates:
            raise ValueError('OCC and visually reviewed Cboe calendar disagree')
    for year in REVIEWED_DAYS:
        raw = bodies[f'cboe-{year}']
        if not raw.startswith(b'%PDF-'):
            raise ValueError('annual calendar is not PDF')
    transition = subprocess.check_output(['pdftotext', '-layout',
        str(archive / 'cboe-transition-2013/raw'), '-'], text=True, timeout=15)
    if ('August 29, 2013' not in transition or not re.search(r'December 2015\s+SPY\s', transition)
            or 'Grandfathered' not in transition or 'February 1, 2015' not in transition):
        raise ValueError('dated SPY grandfathered-expiration notice changed')
    # A source's current as-of footnote cannot establish earlier availability.
    footnote = re.sub(r'<!--.*?-->', '', occ['footnotes'], flags=re.S)
    if 'accurate as of 1/2/2026' not in footnote:
        raise ValueError('unreviewed OCC calendar vintage')
    return {
        'occ_current_monthly_dates': list(map(str, dates)),
        'occ_api_years': sorted({d.year for d in dates}),
        'occ_footnote_as_of': '2026-01-02',
        'occ_footnote_is_original_publication_timestamp': False,
        'cboe_visually_reviewed_dates': list(map(str, reviewed)),
        'cboe_annual_calendar_years': list(REVIEWED_DAYS),
        'frozen_interval_months': 249,
        'months_with_reviewed_calendar_date': sum(d < date(2026, 10, 1) for d in reviewed),
        'missing_annual_calendar_years': list(range(2006, 2024)),
        'as_of_announcement_and_revision_history_admitted': False,
        'transition_notice_date': '2013-08-29',
        'grandfathered_spy_contract_month': '2015-12',
        'grandfathered_legal_expiration': 'Saturday following third Friday; never an equity Saturday close',
        'failure': 'Current calendar snapshots and the dated transition do not supply full 2006–2026 '
                   'archived calendars, advance availability and revisions. Legacy 2006/2009 paths return 404. '
                   'Do not replace missing evidence with hindsight realized sessions or third-Friday arithmetic.',
    }


def action_source(root=ROOT, archive=ARCHIVE):
    paths = list((archive / 'raw/alpaca/corporate_actions' / RUN).glob('*/manifest.json'))
    if len(paths) != 1:
        raise ValueError('missing or ambiguous C11 action archive')
    path = paths[0]
    manifest = json.loads(path.read_bytes())
    request = json.loads(ACTION_REQUEST.to_json())
    if (sha(canonical(manifest).encode())[:24] != path.parent.name
            or manifest['request'] != request or manifest['format_version'] != 1
            or manifest['venue'] != 'alpaca' or manifest['dataset'] != 'corporate_actions'):
        raise ValueError('C11 action request identity changed')
    files = list(path.parent.glob('page-*.parquet'))
    if len(files) != 1 or files[0].name != 'page-00000000.parquet':
        raise ValueError('C11 reviewed action capture requires one exhausted page')
    table = pq.read_table(files[0])
    if table.num_rows != 1 or not table.schema.equals(SCHEMA):
        raise ValueError('C11 action page schema changed')
    row = table.to_pylist()[0]
    payload = json.loads(row['response_json'], parse_float=D)
    if (row['format_version'] != 1 or row['venue'] != 'alpaca' or row['dataset'] != 'corporate_actions'
            or row['request_json'] != ACTION_REQUEST.to_json() or row['page'] != 0
            or row['response_sha256'] != sha(row['response_json'].encode())
            or row['response_sha256'] != ACTION_SHA or row['next_request_json'] is not None
            or payload['next_page_token'] is not None):
        raise ValueError('C11 action checksum, identity or cursor changed')
    groups = payload['corporate_actions']
    if (not isinstance(groups, dict) or any(not isinstance(v, list) for v in groups.values())
            or sum(map(len, groups.values())) != row['record_count']):
        raise ValueError('C11 action record count changed')
    return {'path': str(files[0].relative_to(root)), 'request': request,
            'response_sha256': row['response_sha256'], 'exhausted': True,
            'records': row['record_count'], 'retrieved_at': row['retrieved_at'].isoformat()}, groups


def actions_audit(groups, distributions):
    if set(groups) != {'cash_dividends'}:
        raise ValueError('unreviewed SPY noncash action group')
    cash = groups['cash_dividends']
    ids, dates = set(), set()
    by_date = {r['ex_date']: r for r in distributions}
    disagreements = []
    for row in cash:
        if row['symbol'] != 'SPY' or row['id'] in ids or row['ex_date'] in dates:
            raise ValueError('wrong symbol or duplicate SPY action')
        ids.add(row['id']); dates.add(row['ex_date'])
        date.fromisoformat(row['ex_date'])
        amount = D(str(row['rate']))
        if not amount.is_finite() or amount <= 0:
            raise ValueError('invalid SPY action amount')
        if row['ex_date'] not in by_date or abs(amount - D(by_date[row['ex_date']]['amount'])) > D('.0005'):
            disagreements.append(row['ex_date'])
    if not dates:
        raise ValueError('empty SPY action overlap')
    missing = sorted(set(by_date) - dates)
    return {'cash_records': len(cash), 'noncash_records': 0, 'issuer_distributions': len(distributions),
            'first_broker_ex_date': min(dates), 'last_broker_ex_date': max(dates),
            'issuer_dates_absent_from_broker_query': missing,
            'missing_before_first_broker_date': sum(d < min(dates) for d in missing),
            'missing_on_or_after_first_broker_date': [d for d in missing if d >= min(dates)],
            'amount_or_date_disagreements': disagreements,
            'full_interval_share_action_completeness_proven': False,
            'limitation': 'The query is all-type/data_quality=all and exhausted, but bounds are process dates. '
                'It misses known cash history, notably before 2016. This cannot prove the absence of earlier '
                'splits/in-kind actions. Later cash absences do not alone prove an error in an ex-date table. '
                'Issuer cash schedules and Yahoo zero splits are not a complete noncash-action inventory.'}


def audit_sources():
    inventory, bodies = public_sources()
    calendar = calendar_audit(bodies)
    table = fractional_tif(bodies['alpaca-orders'])
    if table['CLS'] != ['No'] * 4 or table['OPG'] != ['No'] * 4 or table['DAY'] != ['Yes'] * 4:
        raise ValueError('broker fractional execution evidence changed; re-review required')
    receipt, data = spy_source()
    action_ref, groups = action_source()
    actions = actions_audit(groups, data['distributions'])
    return {'public_sources': inventory, 'calendar': calendar,
        'execution': {'fractional_order_tif': table,
            'close_variant_admitted': False,
            'reason': 'Fractional CLS is unsupported; a timed DAY order needs contemporaneous execution '
                'evidence absent from daily bars. No whole-share or endpoint substitution.',
            'next_open_variant': 'Common adverse-cost open-reference counterfactual, not an auction-fill claim; '
                'still fails calendar and share-action admission.'},
        'spy': {'receipt_sha256': receipt['receipt_sha256'], 'data_sha256': receipt['identity']['data_sha256'],
            'sessions': len(data['prices']), 'distributions': len(data['distributions']),
            'first_session': data['prices'][0]['date'], 'last_session': data['prices'][-1]['date'],
            'source_status': receipt['status'], 'excluded_fields': receipt['excluded_fields'],
            'policies': receipt['identity']['policies'], 'source_split': receipt['split'],
            'action_source': action_ref, 'actions': actions},
        'price_and_calendar_returns_computed': False}
