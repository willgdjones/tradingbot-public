"""Offline XLF action evidence audit; never produces prices, cash or returns."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, localcontext
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re

import pyarrow.parquet as pq

from tradingbot.data.archive import canonical

ROOT = Path(__file__).resolve().parents[3]
PRIOR = 'docs/research/13-equity-data-repair.json'
SOURCES = {
    'issuer_notice': ('data/equities/source-repair/xlf-2016-notice/raw.html',
                      'bafc28f7b4879d356d436c54f101c85557dd000b0362761c5b998eb6f170f67b'),
    'issuer_annual': ('data/equities/source-repair/xlf-2016-annual-report/raw.html',
                      '0d022f3c4e28dc4b1407bc51c5987a52a96b6cfd1828e47f3e7c5f9822de25f0'),
    'occ_39575': ('data/equities/source-repair/occ-xlf-distribution/raw.pdf',
                  '3a5069cec93883ab030aba57c7dc9d2cf2b343b4361683708ba56aba6e150273'),
    'issuer_8937': ('data/equities/xlf-action-repair/issuer-8937/raw.pdf',
                    '7533175812afe7d5924513b3cd6144bc6d5216aae76c01fe6070bd7db22ad551'),
    'yahoo_xlf': ('data/equities/c02/sources/XLF/raw.json',
                  '5021ca0002a2e7262257c4325174dff997ca5f2956ffdab89303e993f3374271'),
}
RATIO = Decimal('0.139146')
MISSING = (
    'Account-level whole/fractional allocation and rounding or retention rule for this action.',
    'If fractions are cashed out: actual calculation basis, amount, and availability evidence.',
    'Documented availability of delivered XLRE for sale; issuer pay date is not a broker credit.',
    'Independently validated actual-share XLRE execution prices for the declared disposal policy.',
)
POLICY = {
    'version': 'xlf-incidental-disposal-v1',
    'status': 'declared_before_outcomes_but_not_executable_until_source_admission',
    'entitlement': 'Nominal XLRE receivable = eligible actual XLF shares times 0.139146; no rounding assumption.',
    'ranking': 'XLRE is incidental inventory only, never an additional ranked candidate.',
    'retention': 'Retain the entitlement pending supported delivery; no discretionary long-term holding.',
    'disposal': 'Sell delivered tradable XLRE at the first regular-session open strictly after documented availability, using the candidate cost case and normal ledger/risk checks.',
    'fractional_cash': 'Keep any unresolved fraction pending; no zero write-off, synthetic sale, tax-value cash credit or estimated cash-in-lieu.',
    'sale_cash': 'Release sale proceeds only at the first regular-session open strictly after completed settlement under the frozen source calendar.',
    'cash_in_lieu': 'Release independently supported cash-in-lieu at the first regular-session open strictly after its documented availability date.',
    'income': 'Preserve any XLRE distribution receivable earned before disposal; validate its amount and payment terms before replay.',
    'failure': 'Missing delivery, fractional or execution evidence blocks the unchanged full sample; no deletion of the event, XLF, or adjacent dates.',
}


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def checked_bytes(path: Path, expected: str) -> bytes:
    raw = path.read_bytes()
    if sha(raw) != expected:
        raise ValueError(f'source checksum mismatch: {path.name}')
    return raw


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, value):
        self.parts.append(value)


def issuer_terms(raw: bytes) -> dict:
    parser = _Text()
    parser.feed(raw.decode('utf-8'))
    text = re.sub(r'\s+', ' ', ' '.join(parser.parts))
    patterns = {
        'record_date': r'Shareholders of record on ([A-Za-z]+ \d{1,2}, \d{4}) \(Record Date\)',
        'units_per_xlf_share': r'For each share of XLF held, an eligible shareholder received ([0-9.]+) shares of XLRE\.',
        'issuer_reported_pay_date': r'The special dividend was paid on ([A-Za-z]+ \d{1,2}, \d{4})\.',
    }
    result = {}
    for key, pattern in patterns.items():
        matches = re.findall(pattern, text)
        if len(matches) != 1:
            raise ValueError(f'missing or ambiguous issuer field: {key}')
        result[key] = matches[0]
    if Decimal(result['units_per_xlf_share']) != RATIO:
        raise ValueError('issuer ratio differs from the frozen action')
    for key in ('record_date', 'issuer_reported_pay_date'):
        result[key] = datetime.strptime(result[key], '%B %d, %Y').date().isoformat()
    if (result['record_date'], result['issuer_reported_pay_date']) != ('2016-09-21', '2016-09-22'):
        raise ValueError('issuer dates differ from the frozen action')
    return {'type': 'in_kind_distribution', 'source_asset': 'XLF', 'distribution_asset': 'XLRE',
            'ex_date': '2016-09-19', 'ex_date_source': 'occ_39575_background_and_issuer_8937_page3',
            **result, 'xlf_share_count_multiplier': '1', 'broker_available_at': None,
            'fractional_allocation': None, 'cash_in_lieu_amount': None, 'cash_available_at': None}


def nominal_entitlement(xlf_shares: Decimal) -> Decimal:
    """Unrounded units owed, NOT delivered inventory, spendable cash or an order."""
    if not xlf_shares.is_finite() or xlf_shares < 0:
        raise ValueError('eligible XLF shares must be finite and nonnegative')
    with localcontext() as ctx:
        ctx.prec = max(28, len(xlf_shares.as_tuple().digits) + len(RATIO.as_tuple().digits))
        return xlf_shares * RATIO


def provider_conflicts(payload: dict) -> dict:
    rows = [row for row in payload['corporate_actions']['cash_dividends']
            if row['symbol'] == 'XLF' and row['ex_date'] == '2016-09-19']
    if len(rows) != 1:
        raise ValueError('missing or ambiguous provider action')
    row = rows[0]
    if (Decimal(str(row['rate'])) != RATIO or row.get('record_date') != '2016-09-19'
            or row.get('payable_date') != '2016-09-22'):
        raise ValueError('provider evidence differs from archived conflict')
    return {'original_record': row, 'rejected_fields': {
        'cash_dividends.rate': '0.139146 denotes XLRE units, not USD per XLF share.',
        'record_date': 'Issuer date is 2016-09-21, not 2016-09-19.',
        'process_date': 'Provider processing date does not establish account credit or tradability.',
    }, 'accepted_corroboration': ['ex_date', 'payable_date']}


def audit(root: Path = ROOT) -> dict:
    raw = {key: checked_bytes(root / path, expected) for key, (path, expected) in SOURCES.items()}
    prior_bytes = (root / PRIOR).read_bytes()
    prior = json.loads(prior_bytes)
    diagnostic = next(x for x in prior['diagnostic_archives']
                      if x['request']['params'].get('symbols') == 'XLF,XLRE')
    rows = pq.read_table(root / diagnostic['path']).to_pylist()
    if len(rows) != 1:
        raise ValueError('expected a single archived corporate-action response')
    row = rows[0]
    if (sha(row['response_json'].encode()) != '41fa4bc16b940b297dce564ec1c969827dade3223f96b2fe26206ef58220545f'
            or json.loads(row['request_json']) != diagnostic['request'] or row['next_request_json'] is not None):
        raise ValueError('corporate-action provenance mismatch')
    yahoo = json.loads(raw['yahoo_xlf'])['chart']['result'][0]
    if yahoo['meta']['symbol'] != 'XLF':
        raise ValueError('wrong Yahoo symbol')
    events = yahoo['events']['splits']
    expected = {'1474291800': {'date': 1474291800, 'numerator': 1231.0,
                             'denominator': 1000.0, 'splitRatio': '1231:1000'}}
    if events != expected:
        raise ValueError('vendor action inventory changed')
    attempts = []
    for directory in sorted((root / 'data/equities/xlf-action-repair').iterdir()):
        manifest = directory / 'manifest.json'
        if not manifest.is_file():
            continue
        entry = json.loads(manifest.read_text())
        if entry.get('sha256'):
            body = next(directory.glob('raw.*'))
            checked_bytes(body, entry['sha256'])
        attempts.append({**entry, 'manifest_path': str(manifest.relative_to(root)),
                         'manifest_sha256': sha(manifest.read_bytes())})
    report = {
        'bead': 'tradingbot-vx0', 'status': 'UNRESOLVED_DATA_FAILURE', 'dataset_admitted': False,
        'bounds': {'start': '2006-01-01', 'end_exclusive': '2026-10-01',
                   'holdout_start': '2020-07-10T14:24:00+00:00'},
        'strategy_outcomes_computed': False, 'holdouts_consumed': 0,
        'scope': 'Source-only repair; original failed trials, source captures and candidate parameters unchanged.',
        'action': issuer_terms(raw['issuer_annual']),
        'issuer_tax_form': {'extraction': 'Manually verified all three rendered PDF pages; scanned PDF has no text layer.',
                            'signed_date': '2016-11-15', 'page': 3, 'total_distribution_per_xlf': '4.5292',
                            'return_of_capital_per_xlf': '2.9588', 'taxable_per_xlf': '1.5704',
                            'scope': 'Tax characterization only; no cash-in-lieu rate or broker availability.',
                            'source_typo_preserved': 'Page 3 says September 31, 2016; page 1 says September 30.'},
        'provider_conflicts': provider_conflicts(json.loads(row['response_json'])),
        'yahoo_rejected_split': {'original': events, 'reason': 'Economic adjustment is not an XLF share-count change.'},
        'nominal_unit_examples': {str(q): str(nominal_entitlement(q)) for q in (Decimal('1'), Decimal('100'))},
        'incidental_asset_policy': POLICY, 'missing_evidence': list(MISSING),
        'sources': {key: {'path': path, 'sha256': digest} for key, (path, digest) in SOURCES.items()},
        'provider_archive': diagnostic,
        'capture_attempts': attempts, 'prior_receipt': {'path': PRIOR, 'sha256': sha(prior_bytes)},
        'build_code': {'path': str(Path(__file__).relative_to(ROOT)), 'sha256': sha(Path(__file__).read_bytes())},
    }
    report['receipt_sha256'] = sha(canonical(report).encode())
    return report


if __name__ == '__main__':
    print(json.dumps(audit(), indent=2))
