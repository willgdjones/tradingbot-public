"""Source-only multi-split conversion and immutable reference checks."""
from datetime import date
from decimal import Decimal as D
import json
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from tradingbot.data.archive import RawArchive, Request, SCHEMA
from tradingbot.research.c05_blackout import RUN, actual_share_factor, compare_reference, read_pages, local_blackout


def bar(day, price='16', ratio='1'):
    return SimpleNamespace(date=day, open=D(price), close=D(price), split_ratio=D(ratio))


def test_multi_split_factor_is_actual_share_and_strictly_pre_ex():
    splits = [(date(2011, 3, 9), D('.5')), (date(2012, 2, 22), D('.25')),
              (date(2018, 1, 5), D('.25')), (date(2024, 1, 24), D('.25'))]
    assert actual_share_factor(date(2008, 1, 2), splits) == D(1) / 128
    assert actual_share_factor(date(2018, 1, 4), splits) == D(1) / 16
    assert actual_share_factor(date(2018, 1, 5), splits) == D(1) / 4
    assert actual_share_factor(date(2024, 1, 24), splits) == 1
    assert actual_share_factor(date(2008, 7, 23), [(date(2008, 7, 24), D(10))]) == 10
    with pytest.raises(ValueError, match='duplicate'):
        actual_share_factor(date(2008, 1, 2), splits * 2)


def test_payable_before_ex_is_preserved_and_delivery_extends_blackout():
    days = [date(2008, 7, d) for d in (21, 22, 23, 24, 25, 28, 29)]
    plan = local_blackout(symbol='SLV', announced=date(2008, 7, 11),
        ex_date=date(2008, 7, 24), effective=date(2008, 7, 23), payable=date(2008, 7, 23),
        delivery=date(2008, 7, 28), sessions=days)
    assert plan['actual_payable'] == '2008-07-23'
    assert plan['research_end'] == '2008-07-28' and plan['reentry'] == '2008-07-29'
    assert plan['decision'] == '2008-07-22' and len(plan['blackout_sessions']) == 4
    assert not plan['endpoint_is_broker_credit']


def test_unknown_payable_is_not_forged_and_late_announcement_fails():
    days = [date(2018, 1, d) for d in (2, 3, 4, 5, 8)]
    kwargs = dict(symbol='UNG', announced=date(2017, 12, 22), ex_date=date(2018, 1, 5),
                  effective=date(2018, 1, 4), payable=None, delivery=None, sessions=days)
    plan = local_blackout(**kwargs)
    assert plan['actual_payable'] is None and plan['research_end'] == '2018-01-05'
    assert plan['exit'] == '2018-01-04' and plan['reentry'] == '2018-01-08'
    with pytest.raises(ValueError, match='prior-close'):
        local_blackout(**{**kwargs, 'announced': date(2018, 1, 4)})
    with pytest.raises(ValueError, match='prior-close'):
        local_blackout(**{**kwargs, 'sessions': days[:4]})


def test_bad_primary_open_is_not_silently_replaced_by_reference():
    day = date(2017, 2, 9)
    bars = [bar(day, '11.23')]
    ref = [{'t': '2017-02-09T05:00:00Z', 'o': '11.385', 'c': '11.23'}]
    result = compare_reference(bars, ref, feed='sip', primary={(day, 'open'): D('11.38')})
    [failure] = result['failures']
    assert failure['yahoo_actual_share'] == '11.23' and failure['primary'] == '11.38'
    assert not failure['primary_confirms_yahoo'] and bars[0].open == D('11.23')


def test_matching_primary_close_resolves_thin_close_but_not_missing_proof():
    day = date(2020, 3, 16)
    bars = [bar(day, '12')]
    ref = [{'t': '2020-03-16T04:00:00Z', 'o': '12', 'c': '11.8401'}]
    assert len(compare_reference(bars, ref, feed='sip')['failures']) == 1
    assert not compare_reference(bars, ref, feed='sip', primary={(day, 'close'): D(12)})['failures']
    with pytest.raises(ValueError, match='duplicate'):
        compare_reference(bars, ref * 2, feed='sip')


def test_iex_open_is_diagnostic_and_sip_overlap_gaps_remain_failures():
    bars = [bar(date(2020, 7, d), '10') for d in (27, 28, 29)]
    ref = [{'t': f'2020-07-{d}T04:00:00Z', 'o': '11', 'c': '10'} for d in (27, 29)]
    assert not compare_reference(bars, ref, feed='iex')['failures']
    assert compare_reference(bars, ref, feed='sip')['failures'][-1] == {'missing_overlap_sessions': ['2020-07-28']}


def make_archive(tmp_path):
    request = Request('https://data.alpaca.markets/v2/test', {'symbol': 'GLD'})
    archive = RawArchive(tmp_path, 'alpaca', 'fixture', RUN, request, semantics='synthetic')
    archive.capture(lambda req: json.dumps({'rows': [1], 'next_page_token': None}), lambda req, payload: (1, None))
    return archive, request


def test_reference_validates_raw_bytes_and_exhaustion(tmp_path):
    archive, request = make_archive(tmp_path)
    receipt, pages = read_pages(tmp_path, 'fixture', request, lambda p: len(p['rows']))
    assert pages[0]['rows'] == [1] and receipt['pages'][0]['record_count'] == 1
    path = archive.directory / 'page-00000000.parquet'
    row = pq.ParquetFile(path).read().to_pylist()[0]
    row['response_json'] = row['response_json'].replace('[1]', '[2]')
    pq.write_table(pa.Table.from_pylist([row], schema=SCHEMA), path)
    with pytest.raises(ValueError, match='checksum'):
        read_pages(tmp_path, 'fixture', request, lambda p: len(p['rows']))


@pytest.mark.parametrize('field,value', [('record_count', 2), ('next_request_json', '{}'), ('page', 1)])
def test_reference_rejects_inconsistent_page_receipts(tmp_path, field, value):
    archive, request = make_archive(tmp_path)
    path = archive.directory / 'page-00000000.parquet'
    row = pq.ParquetFile(path).read().to_pylist()[0]
    row[field] = value
    pq.write_table(pa.Table.from_pylist([row], schema=SCHEMA), path)
    with pytest.raises(ValueError):
        read_pages(tmp_path, 'fixture', request, lambda p: len(p['rows']))
