"""Bounded immutable public Treasury captures for C09; no strategy outcomes."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re

import requests

from tradingbot.data.disk_budget import CaptureDiskBudget

ROOT = Path(__file__).resolve().parents[3]
ARCHIVE = ROOT / 'data/history/c09-auctions-20261001'
HOST = 'https://www.treasurydirect.gov'
INDEX_URL = HOST + '/TA_WS/securities/search'


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read(folder, filename, url, params=None):
    meta = json.loads((folder / 'manifest.json').read_text())
    raw = (folder / filename).read_bytes()
    if (meta['url'] != url or meta.get('params') != params
            or meta['sha256'] != digest(raw) or meta['bytes'] != len(raw)):
        raise ValueError('capture identity/checksum/length changed')
    return meta, raw


def capture(folder, filename, url, params=None, limit=4_000_000):
    if not url.startswith(HOST + '/'):
        raise ValueError('only public Treasury URLs are allowed')
    if (folder / 'manifest.json').exists():
        return read(folder, filename, url, params)
    if folder.exists():
        raise ValueError('incomplete capture must be preserved and reviewed')
    budget = CaptureDiskBudget(ROOT / 'data')
    budget.check_free(limit * 3 + 65536)
    with requests.get(url, params=params, timeout=(10, 45), stream=True) as response:
        if not response.url.startswith(HOST + '/'):
            raise ValueError('unexpected redirect away from Treasury')
        chunks, size = [], 0
        for chunk in response.iter_content(65536):
            size += len(chunk)
            if size > limit:
                raise ValueError('Treasury payload exceeds bounded capture')
            chunks.append(chunk)
        raw = b''.join(chunks)
        meta = {'url': url, 'params': params, 'final_url': response.url,
                'status': response.status_code, 'retrieved_at': datetime.now(UTC).isoformat(),
                'sha256': digest(raw), 'bytes': len(raw),
                'content_type': response.headers.get('Content-Type')}
    with budget.reserve(3 * len(raw) + 65536):
        folder.mkdir(parents=True)
        (folder / filename).write_bytes(raw)
        (folder / 'manifest.json').write_text(json.dumps(meta, indent=2, sort_keys=True) + '\n')
    return meta, raw


def index_params(year):
    return {'startDate': f'{year}-01-01',
            'endDate': '2026-09-30' if year == 2026 else f'{year}-12-31',
            'compact': 'true', 'dateFieldName': 'auctionDate', 'format': 'json'}


def index(year, fetch=False):
    function = capture if fetch else read
    meta, raw = function(ARCHIVE / f'auction-index-{year}', 'raw.json', INDEX_URL, index_params(year))
    if meta['status'] != 200:
        raise ValueError('Treasury index HTTP failure')
    rows = json.loads(raw)
    if not isinstance(rows, list) or not rows:
        raise ValueError('empty or changed Treasury index schema')
    keys = set()
    for row in rows:
        day = datetime.fromisoformat(row['i']).date()
        key = row['a'], str(day)
        if not f'{year}-01-01' <= str(day) <= index_params(year)['endDate'] or key in keys:
            raise ValueError('Treasury index date/uniqueness failure')
        keys.add(key)
        if not all(k in row for k in ('a', 'd', 'z3a', 't3a', 'h', 'e3', 'f3', 'f32')):
            raise ValueError('Treasury index missing required source fields')
    return meta, rows


def relevant(row):
    return row['z3a'] == 'Note' and row['t3a'] == '10-Year'


def document_url(year, filename):
    if not re.fullmatch(r'20\d{2}', str(year)) or not re.fullmatch(r'[A-Za-z0-9_.-]+\.pdf', filename):
        raise ValueError('invalid Treasury PDF name')
    return f'{HOST}/instit/annceresult/press/preanre/{year}/{filename}'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('indexes', 'notices', 'results'))
    args = parser.parse_args()
    for year in range(2005, 2027):
        meta, rows = index(year, fetch=args.stage == 'indexes')
        notes = [row for row in rows if relevant(row)]
        if args.stage in ('notices', 'results'):
            for row in notes:
                if args.stage == 'results':
                    names = [('results', row['i'][:4], row['f3'])]
                else:
                    names = [('offering', row['h'][:4], row['e3'])]
                    for name in filter(None, (s.strip() for s in row['f32'].split(','))):
                        match = re.search(r'SPL_(\d{4})', name)
                        names.append(('special', match[1] if match else row['i'][:4], name))
                for kind, pdf_year, name in names:
                    if not name:
                        continue  # Missing links remain an explicit audit failure.
                    result, _ = capture(ARCHIVE / kind / pdf_year / name, 'raw.pdf',
                                        document_url(pdf_year, name))
                    if result['status'] != 200:
                        print(json.dumps({'failed_document': name, 'status': result['status']}), flush=True)
        print(json.dumps({'year': year, 'all_auctions': len(rows), 'nominal_10_year': len(notes),
                          'missing_offering': sum(not r['e3'] for r in notes),
                          'special_links': sum(bool(r['f32']) for r in notes),
                          'sha256': meta['sha256']}), flush=True)


if __name__ == '__main__':
    main()
