from datetime import date
from decimal import Decimal as D
import json
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET

import pytest

from tradingbot.data.archive import RawArchive, Request
from tradingbot.data.free_history import DailyBar
from tradingbot.research import c07_blackout_sources as m


def workbook(path, edits=None):
    ns = m.NS['s']
    root = ET.Element(f'{{{ns}}}worksheet')
    data = ET.SubElement(root, f'{{{ns}}}sheetData')
    header = {'B': 'TICKER', 'D': 'EX-DATE', 'E': 'RECORD DATE', 'F': 'PAYABLE DATE',
              'G': 'DIVIDEND ($)', 'H': 'SHORT TERM CAPITAL GAIN ($)', 'I': 'LONG TERM CAPITAL GAIN ($)'}
    rows = [header]
    for s in m.UNIVERSE:
        rows.append({'B': s, 'D': '03/18/2016', 'E': '03/22/2016', 'F': '03/29/2016', 'G': '0.1'})
    rows += [
        {'B': 'XLK', 'D': '06/16/2006', 'E': '06/20/2006', 'F': '06/28/2006', 'G': '0'},
        {'B': 'XLK', 'D': '03/16/2007', 'E': '03/20/2007', 'F': '03/28/2007', 'G': '0'},
        {'B': 'XLF', 'D': '09/19/2016', 'E': '09/21/2016', 'F': '09/22/2016', 'G': '.139146'},
        # Known invalid out-of-interval issuer row is not a candidate dividend.
        {'B': 'XLE', 'D': '12/20/2002', 'E': '12/24/2002', 'F': '01/31/2002', 'G': '.11549'},
    ]
    if edits:
        edits(rows)
    strings = []
    for i, values in enumerate(rows, 1):
        row = ET.SubElement(data, f'{{{ns}}}row')
        for col, value in values.items():
            cell = ET.SubElement(row, f'{{{ns}}}c', {'r': f'{col}{i}', 't': 's'})
            strings.append(value)
            ET.SubElement(cell, f'{{{ns}}}v').text = str(len(strings)-1)
    ss = ET.Element(f'{{{ns}}}sst')
    for value in strings:
        si = ET.SubElement(ss, f'{{{ns}}}si')
        ET.SubElement(si, f'{{{ns}}}t').text = value
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, 'w') as z:
        z.writestr('xl/sharedStrings.xml', ET.tostring(ss))
        z.writestr('xl/worksheets/sheet1.xml', ET.tostring(root))


def bar(day, dividend=D('.1')):
    return DailyBar(day, D(10), D(11), D(9), D(10), 100, D(9), dividend, D(1))


def test_source_requests_keep_fixed_intervals_and_no_new_trading_symbol():
    req = m.bars_request('XLF', 'sip')
    assert req.params['start'] == '2006-01-01T00:00:00Z'
    assert req.params['end'] == '2026-10-01T00:00:00Z'
    assert req.params['adjustment'] == 'raw'
    assert m.bars_request('XLRE', 'sip', in_kind=True).params['start'] == '2016-09-19T00:00:00Z'
    with pytest.raises(ValueError):
        m.bars_request('XLRE', 'sip')
    with pytest.raises(ValueError):
        m.bars_request('QQQ', 'sip')


def test_pages_reject_wrong_request_and_unexhausted_capture(tmp_path):
    req = m.bars_request('XLB', 'sip')
    archive = RawArchive(tmp_path, 'alpaca', 'fixture', m.RUN, req, semantics='fixture')
    payload = {'bars': {'XLB': [{'t': '2016-01-04T05:00:00Z'}]}, 'next_page_token': 'more'}
    archive.capture(lambda _: json.dumps(payload),
                    lambda r, p: (1, Request(r.url, {**r.params, 'page_token': 'more'})), max_pages=1)
    with pytest.raises(ValueError, match='incomplete'):
        m.read_pages(tmp_path, 'fixture', req, lambda p: len(p['bars']['XLB']))
    with pytest.raises(ValueError, match='manifest identity'):
        m.read_pages(tmp_path, 'fixture', m.bars_request('XLF', 'sip'), lambda p: 1)


