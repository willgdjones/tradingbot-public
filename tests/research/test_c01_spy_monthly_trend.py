"""C01 synthetic regression and durable-admission tests; no real price replay."""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal as D
from copy import deepcopy
import json
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from tradingbot.backtest.holdout import HoldoutSplit, HoldoutViolation, claim_final
from tradingbot.db.models import FamilyHoldoutSpend, HoldoutFamilyAlias, BacktestDataset, Incident, Strategy, Trial
from tradingbot.db.session import get_engine
from tradingbot.data.free_history import DailyBar
from tradingbot.research import c01_spy_monthly_trend as c01
from tradingbot.strategy.spy_monthly_trend import SpyMonthlyTrend


def _month_bars(year, month, price, *, adj=None, div=D(0), n=2):
    adj = price if adj is None else adj
    out = []
    for day in range(3, 3 + n):
        out.append(DailyBar(date=date(year, month, day), open=price, high=price * D("1.01"),
                            low=price * D("0.99"), close=price, volume=1000, adj_close=adj,
                            dividend=(div if day == 3 else D(0)), split_ratio=D(1)))
    return out


def _series(prices, *, start_year=2007, divs=None):
    """prices: list of monthly close/adj values; one entry per consecutive month."""
    divs = divs or {}
    bars = []
    y, m = start_year, 1
    for i, p in enumerate(prices):
        bars += _month_bars(y, m, D(str(p)), div=divs.get(i, D(0)))
        m += 1
        if m > 12:
            m = 1; y += 1
    return bars


def _strat(L):
    return SpyMonthlyTrend(key=f"c01_L{L}",
                           params={"lookback_months": L, "target_weight": "0.95", "symbol": "SPY"})


def test_uptrend_goes_long_and_profits():
    prices = [100 + 10 * i for i in range(8)]  # strictly rising
    res = c01.C01Backtester(_strat(3), 10).run(_series(prices))
    assert res.net_return > 0
    assert res.n_trades == 2           # one entry + terminal liquidation
    assert res.round_trips == 1
    assert res.avg_exposure > 0.4      # long for most of the window
    assert D(res.fees_total) > 0 and D(res.slippage_total) > 0


def test_downtrend_stays_in_cash():
    prices = [200 - 10 * i for i in range(8)]  # strictly falling
    res = c01.C01Backtester(_strat(3), 10).run(_series(prices))
    assert res.n_trades == 0
    assert res.net_return == 0.0
    assert res.avg_exposure == 0.0
    assert D(res.end_equity) == D("140")


def test_dividends_are_credited_when_held():
    prices = [100 + 10 * i for i in range(8)]
    # pay a dividend in month index 5 (while long after warm-up at L=3)
    res = c01.C01Backtester(_strat(3), 10).run(_series(prices, divs={5: D("1.50")}))
    assert D(res.dividends_total) > 0


def test_no_look_ahead_entry_is_next_month_open():
    # Signal first fires at end of month index 2 (L=3), so the earliest trade date
    # is in month index 3 (the next month), never earlier.
    prices = [100 + 10 * i for i in range(8)]
    res = c01.C01Backtester(_strat(3), 10).run(_series(prices))
    first_trade = min(t["date"] for t in res.trades)
    assert first_trade >= date(2007, 4, 1)  # month index 3 == April 2007


def test_split_bars_partitions_at_cutoff():
    split = HoldoutSplit(c01.DATASET_KEY, c01.DATA_START, c01.DATA_END)
    cutoff = split.holdout_start.date()  # 2020-07-10
    bars = [DailyBar(date=d, open=D(1), high=D(1), low=D(1), close=D(1), volume=1,
                     adj_close=D(1), dividend=D(0), split_ratio=D(1))
            for d in (date(2020, 7, 9), date(2020, 7, 10), date(2020, 7, 13))]
    train = c01.split_bars(bars, split, final_holdout=False)
    hold = c01.split_bars(bars, split, final_holdout=True)
    assert [b.date for b in train] == [date(2020, 7, 9)]
    assert [b.date for b in hold] == [date(2020, 7, 10), date(2020, 7, 13)]
    assert cutoff == date(2020, 7, 10)


def test_slippage_cost_scales_with_bp():
    prices = [100 + 10 * i for i in range(8)]
    lo = c01.C01Backtester(_strat(3), 5).run(_series(prices))
    hi = c01.C01Backtester(_strat(3), 10).run(_series(prices))
    assert D(hi.slippage_total) > D(lo.slippage_total)


@pytest.fixture
def durable():
    """Only uniquely named synthetic fixtures are committed, then removed."""
    key = "test-c01-admission-" + uuid4().hex
    engine = get_engine()
    with Session(engine) as session, session.begin():
        row = Strategy(key=key, name="C01 synthetic admission test", status="backtest", allocation_usd=140,
                       config={"research_family": key})
        session.add(row); session.flush(); sid = row.id
    split = HoldoutSplit(key, datetime(2000, 1, 1, tzinfo=UTC), datetime(2010, 1, 1, tzinfo=UTC))
    strategy = SpyMonthlyTrend(key=key, params={"lookback_months": 3, "target_weight": "0.95", "symbol": "SPY"})
    try:
        yield engine, sid, split, strategy
    finally:
        with Session(engine) as session, session.begin():
            session.execute(delete(Incident).where(Incident.details["dataset_key"].astext == key))
            session.execute(delete(FamilyHoldoutSpend).where(FamilyHoldoutSpend.family_key == key))
            session.execute(delete(HoldoutFamilyAlias).where(HoldoutFamilyAlias.family_key == key))
            session.execute(delete(Trial).where(Trial.strategy_id == sid))
            session.execute(delete(Strategy).where(Strategy.id == sid))
            session.execute(delete(BacktestDataset).where(BacktestDataset.key == key))


