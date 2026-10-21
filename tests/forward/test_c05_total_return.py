from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal as D
from uuid import uuid4
import json

import pytest
from sqlalchemy import select

from forward.test_c05_runner import setup as legacy_setup, fill_all
from tradingbot.connectors.alpaca_paper import NAME as CONNECTOR
from tradingbot.connectors.cash import timestamp
from tradingbot.db.models import Fill, FxRate, JevRequest, Strategy, Trial
from tradingbot.forward import c05_runner as legacy
from tradingbot.forward import c05_total_return as p
from tradingbot.forward.c05_state import NAME, dump_core


@pytest.fixture
def setup(legacy_setup, monkeypatch):
    old, api, clock, current = legacy_setup
    session, trial = old.session, old.trial()
    venue = old.connector._venue(lock=True)
    venue.metadata_ = {**venue.metadata_, CONNECTOR: {**venue.metadata_[CONNECTOR], 'guard_required': None}}
    session.get(Strategy, trial.strategy_id).allocation_usd = D(35)
    trial.code_version, trial.strategy_version = p.VERSION, p.RESEARCH_VERSION
    trial.params = {**trial.params, **p.PARAMS, 'dependencies': p.dependencies(),
        'review_sha256': p.digest((p.ROOT / p.PLAN).read_bytes())}
    core = p.restore_core(trial.params, expected_params=p.PARAMS)
    trial.metrics = {NAME: {**trial.metrics[NAME], 'core': dump_core(core), 'activity_receipts': []}}
    session.commit()
    receipts, calls = {}, []
    def write(name, value):
        body = json.dumps(value).encode()
        ref = {'path': name + str(len(receipts)), 'sha256': p.digest(body)}
        receipts[ref['path']] = body
        return ref
    def read(ref):
        body = receipts[ref['path']]
        assert p.digest(body) == ref['sha256']
        return body
    def price_source(connector, sessions):
        calls.append('prices')
        market = [s for s in sessions if s.closes_at < clock[0]][-1]
        independent = write('independent', {'bars': {s: [{'t': market.opens_at.isoformat(), 'c': '100'}] for s in p.SYMBOLS}})
        row = {'last_session': str(market.trade_date), 'reviewed_at': clock[0].isoformat(),
            'watch': {'independent_receipt': independent}, 'raw_receipts': [independent], 'actions': [], 'blackouts': [],
            'vintage': {s: {'last_session': str(market.trade_date), 'adjusted_closes': ['100'] * 126 + ['101'],
                'raw_closes': ['100'] * 127, 'observed_at': clock[0].isoformat()} for s in p.SYMBOLS}}
        return write('prices', row)
    def activity_source(connector, sessions, *, since):
        calls.append('activities')
        return write('activities', {'exhausted': True, 'account_matches_book': True,
            'observed_at': clock[0].isoformat(), 'c05_records': current.get('records', [])})
    monkeypatch.setattr(p, 'read_receipt', read)
    monkeypatch.setattr(legacy, 'read_receipt', read)
    runner = p.Runner(session, api, trial.id, now=lambda: clock[0], price_source=price_source, activity_source=activity_source)
    state = runner.state()
    state['source_review'] = price_source(runner.connector, runner.sessions)
    runner.save(state)
    return runner, api, clock, current, calls


def to_open(setup):
    runner, api, clock, _, _ = setup
    clock[0] = timestamp('2026-10-30T20:05:00Z')
    assert runner.step() == 'close_observed'
    clock[0] = timestamp('2026-11-02T14:25:00Z')
    runner.step()
    clock[0] = timestamp('2026-11-02T14:30:00Z')
    return runner.step()


def test_monthly_close_uses_unchanged_rule_and_35_dollar_slot(setup):
    r, api, clock, current, calls = setup
    assert r.step() == 'close_observed'
    assert r.core.targets == dict.fromkeys(p.SYMBOLS, D('6.65'))
    assert r.core.reserve == D('1.75')
    assert r.connector._book(r.connector._venue())['initial_cash'] == '140'
    assert r.connector._book(r.connector._venue()).get('guard_required') is None
    assert len(r.core.decisions) == 1 and not api.submissions


