"""Synthetic cross-version/family attacks; never replay production observations."""
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import importlib.util
from pathlib import Path
import threading
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from tradingbot.backtest import Backtester
from tradingbot.backtest.holdout import HoldoutSplit, HoldoutViolation, claim_final, family_identity, register_split
from tradingbot.db.models import BacktestDataset, FamilyHoldoutSpend, HoldoutFamilyAlias, Incident, Strategy as StrategyRow, Trial
from tradingbot.db.session import get_engine
from tradingbot.strategy.interface import Strategy

T0 = datetime(2030, 1, 1, tzinfo=UTC)


@pytest.fixture
def case():
    engine = get_engine()
    prefix = 'test-family-' + uuid4().hex
    ids, datasets = [], []
    def strategy(*, family=prefix, candidate=None):
        key = prefix + '-' + str(len(ids))
        config = {} if family is None else {'research_family': family}
        if candidate:
            config['candidate'] = candidate
        with Session(engine) as s, s.begin():
            row = StrategyRow(key=key, name='Synthetic family admission test', status='backtest',
                              allocation_usd=100, config=config)
            s.add(row); s.flush(); ids.append(row.id)
            return row.id
    def split(start=0, end=10):
        key = prefix + '-' + str(len(datasets))
        datasets.append(key)
        return HoldoutSplit(key, T0 + timedelta(days=start), T0 + timedelta(days=end))
    try:
        yield SimpleNamespace(engine=engine, family=prefix, strategy=strategy, split=split)
    finally:
        with Session(engine) as s, s.begin():
            s.execute(delete(Incident).where(Incident.details['requested_strategy_id'].astext.in_([str(i) for i in ids])))
            s.execute(delete(FamilyHoldoutSpend).where(FamilyHoldoutSpend.trial_id.in_(select(Trial.id).where(Trial.strategy_id.in_(ids)))))
            s.execute(delete(Trial).where(Trial.strategy_id.in_(ids)))
            s.execute(delete(HoldoutFamilyAlias).where(HoldoutFamilyAlias.family_key.like(prefix + '%')))
            s.execute(delete(HoldoutFamilyAlias).where(HoldoutFamilyAlias.alias.in_(['strategy:' + str(i) for i in ids])))
            s.execute(delete(StrategyRow).where(StrategyRow.id.in_(ids)))
            s.execute(delete(BacktestDataset).where(BacktestDataset.key.in_(datasets)))


def claim(case, sid, split, *, version=None, reactor=None):
    with Session(case.engine) as session:
        return claim_final(session, split=split, strategy_id=sid, version=version or uuid4().hex * 2,
                           params={'_holdout': {'identity': {'key': reactor or case.family}}}, notes='Synthetic only')


def test_rewrite_and_all_renames_do_not_buy_another_holdout(case):
    first = claim(case, case.strategy(), case.split())
    sid, split = case.strategy(), case.split()
    class Rewritten(Strategy):
        key = case.family + '-rewritten'
        def on_event(self, ctx, event):
            pytest.fail('Strategy received a reused observation')
    reads = []
    def forbidden_feed():
        reads.append(True)
        yield None
    with Session(case.engine) as session:
        with pytest.raises(HoldoutViolation, match=f'trial {first}'):
            Backtester(session, strategy=Rewritten({'entirely': 'new'}), strategy_id=sid).run(
                forbidden_feed(), split=split, final_holdout=True)
        session.rollback()
    assert not reads
    with Session(case.engine) as s:
        incident = s.scalar(select(Incident).where(Incident.details['requested_strategy_id'].astext == str(sid)))
        assert incident.details['kind'] == 'holdout_family_reuse'
        assert incident.details['family_key'] == case.family
        assert incident.details['first_trial_id'] == first


@pytest.mark.parametrize('start,end', [(1, 11), (-2, 8), (-10, 5), (0, 10)])
def test_shifted_partial_or_former_training_window_is_seen(case, start, end):
    sid = case.strategy()
    claim(case, sid, case.split())
    with pytest.raises(HoldoutViolation, match='already consumed/seen'):
        claim(case, sid, case.split(start, end))


def test_successor_can_use_adjacent_unseen_holdout_but_version_stays_single_use(case):
    sid, version = case.strategy(), uuid4().hex * 2
    first = claim(case, sid, case.split(), version=version)
    # Full source [3,13), holdout [10,13): training may use old data;
    # every new held-out timestamp is outside the previous source [0,10).
    second = claim(case, sid, case.split(3, 13))
    assert first != second
    with pytest.raises(HoldoutViolation, match='already consumed'):
        claim(case, sid, case.split(20, 30), version=version)


