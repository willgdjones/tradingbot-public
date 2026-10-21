"""Read-only Alpaca SIP bars/calendar capture using official alpaca-py.

Exact API JSON is archived before SDK float parsing. No broker orders or accounts.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from alpaca.common.exceptions import APIError
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.historical.corporate_actions import CorporateActionsClient
from alpaca.trading.client import TradingClient
from dotenv import dotenv_values
import pyarrow.parquet as pq
from requests import RequestException
from requests.adapters import HTTPAdapter

from .archive import RawArchive, Request, canonical
from .transport import FetchError, RetryingGetter

DATA = 'https://data.alpaca.markets/v2'
PAPER = 'https://paper-api.alpaca.markets/v2'
ACTIONS = 'https://data.alpaca.markets/v1'
NY = ZoneInfo('America/New_York')
DEFAULT_ROOT = Path('data/equities')


class TimeoutAdapter(HTTPAdapter):
    def send(self, request, **kwargs):
        if request.method != 'GET':
            raise ValueError('historical client permits GET only')
        if kwargs.get('timeout') is None:
            kwargs['timeout'] = (5, 30)
        return super().send(request, **kwargs)


class AlpacaHistoryAPI:
    def __init__(self, env: Path = Path('.env')):
        values = dotenv_values(env)
        key, secret = values.get('ALPACA_PAPER_KEY'), values.get('ALPACA_PAPER_SECRET')
        if not key or not secret:
            raise ValueError('Alpaca paper credentials missing from .env')
        self.data = StockHistoricalDataClient(key, secret, raw_data=True)
        self.calendar = TradingClient(key, secret, raw_data=True, paper=True)
        self.actions = CorporateActionsClient(key, secret, raw_data=True)
        self.body = None
        for client in (self.data, self.calendar, self.actions):
            client._retry = 0
            client._session.mount('https://', TimeoutAdapter(max_retries=0))
            client._session.hooks['response'].append(self._capture)

    def _capture(self, response, *args, **kwargs):
        if response.status_code == 200:
            self.body = response.text
        else:
            raise FetchError(response.status_code, response.headers.get('Retry-After'))
        return response

    def __call__(self, request: Request) -> str:
        if request.url == DATA + '/stocks/bars':
            client, path = self.data, '/stocks/bars'
        elif request.url == ACTIONS + '/corporate-actions':
            client, path = self.actions, '/corporate-actions'
        elif request.url == PAPER + '/calendar':
            client, path = self.calendar, '/calendar'
        else:
            raise ValueError('endpoint outside read-only archive allowlist')
        self.body = None
        try:
            client.get(path, request.params)
        except (RequestException, APIError):
            raise FetchError(None) from None
        if self.body is None:
            raise ValueError('SDK response hook did not capture response text')
        return self.body

    def close(self):
        self.data._session.close()
        self.calendar._session.close()
        self.actions._session.close()


def bars_page(request: Request, payload) -> tuple[int, Request | None]:
    bars = payload.get('bars') if isinstance(payload, dict) else None
    if not isinstance(bars, dict) or 'next_page_token' not in payload:
        raise ValueError('malformed bar response')
    if any(not isinstance(rows, list) or not all(isinstance(row, dict) and 't' in row for row in rows) for rows in bars.values()):
        raise ValueError('malformed bars')
    count = sum(len(rows) for rows in bars.values())
    token = payload['next_page_token']
    if token is not None and (not isinstance(token, str) or not token or count == 0):
        raise ValueError('invalid bar page token')
    return count, Request(request.url, {**request.params, 'page_token': token}) if token else None


def bars_key(payload):
    bars = payload.get('bars', {})
    ids = sorted((symbol, row['t']) for symbol, rows in bars.items() for row in rows)
    return hashlib.sha256(canonical(ids).encode()).hexdigest() if ids else None


def calendar_page(request, payload):
    if not isinstance(payload, list) or not all(isinstance(row, dict) and {'date', 'open', 'close', 'settlement_date'} <= row.keys() for row in payload):
        raise ValueError('calendar missing session/settlement dates')
    return len(payload), None


def capture_calendar(get, root: Path, run: str, start: str, end: str):
    archive = RawArchive(root, 'alpaca', 'calendar', run, Request(PAPER + '/calendar', {'start': start, 'end': end}),
                         semantics='Official trading calendar with regular hours and API settlement_date; not account activity')
    progress = archive.capture(get, calendar_page)
    row = pq.read_table(progress.directory / 'page-00000000.parquet').to_pylist()[0]
    return progress, json.loads(row['response_json'])


def capture_bars(get, root: Path, run: str, *, symbols: list[str], timeframe: str,
                 start: str, end: str, adjustment='raw', max_pages=None):
    if timeframe not in {'1Day', '1Min'} or adjustment not in {'raw', 'all'}:
        raise ValueError('unsupported research bars specification')
    if not symbols or any(symbol not in {'SPY', 'QQQ'} for symbol in symbols):
        raise ValueError('research downloader supports SPY/QQQ only')
    params = {'symbols': ','.join(sorted(set(symbols))), 'timeframe': timeframe,
              'start': start, 'end': end, 'adjustment': adjustment,
              'feed': 'sip', 'limit': 10000, 'sort': 'asc', 'asof': '-'}
    archive = RawArchive(root, 'alpaca', 'bars_' + timeframe + '_' + adjustment, run,
                         Request(DATA + '/stocks/bars', params),
                         semantics='SIP aggregate bars; timestamp is interval START; never executable BBO or maker-fill evidence')
    return archive.capture(get, bars_page, page_key=bars_key, max_pages=max_pages)


def capture_actions(get, root, run, *, symbols, start, end):
    request = Request(ACTIONS + '/corporate-actions', {'symbols': ','.join(sorted(symbols)),
                      'start': start, 'end': end, 'limit': 1000, 'sort': 'asc'})
    def advance(request, payload):
        data = payload.get('corporate_actions')
        if not isinstance(data, dict) or 'next_page_token' not in payload:
            raise ValueError('invalid corporate action response')
        count = sum(len(rows) for rows in data.values())
        token = payload['next_page_token']
        return count, Request(request.url, {**request.params, 'page_token': token}) if token else None
    archive = RawArchive(root, 'alpaca', 'corporate_actions', run, request,
                         semantics='Corporate action reference evidence; coverage and ex dates must be validated')
    return archive.capture(get, advance)


def monthly_cycles(calendar: list[dict], through: date) -> list[tuple[dict, dict]]:
    groups = {}
    for row in calendar:
        groups.setdefault(row['date'][:7], []).append(row)
    for rows in groups.values():
        rows.sort(key=lambda row: row['date'])
    months = sorted(groups)
    pairs = []
    for left, right in zip(months, months[1:]):
        a, b = groups[left], groups[right]
        if len(a) < 4 or len(b) < 3:
            continue
        entry, exit = a[-4], b[2]
        if date.fromisoformat(exit['date']) <= through:
            pairs.append((entry, exit))
    return pairs


def tom_capture(get, root, run, start, through):
    day = date.fromisoformat(through)
    next_month = (day.replace(day=28) + timedelta(days=4)).replace(day=1)
    progress, calendar = capture_calendar(get, root, run, start, (next_month + timedelta(days=12)).isoformat())
    print(json.dumps(asdict(progress), default=str), flush=True)
    end = datetime.combine(day + timedelta(days=1), datetime.min.time(), UTC).isoformat()
    for adjustment in ('raw', 'all'):
        progress = capture_bars(get, root, run, symbols=['SPY'], timeframe='1Day', start=start, end=end, adjustment=adjustment)
        print(json.dumps(asdict(progress), default=str), flush=True)
    dates = {row['date']: row for pair in monthly_cycles(calendar, day) for row in pair}
    for index, row in enumerate(sorted(dates.values(), key=lambda row: row['date'])):
        close = datetime.fromisoformat(row['date'] + 'T' + row['close']).replace(tzinfo=NY)
        progress = capture_bars(get, root, run, symbols=['SPY'], timeframe='1Min',
                                start=(close - timedelta(minutes=2)).isoformat(),
                                end=(close - timedelta(microseconds=1)).isoformat())
        if (index + 1) % 25 == 0 or index + 1 == len(dates):
            print(json.dumps({'close_windows_complete': index + 1, 'total': len(dates), 'last_date': row['date']}), flush=True)


def letf_capture(get, root, run, start, through):
    first, last = date.fromisoformat(start), date.fromisoformat(through)
    if first < date(2023, 1, 1) or last > date(2026, 12, 31) or first > last:
        raise ValueError('LETF study is restricted to 2023–2026')
    progress, calendar = capture_calendar(get, root, run, start, (last + timedelta(days=10)).isoformat())
    print(json.dumps(asdict(progress), default=str), flush=True)
    end = datetime.combine(last + timedelta(days=1), datetime.min.time(), UTC).isoformat()
    for adjustment in ('raw', 'all'):
        progress = capture_bars(get, root, run, symbols=['SPY', 'QQQ'], timeframe='1Day', start=start, end=end, adjustment=adjustment)
        print(json.dumps(asdict(progress), default=str), flush=True)
    progress = capture_actions(get, root, run, symbols=['SPY', 'QQQ'], start=start, end=through)
    print(json.dumps(asdict(progress), default=str), flush=True)
    complete = 0
    for row in calendar:
        day = date.fromisoformat(row['date'])
        if day > last:
            continue
        close = datetime.fromisoformat(row['date'] + 'T' + row['close']).replace(tzinfo=NY)
        start_time = datetime.fromisoformat(row['date'] + 'T15:29:00').replace(tzinfo=NY)
        if close <= start_time + timedelta(minutes=1):
            continue
        capture_bars(get, root, run, symbols=['SPY', 'QQQ'], timeframe='1Min',
                     start=start_time.isoformat(), end=(close-timedelta(microseconds=1)).isoformat())
        complete += 1
        if complete % 50 == 0:
            print(json.dumps({'letf_sessions_complete': complete, 'last_date': row['date']}), flush=True)
    print(json.dumps({'letf_sessions_complete': complete, 'finished': True}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    parser.add_argument('--run', required=True)
    commands = parser.add_subparsers(dest='command', required=True)
    for command in ('calendar', 'bars', 'tom', 'letf', 'actions'):
        sub = commands.add_parser(command)
        sub.add_argument('--start', required=True)
        sub.add_argument('--end', required=True)
        if command in {'bars', 'actions'}:
            sub.add_argument('--symbols', nargs='+', choices=['SPY', 'QQQ'], required=True)
        if command == 'bars':
            sub.add_argument('--timeframe', choices=['1Day', '1Min'], default='1Day')
            sub.add_argument('--adjustment', choices=['raw', 'all'], default='raw')
            sub.add_argument('--max-pages', type=int)
    args = parser.parse_args()
    api = AlpacaHistoryAPI()
    get = RetryingGetter(api, interval=0.4)
    try:
        if args.command == 'tom':
            tom_capture(get, args.root, args.run, args.start, args.end)
        elif args.command == 'letf':
            letf_capture(get, args.root, args.run, args.start, args.end)
        elif args.command == 'actions':
            progress = capture_actions(get, args.root, args.run, symbols=args.symbols, start=args.start, end=args.end)
            print(json.dumps(asdict(progress), default=str))
        elif args.command == 'calendar':
            progress, _ = capture_calendar(get, args.root, args.run, args.start, args.end)
            print(json.dumps(asdict(progress), default=str))
        else:
            progress = capture_bars(get, args.root, args.run, symbols=args.symbols, timeframe=args.timeframe,
                                    start=args.start, end=args.end, adjustment=args.adjustment, max_pages=args.max_pages)
            print(json.dumps(asdict(progress), default=str))
    finally:
        api.close()


if __name__ == '__main__':
    main()