def test_real_opening_intents_fills_restart_and_no_duplicate_post(setup):
    r, api, clock, current, calls = setup
    assert to_open(setup) == 'awaiting_buys'
    assert len(api.submissions) == 5
    orders = r.orders()
    assert sum((o.size*o.limit_price for o in orders), D(0)) <= D('33.25')
    fill_all(r, api, clock)
    r.step()
    clone = p.Runner(r.session, api, r.trial_id, now=lambda: clock[0], price_source=r.price_source, activity_source=r.activity_source)
    clone.step()
    assert len(api.submissions) == 5
    assert len(list(r.session.scalars(select(Fill).where(Fill.trial_id == r.trial_id)))) == 5
    assert clone.ctx.marked_equity() == D('34.99')  # Actual/model fee debits remain in equity.
    assert clone.state().get('ready_for_live', False) is False


def test_no_preopen_receipt_refuses_opening(setup):
    r, api, clock, *_ = setup
    r.step()
    clock[0] = timestamp('2026-11-02T14:30:00Z')
    assert r.step() == 'held_for_resolution'
    assert not api.submissions


def test_source_prices_failure_holds_without_orders(setup):
    r, api, clock, *_ = setup
    def unavailable(*args): raise ValueError('price missing')
    r.price_source = unavailable
    assert r.step() == 'held_for_resolution'
    assert not api.submissions


def test_actual_action_is_archived_and_holds_owned_symbol_without_fake_fill(setup):
    r, api, clock, current, calls = setup
    to_open(setup)
    fill_all(r, api, clock)
    r.step()
    before = len(list(r.session.scalars(select(Fill).where(Fill.trial_id == r.trial_id))))
    quantity_before = r.ctx.position(r.ids['GLD'])
    current['records'] = [{'activity_type': 'SSP', 'symbol': 'GLD', 'qty': '2'}]
    with pytest.raises(ValueError, match='attribution'):
        r.observe_activities()
    assert r.state()['hold']['key'] == 'broker-action'
    assert r.state()['activity_receipts']
    assert len(list(r.session.scalars(select(Fill).where(Fill.trial_id == r.trial_id)))) == before
    assert r.ctx.position(r.ids['GLD']) == quantity_before


def test_records_for_unowned_symbols_do_not_block_admission(setup):
    r, api, clock, current, calls = setup
    current['records'] = [{'activity_type': 'DIV', 'symbol': 'DBA', 'net_amount': '10'}]
    r.observe_activities()
    r._balances()
    assert r.evidence.strategy_cash(r.strategy_id) == 35
    assert not r.state().get('hold')


def test_source_or_plan_identity_change_refuses(setup):
    r, api, clock, *_ = setup
    trial = r.trial()
    trial.params = {**trial.params, 'review_sha256': 'wrong'}
    r.session.commit()
    with pytest.raises(ValueError, match='identity'):
        r.step()
    assert not api.submissions


def test_other_shared_costs_reduce_available_cash_without_allocation_changes(setup):
    r, api, clock, *_ = setup
    venue = r.connector._venue()
    other = Strategy(key='other-cost-' + uuid4().hex, name='Other paper', venue_id=venue.id, status='paper', allocation_usd=D(35))
    r.session.add(other); r.session.flush()
    trial = Trial(strategy_id=other.id, mode='paper', params={}, metrics={})
    r.session.add(trial); r.session.flush()
    r.session.add(JevRequest(id=str(uuid4()), started_ts=clock[0], billing_month=clock[0].date().replace(day=1),
        correlation_id=f'paper-trial:{trial.id}:fixture', questions={}, requested_model='jev-latest',
        status='uncertain', reserved_usd=D('.2'), input_price_per_million=D(1), pricing_version='fixture', outcomes={}))
    r.session.commit()
    r._balances()
    assert r.evidence.strategy_cash(r.strategy_id) == D(35)
    assert r.evidence.cash_available == D('139.8')
    assert r.evidence.strategy_offsets[other.id] == D('-.2')
    venue = r.connector._venue(lock=True)
    # The actual book remains owned by the connector, with no extra C05 funds.
    assert D(r.connector._book(venue)['initial_cash']) == 140
    assert r.session.get(Strategy, r.strategy_id).allocation_usd == 35


