"""Free adjusted-price capture and the coordinator's 99% / 5 bp comparison.

This module computes source-return discrepancies, never strategy outcomes.
No issuer/action ledger is required for the historical total-return model.
"""
from __future__ import annotations

import csv
from datetime import UTC, date, datetime
from decimal import Decimal as D
import hashlib
from io import StringIO
import json
from pathlib import Path

import pyarrow.parquet as pq
import requests

from tradingbot.data.alpaca_history import AlpacaHistoryAPI, DATA, NY, bars_page, bars_key
from tradingbot.data.archive import RawArchive, Request, SCHEMA, canonical
from tradingbot.data.disk_budget import CaptureDiskBudget
from tradingbot.data.free_history import USER_AGENT, load_capture
from tradingbot.forward.c05_readiness import ProbeBudget

ROOT = Path(__file__).resolve().parents[3]
ARCHIVE = ROOT / 'data/history/total-return-20261001'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def positive(value):
    value = D(str(value))
    if not value.is_finite() or value <= 0:
        raise ValueError('missing or invalid adjusted price')
    return value


def yahoo_prices(path, symbol, start, end):
    """Reuse original Yahoo bytes; adjusted open = raw open * adj-close/close."""
    manifest, bars = load_capture(path)
    raw = json.loads((path / 'raw.json').read_bytes())
    if raw['chart']['result'][0]['meta']['symbol'] != symbol:
        raise ValueError('Yahoo symbol differs from requested universe')
    rows = {}
    for bar in bars:
        if not start <= bar.date < end:
            continue
        if bar.date in rows:
            raise ValueError('duplicate primary session')
        factor = positive(bar.adj_close) / positive(bar.close)
        rows[bar.date] = {'open': positive(bar.open) * factor, 'close': positive(bar.adj_close),
                          'raw_open': positive(bar.open), 'raw_close': positive(bar.close),
                          'factor': factor}
    if not rows:
        raise ValueError('empty primary interval')
    return rows, {'source': 'Yahoo adjusted total return', 'symbol': symbol,
                   'raw_path': str((path / 'raw.json').relative_to(ROOT)),
                   'sha256': manifest['sha256'],
                   'manifest_sha256': sha((path / 'manifest.json').read_bytes()),
                   'first': str(min(rows)), 'last': str(max(rows)), 'sessions': len(rows)}


def cross_check(primary, secondary):
    """Compare same consecutive PRIMARY session endpoints; never bridge a gap.

Inputs map date -> positive adjusted close. Coverage is explicit; absent
secondary history is not silently counted as agreement or resliced training.
"""
    days = sorted(primary)
    for values in (primary, secondary):
        for value in values.values():
            positive(value)
    disagreements, missing, compared = [], [], []
    for previous, day in zip(days, days[1:]):
        if previous not in secondary or day not in secondary:
            missing.append(str(day))
            continue
        a = primary[day] / primary[previous] - 1
        b = secondary[day] / secondary[previous] - 1
        compared.append(str(day))
        delta = abs(a - b)
        if delta > D('.0005'):
            disagreements.append({'date': str(day), 'previous_session': str(previous),
                'primary_return': str(a), 'secondary_return': str(b), 'difference_bp': str(delta * 10000)})
    count = len(compared)
    agreed = count - len(disagreements)
    passed = count > 0 and agreed * 100 >= count * 99
    return {'passed': passed, 'tolerance_bp': '5', 'minimum_agreement_percent': '99',
            'primary_return_days': max(0, len(days) - 1), 'paired_return_days': count,
            'agreed_return_days': agreed, 'agreement_percent': str(D(agreed) * 100 / count) if count else None,
            'first_paired': compared[0] if compared else None,
            'last_paired': compared[-1] if compared else None,
            'unpaired_dates': missing, 'disagreeing_days': disagreements,
            'scope': 'paired consecutive sessions only; full primary interval retained, unmatched coverage disclosed'}


