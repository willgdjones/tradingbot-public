"""C08 amended source contracts, independent of strategy outcomes."""
from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from tradingbot.research.c08_blackout import compare_reference, pdf_stock_check, report_urls, stock_fields


def test_report_links_preserve_delays_and_fixed_source_bounds():
    def link(day):
        return f'<a href="/petroleum/supply/weekly/archive/{day[:4]}/{day}/wpsr_{day}.php">report</a>'
    raw = ''.join(link(d) for d in ('2017_12_27', '2018_01_04', '2022_06_17_data', '2026_09_30', '2026_10_07')).encode()
    urls = report_urls(raw + link('2018_01_04').encode())
    assert len(urls) == 3
    assert urls[1].endswith('2022_06_17_data/wpsr_2022_06_17_data.php')
    assert urls[-1].endswith('wpsr_2026_09_30.php')
    with pytest.raises(ValueError, match='primary source'):
        report_urls(raw.replace(b'href="/', b'href="https://untrusted.example/'))


def stock_csv():
    return b'''"STUB_1","9/4/20","8/28/20","Difference","Percent Change","9/6/19","Difference","Percent Change"
"Crude Oil","1,100.000","0","0","0","1,000.000","0","0"
"Commercial (Excluding SPR)","450.000","0","0","0","400.000","0","0"
"Strategic Petroleum Reserve (SPR)","650.000","0","0","0","600.000","0","0"
'''


def test_stock_section_uses_commercial_not_spr_or_total_without_signal():
    result = stock_fields(stock_csv(), date(2020, 9, 4))
    assert result['commercial_current'] == '450.000'
    assert result['commercial_year_ago'] == '400.000'
    assert result['comparable_year_ago_date'] == '2019-09-06'
    assert not result['units_verified'] and not result['first_release_vintage_verified']
    assert 'scarcity' not in result


@pytest.mark.parametrize('before,after', [
    (b'9/4/20', b'9/5/20'), (b'9/6/19', b'9/6/18'),
    (b'Commercial (Excluding SPR)', b'Total Stocks (Excluding SPR)'),
    (b'400.000', b'0'), (b'450.000', b'NaN'), (b'450.000', b'460.000'),
])
def test_bad_stock_identity_denominator_and_components_fail(before, after):
    with pytest.raises(ValueError):
        stock_fields(stock_csv().replace(before, after), date(2020, 9, 4))


def test_capture_retries_transport_without_replacing_completed_http(monkeypatch):
    import requests
    from tradingbot.research import c08_blackout as module
    calls = []
    def transport(key, url, **kwargs):
        calls.append(key)
        if len(calls) < 3:
            raise requests.ReadTimeout('synthetic timeout')
        return {'status_code': 404}
    monkeypatch.setattr(module, 'capture', transport)
    monkeypatch.setattr(module.time, 'sleep', lambda _: None)
    assert module.capture_retry('report', 'https://www.eia.gov/test')['status_code'] == 404
    assert len(calls) == 3


def test_price_basis_conversion_stops_on_post_split_date():
    bars = [SimpleNamespace(date=date(2020, 4, d), open=D('16'), close=D('24')) for d in (28, 29)]
    reference = [{'t': '2020-04-28T04:00:00Z', 'o': 2, 'c': 3},
                 {'t': '2020-04-29T04:00:00Z', 'o': 16, 'c': 24}]
    result = compare_reference(bars, reference, primary_close={})
    assert not result['differences_over_1pct'] and not result['missing_sessions']


def test_thin_close_difference_needs_matching_primary_auction():
    day = date(2020, 4, 21)
    bars = [SimpleNamespace(date=day, open=D('16'), close=D('22.48'))]
    reference = [{'t': '2020-04-21T04:00:00Z', 'o': 2, 'c': D('3.18')}]
    for evidence in ({}, {day: D('3.18')}):
        result = compare_reference(bars, reference, primary_close=evidence)
        assert result['differences_over_1pct'][0]['primary_auction_resolution'] is None
    resolved = compare_reference(bars, reference, primary_close={day: D('2.81')})
    assert resolved['differences_over_1pct'][0]['primary_auction_resolution'] == '2.81'
    with pytest.raises(ValueError, match='duplicated'):
        compare_reference(bars, reference * 2, primary_close={})


def pdf_table():
    return '''Table 1. U.S. Petroleum Balance Sheet, Week Ending 9/4/2020
Petroleum Stocks
(Million Barrels)
Commercial (Excluding SPR)1 ........... 450.0 440.0 10.0 2.3 400.0 50.0 12.5
'''


def test_pdf_confirms_stock_units_dates_and_printed_rounding_only():
    fields = stock_fields(stock_csv(), date(2020, 9, 4))
    result = pdf_stock_check(pdf_table(), fields)
    assert result['units'] == 'million barrels' and result['pdf_year_ago'] == '400.0'
    assert fields['first_release_vintage_verified'] is False


@pytest.mark.parametrize('before,after', [
    ('Million Barrels', 'Thousand Barrels per Day'), ('9/4/2020', '9/11/2020'),
    ('450.0', '450.1'), ('400.0', '410.0'),
])
def test_pdf_different_units_dates_or_levels_cannot_certify_csv(before, after):
    with pytest.raises(ValueError):
        pdf_stock_check(pdf_table().replace(before, after), stock_fields(stock_csv(), date(2020, 9, 4)))


