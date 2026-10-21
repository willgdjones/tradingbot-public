"""Bounded immutable C13 documentation and existing paper-capability GETs."""
from datetime import UTC, datetime
import argparse
import hashlib
import json
from pathlib import Path

import requests

from tradingbot.data.alpaca_options import OptionsAPI
from tradingbot.data.disk_budget import CaptureDiskBudget
from tradingbot.data.free_history import USER_AGENT
from tradingbot.forward.c05_readiness import ProbeBudget

ROOT = Path(__file__).resolve().parents[3]
ARCHIVE = ROOT / 'data/history/c13-source-20261001'
SOURCES = {
    'historical-data': 'https://docs.alpaca.markets/us/docs/historical-option-data',
    'trading-options': 'https://docs.alpaca.markets/us/docs/options-trading',
    'contracts': 'https://docs.alpaca.markets/us/reference/get-options-contracts',
    'latest-quotes': 'https://docs.alpaca.markets/us/reference/optionlatestquotes',
    'fee-schedule': 'https://files.alpaca.markets/disclosures/library/BrokFeeSched.pdf',
    'regulatory-fees': 'https://docs.alpaca.markets/us/docs/regulatory-fees',
    'automatic-exercise': 'https://alpaca.markets/support/what-is-automatic-exercise',
    'broker-options': 'https://docs.alpaca.markets/us/docs/options-trading-overview',
    'option-ticks': 'https://alpaca.markets/support/options-pricing-increments-and-options-order-handling',
    'option-fees': 'https://alpaca.markets/support/what-are-the-fees-associated-with-options-trading',
    'dne-support': 'https://alpaca.markets/support/what-is-a-do-not-exercise-dne-and-how-can-i-place-a-dne-on-my-options-position',
    'paper-capability': 'https://paper-api.alpaca.markets/v2/account',
}
ACCOUNT_FIELDS = ('status', 'currency', 'options_approved_level', 'options_trading_level',
                  'trading_blocked', 'account_blocked', 'trade_suspended_by_user')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def load(key, archive=ARCHIVE):
    folder = archive / key
    meta = json.loads((folder / 'manifest.json').read_bytes())
    raw = (folder / 'raw').read_bytes()
    if (meta['url'] != SOURCES[key] or meta['method'] != 'GET'
            or meta['sha256'] != sha(raw) or meta['bytes'] != len(raw)):
        raise ValueError('C13 source identity or bytes changed')
    code = (archive / 'capture-code' / (meta['capture_code_sha256'] + '.py')).read_bytes()
    if sha(code) != meta['capture_code_sha256']:
        raise ValueError('C13 capture code changed')
    return meta, raw


def capture(key, *, budget, archive=ARCHIVE, limit=8_000_000):
    folder = archive / key
    if folder.exists():
        return load(key, archive)
    url = SOURCES[key]
    disk = CaptureDiskBudget(ROOT / 'data')
    disk.check_free(limit * 3 + 65536)

    def fetch():
        if key == 'paper-capability':
            api = OptionsAPI(ROOT / '.env')
            try:
                api.body = None
                api.trading.get_account()
                if api.body is None:
                    raise ValueError('SDK did not capture raw account response')
                full = api.body.encode()
                obj = json.loads(full)
                raw = json.dumps({k: obj.get(k) for k in ACCOUNT_FIELDS}, sort_keys=True).encode()
                return {'url': url, 'response_url': url, 'status': 200,
                        'retrieved_at': datetime.now(UTC).isoformat(),
                        'bytes': len(raw), 'sha256': sha(raw),
                        'source_response_sha256': sha(full),
                        'retention': 'whitelisted projection only; full account body not retained'}, raw
            finally:
                api.close()
        with requests.get(url, headers={'User-Agent': USER_AGENT}, timeout=(5, 25),
                          stream=True, allow_redirects=False) as response:
            chunks, length = [], 0
            for chunk in response.iter_content(65536):
                length += len(chunk)
                if length > limit:
                    raise ValueError('C13 response exceeds size limit')
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
    code = Path(__file__).read_bytes()
    meta.update(method='GET', capture_code_sha256=sha(code))
    with disk.reserve(len(raw) * 3 + len(code) * 3 + 65536):
        folder.mkdir(parents=True, exist_ok=False)
        codes = archive / 'capture-code'
        codes.mkdir(exist_ok=True)
        source = codes / (sha(code) + '.py')
        if not source.exists():
            source.write_bytes(code)
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
        print(json.dumps({'key': key, 'status': meta['status'], 'sha256': meta['sha256']}), flush=True)


if __name__ == '__main__':
    main()
