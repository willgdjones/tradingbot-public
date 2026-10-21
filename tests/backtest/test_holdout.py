"""Admission tests use synthetic events; no real strategy holdout is consumed."""
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import threading
import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from tradingbot.backtest import Backtester, Settlement
from tradingbot.backtest.holdout import HoldoutSplit, HoldoutViolation, register_split
from tradingbot.db.models import (BacktestDataset, FamilyHoldoutSpend, HoldoutFamilyAlias,
                                  Incident, Strategy as StrategyRow, Trial)
from tradingbot.db.session import get_engine
from tradingbot.strategy.interface import MarketEvent, Strategy

T0 = datetime(2020, 1, 1, tzinfo=UTC)


class Observe(Strategy):
    key = "holdout_synthetic_observer"
    def __init__(self, params):
        self.key = params.get("fixture", self.key)
        super().__init__(params)
        self.seen = []
        self.started = False
    def on_start(self, ctx):
        self.started = True
    def on_event(self, ctx, event):
        self.seen.append(event.time)
        if self.params.get("raise"):
            raise RuntimeError("synthetic strategy failure")
        return ()


def event(day):
    return MarketEvent.quote(0, T0 + timedelta(days=day), mid=Decimal("0.5"))


@pytest.fixture
def durable_case():
    """Final admission commits separately; clean up only this synthetic fixture."""
    key = "test-holdout-" + uuid.uuid4().hex
    engine = get_engine()
    with Session(engine) as session, session.begin():
        row = StrategyRow(key=key, name="Synthetic holdout guard test", status="backtest", allocation_usd=100,
                          config={"research_family": key})
        session.add(row); session.flush(); sid = row.id
    split = HoldoutSplit(key, T0, T0 + timedelta(days=10))
    try:
        yield engine, sid, split, {"fixture": key}
    finally:
        with Session(engine) as session, session.begin():
            session.execute(delete(Incident).where(Incident.details["dataset_key"].astext == key))
            session.execute(delete(FamilyHoldoutSpend).where(FamilyHoldoutSpend.family_key == key))
            session.execute(delete(HoldoutFamilyAlias).where(HoldoutFamilyAlias.family_key == key))
            session.execute(delete(Trial).where(Trial.strategy_id == sid))
            session.execute(delete(StrategyRow).where(StrategyRow.id == sid))
            session.execute(delete(BacktestDataset).where(BacktestDataset.key == key))


def test_split_is_elapsed_time_with_exact_boundary():
    split = HoldoutSplit("synthetic", T0, T0 + timedelta(days=10))
    assert split.holdout_start == T0 + timedelta(days=7)
    assert split.contains(event(7).time, final_holdout=True)
    assert not split.contains(event(7).time)
    assert not split.contains(event(10).time, final_holdout=True)
    with pytest.raises(HoldoutViolation, match="timezone-aware"):
        HoldoutSplit("bad", T0.replace(tzinfo=None), T0 + timedelta(days=10))


def test_normal_replay_refuses_holdout_before_strategy_sees_anything(session, strategy_id):
    split = HoldoutSplit("test-normal-boundary", T0, T0 + timedelta(days=10))
    strategy = Observe({})
    bt = Backtester(session, strategy=strategy, strategy_id=strategy_id)
    with pytest.raises(HoldoutViolation, match="strictly before"):
        bt.run([event(0), event(7)], split=split)
    assert not strategy.started and strategy.seen == []
    trial = session.scalar(select(Trial).where(Trial.strategy_id == strategy_id))
    assert trial.status == "failed" and trial.holdout_start == split.holdout_start


def test_normal_replay_records_split_and_refuses_holdout_settlement(session, strategy_id):
    split = HoldoutSplit("test-settlement-boundary", T0, T0 + timedelta(days=10))
    strategy = Observe({})
    result = Backtester(session, strategy=strategy, strategy_id=strategy_id).run([event(0), event(6)], split=split)
    trial = session.get(Trial, result.trial_id)
    assert trial.dataset_key == split.dataset_key and len(trial.strategy_version) == 64
    assert trial.final_holdout is False and strategy.seen == [event(0).time, event(6).time]
    with pytest.raises(HoldoutViolation):
        Backtester(session, strategy=Observe({}), strategy_id=strategy_id).run(
            [event(0)], split=split, settlements=[Settlement(0, Decimal(1), event(7).time)])


def test_dataset_boundaries_cannot_move_between_runs(session):
    split = HoldoutSplit("test-fixed-source", T0, T0 + timedelta(days=10))
    register_split(session, split)
    with pytest.raises(HoldoutViolation, match="bounds are locked"):
        register_split(session, HoldoutSplit(split.dataset_key, T0, T0 + timedelta(days=20)))