def capture_stooq(symbol, start, end, *, archive=ARCHIVE, budget=None):
    """Bounded public CSV request; retain challenge/error HTML without bypass."""
    folder = archive / ('stooq-' + symbol.lower())
    params = {'s': symbol.lower() + '.us', 'd1': start.strftime('%Y%m%d'),
              'd2': end.strftime('%Y%m%d'), 'i': 'd'}
    url = 'https://stooq.com/q/d/l/'
    if folder.exists():
        meta = json.loads((folder / 'manifest.json').read_bytes())
        raw = (folder / 'raw').read_bytes()
        if meta['url'] != url or meta['params'] != params or sha(raw) != meta['sha256']:
            raise ValueError('Stooq capture identity changed')
        return meta, raw
    budget, disk = budget or ProbeBudget(), CaptureDiskBudget(ROOT / 'data')
    disk.check_free(8_000_000 * 3)
    def fetch():
        with requests.get(url, params=params, headers={'User-Agent': USER_AGENT},
                          timeout=(5, 25), stream=True, allow_redirects=False) as response:
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > 8_000_000:
                    raise ValueError('Stooq response exceeds capture bound')
                chunks.append(chunk)
            raw = b''.join(chunks)
            return {'url': url, 'params': params, 'response_url': response.url,
                    'status': response.status_code, 'sha256': sha(raw), 'bytes': len(raw),
                    'retrieved_at': datetime.now(UTC).isoformat()}, raw
    meta, raw = budget.call(fetch)
    if meta['status'] != 200:
        budget.failure()
    with disk.reserve(3 * len(raw) + 65536):
        folder.mkdir(parents=True, exist_ok=False)
        (folder / 'raw').write_bytes(raw)
        (folder / 'manifest.json').write_text(json.dumps(meta, indent=2, sort_keys=True) + '\n')
    return meta, raw


def stooq_prices(raw):
    reader = csv.DictReader(StringIO(raw.decode('utf-8-sig')))
    if not reader.fieldnames or reader.fieldnames[:5] != ['Date', 'Open', 'High', 'Low', 'Close']:
        raise ValueError('Stooq returned no CSV price series')
    result = {}
    for row in reader:
        day = date.fromisoformat(row['Date'])
        if day in result:
            raise ValueError('duplicate secondary session')
        result[day] = positive(row['Close'])
    if not result:
        raise ValueError('empty secondary price series')
    return result


def capture_alpaca(symbols, start, end, *, feed='sip', adjustment='all', archive=ARCHIVE, budget=None):
    if feed not in ('sip', 'iex'):
        raise ValueError('unsupported free historical feed')
    if adjustment not in ('all', 'split'):
        raise ValueError('unsupported adjustment basis')
    params = {'symbols': ','.join(sorted(symbols)), 'timeframe': '1Day',
              'start': start.isoformat() + 'T00:00:00Z', 'end': end.isoformat() + 'T00:00:00Z',
              'adjustment': adjustment, 'feed': feed, 'limit': 10000, 'sort': 'asc', 'asof': '-'}
    raw = RawArchive(archive, 'alpaca', 'bars_1Day_' + adjustment + '_' + feed, 'total-return-20261001',
                     Request(DATA + '/stocks/bars', params),
                     semantics='Free historical adjusted daily bars, total-return research cross-check; not actual execution')
    api, budget, disk = AlpacaHistoryAPI(ROOT / '.env'), budget or ProbeBudget(), CaptureDiskBudget(ROOT / 'data')
    try:
        return raw.capture(lambda request: budget.call(lambda: api(request)), bars_page,
                           page_key=bars_key, max_pages=50,
                           write_guard=lambda size: disk.reserve(3 * size + 65536)).directory
    finally:
        api.close()


