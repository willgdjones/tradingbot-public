from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from tradingbot.research.c05_total_return import compare_returns, dividend_adjusted_reference


def series(n=101):
    return {date(2020, 1, 1) + timedelta(days=i): D(100) for i in range(n)}


def test_daily_return_threshold_and_logged_disagreement():
    a, b = series(), series()
    b[max(b)] = D('100.05')
    assert compare_returns(a, b)['agreement'] == '1'
    b[max(b)] = D('100.05001')
    result = compare_returns(a, b)
    assert result['passed'] and result['agreement'] == '0.99'
    assert result['disagreements'][0]['date'] == str(max(b))
    b[sorted(b)[50]] = D('100.1')
    assert not compare_returns(a, b)['passed']


def test_missing_day_is_not_bridged_or_hidden_in_agreement():
    a, b = series(), series()
    del b[sorted(b)[50]]
    result = compare_returns(a, b)
    assert result['comparisons'] == 98 and not result['passed']
    assert len(result['missing_inside_overlap']) == 2


def test_shorter_reference_reports_uncovered_primary_without_shifting_it():
    a = series()
    b = dict(list(a.items())[20:])
    result = compare_returns(a, b)
    assert result['passed'] and result['comparisons'] == 80
    assert result['yahoo_sessions'] == 101 and result['yahoo_sessions_outside_reference'] == 20


def test_invalid_prices_refused():
    a, b = series(), series()
    b[max(b)] = D(0)
    with pytest.raises(ValueError, match='invalid adjusted price'):
        compare_returns(a, b)


def test_independent_dividend_factor_does_not_apply_split_twice():
    first, ex = date(2020, 1, 1), date(2020, 1, 2)
    # Prices already express an eight-for-one reverse split. The cash action
    # reduces older prices once and never creates separate dividend income.
    result = dividend_adjusted_reference({first: D(80), ex: D(76)},
        [{'ex_date': str(ex), 'amount': '4'}])
    assert result == {first: D(76), ex: D(76)}
    assert result[ex]/result[first] - 1 == 0


def test_reference_rejects_duplicate_or_missing_action_date():
    first, ex, last = date(2020, 1, 1), date(2020, 1, 2), date(2020, 1, 3)
    row = {'ex_date': str(ex), 'amount': '4'}
    with pytest.raises(ValueError, match='duplicate'):
        dividend_adjusted_reference({first:D(80), ex:D(76)}, [row, row])
    with pytest.raises(ValueError, match='missing'):
        dividend_adjusted_reference({first:D(80), last:D(76)}, [row])
