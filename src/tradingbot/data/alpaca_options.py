"""Free, read-only options research archive; never supplies executable quotes.

Current indicative snapshots and provider historical bars/trades stay distinct.
No option orders, exercises, subscriptions or account-permission changes.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import re

from alpaca.common.exceptions import APIError
from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.trading.client import TradingClient
from dotenv import dotenv_values
import pyarrow.parquet as pq
from requests import RequestException

from .alpaca_history import TimeoutAdapter
from .archive import RawArchive, Request, canonical
from .bulk_history import write_json
from .disk_budget import CaptureDiskBudget
from .transport import FetchError, RetryingGetter

DATA = 'https://data.alpaca.markets/v1beta1/options'
PAPER = 'https://paper-api.alpaca.markets/v2/options/contracts'
HISTORY_START = datetime(2024, 2, 1, tzinfo=UTC)
SYMBOL = re.compile(r'[A-Z][A-Z0-9.]{0,15}')
CONTRACT = re.compile(r'[A-Z][A-Z0-9.]{0,6}\d{6}[CP]\d{8}')


def stamp(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Use a timezone-aware timestamp')
    return parsed.astimezone(UTC)


def symbols(value, *, options=False):
    values = sorted(set(value.split(',')))
    pattern = CONTRACT if options else SYMBOL
    if not values or len(values) > 100 or any(not pattern.fullmatch(v) for v in values):
        raise ValueError('Use 1..100 explicit normalized symbols')
    return values


def endpoint(request):
    """GET surfaces only; explicit indicative feed on contemporary data."""
    if request.url == PAPER:
        return 'trading', '/options/contracts'
    suffix = request.url.removeprefix(DATA)
    if request.url.startswith(DATA + '/') and suffix in {'/bars', '/trades'}:
        if 'feed' in request.params:
            raise ValueError('Historical feed is provider-defined; do not mislabel it indicative')
        return 'data', '/options' + suffix
    if (request.url == DATA + '/quotes/latest'
            or request.url.startswith(DATA + '/snapshots/')
            and SYMBOL.fullmatch(suffix.removeprefix('/snapshots/'))):
        if request.params.get('feed') != 'indicative':
            raise ValueError('Only the free indicative snapshot feed is permitted')
        return 'data', '/options' + suffix
    raise ValueError('Endpoint outside read-only options archive allowlist')


class OptionsAPI:
    def __init__(self, env=Path('.env')):
        values = dotenv_values(env)
        key, secret = values.get('ALPACA_PAPER_KEY'), values.get('ALPACA_PAPER_SECRET')
        if not key or not secret:
            raise ValueError('Existing Alpaca paper credentials required in .env')
        self.data = OptionHistoricalDataClient(key, secret, raw_data=True)
        self.trading = TradingClient(key, secret, paper=True, raw_data=True)
        self.body = None
        for client in (self.data, self.trading):
            client._retry = 0
            client._session.mount('https://', TimeoutAdapter(max_retries=0))
            client._session.hooks['response'].append(self._capture)

    def _capture(self, response, *args, **kwargs):
        if response.status_code != 200:
            raise FetchError(response.status_code, response.headers.get('Retry-After'))
        self.body = response.text
        return response

    def __call__(self, request):
        target, path = endpoint(request)
        self.body = None
        try:
            getattr(self, target).get(path, request.params)
        except (RequestException, APIError):
            raise FetchError(None) from None
        if self.body is None:
            raise ValueError('SDK did not capture raw response')
        return self.body

    def close(self):
        self.data._session.close()
        self.trading._session.close()


def build_request(kind, *, underlying=None, option_symbols=None, expiry_from=None,
                  expiry_to=None, status='active', start=None, end=None, timeframe='1Day', now=None):
    if kind in {'contracts', 'chain'}:
        if not underlying or not SYMBOL.fullmatch(underlying):
            raise ValueError('One explicit underlying is required')
        if not expiry_from or not expiry_to or expiry_from > expiry_to:
            raise ValueError('Explicit ordered expiry bounds are required')
        params = {'expiration_date_gte': expiry_from.isoformat(),
                  'expiration_date_lte': expiry_to.isoformat(), 'limit': 1000}
        if kind == 'contracts':
            if status not in {'active', 'inactive'}:
                raise ValueError('Explicit active/inactive contract status required')
            return Request(PAPER, {**params, 'underlying_symbols': underlying,
                                  'status': status, 'show_deliverables': True})
        return Request(DATA + '/snapshots/' + underlying, {**params, 'feed': 'indicative'})
    selected = symbols(option_symbols or '', options=True)
    params = {'symbols': ','.join(selected)}
    if kind == 'quotes':
        return Request(DATA + '/quotes/latest', {**params, 'feed': 'indicative'})
    if kind not in {'bars', 'trades'}:
        raise ValueError('Unknown options dataset')
    if start is None or end is None:
        raise ValueError('History requires explicit inclusive start/end')
    start, end = stamp(start), stamp(end)
    now = now or datetime.now(UTC)
    if not HISTORY_START <= start < end <= now - timedelta(minutes=16):
        raise ValueError('Historical bounds must start Feb 2024+ and end at least 16 minutes ago')
    params.update(start=start.isoformat(), end=end.isoformat(), limit=10000, sort='asc')
    if kind == 'bars':
        if timeframe not in {'1Min', '1Hour', '1Day'}:
            raise ValueError('Choose 1Min, 1Hour or 1Day')
        params['timeframe'] = timeframe
    return Request(DATA + '/' + kind, params)


def rows_for(kind, payload):
    if not isinstance(payload, dict):
        raise ValueError('Expected response object')
    key = {'contracts': 'option_contracts', 'chain': 'snapshots', 'quotes': 'quotes'}.get(kind, kind)
    if key not in payload:
        raise ValueError('Missing options response data field')
    data = payload.get(key)
    if kind == 'contracts':
        if not isinstance(data, list) or any(not isinstance(r, dict) or not r.get('symbol') for r in data):
            raise ValueError('Malformed contract catalog')
        return [(r['symbol'], r) for r in data]
    if data is None and kind in {'bars', 'trades'}:
        data = {}  # documented empty historical result; never a zero price
    if not isinstance(data, dict):
        raise ValueError('Malformed symbol map')
    rows = []
    for symbol, values in data.items():
        if kind not in {'bars', 'trades'}:
            values = [values]
        if not isinstance(values, list) or any(not isinstance(v, dict) for v in values):
            raise ValueError('Malformed option observations')
        for row in values:
            if kind in {'quotes', 'bars', 'trades'} and 't' not in row:
                raise ValueError('Missing observation timestamp')
            rows.append((symbol, row))
    return rows


def advance_for(kind):
    def advance(request, payload):
        rows = rows_for(kind, payload)
        selected = set(request.params.get('symbols', '').split(',')) - {''}
        if selected and any(symbol not in selected for symbol, _ in rows):
            raise ValueError('Response contains an unrequested option symbol')
        if kind in {'bars', 'trades'}:
            lo, hi = stamp(request.params['start']), stamp(request.params['end'])
            if any(not lo <= stamp(row['t']) <= hi for _, row in rows):
                raise ValueError('Historical observation lies outside the requested bounds')
        if kind == 'contracts':
            for _, row in rows:
                expiry = row.get('expiration_date', '')
                if (row.get('underlying_symbol') != request.params['underlying_symbols']
                        or not request.params['expiration_date_gte'] <= expiry <= request.params['expiration_date_lte']):
                    raise ValueError('Contract lies outside the requested underlying/expiry scope')
        if kind == 'quotes':
            return len(rows), None
        if 'next_page_token' not in payload:
            raise ValueError('Missing pagination state')
        token = payload['next_page_token']
        if token is not None and (not isinstance(token, str) or not token or not rows):
            raise ValueError('Invalid pagination token')
        return len(rows), Request(request.url, {**request.params, 'page_token': token}) if token else None
    return advance


def page_key(kind, payload):
    keys = [(symbol, row.get('t'), row.get('i')) for symbol, row in rows_for(kind, payload)]
    return sha256(canonical(sorted(keys)).encode()).hexdigest() if keys else None


def capture(get, root, run, kind, request, *, budget_root=Path('data'), max_pages=100):
    root, budget_root = Path(root), Path(budget_root)
    if not root.resolve().is_relative_to(budget_root.resolve()):
        raise ValueError('Options archive must stay inside the globally budgeted data tree')
    endpoint(request)
    budget = CaptureDiskBudget(budget_root)
    budget.check()
    semantics = ('current indicative snapshot; modified quotes/delayed derived trades; '
                 'available no earlier than retrieval; not executable or historical BBO'
                 if kind in {'chain', 'quotes'} else
                 'current contract metadata snapshot, not historical chain membership'
                 if kind == 'contracts' else
                 'provider historical options ' + kind + '; feed unspecified by endpoint; '
                 'not historical BBO and not eligible for executable-fill proof')
    archive = RawArchive(root, 'alpaca', 'options_' + kind, run, request, semantics=semantics)
    return archive.capture(budget.getter(RetryingGetter(get, interval=.6)), advance_for(kind),
        max_pages=max_pages, page_key=lambda payload: page_key(kind, payload), write_guard=budget.reserve)


def audit(directory):
    directory = Path(directory)
    manifest = json.loads((directory/'manifest.json').read_text())
    kind = manifest['dataset'].removeprefix('options_')
    expected = Request(**manifest['request'])
    selected = set(expected.params.get('symbols', '').split(',')) - {''}
    initial = expected
    seen, stats, hashes = set(), {}, []
    retrieved = []
    files = sorted(directory.glob('page-*.parquet'))
    for n, path in enumerate(files):
        if expected is None or path.name != f'page-{n:08d}.parquet':
            raise ValueError('Broken options archive page sequence')
        page = pq.ParquetFile(path).read().to_pylist()[0]
        if page['request_json'] != expected.to_json():
            raise ValueError('Broken options request chain')
        if sha256(page['response_json'].encode()).hexdigest() != page['response_sha256']:
            raise ValueError('Options response checksum mismatch')
        payload = json.loads(page['response_json'], parse_float=Decimal)
        # Raw JSON remains exact; structural pagination operates on normal JSON.
        count, next_request = advance_for(kind)(expected, json.loads(page['response_json']))
        if count != page['record_count'] or (next_request.to_json() if next_request else None) != page['next_request_json']:
            raise ValueError('Options response pagination/count mismatch')
        key = page_key(kind, json.loads(page['response_json']))
        if key and key in seen:
            raise ValueError('Repeated options observations page')
        seen.add(key)
        retrieved.append(page['retrieved_at'].isoformat())
        hashes.append(page['response_sha256'])
        for symbol, row in rows_for(kind, payload):
            item = stats.setdefault(symbol, {'records': 0, 'first_observation': None, 'last_observation': None})
            item['records'] += 1
            if kind == 'contracts':
                item['contract'] = json.loads(json.dumps({k: row.get(k) for k in ('id', 'underlying_symbol', 'root_symbol',
                    'expiration_date', 'type', 'style', 'strike_price', 'size', 'status',
                    'tradable', 'deliverables', 'open_interest', 'open_interest_date')}, default=str))
            quote = row.get('latestQuote') if kind == 'chain' else row if kind == 'quotes' else None
            if isinstance(quote, dict):
                item['quote'] = {k: str(quote[k]) if isinstance(quote.get(k), Decimal) else quote.get(k)
                                 for k in ('t', 'bp', 'ap', 'bs', 'as', 'bx', 'ax')}
                item['quote_available_no_earlier_than'] = page['retrieved_at'].isoformat()
                if quote.get('t'):
                    item['quote_age_seconds_at_retrieval'] = (page['retrieved_at'] - stamp(quote['t'])).total_seconds()
            ts = quote.get('t') if isinstance(quote, dict) else row.get('t')
            if ts:
                item['first_observation'] = min(item['first_observation'] or ts, ts)
                item['last_observation'] = max(item['last_observation'] or ts, ts)
        expected = next_request
    return {'directory': str(directory), 'dataset': kind, 'request': json.loads(initial.to_json()),
            'complete': bool(files) and expected is None, 'pages': len(files),
            'records': sum(s['records'] for s in stats.values()), 'symbols': stats,
            'requested_symbols_with_no_records': sorted(selected - stats.keys()),
            'retrieved_first': min(retrieved) if retrieved else None,
            'retrieved_last': max(retrieved) if retrieved else None,
            'response_set_sha256': sha256(canonical(hashes).encode()).hexdigest(),
            'semantics': manifest['semantics'], 'executable_fill_evidence': False,
            'historical_chain_membership': False, 'historical_bbo': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', choices=['contracts', 'chain', 'quotes', 'bars', 'trades', 'audit'])
    parser.add_argument('--run-id')
    parser.add_argument('--root', type=Path, default=Path('data/options'))
    parser.add_argument('--underlying')
    parser.add_argument('--symbols')
    parser.add_argument('--expiry-from', type=date.fromisoformat)
    parser.add_argument('--expiry-to', type=date.fromisoformat)
    parser.add_argument('--status', choices=['active', 'inactive'], default='active')
    parser.add_argument('--start'); parser.add_argument('--end')
    parser.add_argument('--timeframe', default='1Day')
    parser.add_argument('--max-pages', type=int, default=100)
    parser.add_argument('--directory', type=Path)
    args = parser.parse_args(argv)
    if args.kind == 'audit':
        if not args.directory:
            parser.error('audit requires --directory')
        print(json.dumps(audit(args.directory), indent=2))
        return
    if not args.run_id:
        parser.error('capture requires --run-id; new current snapshots need a new run')
    request = build_request(args.kind, underlying=args.underlying, option_symbols=args.symbols,
        expiry_from=args.expiry_from, expiry_to=args.expiry_to, status=args.status,
        start=args.start, end=args.end, timeframe=args.timeframe)
    api = OptionsAPI()
    try:
        progress = capture(api, args.root, args.run_id, args.kind, request, max_pages=args.max_pages)
    finally:
        api.close()
    result = audit(progress.directory)
    budget = CaptureDiskBudget(Path('data'))
    write_json(args.root/'audits'/f'{args.run_id}-{args.kind}-{progress.directory.name}.json', result, budget)
    print(json.dumps({**asdict(progress), 'directory': str(progress.directory),
                      'archive_records': result['records'], 'symbols': len(result['symbols'])}))


if __name__ == '__main__':
    main()
