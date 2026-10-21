from datetime import date, timedelta
from decimal import Decimal as D
import json

import pytest

from tradingbot.data.archive import RawArchive, Request
from tradingbot.data.alpaca_history import DATA, bars_page
from tradingbot.research import total_return_data as tr


def test_exact_99_percent_boundary_and_every_disagreement_retained():
    days = [date(2020, 1, 1) + timedelta(days=i) for i in range(201)]
    primary = {day: D(100) for day in days}
    secondary = dict(primary)
    secondary[days[10]] = D('100.06')
    check = tr.cross_check(primary, secondary)
    assert check['passed'] and check['agreement_percent'] == '99'
    assert [row['date'] for row in check['disagreeing_days']] == [str(days[10]), str(days[11])]
    primary.pop(days[-1]); secondary.pop(days[-1])
    assert not tr.cross_check(primary, secondary)['passed']


def test_tolerance_is_absolute_return_difference_in_basis_points():
    days = [date(2020, 1, 1), date(2020, 1, 2)]
    primary = dict(zip(days, [D(100), D(101)]))
    assert tr.cross_check(primary, dict(zip(days, [D(100), D('101.05')])))['passed']
    assert not tr.cross_check(primary, dict(zip(days, [D(100), D('101.05001')])))['passed']


def test_missing_endpoint_never_becomes_a_multi_session_return():
    days = [date(2020, 1, 1) + timedelta(days=i) for i in range(5)]
    primary = {day: D(100 + i) for i, day in enumerate(days)}
    secondary = dict(primary); secondary.pop(days[2])
    result = tr.cross_check(primary, secondary)
    assert result['paired_return_days'] == 2
    assert result['unpaired_dates'] == [str(days[2]), str(days[3])]
    assert result['primary_return_days'] == 4
    assert not tr.cross_check(primary, {})['passed']


def test_invalid_prices_and_html_are_rejected():
    day = date(2020, 1, 1)
    for value in ('0', '-1', 'NaN', 'Infinity'):
        with pytest.raises(ValueError):
            tr.cross_check({day: D(value)}, {})
    with pytest.raises(ValueError, match='no CSV'):
        tr.stooq_prices(b'<html>Verify your browser</html>')
    with pytest.raises(ValueError, match='duplicate'):
        tr.stooq_prices(b'Date,Open,High,Low,Close,Volume\n2020-01-01,1,1,1,1,1\n2020-01-01,1,1,1,1,1\n')


def test_adjusted_open_uses_same_days_factor_without_second_dividend_credit(tmp_path, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(tr, 'ROOT', tmp_path)
    path = tmp_path / 'SPY'; path.mkdir()
    (path / 'manifest.json').write_text('{}')
    (path / 'raw.json').write_text(json.dumps({'chart': {'result': [{'meta': {'symbol': 'SPY'}}]}}))
    bar = SimpleNamespace(date=date(2020, 1, 2), open=D(200), close=D(202),
                          adj_close=D(101), dividend=D(2))
    monkeypatch.setattr(tr, 'load_capture', lambda _: ({'sha256': 'a' * 64}, [bar]))
    rows, _ = tr.yahoo_prices(path, 'SPY', date(2020, 1, 1), date(2020, 2, 1))
    assert rows[bar.date] == {'open': D(100), 'close': D(101), 'raw_open': D(200),
                              'raw_close': D(202), 'factor': D('.5')}
    assert 'dividend' not in rows[bar.date]


def test_adjusted_archive_requires_complete_hash_bound_daily_prices(tmp_path, monkeypatch):
    monkeypatch.setattr(tr, 'ROOT', tmp_path)
    request = Request(DATA + '/stocks/bars', {'symbols': 'SPY', 'timeframe': '1Day',
                                            'adjustment': 'all', 'feed': 'sip'})
    archive = RawArchive(tmp_path, 'alpaca', 'bars_1Day_all_sip', 'test', request, semantics='synthetic test')
    payload = {'bars': {'SPY': [{'t': '2020-01-02T05:00:00Z', 'c': 100}]}, 'next_page_token': None}
    archive.capture(lambda _: json.dumps(payload), bars_page)
    rows, meta = tr.alpaca_prices(archive.directory)
    assert rows == {'SPY': {date(2020, 1, 2): D(100)}}
    assert meta['pages'] == 1
    path = archive.directory / 'manifest.json'
    saved = json.loads(path.read_bytes()); saved['request']['params']['adjustment'] = 'raw'
    path.write_text(json.dumps(saved))
    with pytest.raises(ValueError, match='identity changed'):
        tr.alpaca_prices(archive.directory)


def test_secondary_adjustment_uses_only_independent_prices_and_requires_all_endpoints():
    a, b = date(2020, 1, 2), date(2020, 1, 3)
    result = tr.dividend_adjusted_reference({a: D(100), b: D(99)},
        {a: D(90), b: D(99)}, {a: D(100), b: D(99)})
    assert result == {a: D(90), b: D(99)}
    with pytest.raises(KeyError):
        tr.dividend_adjusted_reference({a: D(100)}, {}, {a: D(100)})