def test_capture_preserves_completed_failure_and_budget_checks(monkeypatch, tmp_path):
    from contextlib import contextmanager
    from tradingbot.research import c08_blackout as module
    events = []
    class Budget:
        def __init__(self, _): pass
        def check_free(self): events.append('free')
        @contextmanager
        def reserve(self, size):
            assert size >= 65536
            events.append('reserve')
            yield
    class Network:
        def get(self, url, **kwargs):
            events.append('GET')
            return SimpleNamespace(content=b'not available', url=url, status_code=404, headers={})
    monkeypatch.setattr(module, 'CaptureDiskBudget', Budget)
    monkeypatch.setattr(module._NETWORK, 'session', Network(), raising=False)
    first = module.capture('x', 'https://www.eia.gov/x', archive=tmp_path)
    assert first['status_code'] == 404
    assert events == ['free', 'GET', 'reserve']
    assert module.capture('x', 'https://www.eia.gov/x', archive=tmp_path) == first
    assert events == ['free', 'GET', 'reserve']
    assert not list(tmp_path.glob('.capture-*'))
    (tmp_path / 'x/raw').write_bytes(b'changed')
    with pytest.raises(ValueError, match='checksum'):
        module.capture('x', 'https://www.eia.gov/x', archive=tmp_path)


def test_incomplete_observation_heading_requires_csv_month_and_full_release_date():
    from tradingbot.research.c08_blackout import archive_layout
    page = b'<p>Data for week ending September, 2020 | Release Date: September 10, 2020</p><a href="csv/table1.csv">table</a>'
    url = 'https://www.eia.gov/petroleum/supply/weekly/archive/2020/2020_09_10/wpsr_2020_09_10.php'
    result = archive_layout(page, url, stock_csv())
    assert result['observation_date'] == '2020-09-04'
    assert result['earliest_calendar_date_for_execution'] == '2020-09-11'
    assert not result['first_release_vintage_verified']
    for bad in (page.replace(b'September,', b'August,'), page.replace(b'September 10,', b'September,')):
        with pytest.raises(ValueError):
            archive_layout(bad, url, stock_csv())


def full_pdf_table():
    return '''Table 1. U.S. Petroleum Balance Sheet, Week Ending 9/4/2020
Petroleum Stocks (Million Barrels)
Current Week 9/4/20 Week Ago 8/28/20 Year Ago 9/6/19
Crude Oil ........... 1100.0 1000.0 100.0 10.0 1000.0 100.0 10.0
Commercial (Excluding SPR)1 ........... 450.0 440.0 10.0 2.3 400.0 50.0 12.5
Strategic Petroleum Reserve (SPR)2 ..... 650.0 560.0 90.0 16.1 600.0 50.0 8.3
Petroleum Supply (Thousand Barrels per Day)
Crude Oil Supply
1 Includes those domestic and Customs-cleared foreign crude oil stocks held at refineries and tank farms or in transit thereto, and in pipelines.
'''


def test_original_pdf_fallback_checks_all_dates_units_components_and_precision():
    from tradingbot.research.c08_blackout import pdf_stock_fields
    fields = pdf_stock_fields(full_pdf_table(), date(2020, 9, 4))
    assert fields['commercial_current'] == '450.0'
    assert fields['commercial_year_ago'] == '400.0'
    assert fields['field_precision_million_barrels'] == '0.1'
    assert not fields['first_release_vintage_verified']
    for before, after in [('Million Barrels', 'Thousand Barrels'), ('9/6/19', '9/6/18'),
                          ('8/28/20', '8/27/20'), ('650.0', '650.2'), ('450.0', '0.0'),
                          ('tank farms', 'SPR holdings')]:
        with pytest.raises(ValueError):
            pdf_stock_fields(full_pdf_table().replace(before, after), date(2020, 9, 4))


def test_impossible_page_publication_requires_explicit_full_report_date():
    from tradingbot.research.c08_blackout import full_report_layout
    raw = b'<p>Data for week ending September 4, 2020 | Release Date: September 1, 2020</p><a href="csv/table1.csv">table</a>'
    url = 'https://www.eia.gov/petroleum/supply/weekly/archive/2020/2020_09_10/wpsr_2020_09_10.php'
    full = 'Data for Week Ended:\nSeptember 4, 2020\nWeekly Petroleum Status Report\fRelease Date: September 10, 2020\fLater pages'
    result = full_report_layout(raw, url, stock_csv(), full)
    assert result['release_date'] == '2020-09-10'
    assert result['rejected_page_release_date'] == '2020-09-01'
    assert result['earliest_calendar_date_for_execution'] == '2020-09-11'
    for changed in (full.replace('Release Date:', 'File Date:'), full.replace('September 4,', 'September 3,'),
                    full.replace('September 10,', 'September 1,')):
        with pytest.raises(ValueError):
            full_report_layout(raw, url, stock_csv(), changed)


def test_pdf_text_cache_requires_identical_content_and_layout(monkeypatch, tmp_path):
    from tradingbot.research import c08_blackout as module
    module._PDF_TEXT_CACHE.clear()
    first, second = tmp_path / 'a.pdf', tmp_path / 'b.pdf'
    first.write_bytes(b'%PDF synthetic one')
    second.write_bytes(first.read_bytes())
    calls = []
    def extract(command, **kwargs):
        calls.append(command)
        return str(len(calls))
    monkeypatch.setattr(module.subprocess, 'check_output', extract)
    assert module.pdf_text(first) == module.pdf_text(second) == '1'
    assert module.pdf_text(second, layout=False) == '2'
    second.write_bytes(b'%PDF synthetic changed')
    assert module.pdf_text(second) == '3'
    assert len(calls) == 3
    module._PDF_TEXT_CACHE.clear()