def test_final_holdout_once_and_second_attempt_incident_survives_rollback(durable_case):
    engine, sid, split, params = durable_case
    with Session(engine) as session:
        first = Backtester(session, strategy=Observe(params), strategy_id=sid).run(
            [event(7), event(9)], split=split, final_holdout=True, params={"run_id": "first"})
        session.commit()
    seen = []
    def never_consume_again():
        seen.append(True)
        yield event(8)
    with Session(engine) as session:
        with pytest.raises(HoldoutViolation, match="already consumed"):
            Backtester(session, strategy=Observe(params), strategy_id=sid).run(
                never_consume_again(), split=split, final_holdout=True, params={"run_id": "new-name"})
        session.rollback()
    assert seen == []
    with Session(engine) as session:
        trials = session.scalars(select(Trial).where(Trial.strategy_id == sid)).all()
        incident = session.scalar(select(Incident).where(Incident.details["dataset_key"].astext == split.dataset_key))
        assert len(trials) == 1 and trials[0].id == first.trial_id and trials[0].status == "complete"
        assert trials[0].final_holdout and incident.details["first_trial_id"] == first.trial_id


def test_failed_or_rolled_back_final_still_consumes_attempt(durable_case):
    engine, sid, split, params = durable_case
    params = {**params, "raise": True}
    with Session(engine) as session:
        with pytest.raises(RuntimeError, match="synthetic strategy failure"):
            Backtester(session, strategy=Observe(params), strategy_id=sid).run([event(8)], split=split, final_holdout=True)
        session.rollback()
    with Session(engine) as session:
        with pytest.raises(HoldoutViolation, match="already consumed"):
            Backtester(session, strategy=Observe(params), strategy_id=sid).run([event(8)], split=split, final_holdout=True)


def test_concurrent_final_attempts_have_exactly_one_winner(durable_case):
    engine, sid, split, params = durable_case
    barrier = threading.Barrier(2)
    def attempt():
        with Session(engine) as session:
            barrier.wait()
            try:
                result = Backtester(session, strategy=Observe(params), strategy_id=sid).run([event(8)], split=split, final_holdout=True)
                session.commit()
                return result.trial_id
            except HoldoutViolation:
                session.rollback()
                return None
    with ThreadPoolExecutor(max_workers=2) as workers:
        outcomes = list(workers.map(lambda _: attempt(), range(2)))
    assert sum(value is not None for value in outcomes) == 1


def test_changed_frozen_parameters_do_not_reset_family_allowance(durable_case):
    engine, sid, split, params = durable_case
    with Session(engine) as session:
        first = Backtester(session, strategy=Observe({**params, "cutoff": Decimal("1.00000000000000000000000000001")}), strategy_id=sid).run([event(8)], split=split, final_holdout=True)
        session.commit()
        with pytest.raises(HoldoutViolation, match="family .*already consumed"):
            Backtester(session, strategy=Observe({**params, "cutoff": Decimal("1.00000000000000000000000000002")}), strategy_id=sid).run([event(8)], split=split, final_holdout=True)
        session.rollback()
        incident = session.scalar(select(Incident).where(Incident.details["dataset_key"].astext == split.dataset_key))
        assert incident.details["strategy_version"] != session.get(Trial, first.trial_id).strategy_version
        assert incident.details["kind"] == "holdout_family_reuse"


def test_new_strategy_row_and_dataset_name_cannot_reset_same_version(durable_case):
    engine, sid, split, params = durable_case
    renamed = HoldoutSplit(split.dataset_key + "-renamed", split.data_start, split.data_end)
    with Session(engine) as session, session.begin():
        row = StrategyRow(key=renamed.dataset_key, name="Synthetic second row", status="backtest", allocation_usd=100,
                          config={"research_family": split.dataset_key})
        session.add(row); session.flush(); second_sid = row.id
    try:
        with Session(engine) as session:
            Backtester(session, strategy=Observe(params), strategy_id=sid).run([event(8)], split=split, final_holdout=True)
            session.rollback()  # The durable claim still exists.
        with Session(engine) as session:
            with pytest.raises(HoldoutViolation, match="already consumed"):
                Backtester(session, strategy=Observe(params), strategy_id=second_sid).run(
                    [event(8)], split=renamed, final_holdout=True)
            session.rollback()
        with Session(engine) as session:
            incident = session.scalar(select(Incident).where(Incident.details["dataset_key"].astext == renamed.dataset_key))
            assert incident.details["requested_strategy_id"] == second_sid
    finally:
        with Session(engine) as session, session.begin():
            session.execute(delete(Incident).where(Incident.details["dataset_key"].astext == renamed.dataset_key))
            session.execute(delete(Trial).where(Trial.strategy_id == second_sid))
            session.execute(delete(StrategyRow).where(StrategyRow.id == second_sid))
            session.execute(delete(BacktestDataset).where(BacktestDataset.key == renamed.dataset_key))