def test_pages_reject_changed_bytes(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq
    req = m.bars_request('XLB', 'sip')
    archive = RawArchive(tmp_path, 'alpaca', 'fixture', m.RUN, req, semantics='fixture')
    archive.capture(lambda _: '{"bars":{"XLB":[]},"next_page_token":null}', lambda r, p: (0, None))
    path = archive.directory / 'page-00000000.parquet'
    rows = pq.ParquetFile(path).read().to_pylist()
    rows[0]['response_json'] = '{"bars":{"XLB":[{}]},"next_page_token":null}'
    pq.write_table(pa.Table.from_pylist(rows, schema=m.SCHEMA), path)
    with pytest.raises(ValueError, match='checksum'):
        m.read_pages(tmp_path, 'fixture', req, lambda p: len(p['bars']['XLB']))


def test_issuer_classifies_units_and_zero_without_inventing_income(tmp_path):
    path = tmp_path / 'source.xlsx'
    workbook(path)
    rows, excluded = m.issuer_rows(path)
    assert len(rows) == 9
    assert sum(D(r['amount']) for r in rows) == D('.9')
    assert {r['kind'] for r in excluded} == {'zero_distribution', 'XLRE_units_not_cash'}
    assert next(r for r in excluded if r['kind'] == 'XLRE_units_not_cash')['amount'] == '0.139146'


@pytest.mark.parametrize('edit', [
    lambda rows: rows.append(dict(rows[1])),
    lambda rows: rows[1].update(F='03/01/2016'),
    lambda rows: rows[1].update(G='-.1'),
    lambda rows: rows[1].update(G='0'),
    lambda rows: rows[-2].update(G='.139147'),
])
def test_issuer_rejects_ambiguous_or_changed_actions(tmp_path, edit):
    path = tmp_path / 'source.xlsx'
    workbook(path, edit)
    with pytest.raises(ValueError):
        m.issuer_rows(path)


def test_cash_counts_duplicates_once_and_uses_latest_documented_payment(tmp_path, monkeypatch):
    path = tmp_path / m.WORKBOOK
    workbook(path)
    monkeypatch.setattr(m, 'WORKBOOK_SHA', m.sha(path.read_bytes()))
    bars = {s: [bar(date(2016, 3, 18))] for s in m.UNIVERSE}
    broker = {'cash_dividends': [
        {'symbol': 'XLF', 'ex_date': '2016-03-18', 'rate': D('.1000001'), 'id': 'a', 'payable_date': '2016-03-31'},
        {'symbol': 'XLF', 'ex_date': '2016-03-18', 'rate': D('.1'), 'id': 'b'},
        {'symbol': 'XLF', 'ex_date': '2016-09-19', 'rate': D('.139146'), 'id': 'spin'},
    ]}
    sessions = [{'date': '2016-03-30', 'opens_at': '2016-03-30T09:30:00-04:00'},
                {'date': '2016-03-31', 'opens_at': '2016-03-31T09:30:00-04:00'},
                {'date': '2016-04-01', 'opens_at': '2016-04-01T09:30:00-04:00'}]
    result = m.cash_audit(bars, broker, sessions, tmp_path)
    xlf = next(r for r in result['distributions'] if r['symbol'] == 'XLF')
    assert xlf['amount'] == '0.1' and xlf['pay_date'] == '2016-03-29'
    assert xlf['cash_endpoint'] == '2016-03-31' and xlf['cash_release'].startswith('2016-04-01')
    assert len(result['distributions']) == 9 and result['broker_duplicate_ordinary_rows'] == 1
    assert len(result['broker_six_decimal_rounding']) == 1
    broker['cash_dividends'][0]['rate'] = D('.100001')
    with pytest.raises(ValueError, match='amount conflict'):
        m.cash_audit(bars, broker, sessions, tmp_path)


def test_price_normalization_does_not_apply_action_twice():
    events = [(date(2016, 9, 19), D('1.231'))]
    assert m.actual_share_factor(date(2016, 9, 16), events) == D('1.231')
    assert m.actual_share_factor(date(2016, 9, 19), events) == 1