def replay(session, fixture, feed):
    _, sid, split, strategy = fixture
    return c01.replay_final_once(session, strategy_row_id=sid, split=split,
                                strategy=strategy, feed_factory=feed, commit="synthetic")


def test_final_admission_is_visible_before_even_loading_the_feed(durable):
    engine, sid, split, strategy = durable
    seen = []
    def feed():
        with Session(engine) as independent:
            trial = independent.scalar(select(Trial).where(Trial.strategy_id == sid))
            assert trial.final_holdout and trial.status == "running"
            assert trial.git_commit == "synthetic"
            seen.append(trial.id)
        return _series([100 + 10*i for i in range(8)])
    with Session(engine) as session:
        result = replay(session, durable, feed)
        assert seen == [result["trial_id"]]
        assert result["status"] == "complete" and result["trades_available"]
        assert result["replayed"]
        assert isinstance(result["result"]["trades"][0]["date"], str)
        assert not result["evidence_audit"]["promotion_eligible"]


def test_repeated_invocation_and_changed_source_identity_only_render_stored(durable):
    engine, sid, split, strategy = durable
    with Session(engine) as session:
        first = replay(session, durable, lambda: _series([100 + 10*i for i in range(8)]))
        before = deepcopy(dict(session.execute(select(Trial.__table__).where(Trial.id == first["trial_id"])).mappings().one()))
    strategy.params["lookback_months"] = 7
    def forbidden():
        pytest.fail("A consumed candidate must not load or replay its price feed")
    with Session(engine) as session:
        second = replay(session, durable, forbidden)
        after = dict(session.execute(select(Trial.__table__).where(Trial.id == first["trial_id"])).mappings().one())
    assert {**first, "replayed": False} == second and before == after
    assert second["params"]["lookback_months"] == 3


@pytest.mark.parametrize("failure", [RuntimeError, KeyboardInterrupt])
def test_failed_or_interrupted_replay_stays_consumed_after_caller_rollback(durable, failure):
    engine, sid, split, strategy = durable
    def bad_feed():
        raise failure("private exception content")
    with Session(engine) as session:
        with pytest.raises(failure): replay(session, durable, bad_feed)
        session.rollback()
    with Session(engine) as session:
        result = replay(session, durable, lambda: pytest.fail("failed attempt retried"))
        trial = session.get(Trial, result["trial_id"])
        assert trial.status == "failed" and trial.final_holdout
        assert failure.__name__ in trial.notes and "private exception content" not in trial.notes


def test_process_lost_after_admission_is_not_retried(durable):
    engine, sid, split, strategy = durable
    with Session(engine) as session:
        tid = claim_final(session, split=split, strategy_id=sid, version=uuid4().hex*2,
                          params={"synthetic": True}, notes="Simulated process loss after durable admission")
        session.rollback()
    with Session(engine) as session:
        result = replay(session, durable, lambda: pytest.fail("interrupted feed retried"))
        assert result["trial_id"] == tid and result["status"] == "running"
        assert result["result"] is None


def test_admission_failure_never_loads_feed(durable, monkeypatch):
    engine, sid, split, strategy = durable
    def refuse(*args, **kwargs):
        raise HoldoutViolation("synthetic admission refused")
    monkeypatch.setattr(c01, "claim_final", refuse)
    with Session(engine) as session:
        with pytest.raises(HoldoutViolation, match="refused"):
            replay(session, durable, lambda: pytest.fail("feed read before admission"))
        assert session.scalar(select(Trial.id).where(Trial.strategy_id == sid)) is None


@pytest.mark.parametrize("args", [["--no-ledger"], ["--no-holdout"], ["--capture", "an-existing-archive"]])
def test_legacy_cli_replay_flags_fail_before_database_or_simulation(monkeypatch, args):
    monkeypatch.setattr(c01, "local_engine", lambda: pytest.fail("DB should not be needed for refusal"))
    monkeypatch.setattr(c01.C01Backtester, "run", lambda *a: pytest.fail("legacy replay"))
    with pytest.raises(SystemExit) as error: c01.main(args)
    assert error.value.code == 2


def test_stored_cli_uses_ledger_only_and_preserves_existing_export(durable, monkeypatch, tmp_path, capsys):
    engine, sid, split, strategy = durable
    with Session(engine) as session:
        first = replay(session, durable, lambda: _series([100 + 10*i for i in range(8)]))
    monkeypatch.setattr(c01, "local_engine", lambda: engine)
    monkeypatch.setattr(c01, "STRATEGY_KEY", strategy.key)
    monkeypatch.setattr(c01, "DATASET_KEY", split.dataset_key)
    monkeypatch.setattr(c01.C01Backtester, "run", lambda *a: pytest.fail("stored export replayed"))
    target = tmp_path / "stored.json"
    c01.main(["--out", str(target)])
    exported = json.loads(target.read_text())
    assert exported["holdout"] == {**first, "replayed": False}
    assert exported["verdict"]["outcome"] == "FAILED_AUDIT"
    before = target.read_bytes()
    with pytest.raises(FileExistsError): c01.main(["--out", str(target)])
    assert target.read_bytes() == before
    assert '"replayed": false' in capsys.readouterr().out


def test_legacy_metrics_without_trade_details_are_not_fabricated(durable, monkeypatch):
    engine, sid, split, strategy = durable
    with Session(engine) as session:
        first = replay(session, durable, lambda: _series([100 + 10*i for i in range(8)]))
        trial = session.get(Trial, first["trial_id"])
        metrics = deepcopy(trial.metrics); metrics.pop("trades")
        trial.metrics = metrics; session.commit()
        stored = c01.stored_final(trial)
        assert not stored["trades_available"] and "trades" not in stored["result"]
