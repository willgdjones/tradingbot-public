"""C08 Amendment 21 source preparation; no signals or strategy returns here."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import io
import json
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import pyarrow.parquet as pq
import requests

from tradingbot.data.archive import SCHEMA, canonical
from tradingbot.data.disk_budget import CaptureDiskBudget
from tradingbot.data.equity_source_repair import primary_closing_price
from tradingbot.data.free_history import USER_AGENT, parse_yahoo
from tradingbot.research.action_blackout import CorporateAction, plan_blackouts
from tradingbot.research.c05_commodity_trend import load_document
from tradingbot.research.c06_sources import spy_source
from tradingbot.research.c08_source_audit import (
    ARCHIVE as ORIGINAL, DOCUMENTS, EIA_ROOT, END, ROOT, START, Links,
    document_text, eia_layout, load_capture, sha, uso_source,
)

ARCHIVE = ROOT / 'data/research/c08-blackout'
METHOD_SOURCES = {
    'eia-method-current': 'https://www.eia.gov/petroleum/supply/weekly/pdf/appendixb.pdf',
    'eia-errata-current': 'https://www.eia.gov/petroleum/supply/weekly/pdf/appendix_e.pdf',
    'uso-product-current': 'https://www.uscfinvestments.com/uso',
}
REVIEW_SOURCES = {
    'eia-correction-2019': (EIA_ROOT + '2019/2019_05_22/wpsr_notice_07252019.php', 'e726d645b919d1017f43eb979739261e23b275ec1919bb94a598dafa922b008d'),
    'eia-changes-2020': (EIA_ROOT + '2020/2020_04_01/wpsr_notice_04012020.php', '3090d038b25a0a6d87e1b47aa7de15d8dd4311a288d6c50850f5712306860f53'),
    'eia-storage-2020': (EIA_ROOT + '2020/2020_04_08/wcrudeoilstorage_notice.php', '1f6f0c2b53eea6e05a3e42defe1786faaf786e3f51d56b1c22b1a0da28a0c028'),
    'eia-changes-2023': (EIA_ROOT + '2023/2023_11_15/wpsr_notice_11132023.php', '2f7bc01300246b98f0e215a2505236780076bc82607749aaa65517d9e4a95f56'),
}
STOCK_DEFINITION = 'Includes those domestic and Customs-cleared foreign crude oil stocks held at refineries and tank farms or in transit thereto, and in pipelines.'
FULL_REPORT_PUBLICATION = {
    'report-2026_06_24': {'page_sha256': 'af82f596c323e958b5e7a042ff1204070ef726e66c636e15f9a8bfac8f477a20',
                        'pdf_sha256': '90029fb07022f4e26c8ef0531d4db362578eca86d4029aaf66308c0e447c28ee'}
}
_NETWORK = threading.local()
_PDF_TEXT_CACHE = {}


def capture(key, url, *, archive=ARCHIVE):
    """Same receipt contract; free-space checks and coordinated periodic full scans.

    Completed directories are immutable. A staging directory is atomically
    renamed only after its raw bytes and checksum receipt are both written.
    """
    directory = archive / key
    if directory.exists():
        return load_capture(directory, key, url)[0]
    budget = CaptureDiskBudget(ROOT / 'data')
    budget.check_free()
    if not hasattr(_NETWORK, 'session'):
        _NETWORK.session = requests.Session()
    response = _NETWORK.session.get(url, headers={'User-Agent': USER_AGENT}, timeout=(10, 60))
    raw = response.content
    receipt = {'key': key, 'request_url': url, 'params': None, 'response_url': response.url,
               'status_code': response.status_code, 'retrieved_at': datetime.now(UTC).isoformat(),
               'sha256': sha(raw), 'bytes': len(raw), 'content_type': response.headers.get('content-type')}
    with budget.reserve(3 * len(raw) + 65536):
        archive.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.capture-', dir=archive) as stage:
            staged = Path(stage) / key
            staged.mkdir()
            (staged / 'raw').write_bytes(raw)
            (staged / 'manifest.json').write_text(json.dumps(receipt, indent=2) + '\n')
            if directory.exists():
                existing, _ = load_capture(directory, key, url)
                if existing['sha256'] != receipt['sha256']:
                    raise ValueError('concurrent capture has different bytes')
                return existing
            staged.rename(directory)
    return receipt


def read_reference(archive: Path, dataset: str, expected: dict):
    """Validate a frozen single exhausted raw archive page before diagnostics."""
    paths = list((archive / 'raw/alpaca' / dataset / 'c08-amendment21-20261001').glob('*/manifest.json'))
    if len(paths) != 1:
        raise ValueError('missing or ambiguous C08 reference archive')
    path = paths[0]
    manifest = json.loads(path.read_text())
    if sha(canonical(manifest).encode())[:24] != path.parent.name or manifest['request'] != expected:
        raise ValueError('C08 reference identity/request changed')
    files = sorted(path.parent.glob('page-*.parquet'))
    if len(files) != 1 or files[0].name != 'page-00000000.parquet':
        raise ValueError('C08 reference requires one exhausted page')
    table = pq.ParquetFile(files[0]).read()
    if table.num_rows != 1 or not table.schema.equals(SCHEMA):
        raise ValueError('C08 reference schema mismatch')
    row = table.to_pylist()[0]
    payload = json.loads(row['response_json'], parse_float=Decimal)
    if (row['request_json'] != canonical(expected) or row['page'] != 0
            or sha(row['response_json'].encode()) != row['response_sha256']
            or row['next_request_json'] is not None or payload.get('next_page_token', 'missing') is not None):
        raise ValueError('C08 reference checksum or exhaustion mismatch')
    return {'path': str(files[0].relative_to(ROOT)), 'response_sha256': row['response_sha256'],
            'request': expected, 'record_count': row['record_count']}, payload


def compare_reference(bars, reference, *, primary_close):
    """Source-only actual-share checks; a thin-venue exception needs auction proof."""
    by_date = {b.date: b for b in bars}
    seen = set()
    differences = []
    worst = {'open': Decimal(0), 'close': Decimal(0)}
    for other in reference:
        stamp = datetime.fromisoformat(other['t'].replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            raise ValueError('reference timestamp must be timezone aware')
        day = stamp.astimezone(ZoneInfo('America/New_York')).date()
        if day not in by_date or day in seen:
            raise ValueError('missing/duplicated reference session')
        seen.add(day)
        factor = Decimal('.125') if day < date(2020, 4, 29) else Decimal(1)
        for field in ('open', 'close'):
            raw = Decimal(str(other[field[0]]))
            if not raw.is_finite() or raw <= 0:
                raise ValueError('invalid reference price')
            actual = getattr(by_date[day], field) * factor
            gap = abs(actual / raw - 1)
            worst[field] = max(worst[field], gap)
            if gap > Decimal('.01'):
                proof = primary_close.get(day) if field == 'close' else None
                resolved = proof is not None and abs(actual / proof - 1) <= Decimal('.000001')
                differences.append({'date': str(day), 'field': field, 'yahoo_actual_share': str(actual),
                                    'reference': str(raw), 'relative_difference': str(gap),
                                    'primary_auction_resolution': str(proof) if resolved else None})
    return {'sessions': len(seen), 'first': str(min(seen)), 'last': str(max(seen)),
            'missing_sessions': [str(d) for d in sorted(by_date.keys() - seen)],
            'worst_relative_difference': {k: str(v) for k, v in worst.items()},
            'differences_over_1pct': differences}


def price_audit(sessions, archive=ARCHIVE):
    source, coverage = uso_source(ORIGINAL, sessions)
    if not coverage['coverage_ok'] or coverage['split_events'] != [{'date': '2020-04-29', 'ratio': '0.125'}]:
        raise ValueError('USO source coverage/split inventory changed')
    _, bars = parse_yahoo((ORIGINAL / 'USO/raw').read_text())
    auction_request = {'url': 'https://data.alpaca.markets/v2/stocks/USO/trades', 'params': {
        'start': '2020-04-21T20:00:00Z', 'end': '2020-04-21T20:00:10Z',
        'feed': 'sip', 'limit': 10000, 'sort': 'asc'}}
    auction, payload = read_reference(archive, 'uso_primary_close', auction_request)
    if len(payload['trades']) != auction['record_count']:
        raise ValueError('auction record count mismatch')
    close = primary_closing_price(payload['trades'], datetime(2020, 4, 21, 20, tzinfo=UTC), 'P')
    auction.update({'exchange': 'P / NYSE Arca', 'price': str(close), 'date': '2020-04-21',
                    'listing_source': 'USCF split announcement identifies NYSE Arca'})
    references = []
    failures = []
    for feed in ('iex', 'sip'):
        params = {'symbols': 'USO', 'timeframe': '1Day', 'start': '2018-01-01T00:00:00Z',
                  'end': '2026-10-01T00:00:00Z', 'adjustment': 'raw', 'feed': feed,
                  'limit': 10000, 'sort': 'asc', 'asof': '-'}
        receipt, payload = read_reference(archive, 'bars_1Day_raw_' + feed,
            {'url': 'https://data.alpaca.markets/v2/stocks/bars', 'params': params})
        if set(payload['bars']) != {'USO'} or len(payload['bars']['USO']) != receipt['record_count']:
            raise ValueError('USO reference symbols/count mismatch')
        compared = compare_reference(bars, payload['bars']['USO'], primary_close={date(2020, 4, 21): close})
        # IEX is a single-venue close cross-check. Its opening trade is not the
        # primary-market opening auction; those differences remain diagnostic.
        for difference in compared['differences_over_1pct']:
            if (feed == 'sip' or difference['field'] == 'close') and not difference['primary_auction_resolution']:
                failures.append({'feed': feed, **difference})
        if feed == 'sip' and compared['missing_sessions']:
            failures.append({'feed': feed, 'missing_sessions': compared['missing_sessions']})
        references.append({'feed': feed, **receipt, **compared})
    return {'source': source, 'coverage': coverage, 'references': references,
            'auction': auction, 'failures': failures, 'price_corrections': [],
            'policy': 'Yahoo open/close multiplied by 1/8 strictly before Apr29 2020; no adjusted-close fills. '
                      'Raw SIP open/close and IEX closes use the existing 1% diagnostic bound. '
                      'IEX opens are separate-venue diagnostics; not primary auction validation.'}


def action_audit(sessions, archive=ARCHIVE):
    request = {'url': 'https://data.alpaca.markets/v1/corporate-actions', 'params': {
        'symbols': 'USO', 'start': '2018-01-01', 'end': '2026-09-30', 'limit': 1000, 'sort': 'asc'}}
    receipt, body = read_reference(archive, 'corporate_actions', request)
    if body['corporate_actions'].keys() != {'reverse_splits'} or receipt['record_count'] != 1:
        raise ValueError('USO broker action inventory differs from reviewed split')
    actions = body['corporate_actions']['reverse_splits']
    if len(actions) != 1:
        raise ValueError('ambiguous USO reverse split')
    action = actions[0]
    expected = {'symbol': 'USO', 'old_rate': 8, 'new_rate': 1, 'ex_date': '2020-04-29',
                'payable_date': '2020-04-29', 'process_date': '2020-04-29', 'record_date': '2020-04-29',
                'old_cusip': '91232N108', 'new_cusip': '91232N207'}
    if any(action.get(k) != v for k, v in expected.items()):
        raise ValueError('USO reverse split dates/ratio/identity changed')
    key = 'uso-2020-issuer-release'
    issuer, raw = load_document(ROOT / 'data/research/c05/documents' / key, key)
    if issuer['status_code'] != 200 or issuer['sha256'] != 'f6c45b79216bc0139f6819482a127bc68eb310915b4932ce2cee79cd0ec34364':
        raise ValueError('USCF announcement receipt changed')
    published = re.findall(r'"datePublished"\s*:\s*"([^"]+)"', raw.decode())
    if published != ['2020-04-22T07:45:00-04:00']:
        raise ValueError('USCF announcement timestamp is missing or ambiguous')
    text = document_text(raw)
    if any(term not in text for term in ('one-for-eight', 'cash in lieu', 'April 29', 'April 28')):
        raise ValueError('USCF action terms missing')
    event = CorporateAction('USO', 'reverse_split', date(2020, 4, 22), date(2020, 4, 29),
                            date(2020, 4, 29), issuer['request_url'])
    [plan] = plan_blackouts([event], sessions)
    days = sorted(d for d in sessions if plan.exit <= d < plan.reentry)
    return {'broker_source': receipt, 'broker_action': action, 'issuer_source': issuer,
            'announced_at': published[0], 'decision': str(plan.decision), 'exit': str(plan.exit),
            'reentry': str(plan.reentry), 'blackout_sessions': list(map(str, days)),
            'payable_basis': 'Alpaca corporate-action payable_date, not an assertion of fractional cash-in-lieu credit',
            'share_exchange_effective': '2020-04-28 after close per issuer; post-split trading Apr29',
            'blackout_kind': 'reverse_split', 'cash_credit_assumed': False}


def report_urls(raw: bytes) -> list[str]:
    """Enumerate the fixed date range from actual index links, not guessed Wednesdays."""
    links = Links()
    links.feed(raw.decode('utf-8'))
    selected = set()
    for href in links.hrefs:
        url = urljoin(EIA_ROOT, href)
        parsed = urlparse(url)
        match = re.fullmatch(
            r'/petroleum/supply/weekly/archive/(\d{4})/(\d{4}_\d{2}_\d{2}(?:_data)?)/wpsr_\2\.(?:php|html)',
            parsed.path,
        )
        if not match:
            continue
        day = datetime.strptime(match[2][:10], '%Y_%m_%d').date()
        if START.date() <= day < END.date():
            if parsed.scheme != 'https' or parsed.netloc != 'www.eia.gov' or parsed.query or parsed.fragment:
                raise ValueError('EIA report link leaves the fixed primary source')
            if int(match[1]) != day.year:
                raise ValueError('EIA report path years disagree')
            selected.add(url)
    if not selected:
        raise ValueError('EIA report index has no candidate-period links')
    return sorted(selected)


def stock_fields(raw: bytes, observation: date) -> dict:
    """Validate the dated stock section and extract fields without computing scarcity.

    Units must separately be certified from the corresponding report/PDF: the
    CSV has no unit label. These fields alone never admit a signal or replay.
    """
    rows = list(csv.reader(io.StringIO(raw.decode('cp1252'))))
    if not rows or len(rows[0]) != 8:
        raise ValueError('EIA stock header width changed')
    header = rows[0]
    if [header[i] for i in (0, 3, 4, 6, 7)] != [
        'STUB_1', 'Difference', 'Percent Change', 'Difference', 'Percent Change',
    ]:
        raise ValueError('EIA stock columns changed')
    current, previous, year_ago = (datetime.strptime(header[i], '%m/%d/%y').date() for i in (1, 2, 5))
    if current != observation or (current - previous).days != 7 or (current - year_ago).days not in (364, 371):
        raise ValueError('EIA stock observation/comparison dates disagree')
    expected = ['Crude Oil', 'Commercial (Excluding SPR)', 'Strategic Petroleum Reserve (SPR)']
    if len(rows) < 4 or [r[0] if r else None for r in rows[1:4]] != expected:
        raise ValueError('EIA crude-stock section changed')
    if sum(bool(r and r[0] == expected[1]) for r in rows) != 1:
        raise ValueError('EIA commercial stocks are ambiguous')
    values = []
    for row in rows[1:4]:
        if len(row) != 8:
            raise ValueError('EIA stock row width changed')
        pair = [Decimal(row[i].replace(',', '')) for i in (1, 5)]
        if any(not v.is_finite() or v <= 0 for v in pair):
            raise ValueError('EIA stock levels/denominators must be finite and positive')
        values.append(pair)
    if any(abs(values[0][i] - values[1][i] - values[2][i]) > Decimal('.002') for i in (0, 1)):
        raise ValueError('EIA crude stocks do not reconcile commercial plus SPR')
    return {'observation_date': str(current), 'previous_date': str(previous),
            'comparable_year_ago_date': str(year_ago),
            'commercial_current': str(values[1][0]), 'commercial_year_ago': str(values[1][1]),
            'units_verified': False, 'first_release_vintage_verified': False}


def pdf_stock_check(text: str, fields: dict):
    """Check dated PDF units and its independently rendered rounded stock row."""
    heading = re.search(r'Table 1\. U\.S\. Petroleum Balance Sheet, Week Ending (\d{1,2}/\d{1,2}/\d{4})', text)
    if heading is None or datetime.strptime(heading[1], '%m/%d/%Y').date().isoformat() != fields['observation_date']:
        raise ValueError('EIA PDF observation date differs from CSV/page')
    if not re.search(r'Petroleum Stocks\s+.*?\(Million Barrels\)', text[:1600], re.DOTALL):
        raise ValueError('EIA PDF stock units not established')
    rows = re.findall(r'^.*Commercial\s+\(Excluding SPR\)[^\n]*$', text, re.MULTILINE)
    if len(rows) != 1:
        raise ValueError('EIA PDF commercial-stock row is ambiguous')
    tail = rows[0].split('(Excluding SPR)', 1)[1]
    values = [Decimal(x.replace(',', '')) for x in re.findall(r'-?\d[\d,]*\.\d+', tail)]
    if len(values) != 7:
        raise ValueError('EIA PDF stock columns changed')
    for value, name in ((values[0], 'commercial_current'), (values[4], 'commercial_year_ago')):
        if abs(value - Decimal(fields[name])) > Decimal('.05'):
            raise ValueError('EIA PDF/CSV stock levels disagree beyond printed rounding')
    return {'units': 'million barrels', 'pdf_csv_rounding_tolerance': '0.05',
            'pdf_current': str(values[0]), 'pdf_year_ago': str(values[4])}


def pdf_stock_fields(text: str, observation: date):
    """Original dated PDF fallback, retaining its stated 0.1-million precision."""
    heading = re.search(r'Table 1\. U\.S\. Petroleum Balance Sheet, Week Ending (\d{1,2}/\d{1,2}/\d{4})', text)
    if heading is None or datetime.strptime(heading[1], '%m/%d/%Y').date() != observation:
        raise ValueError('EIA PDF observation date differs from release page')
    if not re.search(r'Petroleum Stocks\s+.*?\(Million Barrels\)', text[:1600], re.DOTALL):
        raise ValueError('EIA PDF stock units not established')
    if STOCK_DEFINITION not in ' '.join(text.split()):
        raise ValueError('EIA PDF commercial stock definition changed')
    first_stock = re.search(r'^\s*Crude Oil\s*\.', text, re.MULTILINE)
    if first_stock is None:
        raise ValueError('EIA PDF crude stocks header missing')
    dates = [datetime.strptime(s, '%m/%d/%y').date() for s in
             re.findall(r'\b\d{1,2}/\d{1,2}/\d{2}\b', text[:first_stock.start()])]
    if (len(dates) != 3 or len(set(dates)) != 3 or max(dates) != observation
            or (observation - sorted(dates)[1]).days != 7
            or (observation - min(dates)).days not in (364, 371)):
        raise ValueError('EIA PDF stock comparison dates changed')
    values = []
    stocks = text.split('Petroleum Supply', 1)[0]
    for label in ('Crude Oil', 'Commercial (Excluding SPR)', 'Strategic Petroleum Reserve (SPR)'):
        rows = re.findall(r'^\s*' + re.escape(label) + r'[^\n]*$', stocks, re.MULTILINE)
        if len(rows) != 1:
            raise ValueError('EIA PDF crude-stock components ambiguous')
        numbers = [Decimal(n.replace(',', '')) for n in re.findall(r'-?\d[\d,]*\.\d+', rows[0].split(label)[1])]
        if len(numbers) != 7 or any(not numbers[i].is_finite() or numbers[i] <= 0 for i in (0, 4)):
            raise ValueError('EIA PDF stock fields changed or nonpositive')
        values.append([numbers[0], numbers[4]])
    # Three independently rounded 0.1-million levels permit 0.15 in their sum.
    if any(abs(values[0][i] - values[1][i] - values[2][i]) > Decimal('.15') for i in (0, 1)):
        raise ValueError('EIA PDF crude stocks do not reconcile at printed precision')
    return {'observation_date': str(observation), 'previous_date': str(sorted(dates)[1]),
        'comparable_year_ago_date': str(min(dates)), 'commercial_current': str(values[1][0]),
        'commercial_year_ago': str(values[1][1]), 'units_verified': True,
        'field_precision_million_barrels': '0.1', 'source_format': 'original dated Table 1 PDF',
        'commercial_definition_verified': True,
        'first_release_vintage_verified': False}


def pdf_text(path, *, layout=True):
    raw = path.read_bytes()
    if not raw.startswith(b'%PDF'):
        raise ValueError('HTTP response is not a PDF')
    key = (sha(raw), layout)
    if key in _PDF_TEXT_CACHE:
        return _PDF_TEXT_CACHE[key]
    command = ['pdftotext', *(['-layout'] if layout else []), str(path), '-']
    text = subprocess.check_output(command, text=True, stderr=subprocess.PIPE)
    if len(_PDF_TEXT_CACHE) >= 1024:
        _PDF_TEXT_CACHE.pop(next(iter(_PDF_TEXT_CACHE)))
    _PDF_TEXT_CACHE[key] = text
    return text


def attachment_urls(raw, url, suffix):
    links = Links()
    links.feed(raw.decode('utf-8'))
    urls = sorted({urljoin(url, href) for href in links.hrefs if href.endswith(suffix)})
    if any(urlparse(link).netloc != 'www.eia.gov' for link in urls):
        raise ValueError('EIA attachment left primary host')
    return urls


def dated_attachment_urls(raw, url, suffix):
    urls = attachment_urls(raw, url, suffix)
    expected = urljoin(url, suffix)
    if expected in urls:
        return [expected]
    if urls:
        raise ValueError('EIA attachment is not in this dated archive directory')
    return []


def archive_layout(raw, url, csv_raw):
    """Resolve one incomplete observation heading from its dated table only.

    A full publication date still must be present on the page. The PDF date
    is separately required to agree with the CSV before the record is usable.
    No URL-derived date or assumed Wednesday is an admission input.
    """
    try:
        return eia_layout(raw, url)
    except ValueError:
        body = document_text(raw)
        matches = re.findall(r'Data for week ending (\w+), (\d{4})\s*\|\s*Release Date:\s*(\w+ \d{1,2}, \d{4})', body)
        if len(matches) != 1:
            raise
        month, year, released = matches[0]
        header = next(csv.reader(io.StringIO(csv_raw.decode('cp1252'))))
        observation = datetime.strptime(header[1], '%m/%d/%y').date()
        release = datetime.strptime(released, '%B %d, %Y').date()
        links = attachment_urls(raw, url, 'csv/table1.csv')
        if (observation.strftime('%B') != month or str(observation.year) != year
                or release <= observation or len(links) != 1):
            raise ValueError('incomplete EIA heading disagrees with its dated table')
        return {'observation_date': str(observation), 'release_date': str(release),
                'release_weekday': release.strftime('%A'), 'timestamp_precision': 'date_only',
                'earliest_calendar_date_for_execution': str(release + timedelta(days=1)),
                'table1_url': links[0], 'first_release_vintage_verified': False,
                'notice': 'Incomplete page observation heading; CSV date requires separate PDF agreement'}


def full_report_layout(raw, url, csv_raw, full_text):
    """Independent explicit release date, never a URL or weekday inference."""
    page_dates = re.findall(r'Data for week ending (\w+ \d{1,2}, \d{4})\s*\|\s*Release Date:\s*(\w+ \d{1,2}, \d{4})', document_text(raw))
    cover = full_text.split('\f', 1)[0]
    cover_dates = re.findall(r'\b(\w+ \d{1,2}, \d{4})\b', cover)
    released = re.findall(r'Release Date:\s*(\w+ \d{1,2}, \d{4})', '\f'.join(full_text.split('\f')[:2]))
    if len(page_dates) != 1 or len(cover_dates) != 1 or len(released) != 1 or 'Data for Week Ended:' not in cover:
        raise ValueError('full EIA PDF has ambiguous observation/publication evidence')
    observation, page_release = (datetime.strptime(v, '%B %d, %Y').date() for v in page_dates[0])
    release = datetime.strptime(released[0], '%B %d, %Y').date()
    csv_date = datetime.strptime(next(csv.reader(io.StringIO(csv_raw.decode('cp1252'))))[1], '%m/%d/%y').date()
    if (datetime.strptime(cover_dates[0], '%B %d, %Y').date() != observation or csv_date != observation
            or page_release > observation or release <= observation):
        raise ValueError('full EIA PDF does not resolve the impossible page publication date')
    urls = dated_attachment_urls(raw, url, 'csv/table1.csv')
    if len(urls) != 1:
        raise ValueError('dated CSV absent from publication exception')
    return {'observation_date': str(observation), 'release_date': str(release),
        'rejected_page_release_date': str(page_release), 'release_weekday': release.strftime('%A'),
        'timestamp_precision': 'date_only', 'earliest_calendar_date_for_execution': str(release + timedelta(days=1)),
        'table1_url': urls[0], 'first_release_vintage_verified': False,
        'notice': 'Impossible page publication date replaced only by the full report explicit release date on page ii'}


def eia_audit(archive=ARCHIVE):
    """Report completeness/schema/units/notice evidence; never calculate a signal."""
    index_receipt, raw_index = load_capture(ORIGINAL / 'eia-index', 'eia-index', EIA_ROOT)
    records, pending, failures, notices, unusable = [], [], [], {}, []
    for url in report_urls(raw_index):
        key = 'report-' + Path(urlparse(url).path).stem.removeprefix('wpsr_')
        if not (archive / key / 'manifest.json').exists():
            pending.append(key)
            continue
        try:
            page_receipt, raw = load_capture(archive / key, key, url)
            if page_receipt['status_code'] != 200:
                unusable.append({'key': key, 'reason': f'HTTP {page_receipt["status_code"]}', 'page_source': page_receipt})
                continue
            csv_urls = attachment_urls(raw, url, 'csv/table1.csv')
            if not csv_urls and 'EIA - Sorry! Unexpected Error' in document_text(raw):
                unusable.append({'key': key, 'reason': 'EIA application error page returned HTTP 200', 'page_source': page_receipt})
                continue
            if len(csv_urls) != 1:
                raise ValueError('missing or ambiguous EIA table 1 CSV link')
            csv_key = key + '-table1'
            csv_receipt, csv_raw = load_capture(archive / csv_key, csv_key, csv_urls[0])
            if csv_receipt['status_code'] != 200:
                unusable.append({'key': key, 'reason': 'EIA CSV HTTP failure', 'page_source': page_receipt, 'csv_source': csv_receipt})
                continue
            publication_source = None
            if key in FULL_REPORT_PUBLICATION:
                expected = FULL_REPORT_PUBLICATION[key]
                urls = dated_attachment_urls(raw, url, 'pdf/wpsrall.pdf')
                if len(urls) != 1 or page_receipt['sha256'] != expected['page_sha256']:
                    raise ValueError('C08 reviewed publication exception page changed')
                pdf_key = key + '-pdf-wpsrall.pdf'
                publication_source, _ = load_capture(archive / pdf_key, pdf_key, urls[0])
                if publication_source['status_code'] != 200 or publication_source['sha256'] != expected['pdf_sha256']:
                    raise ValueError('C08 reviewed publication proof changed')
                layout = full_report_layout(raw, url, csv_raw, pdf_text(archive / pdf_key / 'raw'))
            else:
                layout = archive_layout(raw, url, csv_raw)
            observation = date.fromisoformat(layout['observation_date'])
            fields = None
            csv_error = None
            try:
                fields = stock_fields(csv_raw, observation)
            except ValueError as error:
                csv_error = str(error)
            links = Links()
            links.feed(raw.decode('utf-8'))
            checks = {}
            attached_sources = {'pdf/wpsrall.pdf': publication_source} if publication_source else {}
            for suffix in ('pdf/table1.pdf', 'pdf/appendixb.pdf', 'pdf/appendix_e.pdf'):
                urls = dated_attachment_urls(raw, url, suffix)
                if len(urls) != 1:
                    if suffix == 'pdf/appendix_e.pdf' and not urls:
                        continue
                    raise ValueError(f'missing or ambiguous archived {suffix}')
                attachment_key = key + '-' + suffix.replace('/', '-')
                receipt, _ = load_capture(archive / attachment_key, attachment_key, urls[0])
                if receipt['status_code'] != 200:
                    raise ValueError(f'HTTP failure for {suffix}')
                text = pdf_text(archive / attachment_key / 'raw')
                attached_sources[suffix] = receipt
                if suffix == 'pdf/table1.pdf':
                    pdf_fields = pdf_stock_fields(text, observation)
                    if fields is not None:
                        try:
                            checks['stocks'] = pdf_stock_check(text, fields)
                        except ValueError as error:
                            csv_error = str(error)
                    if csv_error:
                        fields = pdf_fields
                        checks['stocks'] = {'units': 'million barrels', 'pdf_only_fallback': True,
                            'rejected_csv_reason': csv_error, 'field_precision_million_barrels': '0.1'}
                    else:
                        fields.update(units_verified=True, source_format='original dated Table 1 CSV confirmed by PDF',
                                      field_precision_million_barrels='0.001', commercial_definition_verified=True)
                elif suffix == 'pdf/appendixb.pdf':
                    linear = ' '.join(pdf_text(archive / attachment_key / 'raw', layout=False).split())
                    expected = 'it will be disseminated in the next regularly scheduled release of the weekly products'
                    checks['revision_policy_next_regular_release'] = expected in linear
                    if not checks['revision_policy_next_regular_release']:
                        raise ValueError('historical revision policy not established')
                else:
                    notices[receipt['sha256']] = {'url': urls[0], 'key': attachment_key,
                        'text': ' '.join(text.split()), 'reviewed': False}
            body = document_text(raw)
            # Keep concrete notice text for manual relevance/chronology review;
            # a production notice cannot silently stand in for a stocks revision.
            snippets = []
            for hit in re.finditer(r'\b(?:Notice|Correction|Revisions?|Errata)\b', body, re.IGNORECASE):
                snippets.append(body[max(0, hit.start()-70):hit.start()+650])
            records.append({'key': key, 'layout': layout, 'fields': fields, 'checks': checks,
                            'page_source': page_receipt, 'csv_source': csv_receipt,
                            'attached_sources': attached_sources, 'notice_snippets': snippets,
                            'release_notices': body.split('full report', 1)[-1].split('Highlights Weekly Petroleum Status Report Highlights', 1)[0].strip()})
        except FileNotFoundError:
            pending.append(key)
        except (ValueError, subprocess.CalledProcessError) as exc:
            failures.append({'key': key, 'error': str(exc)})
    return {'selected_reports': len(report_urls(raw_index)), 'validated_reports': len(records),
            'pending': pending, 'failures': failures, 'unusable_releases': unusable, 'records': records,
            'errata_documents': notices, 'archive_index': index_receipt,
            'vintage_admitted': False, 'strategy_signals_computed': False}


def prospectus_audit(archive=ARCHIVE):
    url = 'https://secure.alpsinc.com/MarketingAPI/api/v1/Content/uscfinvestments/united-states-oil-fund-pro-20260424.pdf'
    key = 'uso-prospectus-distributor-2026'
    receipt, raw = load_capture(archive / key, key, url)
    if receipt['status_code'] != 200 or receipt['sha256'] != '434772db779993120ec0f35d8ee7c3f637e718d741d6aef83793de8f6df56d3b':
        raise ValueError('USO prospectus capture changed')
    text = ' '.join(pdf_text(archive / key / 'raw', layout=False).split())
    terms = ('USO has not previously made any cash distributions',
             'Beginning with the monthly roll in September 2023 and ending with the monthly roll in January 2024',
             'Prior to January 1 2026, USO rolled its positions over a ten-day period instead of a five-day period',
             'during the Spring of 2020, USO had to rebalance and adjust the types of holdings in its portfolio')
    if any(term not in text for term in terms):
        raise ValueError('USO source disclosures do not establish reviewed exposure/cash facts')
    return {'source': receipt, 'prior_cash_distributions': False,
        'ordinary_cash_scope': 'Prospectus through Apr24 2026; Yahoo and Alpaca event inventories through Sep30 2026 separately required empty',
        'exposure_regimes': [
            {'name': 'pre_2020', 'start': '2018-01-01', 'end': '2020-01-01'},
            {'name': 'changed_2020_holdings', 'start': '2020-01-01', 'end': '2023-09-01',
             'caveat': 'Calendar-year bucket includes months before the spring2020 change; not a claimed exact change date'},
            {'name': 'transition_Sep2023_Jan2024', 'start': '2023-09-01', 'end': '2024-02-01'},
            {'name': 'later_10day_roll', 'start': '2024-02-01', 'end': '2026-01-01'},
            {'name': 'later_5day_roll', 'start': '2026-01-01', 'end': '2026-10-01'}]}


def freeze_source(eia, review, archive=ARCHIVE):
    """Freeze a fully reviewed source bundle, without calculating any signal."""
    from tradingbot.backtest.holdout import HoldoutSplit
    from tradingbot.connectors.cash import MarketSession
    if (eia['pending'] or eia['failures'] or not eia['records']
            or len(eia['records']) + len(eia['unusable_releases']) != eia['selected_reports']):
        raise ValueError('C08 EIA source audit incomplete or conflicting')
    audit_sha = sha(canonical(eia).encode())
    if (review.get('audit_sha256') != audit_sha or review.get('conclusion') != 'dated-original-archive-admitted'
            or review.get('strategy_outcomes_inspected') is not False
            or sorted(review.get('reviewed_errata_sha256', [])) != sorted(eia['errata_documents'])):
        raise ValueError('C08 revision/notice review does not cover this exact source audit')
    review_sources = {}
    for key, (url, digest) in REVIEW_SOURCES.items():
        receipt, _ = load_capture(archive / key, key, url)
        if receipt['status_code'] != 200 or receipt['sha256'] != digest:
            raise ValueError('C08 linked EIA notice evidence changed')
        review_sources[key] = receipt
    spy_receipt, spy = spy_source()
    selected = [r for r in spy['prices'] if START <= datetime.fromisoformat(r['closes_at']) < END]
    sessions = {date.fromisoformat(r['date']): MarketSession(date.fromisoformat(r['date']),
        date.fromisoformat(r['completed_settlement']), datetime.fromisoformat(r['opens_at']),
        datetime.fromisoformat(r['closes_at'])) for r in selected}
    prices, actions, disclosure = price_audit(sessions, archive), action_audit(sessions, archive), prospectus_audit(archive)
    if prices['failures'] or prices['coverage'].get('dividend_events'):
        raise ValueError('C08 prices or ordinary cash distributions are not admitted')
    raw = (ORIGINAL / 'USO/raw').read_text()
    chart = json.loads(raw)['chart']['result'][0]
    if chart.get('events', {}).get('dividends'):
        raise ValueError('USO ordinary distribution inventory is not empty')
    _, bars = parse_yahoo(raw)
    by_date = {bar.date: bar for bar in bars}
    dividends = {r['ex_date']: r['amount'] for r in spy['distributions']}
    rows = []
    for reference in selected:
        day = date.fromisoformat(reference['date'])
        bar = by_date[day]
        factor = Decimal('.125') if day < date(2020, 4, 29) else Decimal(1)
        rows.append({**reference, 'open': str(bar.open * factor), 'close': str(bar.close * factor),
                     'spy_close': reference['close'], 'spy_distribution': dividends.get(reference['date'], '0'),
                     'uso_split_continuous_close': str(bar.close)})
    releases = []
    for record in eia['records']:
        day = date.fromisoformat(record['layout']['release_date'])
        available = datetime.combine(day + timedelta(days=1), datetime.min.time(), ZoneInfo('America/New_York'))
        releases.append({'key': record['key'], 'release_date': str(day), 'available_at': available.isoformat(),
            **record['fields'], 'first_release_vintage_verified': False, 'dated_archive_vintage_admitted': True,
            'vintage_basis': 'dated primary archive plus contemporaneous methodology/revision-notice review; not independent capture on original release day',
            'source_sha256': record['attached_sources']['pdf/table1.pdf']['sha256']
                if record['checks']['stocks'].get('pdf_only_fallback') else record['csv_source']['sha256']})
    releases.sort(key=lambda r: (r['available_at'], r['observation_date']))
    if len({r['observation_date'] for r in releases}) != len(releases):
        raise ValueError('C08 archive has duplicate usable observation dates')
    blackouts = [{k: actions[k] for k in ('decision', 'exit', 'reentry', 'blackout_kind', 'announced_at')}]
    source = {'prices': rows, 'releases': releases, 'blackouts': blackouts,
              'exposure_regimes': disclosure['exposure_regimes'], 'unusable_releases': eia['unusable_releases']}
    raw_data = (json.dumps(source, sort_keys=True, indent=2) + '\n').encode()
    identity = {'data_sha256': sha(raw_data), 'eia_audit_sha256': audit_sha,
                'spy_calendar_benchmark_receipt_sha256': spy_receipt['receipt_sha256'],
                'uso_yahoo_sha256': prices['source']['sha256'], 'action_source': actions['broker_source'],
                'prospectus_sha256': disclosure['source']['sha256'], 'data_start': START.isoformat(), 'data_end': END.isoformat(),
                'policy': 'Amendment21; original dated EIA CSV confirmed by PDF or explicitly logged PDF-only fallback; missing reports no signal; 14-day expiry; conservative T+1 cash'}
    split = HoldoutSplit('c08-amendment21-' + sha(canonical(identity).encode())[:40], START, END)
    paths = ['src/tradingbot/research/c08_blackout.py', 'src/tradingbot/research/c08_source_audit.py',
             'src/tradingbot/research/c06_sources.py', 'src/tradingbot/research/c05_commodity_trend.py',
             'src/tradingbot/data/free_history.py', 'src/tradingbot/research/action_blackout.py',
             'src/tradingbot/data/equity_source_repair.py']
    manifest = {'status': 'SOURCE_ADMITTED_NO_STRATEGY_OUTCOMES', 'candidate': 'C08-amendment21',
        'identity': identity, 'split': split.metadata(), 'review': review, 'review_sources': review_sources,
        'source_code_sha256': {name: sha((ROOT / name).read_bytes()) for name in paths},
        'price_audit': prices, 'action_audit': actions, 'disclosure': disclosure,
        'sessions': len(rows), 'usable_releases': len(releases), 'unusable_releases': len(eia['unusable_releases']),
        'strategy_outcomes_inspected': False, 'training_cases_attempted': 0, 'final_holdout_attempts': 0}
    manifest['receipt_sha256'] = sha(canonical(manifest).encode())
    encoded = (json.dumps(manifest, sort_keys=True, indent=2) + '\n').encode()
    audit_bytes = (json.dumps(eia, sort_keys=True, indent=2) + '\n').encode()
    directory = archive / 'frozen-source-v1'
    with CaptureDiskBudget(ROOT / 'data').reserve(3 * (len(raw_data) + len(encoded) + len(audit_bytes)) + 65536):
        directory.mkdir(exist_ok=True)
        for name, content in [('data.json', raw_data), ('manifest.json', encoded), ('eia-audit.json', audit_bytes)]:
            path = directory / name
            if path.exists() and path.read_bytes() != content:
                raise ValueError('refuse replacement of C08 frozen source artifact')
            if not path.exists():
                path.write_bytes(content)
    return manifest


def capture_retry(key, url):
    """Retry transport failures only; completed HTTP receipts are immutable."""
    for attempt in range(3):
        try:
            return capture(key, url, archive=ARCHIVE)
        except requests.RequestException:
            if attempt == 2:
                raise
            time.sleep(1 + attempt)


def capture_report(url):
    key = 'report-' + Path(urlparse(url).path).stem.removeprefix('wpsr_')
    receipt = capture_retry(key, url)
    if receipt['status_code'] != 200:
        return {'key': key, 'status': receipt['status_code']}
    raw = load_capture(ARCHIVE / key, key, url)[1]
    csv_urls = attachment_urls(raw, url, 'csv/table1.csv')
    if not csv_urls and 'EIA - Sorry! Unexpected Error' in document_text(raw):
        return {'key': key, 'status': 200, 'unusable': 'EIA application error'}
    if len(csv_urls) != 1:
        raise ValueError('missing or ambiguous EIA table 1 CSV link')
    linked = [('table1', csv_urls[0])]
    parser = Links()
    parser.feed(raw.decode('utf-8'))
    for suffix in ('pdf/table1.pdf', 'pdf/appendixb.pdf', 'pdf/appendix_e.pdf'):
        matches = dated_attachment_urls(raw, url, suffix)
        if len(matches) > 1:
            raise ValueError(f'ambiguous {suffix} links in {url}')
        if matches:
            linked.append((suffix.replace('/', '-'), matches[0]))
    for kind, link in linked:
        if urlparse(link).netloc != 'www.eia.gov':
            raise ValueError('EIA archive attachment left primary host')
        capture_retry(key + '-' + kind, link)
        time.sleep(.25)
    if key in FULL_REPORT_PUBLICATION:
        urls = dated_attachment_urls(raw, url, 'pdf/wpsrall.pdf')
        if len(urls) != 1:
            raise ValueError('missing reviewed full-report publication proof')
        capture_retry(key + '-pdf-wpsrall.pdf', urls[0])
    return {'key': key, 'status': 200}


def capture_sources(*, limit: int | None = None, workers: int = 4):
    """Resumable primary-source capture under the shared 20GB/30GB disk limits."""
    _, index = load_capture(ORIGINAL / 'eia-index', 'eia-index', EIA_ROOT)
    urls = report_urls(index)
    if limit is not None:
        if limit < 1:
            raise ValueError('capture limit must be positive')
        urls = urls[:limit]
    if workers not in (1, 2, 3, 4):
        raise ValueError('capture allows one to four workers')
    CaptureDiskBudget(ROOT / 'data').check()
    failures = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(capture_report, url): url for url in urls}
        for i, future in enumerate(as_completed(futures), 1):
            try:
                result = future.result()
                if result['status'] != 200:
                    failures.append(result)
            except (requests.RequestException, ValueError) as exc:
                failures.append({'url': futures[future], 'error': str(exc)})
            if i % 10 == 0 or i == len(urls):
                print(json.dumps({'reports_finished': i, 'selected_reports': len(urls),
                                  'failures': failures}), flush=True)
    for key, url in METHOD_SOURCES.items():
        capture_retry(key, url)
    if failures:
        raise ValueError(f'incomplete EIA capture: {failures}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', action='store_true')
    parser.add_argument('--limit', type=int)
    args = parser.parse_args()
    if args.capture:
        capture_sources(limit=args.limit)


if __name__ == '__main__':
    main()
