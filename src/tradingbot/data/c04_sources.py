"""C04 data audit: issuer distributions, exact sessions and immutable provenance.

No strategy returns are calculated here. The issuer's payment dates determine
cash availability; vendor adjusted prices never stand in for dividend cash.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal as D
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET

from tradingbot.backtest.holdout import HoldoutSplit
from tradingbot.data.archive import canonical
from tradingbot.data.free_history import load_capture, parse_yahoo
from tradingbot.research.equity_data import load_equities

START = datetime(2006, 1, 1, tzinfo=UTC)
END = datetime(2026, 10, 1, tzinfo=UTC)
NS = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
POLICY = {
    'execution': 'Yahoo unadjusted-for-dividend OHLC; SPY has no source splits',
    'signal': 'daily total return = (raw close + issuer ex-date distribution) / previous raw close - 1',
    'dividend': 'SSGA actual amount and payable date; entitlement before ex-date open; unpaid is a receivable',
    'yahoo_amounts': 'rounding to 0.001 except 2021-12-17: 1.633 vs issuer 1.636431; issuer authoritative',
    'settlement_required': 'T+1 current-account counterfactual; native historical T+3/T+2 dates are inadmissible',
    'crosscheck': 'IEX raw daily overlap; independent venue close within 1 percent; no price substitution',
    'prior_inspection': 'SPY overlaps previously inspected #5/#6/C01; diagnostic, not fresh unseen proof',
}


@dataclass(frozen=True)
class Distribution:
    ex_date: date
    record_date: date
    pay_date: date
    amount: D


@dataclass(frozen=True)
class PaymentDateAmendment:
    """One explicit, reviewed correction bound to original and primary evidence.

    This changes a derived row only. Both source files remain unmodified, and
    the default reader continues to reject the original contradiction.
    """
    source_sha256: str
    symbol: str
    original: Distribution
    corrected_pay_date: date
    evidence_path: Path
    evidence_sha256: str

    def verify(self, source_path: Path, symbol: str) -> None:
        if (symbol != self.symbol
                or hashlib.sha256(source_path.read_bytes()).hexdigest() != self.source_sha256
                or hashlib.sha256(self.evidence_path.read_bytes()).hexdigest() != self.evidence_sha256
                or self.corrected_pay_date == self.original.pay_date
                or self.corrected_pay_date < self.original.record_date):
            raise ValueError('payment amendment source, evidence or date mismatch')


def issuer_distributions(path: Path, symbol='SPY', *,
                         payment_amendment: PaymentDateAmendment | None = None) -> dict[date, Distribution]:
    """Read the issuer workbook without modifying it; reject formulas/duplicates.

    The pinned issuer sheet stores dates as MM/DD/YYYY strings. A changed layout
    must be audited explicitly rather than silently decoding numeric Excel dates.
    """
    if payment_amendment is not None:
        payment_amendment.verify(path, symbol)
    amended_rows = 0
    with ZipFile(path) as z:
        strings = [''.join(n.text or '' for n in si.findall('.//s:t', NS)).strip()
                   for si in ET.fromstring(z.read('xl/sharedStrings.xml'))]
        rows = ET.fromstring(z.read('xl/worksheets/sheet1.xml')).findall('.//s:row', NS)
        records = []
        for row in rows:
            values = {}
            for c in row.findall('s:c', NS):
                v = c.find('s:v', NS)
                if v is not None:
                    col = ''.join(ch for ch in c.attrib['r'] if ch.isalpha())
                    values[col] = strings[int(v.text)] if c.attrib.get('t') == 's' else v.text
            records.append((row, values))
    required = {'B':'TICKER', 'D':'EX-DATE', 'E':'RECORD DATE', 'F':'PAYABLE DATE',
                'G':'DIVIDEND ($)', 'H':'SHORT TERM CAPITAL GAIN ($)', 'I':'LONG TERM CAPITAL GAIN ($)'}
    header = records[0][1]
    normalize = lambda s: ' '.join(s.split())
    if any(normalize(header.get(k, '')) != v for k, v in required.items()):
        raise ValueError('issuer worksheet headers changed')
    out = {}
    for row, values in records[1:]:
        if values.get('B') != symbol:
            continue
        if row.findall('.//s:f', NS):
            raise ValueError('issuer distribution row contains formulas')
        ex, record, pay = (datetime.strptime(values[k], '%m/%d/%Y').date() for k in ('D','E','F'))
        amount = sum((D(values.get(k, '0').replace(',', '').strip() or '0') for k in ('G','H','I')), D(0))
        if payment_amendment is not None and ex == payment_amendment.original.ex_date:
            if Distribution(ex, record, pay, amount) != payment_amendment.original:
                raise ValueError('payment amendment does not match exact original row')
            pay = payment_amendment.corrected_pay_date
            amended_rows += 1
        if ex in out or not ex <= record <= pay or not amount.is_finite() or amount <= 0:
            raise ValueError(f'invalid or duplicated issuer distribution: {symbol} ex={ex}, record={record}, pay={pay}, amount={amount}')
        out[ex] = Distribution(ex, record, pay, amount)
    if not out:
        raise ValueError('issuer has no matching distributions')
    if payment_amendment is not None and amended_rows != 1:
        raise ValueError('payment amendment must match exactly one row')
    return out


def audit(root=Path('data/equities/c04'), yahoo=Path('data/equities/raw/free/SPY')):
    source, bars = load_capture(yahoo)
    raw_meta, _ = parse_yahoo((yahoo / 'raw.json').read_text())
    issuer_path = root / 'sources/ssga-historical-distributions.xlsx'
    issuer_meta = json.loads(issuer_path.with_suffix('.json').read_text())
    issuer_sha = hashlib.sha256(issuer_path.read_bytes()).hexdigest()
    if issuer_sha != issuer_meta['sha256']:
        raise ValueError('issuer checksum mismatch')
    distributions = {d:v for d,v in issuer_distributions(issuer_path).items() if START.date() <= d < END.date()}
    data = load_equities(root, 'c04-20261001')
    expected = {d for d,s in data.sessions.items() if START <= s.closes_at < END}
    actual = {b.date for b in bars}
    if actual != expected or len(actual) != len(bars) or raw_meta['null_rows']:
        raise ValueError(f'calendar coverage failure: missing={sorted(expected-actual)}, extra={sorted(actual-expected)}, nulls={raw_meta["null_rows"]}')
    if any(b.split_ratio != 1 or min(b.open,b.high,b.low,b.close,b.adj_close) <= 0
           or not b.low <= min(b.open,b.close) <= max(b.open,b.close) <= b.high for b in bars):
        raise ValueError('invalid prices or unsupported split')
    yahoo_divs = {b.date:b.dividend for b in bars if b.dividend}
    if yahoo_divs.keys() != distributions.keys():
        raise ValueError('issuer/Yahoo ex-date disagreement')
    differences = []
    for d, amount in yahoo_divs.items():
        diff = amount - distributions[d].amount
        if diff:
            differences.append({'ex_date': str(d), 'yahoo': str(amount), 'issuer': str(distributions[d].amount)})
        if abs(diff) > D('.0005') and not (d == date(2021,12,17) and amount == D('1.633') and distributions[d].amount == D('1.636431')):
            raise ValueError('unresolved distribution amount disagreement')
    overlap = data.daily('SPY')
    comparable = [(b, overlap[b.date]) for b in bars if b.date in overlap]
    if not comparable:
        raise ValueError('insufficient independent IEX overlap')
    worst = max(abs(b.close - o.close) / o.close for b,o in comparable)
    if worst > D('.01'):
        raise ValueError(f'unresolved independent raw-close disagreement: {worst}')
    # This known ordinary business week exposes native T+3 calendar history.
    # Never silently call it T+1 or replace it with a weekday approximation.
    if data.sessions[date(2006,1,3)].settlement_date != date(2006,1,4):
        raise ValueError('native historical settlement calendar is not the required T+1 counterfactual')
    identity = {'yahoo_sha256': source['sha256'], 'issuer_sha256': issuer_sha,
                'calendar_iex_sha256': data.source_hash, 'policy': POLICY,
                'data_start': START.isoformat(), 'data_end': END.isoformat()}
    digest = hashlib.sha256(canonical(identity).encode()).hexdigest()
    split = HoldoutSplit('sweep-c04-v1:' + digest, START, END)
    manifest = {'identity': identity, 'split': split.metadata(), 'sessions': len(bars),
                'distributions': len(distributions), 'distribution_reconciliations': differences,
                'iex_overlap_sessions': len(comparable), 'iex_worst_relative_close_difference': str(worst),
                'source_metadata': {'yahoo':source, 'issuer':issuer_meta},
                'missing_sessions': [], 'strategy_returns_inspected': False}
    return manifest, bars, distributions, data.sessions, split
