"""Gotobi research helpers: calendar roll-back, anchors, partitions and costs."""
from datetime import UTC, date, datetime, timedelta
import math

import pytest

from tradingbot.backtest.holdout import HoldoutSplit
from tradingbot.research import gotobi as g


def test_business_day_excludes_weekends_national_and_bank_holidays():
    holidays = {date(2026, 9, 21)}
    assert g.business_day(date(2026, 9, 24), holidays)
    assert not g.business_day(date(2026, 9, 21), holidays)
    assert not g.business_day(date(2026, 9, 26), holidays)  # Saturday
    assert not g.business_day(date(2026, 1, 2), holidays)  # bank holiday, a Friday
    assert not g.business_day(date(2025, 12, 31), holidays)


def test_gotobi_days_roll_back_and_label_month_end():
    holidays = {date(2026, 9, 21), date(2026, 9, 22), date(2026, 9, 23)}
    days = g.gotobi_days(date(2026, 9, 1), date(2026, 10, 31), holidays)
    september = {d: v for d, v in days.items() if d.month == 9}
    assert september == {date(2026, 9, 4): ['five'],  # 5th is a Saturday
                         date(2026, 9, 10): ['five'], date(2026, 9, 15): ['five'],
                         date(2026, 9, 18): ['five'],  # 20th Sunday -> Friday
                         date(2026, 9, 25): ['five'], date(2026, 9, 30): ['five', 'month_end']}
    # October: the 30th is a Friday and the 31st (month end) rolls back onto it.
    assert days[date(2026, 10, 30)] == ['five', 'month_end']


def test_gotobi_roll_back_crosses_new_year_bank_holidays():
    holidays = {date(2025, 1, 1)}
    days = g.gotobi_days(date(2024, 12, 1), date(2025, 1, 31), holidays)
    # Dec 31 (month end) and Jan 5 both land on Monday Dec 30.
    assert days[date(2024, 12, 30)] == ['five', 'month_end']
    assert date(2025, 1, 6) not in days and date(2025, 1, 10) in days


def test_month_end_only_day_in_31_day_month():
    days = g.gotobi_days(date(2026, 8, 1), date(2026, 8, 31), set())
    assert days[date(2026, 8, 31)] == ['month_end']
    assert days[date(2026, 8, 28)] == ['five']  # 30th is a Sunday


def test_anchor_times_are_fixed_utc_minutes():
    assert g.anchor_utc(date(2026, 9, 30), '09:55') == datetime(2026, 9, 30, 0, 55, tzinfo=UTC)
    assert g.anchor_utc(date(2026, 9, 30), '03:00') == datetime(2026, 9, 29, 18, 0, tzinfo=UTC)
    assert (18, 4) in g.needed_minutes() and (0, 59) in g.needed_minutes() and (18, 5) not in g.needed_minutes()


def test_pick_anchor_uses_first_bar_within_five_minutes():
    at = datetime(2026, 9, 30, 0, 55, tzinfo=UTC)
    bars = {at+timedelta(minutes=2): (150.0, 150.01), at+timedelta(minutes=3): (151.0, 151.01)}
    assert g.pick_anchor(bars, at)['quote'] == [150.0, 150.01]
    assert g.pick_anchor({at+timedelta(minutes=5): (150.0, 150.01)}, at) is None
    crossed = g.pick_anchor({at: (150.02, 150.0)}, at)
    assert crossed['crossed'] and g.fill(crossed, 'ask') == g.fill(crossed, 'bid') == pytest.approx(150.01)
    assert g.pick_anchor({at: (0.0, 150.0)}, at) == 'invalid'
    assert g.pick_anchor({at: (150.0,)}, at)['quote'] == [150.0]


def quote(bid, spread=0.02):
    return {'bar': 'x', 'quote': [bid, bid+spread]}


def synthetic(days, gotobi, prices):
    return {'pairs': {'USDJPY': {'fxcm': {d.isoformat(): {a: quote(p) for a, p in prices[d].items()} for d in days}}},
            'calendar': {'business_days': [d.isoformat() for d in days],
                         'gotobi': {d.isoformat(): ['five'] for d in gotobi}}}


SPLIT = HoldoutSplit('test-gotobi', datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 10, 1, tzinfo=UTC))