def test_other_declared_family_has_its_own_allowance(case):
    one = claim(case, case.strategy(), case.split())
    other = case.family + '-independent'
    two = claim(case, case.strategy(family=other), case.split(), reactor=other)
    assert one != two


@pytest.mark.parametrize('rename_row', [False, True])
def test_changing_family_declaration_is_refused_by_row_or_reactor_alias(case, rename_row):
    sid = case.strategy()
    claim(case, sid, case.split())
    if rename_row:
        sid = case.strategy(family=case.family + '-fake-new')
    else:
        with Session(case.engine) as s, s.begin():
            s.get(StrategyRow, sid).config = {'research_family': case.family + '-fake-new'}
    with pytest.raises(HoldoutViolation, match='binding is immutable'):
        claim(case, sid, case.split(20, 30))
    with Session(case.engine) as s:
        assert s.scalar(select(Incident.id).where(Incident.details['requested_strategy_id'].astext == str(sid)))


def test_missing_or_conflicting_family_fails_closed_and_logs(case):
    for sid in (case.strategy(family=None), case.strategy(candidate='C05-amendment21')):
        with pytest.raises(HoldoutViolation, match='consistent research_family'):
            claim(case, sid, case.split())
        with Session(case.engine) as s:
            assert s.scalar(select(Trial.id).where(Trial.strategy_id == sid)) is None
            assert s.scalar(select(Incident.id).where(Incident.details['requested_strategy_id'].astext == str(sid)))


def test_concurrent_different_versions_and_rows_have_one_winner(case):
    ids, splits = [case.strategy(), case.strategy()], [case.split(), case.split()]
    barrier = threading.Barrier(2)
    def attempt(i):
        barrier.wait()
        try:
            return claim(case, ids[i], splits[i], reactor=case.family + str(i))
        except HoldoutViolation:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(attempt, range(2)))
    assert sum(x is not None for x in result) == 1


@pytest.mark.parametrize('status', ['running', 'failed', 'complete'])
def test_failed_empty_or_short_replay_does_not_shrink_consumed_source(case, status):
    sid, split = case.strategy(), case.split()
    first = claim(case, sid, split)
    with Session(case.engine) as s, s.begin():
        trial = s.get(Trial, first)
        trial.status = status
        trial.data_start = trial.data_end = split.holdout_start
    with pytest.raises(HoldoutViolation):
        claim(case, sid, case.split(2, 12))
    with Session(case.engine) as s:
        receipt = s.get(FamilyHoldoutSpend, first)
        assert receipt.data_start == split.data_start and receipt.data_end == split.data_end
        with pytest.raises(DBAPIError, match='immutable'):
            s.execute(text('UPDATE family_holdout_spends SET data_end=data_end WHERE trial_id=:id'), {'id': first})
        s.rollback()
        with pytest.raises(DBAPIError, match='immutable'):
            s.execute(text('UPDATE holdout_family_aliases SET family_key=family_key WHERE alias=:alias'), {'alias': f'strategy:{sid}'})
        s.rollback()


