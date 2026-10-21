from datetime import datetime
from decimal import Decimal as D
from types import SimpleNamespace

from tradingbot.research.turn_of_month import exit_date_regimes


def trip(stamp, net='1', fee='.04'):
    return SimpleNamespace(exit_ts=datetime.fromisoformat(stamp), net_pnl=D(net), fees=D(fee))


def test_open_bounds_include_pre_2016_and_post_2026_without_false_labels():
    trips = [trip('2006-01-03T21:00:00+00:00', '2'),
             trip('2016-01-04T21:00:00+00:00', '-1'),
             trip('2022-12-30T21:00:00+00:00', '3'),
             trip('2027-01-04T21:00:00+00:00', '7')]
    report = exit_date_regimes(trips)
    periods = report['periods']
    assert report['timezone'] == 'America/New_York'
    assert periods['before_2023']['trades'] == 3
    assert periods['before_2023']['net_usd'] == 4
    assert periods['before_2023']['fees_usd'] == D('.12')
    assert periods['before_2023']['start_inclusive'] is None
    assert periods['before_2023']['first_exit_date'] == '2006-01-03'
    assert periods['before_2023']['end_exclusive'] == '2023-01-01'
    for name in ('from_2023', 'from_2025'):
        assert periods[name]['trades'] == 1 and periods[name]['net_usd'] == 7
        assert periods[name]['end_exclusive'] is None
        assert periods[name]['last_exit_date'] == '2027-01-04'
    assert '2016_2022' not in periods and '2023_2026' not in periods and '2025_2026' not in periods


def test_exit_date_uses_exchange_timezone_and_half_open_boundaries():
    report = exit_date_regimes([
        trip('2023-01-01T04:59:59+00:00', '1'),  # still December 31 in New York
        trip('2023-01-01T05:00:00+00:00', '2'),
        trip('2025-01-01T04:59:59+00:00', '4'),  # still in 2024
        trip('2025-01-01T05:00:00+00:00', '8'),
    ])['periods']
    assert report['before_2023']['trades'] == 1 and report['before_2023']['net_usd'] == 1
    assert report['from_2023']['trades'] == 3 and report['from_2023']['net_usd'] == 14
    middle = report['2023_2024']
    assert middle['trades'] == 2 and middle['net_usd'] == 6
    assert (middle['start_inclusive'], middle['end_exclusive']) == ('2023-01-01', '2025-01-01')
    assert (middle['first_exit_date'], middle['last_exit_date']) == ('2023-01-01', '2024-12-31')
    assert report['from_2025']['trades'] == 1 and report['from_2025']['net_usd'] == 8


def test_empty_periods_do_not_claim_observed_coverage():
    for period in exit_date_regimes([])['periods'].values():
        assert period['trades'] == 0 and period['net_usd'] == 0
        assert period['first_exit_date'] is period['last_exit_date'] is None
        assert period['mean_net_usd'] is period['win_rate'] is period['one_sided_t_pvalue'] is None


def test_input_order_does_not_change_date_extent_or_mutate_trips():
    trips = [trip('2007-12-31T21:00:00+00:00'), trip('2006-01-03T21:00:00+00:00')]
    before = [vars(t).copy() for t in trips]
    forward = exit_date_regimes(trips)
    assert forward == exit_date_regimes(list(reversed(trips)))
    assert [vars(t) for t in trips] == before
