from datetime import date, datetime
from pathlib import Path
import json

import pytest

from tradingbot.data.settlement_calendar import PublishedSettlementCalendar, native_cycle, reconstruct_t1

EVIDENCE = Path(__file__).resolve().parents[2] / 'docs/research/13-equity-data-repair-calendar.json'


def d(value):
    return date.fromisoformat(value)


def test_regulatory_transition_is_effective_on_trade_date():
    assert native_cycle(d('2017-09-01')) == 3
    assert native_cycle(d('2017-09-05')) == 2
    assert native_cycle(d('2024-05-24')) == 2
    assert native_cycle(d('2024-05-28')) == 1


def test_t3_source_proves_t1_without_assuming_weekdays():
    native = {d(a):d(b) for a,b in [
        ('2006-12-27','2007-01-02'), ('2006-12-28','2007-01-03'),
        ('2006-12-29','2007-01-04'), ('2007-01-02','2007-01-05'),
        ('2007-01-03','2007-01-08'), ('2007-01-04','2007-01-09')]}
    result = reconstruct_t1(native, [d('2006-12-29'),d('2007-01-02'),d('2007-01-03')])
    assert result == {d('2006-12-29'):d('2007-01-02'), d('2007-01-02'):d('2007-01-03'),
                      d('2007-01-03'):d('2007-01-04')}


def test_t1_retains_bank_holiday_even_when_market_trades():
    native = {d('2026-10-09'):d('2026-10-13')}
    assert reconstruct_t1(native,list(native)) == native


def test_refuses_source_that_switches_to_t2_before_sec_transition():
    native = {d('2017-07-05'):d('2017-07-07')}
    with pytest.raises(ValueError,match='cannot contain 3 settlement days'):
        reconstruct_t1(native,list(native))


def test_ambiguous_eligibility_is_not_replaced_with_next_weekday():
    native = {d('2006-01-03'):d('2006-01-07')}
    with pytest.raises(ValueError,match='ambiguous'):
        reconstruct_t1(native,list(native))


def test_individually_plausible_but_jointly_inconsistent_dates_fail():
    native = {d('2026-01-02'):d('2026-01-06'),d('2026-01-01'):d('2026-01-05')}
    with pytest.raises(ValueError,match='inconsistent native calendar constraints'):
        reconstruct_t1(native,list(native))


@pytest.mark.parametrize('trade,scheduled', [
    ('2006-04-13','2006-04-17'),  # Good Friday: banks open, NSCC closed.
    ('2006-12-29','2007-01-02'),  # Ford: exchange closed, settlement open.
    ('2012-10-26','2012-10-29'),  # Sandy: exchange closed, settlement open.
    ('2017-07-05','2017-07-06'),  # T+1 counterfactual, not bad provider native T+2.
    ('2017-09-01','2017-09-05'),  # Regulatory change does not change eligibility.
    ('2017-11-09','2017-11-10'),  # Saturday Veterans Day is not observed Friday.
    ('2018-12-04','2018-12-05'),  # Bush mourning day.
    ('2021-06-17','2021-06-18'),  # First federal Juneteenth: DTCC remained open.
    ('2022-06-17','2022-06-21'),
    ('2023-11-09','2023-11-10'),  # Specific DTC notice corrects FINRA table.
    ('2024-03-28','2024-04-01'),
    ('2024-05-24','2024-05-28'),
    ('2025-01-08','2025-01-09'),  # Carter mourning day.
    ('2026-07-02','2026-07-06'),  # Limited DTC opening is not regular settlement.
    ('2026-10-09','2026-10-13'),  # Columbus Day: exchange open, settlement closed.
])
def test_published_primary_schedule_distinguishes_market_and_bank_days(trade,scheduled):
    calendar = PublishedSettlementCalendar.from_evidence(EVIDENCE)
    assert calendar.dates_after(d(trade)) == (d(scheduled),d(scheduled))


def test_delayed_completion_never_releases_cash_on_scheduled_date_or_completion_morning():
    calendar = PublishedSettlementCalendar.from_evidence(EVIDENCE)
    assert calendar.dates_after(d('2026-06-26')) == (d('2026-06-29'),d('2026-06-30'))
    opens = [datetime.fromisoformat(f'{day}T13:30:00+00:00')
             for day in ['2026-06-29','2026-06-30','2026-07-01']]
    assert calendar.conservative_cash_release(d('2026-06-26'),opens) == opens[-1]
    with pytest.raises(ValueError,match='missing session'):
        calendar.conservative_cash_release(d('2026-06-26'),opens[:-1])
    with pytest.raises(ValueError,match='timezone-aware'):
        calendar.conservative_cash_release(d('2026-06-26'),[opens[0].replace(tzinfo=None)])


def test_source_calendar_does_not_extrapolate_or_accept_changed_evidence(tmp_path):
    calendar = PublishedSettlementCalendar.from_evidence(EVIDENCE)
    with pytest.raises(ValueError,match='outside finite'):
        calendar.dates_after(d('2026-12-31'))
    payload = json.loads(EVIDENCE.read_text())
    payload['closed_weekdays'].pop()
    changed = tmp_path / 'changed.json'
    changed.write_text(json.dumps(payload))
    with pytest.raises(ValueError,match='hash mismatch'):
        PublishedSettlementCalendar.from_evidence(changed)