def migration():
    path = next(Path('src/tradingbot/db/migrations/versions').glob('*family_holdout.py'))
    spec = importlib.util.spec_from_file_location('family_holdout_migration', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('candidate,reactor,family', [
    ('C04-readmission', 'sweep_c04_inverse_variance_readmission_v2', 'c04'),
    ('C05-amendment21', 'sweep_c05_commodity_trend_blackout_v1', 'c05'),
    ('C01', 'c01_L8', 'c01'), (None, 'tom_random_window_control', 'turn_of_month'),
    (None, 'longshot', 'longshot'),
])
def test_frozen_migration_and_runtime_map_legacy_families(candidate, reactor, family):
    config, params = {'candidate': candidate}, {'_frozen': {'key': reactor}}
    assert family_identity(SimpleNamespace(id=1, config=config), params)[0] == family
    assert migration().legacy_family(config, params)[0] == family


def test_backfill_keeps_legacy_final_bytes_and_full_declared_bounds(case):
    sid, split = case.strategy(), case.split()
    with Session(case.engine) as s, s.begin():
        register_split(s, split)
        row = Trial(strategy_id=sid, mode='backtest', status='failed', final_holdout=True,
                    strategy_version=uuid4().hex * 2, dataset_key=split.dataset_key,
                    holdout_start=split.holdout_start, data_start=split.holdout_start,
                    data_end=split.holdout_start, params={'_frozen': {'key': case.family}})
        s.add(row); s.flush(); tid = row.id
    with pytest.raises(HoldoutViolation, match='no family receipt'):
        claim(case, sid, case.split(20, 30))
    with case.engine.begin() as c:
        before = c.scalar(text('SELECT to_jsonb(t)::text FROM trials t WHERE id=:id'), {'id': tid})
        migration().backfill_receipts(c)
        migration().backfill_receipts(c)  # Idempotent; no new admission.
        after = c.scalar(text('SELECT to_jsonb(t)::text FROM trials t WHERE id=:id'), {'id': tid})
        assert before == after
    with Session(case.engine) as s:
        receipt = s.get(FamilyHoldoutSpend, tid)
        assert (receipt.data_start, receipt.holdout_start, receipt.data_end) == (split.data_start, split.holdout_start, split.data_end)
    with pytest.raises(HoldoutViolation, match='already consumed/seen'):
        claim(case, sid, case.split())


def test_renamed_holdout_cannot_relabel_logged_training_data(case):
    sid, train_split = case.strategy(), case.split(0, 30)
    with Session(case.engine) as s, s.begin():
        register_split(s, train_split)
        trial = Trial(strategy_id=sid, mode='backtest', status='failed', final_holdout=False,
                      dataset_key=train_split.dataset_key, holdout_start=train_split.holdout_start,
                      params={'_holdout': {'identity': {'key': case.family}}})
        s.add(trial); s.flush(); tid = trial.id
    # The proposed held-out [14,20) was already inside training [0,21).
    with pytest.raises(HoldoutViolation, match=f'training trial {tid}'):
        claim(case, case.strategy(), case.split(0, 20))
    # Normal training [0,21) does not overlap its proper holdout [21,30).
    assert claim(case, case.strategy(), train_split)


def test_prior_training_reactor_alias_applies_to_another_strategy_row(case):
    sid, split = case.strategy(family=None), case.split(0, 30)
    with Session(case.engine) as s, s.begin():
        register_split(s, split)
        s.add(Trial(strategy_id=sid, mode='backtest', status='complete', final_holdout=False,
                    dataset_key=split.dataset_key, holdout_start=split.holdout_start,
                    params={'_holdout': {'identity': {'key': case.family}}}))
    with pytest.raises(HoldoutViolation, match='already seen in training'):
        claim(case, case.strategy(), case.split(0, 20))


@pytest.mark.parametrize('candidate,reactor', [
    ('C05', 'sweep_c05_commodity_trend_total_return_v1'),
    ('C08', 'sweep_c08_inventory_total_return_v1'),
])
def test_revision_requires_exact_owner_authorized_model_and_reactor(candidate, reactor):
    config = {'candidate': candidate, 'research_revision': 'total_return_d267cf7'}
    row = SimpleNamespace(id=1, config=config)
    identity = {'_frozen': {'key': reactor}}
    assert family_identity(row, identity)[0] == candidate.lower() + ':revision:total_return_d267cf7'
    for key in (reactor.replace('total_return', 'blackout'), 'sweep_' + candidate.lower() + '_renamed'):
        with pytest.raises(HoldoutViolation, match='owner-authorized'):
            family_identity(row, {'_frozen': {'key': key}})
    row.config = {'candidate': candidate, 'research_revision': 'arbitrary-new-version'}
    with pytest.raises(HoldoutViolation, match='owner-authorized'):
        family_identity(row, identity)


def test_authorized_revision_preserves_old_spend_and_is_still_single_use(case, monkeypatch):
    from tradingbot.backtest import holdout
    reactor = case.family + '-total-return'
    monkeypatch.setitem(holdout.OWNER_APPROVED_RESEARCH_REVISIONS, (case.family, 'test-revision'), reactor)
    old = claim(case, case.strategy(), case.split())
    def revised():
        sid = case.strategy()
        with Session(case.engine) as s, s.begin():
            row = s.get(StrategyRow, sid)
            row.config = {**row.config, 'research_revision': 'test-revision'}
        return sid
    new = claim(case, revised(), case.split(), reactor=reactor)
    assert new != old
    with pytest.raises(HoldoutViolation, match=f'trial {new}'):
        claim(case, revised(), case.split(), reactor=reactor)
    with pytest.raises(HoldoutViolation, match=f'trial {old}'):
        claim(case, case.strategy(), case.split())
    with Session(case.engine) as s:
        assert s.get(FamilyHoldoutSpend, old).family_key == case.family
        assert s.get(FamilyHoldoutSpend, new).family_key == case.family + ':revision:test-revision'
