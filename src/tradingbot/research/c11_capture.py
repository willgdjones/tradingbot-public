"""Immutable public C11 calendar/execution evidence; no prices or strategy outcomes."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path

import requests

from tradingbot.data.disk_budget import CaptureDiskBudget
from tradingbot.data.alpaca_history import AlpacaHistoryAPI, ACTIONS
from tradingbot.data.archive import RawArchive, Request
from tradingbot.data.free_history import USER_AGENT
from tradingbot.forward.c05_readiness import ProbeBudget

ROOT = Path(__file__).resolve().parents[3]
ARCHIVE = ROOT / 'data/history/c11-expiry-20261001'
RUN = 'c11-source-20261001'
ACTION_REQUEST = Request(ACTIONS + '/corporate-actions', {
    'symbols': 'SPY', 'start': '2006-01-01', 'end': '2026-09-30',
    'data_quality': 'all', 'limit': 1000, 'sort': 'asc'})
SOURCES = {
    'cboe-calendar-index': 'https://www.cboe.com/about/hours/us-options/',
    'occ-calendar-index': 'https://www.optionseducation.org/referencelibrary/expiration-calendar',
    'occ-calendar-js': 'https://www.optionseducation.org/js/calendar.js?v=WPzIDGRFCEuzILp8LXGDfDAvSCqdY2rPoIcnENPcBZs',
    'occ-calendar-api': 'https://www.optionseducation.org/api/expirationcalendar',
    'cboe-2024': 'https://cdn.cboe.com/resources/options/Cboe2024OPTIONSCalendar.pdf',
    'cboe-2025': 'https://cdn.cboe.com/resources/options/Cboe2025OPTIONSCalendar.pdf',
    'cboe-2026': 'https://cdn.cboe.com/resources/options/Cboe2026OPTIONSCalendar.pdf',
    'occ-transition-2013': 'https://public-inspection.federalregister.gov/2013-14793.pdf',
    'cboe-transition-2013': 'https://cdn.cboe.com/resources/regulation/circulars/regulatory/RG-C2-2013-041.pdf',
    'cboe-weekdays-2022': 'https://ir.cboe.com/news/news-details/2022/Cboe-to-Add-Tuesday-and-Thursday-Expirations-for-SPX-Weeklys-Options-04-13-2022/default.aspx',
    'alpaca-fractional': 'https://docs.alpaca.markets/us/docs/fractional-trading.md',
    'alpaca-orders': 'https://docs.alpaca.markets/us/docs/orders-at-alpaca.md',
    'alpaca-action-docs': 'https://docs.alpaca.markets/us/reference/corporateactions-1.md',
    # Legacy path seen in historical search references; these are probes, not
    # asserted existing documents or proof of publication before a decision.
    'legacy-cboe-2009': 'https://www.cboe.com/AboutCBOE/xcal2009.pdf',
    'legacy-cboe-2006': 'https://www.cboe.com/AboutCBOE/xcal2006.pdf',
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(folder, url):
    meta = json.loads((folder / 'manifest.json').read_bytes())
    raw = (folder / 'raw').read_bytes()
    if (meta['url'] != url or meta['sha256'] != sha(raw) or meta['bytes'] != len(raw)
            or meta['method'] != 'GET' or meta['params'] is not None):
        raise ValueError('C11 source identity or checksum changed')
    return meta, raw


def capture(key, *, budget=None, limit=8_000_000):
    if key not in SOURCES:
        raise ValueError('unregistered C11 source')
    url, folder = SOURCES[key], ARCHIVE / key
    if folder.exists():
        return read(folder, url)
    disk, budget = CaptureDiskBudget(ROOT / 'data'), budget or ProbeBudget()
    disk.check_free(limit * 3 + 65536)
    def fetch():
        with requests.get(url, headers={'User-Agent': USER_AGENT}, timeout=(5, 30),
                          stream=True, allow_redirects=False) as response:
            chunks, length = [], 0
            for chunk in response.iter_content(65536):
                length += len(chunk)
                if length > limit:
                    raise ValueError('C11 response exceeds size bound')
                chunks.append(chunk)
            raw = b''.join(chunks)
            meta = {'url': url, 'method': 'GET', 'params': None, 'response_url': response.url,
                    'status': response.status_code, 'sha256': sha(raw), 'bytes': len(raw),
                    'retrieved_at': datetime.now(UTC).isoformat(),
                    'content_type': response.headers.get('Content-Type'),
                    'location': response.headers.get('Location')}
        return meta, raw
    meta, raw = budget.call(fetch)
    # Persist a failed response before updating the shared error-window guard.
    with disk.reserve(3 * len(raw) + 65536):
        folder.mkdir(parents=True, exist_ok=False)
        (folder / 'raw').write_bytes(raw)
        (folder / 'manifest.json').write_text(json.dumps(meta, indent=2, sort_keys=True) + '\n')
    if meta['status'] != 200:
        budget.failure()
    return meta, raw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('keys', nargs='*', choices=tuple(SOURCES))
    parser.add_argument('--actions', action='store_true', help='Read-only all-type SPY action query')
    args = parser.parse_args()
    budget = ProbeBudget()
    if args.actions:
        api = AlpacaHistoryAPI()
        try:
            result = capture_actions(api, budget)
            print(json.dumps({'actions_archive': str(result.directory)}))
        finally:
            api.close()
        return
    for key in args.keys or SOURCES:
        meta, _ = capture(key, budget=budget)
        print(json.dumps({'source': key, 'status': meta['status'], 'bytes': meta['bytes'],
                          'sha256': meta['sha256']}), flush=True)


def action_page(request, payload):
    groups, token = payload['corporate_actions'], payload['next_page_token']
    if not isinstance(groups, dict) or any(not isinstance(v, list) for v in groups.values()):
        raise ValueError('invalid action groups')
    count = sum(len(v) for v in groups.values())
    if token is not None and (not isinstance(token, str) or not token or not count):
        raise ValueError('invalid action cursor')
    return count, Request(request.url, {**request.params, 'page_token': token}) if token else None


def capture_actions(api, budget):
    archive = RawArchive(ARCHIVE, 'alpaca', 'corporate_actions', RUN, ACTION_REQUEST,
        semantics='All-type SPY corporate actions; processing-date bounds, not proof of full history or causal availability')
    return archive.capture(lambda request: budget.call(lambda: api(request)), action_page, max_pages=20)


if __name__ == '__main__':
    main()
