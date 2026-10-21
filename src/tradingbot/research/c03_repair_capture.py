"""Immutable, bounded public source capture for C03's historical cash repair."""
from datetime import UTC, datetime
import argparse
import hashlib
import json
from pathlib import Path

import requests

from tradingbot.data.disk_budget import CaptureDiskBudget
from tradingbot.data.free_history import USER_AGENT
from tradingbot.forward.c05_readiness import ProbeBudget

ROOT = Path(__file__).resolve().parents[3]
ARCHIVE = ROOT / 'data/history/c03-source-repair-20261001'
SOURCES = {
    'dividend-com': 'https://www.dividend.com/etfs/vnq-vanguard-real-estate-etf/',
    'stock-screener': 'https://stock-screener.org/vnq-dividend-history',
    'marketlog': 'https://www.marketlog.com/symbol/vnq-arcx/dividends',
    'investidor10': 'https://investidor10.com.br/etfs-global/vnq/',
    'vanguard-product': 'https://advisors.vanguard.com/investments/products/vnq/vanguard-real-estate-etf',
    'vanguard-product-script': 'https://advisors.vanguard.com/investments/products/assets/index-BE_OnPBx.js',
    'vanguard-2007-report': 'https://www.sec.gov/Archives/edgar/data/734383/000093247107001480/specializedfundsfinal.htm',
    'vnq-arca-listing-2008': 'https://www.nyse.com/publicdocs/nyse/markets/nyse-arca/rule-interpretations/2008/NYSEArca-RB-08-95.pdf',
    'divvydiary-june-2009': 'https://divvydiary.com/en/calendar/2009-june-30',
    'vanguard-product-page-script': 'https://advisors.vanguard.com/investments/products/assets/ProductPage-__rguhch.js',
    'vanguard-2010-report-mirror': 'https://www.collegecounts529.com/pdf/vgsix-ann.pdf',
    'vanguard-price-script': 'https://advisors.vanguard.com/investments/products/assets/Price-BM5WxWUc.js',
    'vanguard-distribution-store': 'https://advisors.vanguard.com/investments/products/assets/priceDistributionsStore-eyCappkh.js',
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def load(key, archive=ARCHIVE):
    folder = archive / key
    meta, raw = json.loads((folder / 'manifest.json').read_bytes()), (folder / 'raw').read_bytes()
    if (meta['url'] != SOURCES[key] or meta['sha256'] != sha(raw)
            or meta['bytes'] != len(raw)):
        raise ValueError('C03 source identity or bytes changed')
    return meta, raw


def capture(key, *, budget, archive=ARCHIVE, limit=8_000_000):
    url = SOURCES[key]
    folder = archive / key
    if folder.exists():
        return load(key, archive)
    disk = CaptureDiskBudget(ROOT / 'data')
    disk.check_free(limit * 3 + 65536)

    def fetch():
        with requests.get(url, headers={'User-Agent': USER_AGENT}, timeout=(5, 25),
                          stream=True, allow_redirects=False) as response:
            chunks, length = [], 0
            for chunk in response.iter_content(65536):
                length += len(chunk)
                if length > limit:
                    raise ValueError('C03 response exceeds size limit')
                chunks.append(chunk)
            raw = b''.join(chunks)
            return {'url': url, 'response_url': response.url, 'status': response.status_code,
                    'retrieved_at': datetime.now(UTC).isoformat(), 'bytes': len(raw),
                    'sha256': sha(raw), 'content_type': response.headers.get('Content-Type'),
                    'location': response.headers.get('Location')}, raw

    try:
        meta, raw = budget.call(fetch)
    except requests.RequestException as error:
        raw = b''
        meta = {'url': url, 'response_url': None, 'status': None,
                'retrieved_at': datetime.now(UTC).isoformat(), 'bytes': 0,
                'sha256': sha(raw), 'error_type': type(error).__name__}
    if meta['status'] is not None and meta['status'] != 200:
        budget.failure()
    meta['capture_code_sha256'] = sha(Path(__file__).read_bytes())
    with disk.reserve(len(raw) * 3 + 65536):
        folder.mkdir(parents=True, exist_ok=False)
        (folder / 'raw').write_bytes(raw)
        (folder / 'manifest.json').write_text(json.dumps(meta, indent=2, sort_keys=True) + '\n')
    return meta, raw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('keys', nargs='+', choices=list(SOURCES))
    args = parser.parse_args()
    budget = ProbeBudget()
    for key in args.keys:
        meta, _ = capture(key, budget=budget)
        print(json.dumps({'key': key, **meta}), flush=True)


if __name__ == '__main__':
    main()