def alpaca_prices(folder, *, adjustment='all'):
    manifest = json.loads((folder / 'manifest.json').read_bytes())
    if sha(canonical(manifest).encode())[:24] != folder.name:
        raise ValueError('Alpaca archive identity changed')
    if (manifest['request']['url'] != DATA + '/stocks/bars'
            or manifest['request']['params'].get('adjustment') != adjustment
            or manifest['request']['params'].get('timeframe') != '1Day'):
        raise ValueError('adjusted daily Alpaca prices required')
    expected, result, hashes, pages = canonical(manifest['request']), {}, [], 0
    for index, path in enumerate(sorted(folder.glob('page-*.parquet'))):
        table = pq.read_table(path)
        if path.name != f'page-{index:08d}.parquet' or table.num_rows != 1 or not table.schema.equals(SCHEMA):
            raise ValueError('Alpaca page schema or sequence changed')
        row = table.to_pylist()[0]
        if row['request_json'] != expected or sha(row['response_json'].encode()) != row['response_sha256']:
            raise ValueError('Alpaca raw price checksum or request chain changed')
        payload = json.loads(row['response_json'], parse_float=D)
        count, next_request = bars_page(Request.from_json(expected), payload)
        expected = next_request.to_json() if next_request else None
        if count != row['record_count'] or expected != row['next_request_json']:
            raise ValueError('Alpaca page count or cursor changed')
        for symbol, bars in payload['bars'].items():
            target = result.setdefault(symbol, {})
            for bar in bars:
                day = datetime.fromisoformat(bar['t'].replace('Z', '+00:00')).astimezone(NY).date()
                if day in target:
                    raise ValueError('duplicate adjusted secondary session')
                target[day] = positive(bar['c'])
        hashes.append(row['response_sha256']); pages += 1
    if expected is not None or not pages:
        raise ValueError('incomplete adjusted price capture')
    return result, {'source': 'Alpaca adjusted ' + manifest['request']['params']['feed'],
                     'path': str(folder.relative_to(ROOT)), 'request': manifest['request'],
                     'response_hashes': hashes, 'pages': pages,
                     'manifest_sha256': sha((folder / 'manifest.json').read_bytes())}


def nasdaq_prices(symbol, start, end, *, archive=ARCHIVE, budget=None):
    """Public split-adjusted reference; dividend factor must come from elsewhere."""
    if not symbol.isalpha() or not symbol.isupper():
        raise ValueError('invalid reference symbol')
    folder = archive / ('nasdaq-' + symbol.lower())
    url = f'https://api.nasdaq.com/api/quote/{symbol}/historical'
    params = {'assetclass': 'etf', 'fromdate': start.isoformat(),
              'todate': end.isoformat(), 'limit': 10000}
    if not folder.exists():
        budget, disk = budget or ProbeBudget(), CaptureDiskBudget(ROOT / 'data')
        disk.check_free(24_000_000)
        def fetch():
            with requests.get(url, params=params, headers={'User-Agent': USER_AGENT,
                    'Accept': 'application/json, text/plain, */*'}, timeout=(5, 25),
                    stream=True, allow_redirects=False) as response:
                chunks, size = [], 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > 8_000_000:
                        raise ValueError('Nasdaq response exceeds capture bound')
                    chunks.append(chunk)
                raw = b''.join(chunks)
                return raw, {'url': url, 'params': params, 'status': response.status_code,
                    'retrieved_at': datetime.now(UTC).isoformat(), 'sha256': sha(raw)}
        raw, meta = budget.call(fetch)
        with disk.reserve(3 * len(raw) + 65536):
            folder.mkdir(parents=True, exist_ok=False)
            (folder / 'raw.json').write_bytes(raw)
            (folder / 'manifest.json').write_text(json.dumps(meta, indent=2, sort_keys=True) + '\n')
    raw = (folder / 'raw.json').read_bytes()
    meta = json.loads((folder / 'manifest.json').read_bytes())
    if meta['url'] != url or meta['params'] != params or meta['status'] != 200 or sha(raw) != meta['sha256']:
        raise ValueError('Nasdaq response identity, status or checksum changed')
    doc = json.loads(raw)['data']
    rows = doc['tradesTable']['rows']
    if doc['symbol'] != symbol or len(rows) != int(doc['totalRecords']):
        raise ValueError('missing Nasdaq rows or wrong symbol')
    result = {}
    for row in rows:
        day = datetime.strptime(row['date'], '%m/%d/%Y').date()
        if day in result or not start <= day <= end:
            raise ValueError('duplicate or out-of-range Nasdaq session')
        result[day] = positive(row['close'].replace('$', '').replace(',', ''))
    if not result:
        raise ValueError('empty Nasdaq reference')
    return result, {**meta, 'source': 'Nasdaq split-adjusted daily close',
                     'path': str(folder.relative_to(ROOT)), 'sessions': len(result)}


def dividend_adjusted_reference(split_closes, all_adjusted, split_adjusted):
    """Independent reference: no primary Yahoo price or factor is used."""
    return {day: positive(value) * positive(all_adjusted[day]) / positive(split_adjusted[day])
            for day, value in split_closes.items()}
