"""Readmission of the original C03/C04 sources; no strategy outcomes here."""
from datetime import datetime
import json

from tradingbot.backtest.holdout import HoldoutSplit
from tradingbot.connectors.cash import NEW_YORK
from tradingbot.data.archive import canonical
from tradingbot.data.disk_budget import CaptureDiskBudget
from tradingbot.research.c06_sources import ROOT, START, END, sha, spy_source

ARCHIVE = ROOT / 'data/history/c03-c04-readmission-20261001'


def c04_source():
    receipt, spy = spy_source()
    dividends = {d['ex_date']: d for d in spy['distributions']}
    prices = [{**r, 'quotes': {'SPY': {'open': r['open'], 'close': r['close'],
        'distribution': dividends.get(r['date'], {}).get('amount', '0')}}} for r in spy['prices']]
    distributions = [{**r, 'symbol': 'SPY', 'cash_available_session':
        datetime.fromisoformat(r['conservative_cash_release']).astimezone(NEW_YORK).date().isoformat()}
        for r in spy['distributions']]
    body = {'candidate': 'C04', 'prices': prices, 'distributions': distributions, 'blackouts': []}
    raw = (canonical(body) + '\n').encode()
    identity = {'candidate': 'C04', 'data_sha256': sha(raw),
        'spy_source_receipt': receipt['receipt_sha256'],
        'policy_sha256': sha((ROOT / 'docs/research/24-c03-c04-readmission-plan.md').read_bytes()),
        'cash': receipt['identity']['policies']['cash'],
        'signal': 'causal daily (close + issuer ex-date amount)/previous close - 1; full preceding calendar month',
        'scope': 'SPY open/close only; no adjusted close, high, low or volume',
        'prior_failure': 3377, 'prior_inspection': 'SPY #5/#6/C01; diagnostic, no fresh unseen claim'}
    split = HoldoutSplit('c04-readmission-v1:' + sha(canonical(identity).encode()), START, END)
    manifest = {'status': 'SOURCE_ADMITTED_NO_STRATEGY_OUTCOMES', 'identity': identity,
        'split': split.metadata(), 'sessions': len(prices), 'distributions': len(distributions),
        'source_code_sha256': {name: sha((ROOT / name).read_bytes()) for name in (
            'src/tradingbot/research/c03_c04_sources.py', 'src/tradingbot/research/c06_sources.py')},
        'source_receipt': receipt, 'strategy_outcomes_inspected': False}
    manifest['receipt_sha256'] = sha(canonical(manifest).encode())
    path = ARCHIVE / 'c04-source-v1'
    with CaptureDiskBudget(ROOT / 'data').reserve(3 * len(raw) + 65536):
        path.mkdir(parents=True, exist_ok=True)
        for target, data in ((path / 'data.json', raw), (path / 'manifest.json',
                (json.dumps(manifest, indent=2, sort_keys=True) + '\n').encode())):
            if target.exists() and target.read_bytes() != data:
                raise ValueError('refuse replacement of frozen C04 source')
            target.write_bytes(data)
    (ROOT / 'docs/research/24-c03-c04-c04-source.json').write_text(json.dumps(manifest, indent=2, sort_keys=True)+'\n')
    return manifest


if __name__ == '__main__':
    result = c04_source()
    print(json.dumps({k: result[k] for k in ('status', 'receipt_sha256', 'sessions', 'distributions')}))
