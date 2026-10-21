from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from connectors.conftest import FakeAPI, isolate_alpaca_venue
from tradingbot.connectors.cash import timestamp
from tradingbot.db.models import Fill, FxRate, Incident, Order, Strategy, Trial, Venue
from tradingbot.db.seed import seed
from tradingbot.db.session import get_engine
from tradingbot.forward.turn_of_month import NAME, Runner, import_fx, plan


def calendar_rows(start=date(2026, 9, 1), end=date(2026, 11, 10)):
    # Synthetic deterministic test calendar, never used for an actual run.
    holidays = {date(2026, 9, 7)}
    rows = []
    while start <= end:
        if start.weekday() < 5 and start not in holidays:
            rows.append({"date": start.isoformat(), "settlement_date": (start + timedelta(days=3 if start.weekday() == 4 else 1)).isoformat(),
                         "open": "09:30", "close": "16:00"})
        start += timedelta(days=1)
    return rows


@pytest.fixture
def setup():
    seed()
    connection = get_engine().connect()
    outer = connection.begin()
    session = Session(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
    try:
        isolate_alpaca_venue(session)
        now = [timestamp("2026-09-25T19:58:00Z")]
        api = FakeAPI(now)
        rows = calendar_rows()
        api.calendar = lambda day: deepcopy([row for row in rows if row["date"] == day.isoformat()])
        api.calendar_range = lambda start, end: deepcopy([row for row in rows if start.isoformat() <= row["date"] <= end.isoformat()])
        from tradingbot.connectors.alpaca_paper import AlpacaPaperConnector
        connector = AlpacaPaperConnector(session, api, now=lambda: now[0])
        iid = connector.register_equity("SPY")
        connector.initialize_cash(D(100))
        row = Strategy(key="tom-forward-test-" + uuid4().hex, name="Forward test", venue_id=session.scalar(select(Venue.id).where(Venue.key == "alpaca")), status="paper", allocation_usd=D(100))
        session.add(row); session.flush()
        params = plan(rows, start=timestamp("2026-09-01T00:00:00Z"), through=date(2026, 11, 4), instrument_id=iid)
        trial = Trial(strategy_id=row.id, mode="paper", code_version=NAME, params=params, metrics={NAME: {"attempts": {}}})
        session.add_all([trial, FxRate(base="USD", quote="GBP", ts=now[0]-timedelta(days=1), rate=D(".8"), source="forward-test")])
        session.commit()
        runner = Runner(session, api, trial.id, now=lambda: now[0])
        yield runner, api, now
    finally:
        session.close()
        try:
            assert outer.is_active
            outer.rollback()
        finally:
            connection.close()


def test_plan_shared_fourth_last_third_next_rule_and_no_catchup():
    rows = calendar_rows()
    params = plan(rows, start=timestamp("2026-09-30T22:00:00Z"), through=date(2026, 11, 4), instrument_id=1)
    assert params["schedule"] == {"2026-10-27": "buy", "2026-11-04": "sell"}
    early = deepcopy(rows)
    next(r for r in early if r["date"] == "2026-10-27")["close"] = "13:00"
    assert plan(early, start=timestamp("2026-09-30T22:00:00Z"), through=date(2026, 11, 4), instrument_id=1)["session_closes"]["2026-10-27"] == "13:00:00"
    with pytest.raises(ValueError):
        plan(rows[::-1], start=timestamp("2026-09-30T22:00:00Z"), through=date(2026, 11, 4), instrument_id=1)


def test_scheduled_submission_and_restart_are_once_only(setup):
    runner, api, now = setup
    assert runner.step() == "observing"
    assert not api.submissions
    now[0] = timestamp("2026-09-25T19:59:00Z")
    assert runner.step() == "open"
    assert len(api.submissions) == 1
    assert api.submissions[0]["qty"] == "0.249000000"
    restarted = Runner(runner.session, api, runner.trial_id, now=lambda: now[0])
    restarted.step()
    assert len(api.submissions) == 1
    assert all(o.mode == "paper" for o in runner.session.scalars(select(Order).where(Order.trial_id == runner.trial_id)))


def test_unknown_post_is_polled_without_a_second_submission(setup):
    runner, api, now = setup
    now[0] = timestamp("2026-09-25T19:59:00Z")
    api.timeout_submit = True
    assert runner.step() == "pending"
    Runner(runner.session, api, runner.trial_id, now=lambda: now[0]).step()
    assert len(api.submissions) == 1
    assert runner.orders()[0].metadata_["submission_unknown"] is False


def test_partial_entry_exit_uses_only_filled_owned_shares(setup):
    runner, api, now = setup
    now[0] = timestamp("2026-09-25T19:59:00Z")
    runner.step()
    request = runner.state()["attempts"]["2026-09-25"]["request_id"]
    now[0] += timedelta(seconds=1)
    api.fill(request, qty=".1")
    api.orders["tbp-" + request]["status"] = "expired"
    runner.step()
    assert runner.ctx.position(runner.iid) == D(".1")
    now[0] = timestamp("2026-10-05T19:59:00Z")
    runner.session.add(FxRate(base="USD", quote="GBP", ts=now[0]-timedelta(days=1), rate=D(".8"), source="forward-test")); runner.session.commit()
    runner.step()
    assert len(api.submissions) == 2 and api.submissions[1]["qty"] == "0.1000000000"
    exit_request = runner.state()["attempts"]["2026-10-05"]["request_id"]
    now[0] += timedelta(seconds=1)
    api.fill(exit_request, qty=".1")
    runner.step()
    assert runner.ctx.position(runner.iid) == 0
    assert len(list(runner.session.scalars(select(Fill).where(Fill.trial_id == runner.trial_id)))) == 2
    assert D(runner.state()["modeled_regulatory_fees"]) > 0


@pytest.mark.parametrize("fault", ["stale", "killed", "halt", "errors", "fx"])
def test_risk_and_fx_veto_send_no_order(setup, fault):
    runner, api, now = setup
    now[0] = timestamp("2026-09-25T19:59:00Z")
    if fault == "stale": api.quote_age = timedelta(seconds=31)
    if fault == "killed": runner.session.get(Strategy, runner.strategy_id).status = "killed"
    if fault == "halt": runner.connector.risk.trigger_daily_halt("paper", D(-50), now[0])
    if fault == "errors":
        for _ in range(5): runner.connector.risk.record_api_error(now[0])
    if fault == "fx":
        from sqlalchemy import delete
        runner.session.execute(delete(FxRate))
    runner.session.commit()
    try: runner.step()
    except ValueError: pass
    assert not api.submissions


def test_crash_after_claim_never_resends_or_enters_late(setup):
    runner, api, now = setup
    state = runner.state()
    runner.save({**state, "attempts": {"2026-09-25": {"status": "claimed", "side": "buy"}}})
    now[0] = timestamp("2026-09-25T19:59:00Z")
    runner.step()
    now[0] = timestamp("2026-09-25T20:01:00Z")
    runner.step()
    assert not api.submissions
    assert "claimed-2026-09-25" in runner.state()["incidents"]


def test_missed_window_does_not_submit_after_close(setup):
    runner, api, now = setup
    now[0] = timestamp("2026-09-25T20:00:00Z")
    assert runner.step() == "outside_session"
    assert runner.state()["attempts"]["2026-09-25"]["status"] == "missed_window"
    assert not api.submissions


def test_early_close_uses_new_york_calendar_time(setup):
    runner, api, now = setup
    trial = runner.trial()
    params = deepcopy(trial.params)
    next(r for r in params["calendar"] if r["date"] == "2026-09-25")["close"] = "13:00"
    params["session_closes"]["2026-09-25"] = "13:00:00"
    trial.params = params
    runner.session.commit()
    api.calendar = lambda day: deepcopy([r for r in params["calendar"] if r["date"] == day.isoformat()])
    early = Runner(runner.session, api, runner.trial_id, now=lambda: now[0])
    now[0] = timestamp("2026-09-25T16:58:59Z")
    early.step()
    assert not api.submissions
    now[0] += timedelta(seconds=1)
    assert early.step() == "open"


def test_exit_residual_is_an_incident_without_unscheduled_orders(setup):
    runner, api, now = setup
    now[0] = timestamp("2026-09-25T19:59:00Z")
    runner.step()
    request = runner.state()["attempts"]["2026-09-25"]["request_id"]
    now[0] += timedelta(seconds=1)
    api.fill(request, qty=".249")
    runner.step()
    now[0] = timestamp("2026-10-05T20:01:00Z")
    runner.step()
    assert len(api.submissions) == 1
    assert "residual-exit-2026-10-05" in runner.state()["incidents"]


def test_ecb_conversion_is_dated_and_repeatable(setup):
    runner, _, _ = setup
    body = b'<Envelope><Cube time="2026-09-23"><Cube currency="USD" rate="1.2"/><Cube currency="GBP" rate=".9"/></Cube></Envelope>'
    import_fx(runner.session, body, timestamp("2026-09-25T12:00:00Z"))
    import_fx(runner.session, body, timestamp("2026-09-25T12:00:00Z"))
    row = runner.session.scalar(select(FxRate).where(FxRate.ts == timestamp("2026-09-24T00:00:00Z")))
    assert row.rate == D(".75")


def test_slot_context_subtracts_modeled_fees_and_preserves_cash_floor(setup):
    runner, api, now = setup
    runner.save({**runner.state(), 'modeled_regulatory_fees': '3.50'})
    assert runner.ctx.available_cash(runner.iid) == D('96.50')
    assert runner.ctx.available_cash(-1) is None
    runner.core.params.update(entry_notional='140', use_available_cash=True, entry_fee_reserve='.01')
    now[0] = timestamp('2026-09-25T19:59:00Z')
    # Read-only sizing alone never places a venue order.
    from tradingbot.strategy.interface import MarketEvent
    event = MarketEvent.quote(runner.iid, now[0], bid=D('99.99'), ask=D('100'))
    runner.snapshots[runner.iid] = event.as_snapshot()
    order, = runner.core.on_event(runner.ctx, event)
    assert order.size * order.limit_price == D('96.49')
    assert not api.submissions


def slot_trials():
    from types import SimpleNamespace
    common = dict(mode='backtest', status='complete', strategy_version='frozen',
                  dataset_key='fixture', holdout_start=timestamp('2023-07-12T01:06:00Z'),
                  pnl_after_fees=D('1'), params={'variant': 'tom_minute_2bp',
                      'strategy_params': {'entry_notional': '140', 'use_available_cash': True,
                          'entry_fee_reserve': '.01', 'seconds_before_close': 60},
                      '_holdout': {'identity': {'key': 'turn_of_month'}}})
    return (SimpleNamespace(id=1, final_holdout=False, **deepcopy(common)),
            SimpleNamespace(id=2, final_holdout=True, **deepcopy(common)))


def test_slot_evidence_requires_profitable_matching_locked_trials():
    from tradingbot.forward.turn_of_month import slot_evidence
    train, final = slot_trials()
    evidence = slot_evidence(train, final)
    assert evidence['primary_trial'] == 1 and evidence['holdout_trial'] == 2
    assert evidence['entry_notional'] == '140' and evidence['use_available_cash']
    for field, value in [('pnl_after_fees', D(0)), ('strategy_version', 'changed'),
                         ('dataset_key', 'different'), ('final_holdout', False),
                         ('status', 'running'), ('holdout_start', None)]:
        train, final = slot_trials()
        setattr(final, field, value)
        with pytest.raises(ValueError):
            slot_evidence(train, final)
    train, final = slot_trials()
    final.params['strategy_params']['entry_notional'] = '24.90'
    with pytest.raises(ValueError):
        slot_evidence(train, final)


def test_only_unused_paper_can_be_superseded(setup):
    from tradingbot.forward.turn_of_month import unused_paper_trial
    runner, api, now = setup
    before = deepcopy(runner.trial().params)
    assert unused_paper_trial(runner.session, runner.strategy_id, runner.trial_id).id == runner.trial_id
    with pytest.raises(ValueError):
        unused_paper_trial(runner.session, runner.strategy_id, -1)
    runner.save({**runner.state(), 'attempts': {'2026-09-25': {'status': 'claimed'}}})
    with pytest.raises(ValueError):
        unused_paper_trial(runner.session, runner.strategy_id, runner.trial_id)
    runner.save({**runner.state(), 'attempts': {}})
    now[0] = timestamp('2026-09-25T19:59:00Z')
    runner.step()
    runner.save({**runner.state(), 'attempts': {}})
    with pytest.raises(ValueError):
        unused_paper_trial(runner.session, runner.strategy_id, runner.trial_id)
    assert runner.trial().params == before and runner.trial().status == 'running'