def test_long_window_returns_costs_and_partition():
    assert SPLIT.holdout_start == datetime(2026, 9, 22, tzinfo=UTC)
    days = [date(2026, 9, 15), date(2026, 9, 16), date(2026, 9, 25)]
    prices = {d: {'03:00': 149.0, '09:00': 150.0, '09:55': 150.3, '12:00': 150.0} for d in days}
    source = synthetic(days, [date(2026, 9, 15)], prices)
    rows, counts = g.trades(source, 'USDJPY', 'open_fix', SPLIT, final=False)
    assert [r['day'] for r in rows] == ['2026-09-15', '2026-09-16']
    first = rows[0]
    assert first['gotobi'] and not rows[1]['gotobi']
    gross = math.log(150.31/150.01)*1e4
    assert first['gross_bp'] == pytest.approx(gross)
    assert first['quoted_bp'] == pytest.approx(math.log(150.3/150.02)*1e4)
    crossed = synthetic(days, [], {d: {**prices[d], '09:55': 150.3} for d in days})
    crossed['pairs']['USDJPY']['fxcm']['2026-09-15']['09:55'] = {'bar': 'x', 'quote': [150.3, 150.28], 'crossed': True}
    rows_x, _ = g.trades(crossed, 'USDJPY', 'open_fix', SPLIT, final=False)
    assert rows_x[0]['quoted_bp'] == pytest.approx(math.log(150.29/150.02)*1e4)
    assert first['net_bp'] == pytest.approx(gross-3.0)
    assert first['net_usd'] == pytest.approx(140*(gross-3.0)/1e4)
    held, _ = g.trades(source, 'USDJPY', 'open_fix', SPLIT, final=True)
    assert [r['day'] for r in held] == ['2026-09-25']


def test_straddling_trade_is_dropped_and_counted():
    day = date(2026, 9, 22)  # Tuesday: 03:00 JST entry is Sep 21 18:00 UTC, before the cut
    source = synthetic([day], [day], {day: {'03:00': 149.0, '09:00': 150.0, '09:55': 150.3, '12:00': 150.0}})
    for final in (False, True):
        rows, counts = g.trades(source, 'USDJPY', 'early_fix', SPLIT, final=final)
        assert rows == [] and counts['straddle'] == 1


def test_short_fade_requires_positive_pre_fix_drift():
    up, down = date(2026, 9, 15), date(2026, 9, 16)
    prices = {up: {'03:00': 149.0, '09:00': 150.0, '09:55': 150.3, '12:00': 150.0},
              down: {'03:00': 151.0, '09:00': 150.0, '09:55': 150.3, '12:00': 150.0}}
    rows, counts = g.trades(synthetic([up, down], [up, down], prices), 'USDJPY', 'post_fix_fade', SPLIT, final=False)
    assert [r['day'] for r in rows] == ['2026-09-15'] and counts['condition_false'] == 1
    # Short: sell the 09:55 bid, buy back the 12:00 ask.
    assert rows[0]['quoted_bp'] == pytest.approx(math.log(150.3/150.02)*1e4)
    assert rows[0]['gross_bp'] == pytest.approx(-math.log(150.01/150.31)*1e4)


def test_missing_anchor_and_weekday_filter():
    monday, tuesday = date(2026, 9, 14), date(2026, 9, 15)
    source = synthetic([monday, tuesday], [], {d: {'03:00': 149.0, '09:00': 150.0, '09:55': 150.3, '12:00': 150.0}
                                                for d in (monday, tuesday)})
    source['pairs']['USDJPY']['fxcm']['2026-09-15']['09:55'] = None
    rows, counts = g.trades(source, 'USDJPY', 'early_fix', SPLIT, final=False)
    assert rows == [] and counts['missing_anchor'] == 1  # Monday is outside W2


def test_welch_and_admission_rule():
    diff = g.welch([5.0, 6.0, 7.0, 6.0], [0.0, 1.0, -1.0, 0.0])
    assert diff['difference_bp'] == pytest.approx(6.0) and diff['p_value'] < .01
    metrics = {'trades': 4, 'mean_net_bp': 3.0, 'p_net': .01, 'gotobi_minus_control': diff}
    assert g.admitted(metrics) and g.passed_final(metrics)
    assert not g.admitted({**metrics, 'p_net': .2})
    assert not g.passed_final({**metrics, 'mean_net_bp': -0.1})


def test_cross_check_agreement_threshold():
    days = [date(2026, 9, 15)+timedelta(days=i) for i in range(3)]
    primary = {d: {a: quote(150.0+i*0.1) for i, a in enumerate(g.ANCHORS)} for d in days}
    same = {d: {a: {'bar': 'x', 'quote': [v['quote'][0]]} for a, v in primary[d].items()} for d in days}
    assert all(c['passed'] for c in g.cross_check(days, primary, same).values())
    shifted = {d: {**same[d], '09:55': {'bar': 'x', 'quote': [151.0]}} for d in days}
    check = g.cross_check(days, primary, shifted)
    assert not check['open_fix']['passed'] and check['open_fix']['agreement'] == 0.0
    # A day the primary source cannot supply is not a cross-check coverage gap.
    gap = {**primary, days[0]: {**primary[days[0]], '09:00': None}}
    check = g.cross_check(days, gap, same)['open_fix']
    assert check['fxcm_usable_days'] == 2 and check['coverage'] == 1.0 and check['passed']