def test_prepare_has_no_historical_replay_no_funding_and_no_orders(setup, monkeypatch):
    r, api, clock, *_ = setup
    prior = r.trial()
    prior.status = 'complete'
    r.session.commit()
    monkeypatch.setattr(p, 'historical_evidence', lambda s: [{'trial_id':5385}, {'trial_id':5401}])
    book_before = deepcopy(r.connector._book(r.connector._venue()))
    result = p.prepare(r.session, api, through=date(2026,12,1), git_commit='fixture', now=clock[0],
        price_source=r.price_source, activity_source=r.activity_source)
    assert result['status'] == 'active_paper_not_ready_for_live'
    assert r.connector._book(r.connector._venue()) == book_before
    assert r.session.get(Strategy, r.strategy_id).allocation_usd == 35
    assert not api.submissions
    new = r.session.get(Trial,result['trial_id'])
    assert new.params['historical_evidence'] == [{'trial_id':5385}, {'trial_id':5401}]
    assert new.params['slot_usd'] == '35'
    with pytest.raises(ValueError, match='continuation'):
        p.prepare(r.session, api, through=date(2026,12,1), git_commit='fixture', now=clock[0])


def test_failed_source_prepare_is_ledgered_disabled(setup, monkeypatch):
    r, api, clock, *_ = setup
    r.trial().status = 'complete';r.session.commit()
    monkeypatch.setattr(p, 'historical_evidence', lambda s: [])
    def fail(*args): raise ValueError('missing')
    result = p.prepare(r.session, api, through=date(2026,12,1), git_commit='fixture', now=clock[0],
        price_source=fail, activity_source=r.activity_source)
    assert result['status'] == 'failed' and result['stage'] == 'prices'
    trial = r.session.get(Trial,result['trial_id'])
    assert trial.status == 'failed' and trial.trade_count == 0
    assert r.session.get(Strategy,trial.strategy_id).allocation_usd == 0
    assert not api.submissions


def test_unknown_post_is_never_retried_and_keeps_reservation(setup):
    r, api, clock, *_ = setup
    api.timeout_submit = True
    to_open(setup)
    assert len(api.submissions) == 1
    assert r.state().get('hold')
    assert r.orders()[0].metadata_['submission_unknown']
    r.step()  # Known-order GET resolves the acknowledgement; no second POST.
    assert len(api.submissions) == 1
    assert r.orders() and r.connector.cash().reserved > 0


def test_current_day_preparation_includes_only_future_close_work(setup, monkeypatch):
    r, api, clock, *_ = setup
    r.trial().status = 'complete'; r.session.commit()
    clock[0] = timestamp('2026-10-30T15:00:00Z')
    monkeypatch.setattr(p, 'historical_evidence', lambda s: [])
    result = p.prepare(r.session, api, through=date(2026,12,1), git_commit='fixture', now=clock[0],
        price_source=r.price_source, activity_source=r.activity_source)
    assert result['status'] == 'active_paper_not_ready_for_live'
    trial = r.session.get(Trial,result['trial_id'])
    assert trial.params['session_dates'][0] == '2026-10-30'
    clone = p.Runner(r.session, api, trial.id, now=lambda: clock[0], price_source=r.price_source, activity_source=r.activity_source)
    assert clone.step() == 'observing'
    assert clone.state()['phases']['2026-10-30:open']['status'] == 'missed_window'
    assert not api.submissions


