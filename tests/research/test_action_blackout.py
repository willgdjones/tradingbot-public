from datetime import date, timedelta

import pytest

from tradingbot.research.action_blackout import (
    BlackoutBook, CorporateAction, UnadmittableAction, plan_blackouts)


def weekdays(start, end):
    day, out = start, []
    while day <= end:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


SESSIONS = weekdays(date(2020, 4, 1), date(2020, 5, 29))
USO = CorporateAction('USO', 'reverse_split', date(2020, 4, 21), date(2020, 4, 29), date(2020, 4, 29), 'issuer')


def test_exit_before_ex_date_and_reenter_after_payable():
    [plan] = plan_blackouts([USO], SESSIONS)
    assert (plan.decision, plan.exit, plan.reentry) == (date(2020, 4, 27), date(2020, 4, 28), date(2020, 4, 30))
    book = BlackoutBook([plan])
    assert book.forced_exits(date(2020, 4, 28)) == ['USO']
    assert book.forced_exits(date(2020, 4, 27)) == []
    assert book.holdable('USO', date(2020, 4, 27))
    assert not book.holdable('USO', date(2020, 4, 28))
    assert not book.holdable('USO', date(2020, 4, 29))
    assert book.holdable('USO', date(2020, 4, 30))
    assert book.holdable('SPY', date(2020, 4, 29))


def test_in_kind_distribution_waits_past_payable_across_weekend():
    xlf = CorporateAction('XLF', 'in_kind_distribution', date(2020, 4, 1), date(2020, 4, 15),
                          date(2020, 4, 17), 'issuer')
    [plan] = plan_blackouts([xlf], SESSIONS)
    assert (plan.exit, plan.reentry) == (date(2020, 4, 14), date(2020, 4, 20))


def test_ex_date_on_non_session_uses_prior_session():
    action = CorporateAction('XLE', 'split', date(2020, 4, 1), date(2020, 4, 18), date(2020, 4, 18), 'x')
    [plan] = plan_blackouts([action], SESSIONS)
    assert (plan.decision, plan.exit, plan.reentry) == (date(2020, 4, 16), date(2020, 4, 17), date(2020, 4, 20))


def test_late_announcement_is_unadmittable():
    late = CorporateAction('USO', 'reverse_split', date(2020, 4, 28), date(2020, 4, 29), date(2020, 4, 29), 'x')
    with pytest.raises(UnadmittableAction, match='after exit decision'):
        plan_blackouts([late], SESSIONS)


@pytest.mark.parametrize('ex_date, payable', [(date(2020, 4, 2), date(2020, 4, 2)),
                                              (date(2020, 5, 20), date(2020, 5, 29))])
def test_events_at_record_edges_fail_closed(ex_date, payable):
    action = CorporateAction('USO', 'split', date(2020, 3, 1), ex_date, payable, 'x')
    with pytest.raises(UnadmittableAction, match='outside session record'):
        plan_blackouts([action], SESSIONS)


def test_inconsistent_dates_fail_closed():
    action = CorporateAction('USO', 'split', date(2020, 4, 1), date(2020, 4, 20), date(2020, 4, 17), 'x')
    with pytest.raises(UnadmittableAction, match='inconsistent'):
        plan_blackouts([action], SESSIONS)


def test_cash_dividends_are_out_of_scope():
    dividend = CorporateAction('SPY', 'cash_dividend', date(2020, 4, 1), date(2020, 4, 20), date(2020, 4, 30), 'x')
    assert plan_blackouts([dividend], SESSIONS) == []