def test_summarize_reports_drawdown_regimes_and_control():
    days = [date(2026, 9, 14)+timedelta(days=i) for i in range(5)]
    prices = {d: {'03:00': 149.0, '09:00': 150.0, '09:55': 150.0+0.1*(i % 2), '12:00': 150.0}
              for i, d in enumerate(days)}
    source = synthetic(days, days[:3], prices)
    rows, counts = g.trades(source, 'USDJPY', 'open_fix', SPLIT, final=False)
    metrics = g.summarize(rows, counts, SPLIT, final=False)
    assert metrics['trades'] == 3 and metrics['control']['trades'] == 2
    assert metrics['monthly_marked_net_usd'].keys() == {'2026-09'}
    assert metrics['regimes']['2023-2026']['trades'] == 3 and metrics['regimes']['2016-2019'] is None
    assert float(metrics['max_drawdown']['usd']) > 0 and metrics['max_drawdown']['bp'] > 0
    assert metrics['luck']['p_value'] is None  # fewer than 30 months
    assert metrics['diagnostics']['monday_gotobi']['trades'] == 1
    empty = g.summarize([], counts, SPLIT, final=True)
    assert empty['trades'] == 0 and empty['mean_net_bp'] is None and not g.admitted(empty)


def test_parsers_keep_anchor_minutes_and_time_histdata_by_weekly_open(tmp_path, monkeypatch):
    import gzip
    import zipfile
    monkeypatch.setattr(g, 'ARCHIVE', tmp_path)
    header = b'DateTime,BidOpen,BidHigh,BidLow,BidClose,AskOpen,AskHigh,AskLow,AskClose\n'
    fx = tmp_path/'fxcm'/'USDJPY'/'2026-39.csv.gz'
    fx.parent.mkdir(parents=True)
    fx.write_bytes(gzip.compress(header +
        b'09/27/2026 21:00:00.000,150.0,150.0,150.0,150.0,150.02,150.0,150.0,150.0\n'
        b'09/30/2026 00:55:00.000,150.1,150.2,150.0,150.1,150.12,150.2,150.0,150.1\n'
        b'09/30/2026 01:30:00.000,151.1,151.2,151.0,151.1,151.12,151.2,151.0,151.1\n'))
    (tmp_path/'fxcm'/'USDJPY'/'2026-40.csv.gz').write_bytes(gzip.compress(header +
        b'10/04/2026 23:30:00.000,150.0,150.0,150.0,150.0,150.02,150.0,150.0,150.0\n'))
    bars, opens = g.fxcm_bars('USDJPY', g.needed_minutes())
    assert bars == {datetime(2026, 9, 30, 0, 55, tzinfo=UTC): (150.1, 150.12)}
    assert opens['weeks'] == 2 and opens['late_or_early'] == ['2026-40.csv.gz: 2026-10-04T23:30:00']
    hd = tmp_path/'histdata'/'USDJPY'/'2026.zip'
    hd.parent.mkdir(parents=True)
    with zipfile.ZipFile(hd, 'w') as z:
        z.writestr('DAT_ASCII_USDJPY_M1_2026.csv', '\n'.join([
            '20260104 170000;157.0;0;0;0;0',  # winter week opens 17:00 local = 22:00 UTC: offset 5
            '20260106 195500;157.5;0;0;0;0',
            '20260927 170000;150.0;0;0;0;0',  # US and EU summer: 17:00 local = 21:00 UTC: offset 4
            '20260929 205500;150.09;0;0;0;0',
            '20260929 195500;151.0;0;0;0;0',
            # EU winter, US summer: the feed opens at 16:00 local, still 21:00 UTC: offset 5
            '20261025 160000;152.0;0;0;0;0',
            '20261027 195500;152.5;0;0;0;0']))
    bars, offsets = g.histdata_bars('USDJPY', g.needed_minutes())
    assert bars == {datetime(2026, 1, 7, 0, 55, tzinfo=UTC): (157.5,), datetime(2026, 9, 30, 0, 55, tzinfo=UTC): (150.09,),
                    datetime(2026, 10, 28, 0, 55, tzinfo=UTC): (152.5,)}
    assert offsets == {'5': 2, '4': 1}