def test_flat_terminal_completes_but_never_qualifies_live(setup):
    r, api, clock, *_ = setup
    clock[0] = timestamp('2026-12-01T14:25:00Z')
    # Completed preceding-session prices are captured, without historical signal replay.
    state = r.state();state['source_review'] = r.price_source(r.connector,r.sessions);r.save(state)
    r.step()
    clock[0] = timestamp('2026-12-01T14:30:00Z')
    assert r.step() == 'complete_requires_fidelity_review'
    trial = r.session.get(Trial,r.trial_id)
    assert trial.status == 'complete' and trial.pnl_after_fees == 0
    assert trial.metrics[NAME]['ready_for_live'] is False
    assert not api.submissions


def test_owned_terminal_liquidation_sells_all_without_new_buys(setup):
    r, api, clock, *_ = setup
    to_open(setup)
    fill_all(r, api, clock); r.step()
    assert all(r.ctx.position(i) > 0 for i in r.ids.values())
    clock[0] = timestamp('2026-12-01T14:25:00Z')
    state = r.state();state['source_review'] = r.price_source(r.connector,r.sessions);r.save(state)
    r.session.add(FxRate(base='USD', quote='GBP', ts=timestamp('2026-12-01T00:00:00Z'), rate=D('.8'), source='fixture'))
    r.session.commit()
    r.step()
    clock[0] = timestamp('2026-12-01T14:30:00Z')
    assert r.step() == 'awaiting_reductions'
    assert len(api.submissions) == 10 and all(o.side == 'sell' for o in r.orders())
    fill_all(r, api, clock)
    assert r.step() == 'complete_requires_fidelity_review'
    assert all(r.ctx.position(i) == 0 for i in r.ids.values())
    trial = r.session.get(Trial,r.trial_id)
    assert trial.status == 'complete' and trial.fees_total > 0
    assert trial.pnl_after_fees < 0 and trial.metrics[NAME]['ready_for_live'] is False
    assert len(api.submissions) == 10


def test_preopen_broker_activity_failure_refuses_new_orders(setup):
    r, api, clock, *_ = setup
    def fail(*args, **kwargs): raise ValueError('unavailable')
    r.activity_source = fail
    clock[0] = timestamp('2026-11-02T14:25:00Z')
    assert r.step() == 'held_for_resolution'
    clock[0] = timestamp('2026-11-02T14:30:00Z')
    assert r.step() == 'held_for_resolution' and not api.submissions


def bell_without_uso(setup, *, regular_after):
    # 2026-10-07: USO's first regular-session IEX quote came 16 s after the bell,
    # so the 09:30:04 capture failed and permanently held trial 7852.
    r, api, clock, *_ = setup
    assert r.step() == 'close_observed'
    clock[0] = timestamp('2026-11-02T14:25:00Z')
    r.step()
    bell, one = timestamp('2026-11-02T14:30:00Z'), api.quote
    api.quote = lambda s: ({**one(s), 't': (bell - timedelta(seconds=2)).isoformat()}
                           if s == 'USO' and clock[0] < bell + regular_after else one(s))
    clock[0] = bell + timedelta(seconds=4)
    assert r.step() == 'awaiting_opening_marks'
    assert not api.submissions and not r.state().get('hold')
    return r, api, clock, bell


def test_opening_marks_missing_at_the_bell_are_retried_inside_the_window(setup):
    r, api, clock, bell = bell_without_uso(setup, regular_after=timedelta(seconds=16))
    clock[0] = bell + timedelta(seconds=17)
    assert r.step() == 'awaiting_buys' and len(api.submissions) == 5


def test_opening_marks_missing_all_window_miss_the_phase_without_a_hold(setup):
    r, api, clock, bell = bell_without_uso(setup, regular_after=timedelta(hours=1))
    clock[0] = bell + timedelta(seconds=59)
    assert r.step() == 'awaiting_opening_marks'
    clock[0] = bell + timedelta(seconds=61)
    r.step()
    assert r.state()['phases']['2026-11-02:open']['status'] == 'missed_window'
    assert not r.state().get('hold') and not api.submissions
