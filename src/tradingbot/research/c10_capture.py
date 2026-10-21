"""Immutable source-only TLT capture; no strategy signals or return calculations."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path

import requests

from tradingbot.data.alpaca_history import AlpacaHistoryAPI, DATA, ACTIONS, bars_page, bars_key
from tradingbot.data.archive import RawArchive, Request
from tradingbot.data.disk_budget import CaptureDiskBudget
from tradingbot.data.free_history import USER_AGENT, YAHOO_CHART
from tradingbot.forward.c05_readiness import ProbeBudget

ROOT = Path(__file__).resolve().parents[3]
ARCHIVE = ROOT / 'data/history/c10-month-end-20261001'
RUN = 'c10-source-20261001'
START = datetime(2006, 1, 1, tzinfo=UTC)
END = datetime(2026, 10, 1, tzinfo=UTC)
PUBLIC = {
    'yahoo-tlt': (YAHOO_CHART.format(symbol='TLT'), {
        'period1': int(START.timestamp()), 'period2': int(END.timestamp()),
        'interval': '1d', 'events': 'div,split', 'includeAdjustedClose': 'true'}),
    'stooq-tlt': ('https://stooq.com/q/d/l/', {'s': 'tlt.us', 'd1': '20060101', 'd2': '20260930', 'i': 'd'}),
    'tlt-issuer': ('https://www.ishares.com/us/products/239454/ishares-20-year-treasury-bond-etf', None),
}
EVIDENCE = {
    'nasdaq-sandy-oct29': ('https://www.nasdaqtrader.com/TraderNews.aspx?id=ETA2012-44', None),
    'nasdaq-sandy-oct30': ('https://www.nasdaqtrader.com/TraderNews.aspx?id=ETA2012-45', None),
    'nasdaq-sandy-reopen': ('https://www.nasdaqtrader.com/TraderNews.aspx?id=ETA2012-48', None),
    'nyse-2024-2026': ('https://ir.theice.com/press/news-details/2023/NYSE-Group-Announces-2024-2025-and-2026-Holiday-and-Early-Closings-Calendar/default.aspx', None),
    'dtcc-tlt-name-2008': ('https://www.dtcc.com/~/media/Files/pdf/2008/12/9/OTC238.pdf', None),
    'blackrock-tlt-listing-2016': ('https://ir.blackrock.com/news-and-events/press-releases/press-releases-details/2016/BlackRock-Announces-Primary-Listing-Venue-Changes-for-11-iShares-ETFs/default.aspx', None),
    'sec-tlt-benchmark-2025': ('https://www.sec.gov/Archives/edgar/data/1100663/000119312525151221/d943072d497k.htm', None),
    'occ-sandy-settlement': ('https://infomemo.theocc.com/infomemos?date=201210&number=31464', None),
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(folder, url, params=None):
    meta = json.loads((folder / 'manifest.json').read_bytes())
    raw = (folder / 'raw').read_bytes()
    if (meta['url'] != url or meta['params'] != params or meta['sha256'] != sha(raw)
            or meta['bytes'] != len(raw)):
        raise ValueError('Source request identity or raw content changed')
    return meta, raw


def capture(folder, url, params=None, *, budget=None, limit=8_000_000):
    folder = folder.resolve()
    if not folder.is_relative_to(ARCHIVE) or folder == ARCHIVE:
        raise ValueError('Capture must be within C10 archive')
    allowed = {u for u, _ in (PUBLIC | EVIDENCE).values()}
    if url not in allowed:
        raise ValueError('Unregistered public source')
    if folder.exists():
        return read(folder, url, params)
    disk, budget = CaptureDiskBudget(ROOT / 'data'), budget or ProbeBudget()
    disk.check_free(limit * 3 + 65536)
    def fetch():
        with requests.get(url, params=params, headers={'User-Agent': USER_AGENT},
                          timeout=(5, 30), stream=True, allow_redirects=False) as response:
            chunks, length = [], 0
            for chunk in response.iter_content(65536):
                length += len(chunk)
                if length > limit:
                    raise ValueError('Source exceeds bounded response size')
                chunks.append(chunk)
            raw = b''.join(chunks)
            meta = {'url': url, 'params': params, 'response_url': response.url,
                    'status': response.status_code, 'sha256': sha(raw), 'bytes': len(raw),
                    'retrieved_at': datetime.now(UTC).isoformat(),
                    'content_type': response.headers.get('Content-Type')}
        return meta, raw
    meta, raw = budget.call(fetch)
    if meta['status'] != 200:
        budget.failure()
    with disk.reserve(3 * len(raw) + 65536):
        folder.mkdir(parents=True, exist_ok=False)
        (folder / 'raw').write_bytes(raw)
        (folder / 'manifest.json').write_text(json.dumps(meta, indent=2, sort_keys=True) + '\n')
    return meta, raw


def capture_api(api, budget):
    get = lambda request: budget.call(lambda: api(request))
    params = {'symbols': 'TLT', 'timeframe': '1Day', 'start': '2016-01-01T00:00:00Z',
              'end': '2026-10-01T00:00:00Z', 'adjustment': 'raw', 'feed': 'iex',
              'limit': 10000, 'sort': 'asc', 'asof': '-'}
    archive = RawArchive(ARCHIVE, 'alpaca', 'bars_1Day_raw_iex', RUN,
        Request(DATA + '/stocks/bars', params),
        semantics='Independent raw IEX daily open/close overlap; not execution BBO or full-history coverage')
    progress = archive.capture(get, bars_page, page_key=bars_key, max_pages=20)
    print(json.dumps({'source': 'iex-tlt', 'progress': str(progress.directory)}), flush=True)
    params = {'symbols': 'TLT', 'start': '2006-01-01', 'end': '2026-09-30',
              'data_quality': 'all', 'limit': 1000, 'sort': 'asc'}
    def advance(request, payload):
        groups = payload['corporate_actions']
        if not isinstance(groups, dict) or any(not isinstance(v, list) for v in groups.values()):
            raise ValueError('Invalid action groups')
        count = sum(len(v) for v in groups.values())
        token = payload['next_page_token']
        if token is not None and (not isinstance(token, str) or not token or not count):
            raise ValueError('Invalid action cursor')
        return count, Request(request.url, {**request.params, 'page_token': token}) if token else None
    archive = RawArchive(ARCHIVE, 'alpaca', 'corporate_actions', RUN,
        Request(ACTIONS + '/corporate-actions', params),
        semantics='All-type reference action inventory; vendor coverage/creation time need independent admission')
    progress = archive.capture(get, advance, max_pages=20)
    print(json.dumps({'source': 'actions-tlt', 'progress': str(progress.directory)}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('public', 'evidence', 'api'))
    args = parser.parse_args()
    budget = ProbeBudget()
    if args.stage in ('public', 'evidence'):
        for key, (url, params) in (PUBLIC if args.stage == 'public' else EVIDENCE).items():
            meta, _ = capture(ARCHIVE / key, url, params, budget=budget)
            print(json.dumps({'source': key, 'status': meta['status'], 'sha256': meta['sha256'],
                              'bytes': meta['bytes']}), flush=True)
    else:
        api = AlpacaHistoryAPI()
        try:
            capture_api(api, budget)
        finally:
            api.close()


if __name__ == '__main__':
    main()
