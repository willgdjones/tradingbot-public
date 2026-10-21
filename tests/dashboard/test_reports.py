"""Dashboard report-query tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select

from tradingbot.dashboard import reports
from tradingbot.db import enums
from tradingbot.db.models import BacktestDataset, Incident, RiskHalt, Trial, Venue
from tradingbot.ledger import Ledger

D = Decimal
TS = datetime(2026, 9, 30, 16, 0, tzinfo=timezone.utc)


def _round_trip(led, instrument, strategy, mode, buy, sell, fee="0.01"):
    o1 = led.record_order(instrument_id=instrument.id, mode=mode, side=enums.Side.BUY,
                          order_type=enums.OrderType.LIMIT, size=D("10"), strategy_id=strategy.id)
    led.record_fill(order=o1, price=D(buy), size=D("10"), liquidity=enums.Liquidity.MAKER,
                    fill_ts=TS, fee=D(fee))
    o2 = led.record_order(instrument_id=instrument.id, mode=mode, side=enums.Side.SELL,
                          order_type=enums.OrderType.LIMIT, size=D("10"), strategy_id=strategy.id)
    led.record_fill(order=o2, price=D(sell), size=D("10"), liquidity=enums.Liquidity.MAKER,
                    fill_ts=TS + timedelta(minutes=1), fee=D(fee))


def test_leaderboard_has_all_strategies_and_computes_pnl(session, instrument, strategy):
    led = Ledger(session)
    _round_trip(led, instrument, strategy, enums.Mode.LIVE, "0.40", "0.60")

    board = reports.leaderboard(session, mode=enums.Mode.LIVE)
    # Every seeded strategy appears. (The shared DB may also hold research
    # strategies committed by other runners, so assert the seeded set is present
    # rather than an exact global count.)
    seeded = {"longshot", "rewards", "spx_ranges", "weather", "letf_eod",
              "turn_of_month", "promotions", "x_mention"}
    assert seeded <= {r["key"] for r in board}
    row = next(r for r in board if r["key"] == "longshot")
    assert row["trade_count"] == 1
    assert row["pnl_after_fees"] == D("1.98")  # 2.0 gross - 0.02 fees
    assert row["statistics"]["hit_rate"] == 1
    assert row["statistics"]["max_drawdown"] == D(".01")  # entry fee is visible before exit
    assert row["statistics"]["sharpe"] is row["statistics"]["oos_t_stat"] is None
    # best P&L should sort to the top
    assert board[0]["key"] == "longshot"


def test_leaderboard_mode_isolation(session, instrument, strategy):
    led = Ledger(session)
    _round_trip(led, instrument, strategy, enums.Mode.BACKTEST, "0.40", "0.60")
    live_board = reports.leaderboard(session, mode=enums.Mode.LIVE)
    row = next(r for r in live_board if r["key"] == "longshot")
    assert row["trade_count"] == 0  # nothing in live mode


def test_backtest_ledgers_cached_until_backtest_fills_change(session, instrument, strategy, monkeypatch):
    calls = []
    compute = reports._compute_ledgers
    monkeypatch.setattr(reports, "_compute_ledgers", lambda s, modes: calls.append(set(modes)) or compute(s, modes))
    monkeypatch.setattr(reports, "_BACKTEST_CACHE", {})
    first = reports._scoped_ledgers(session, {enums.Mode.BACKTEST, enums.Mode.LIVE})
    assert reports._scoped_ledgers(session, {enums.Mode.BACKTEST, enums.Mode.LIVE}) == first
    assert calls.count({enums.Mode.BACKTEST}) == 1  # second call reused the replay
    _round_trip(Ledger(session), instrument, strategy, enums.Mode.BACKTEST, "0.40", "0.60")
    after = reports._scoped_ledgers(session, {enums.Mode.BACKTEST})
    assert calls.count({enums.Mode.BACKTEST}) == 2
    assert after[(strategy.id, enums.Mode.BACKTEST)]["trade_count"] == (
        first.get((strategy.id, enums.Mode.BACKTEST), {"trade_count": 0})["trade_count"] + 1)


def test_backtest_vs_live_gap(session, instrument, strategy):
    led = Ledger(session)
    _round_trip(led, instrument, strategy, enums.Mode.BACKTEST, "0.40", "0.60")  # +1.98
    _round_trip(led, instrument, strategy, enums.Mode.LIVE, "0.40", "0.55")  # +1.48
    rows = reports.backtest_vs_live_gap(session)
    row = next(r for r in rows if r["key"] == "longshot")
    assert row["backtest_pnl_after_fees"] == D("1.98")
    assert row["live_pnl_after_fees"] == D("1.48")  # (0.55-0.40)*10 - 0.02
    assert row["gap"] == D("-0.50")


def test_recent_incidents(session, strategy):
    session.add(Incident(severity=enums.Severity.CRITICAL,
                         category=enums.IncidentCategory.DAILY_HALT,
                         mode=enums.Mode.LIVE, message="test halt"))
    session.flush()
    incs = reports.recent_incidents(session)
    assert any(i["message"] == "test halt" and i["severity"] == "critical" for i in incs)


def test_active_halts(session, strategy):
    session.add(RiskHalt(scope=enums.HaltScope.GLOBAL_DAILY, mode=enums.Mode.LIVE,
                         halt_date=TS.date(), reason="test", pnl_at_trigger=D("-60"), active=True))
    session.add(RiskHalt(scope=enums.HaltScope.STRATEGY, strategy_id=strategy.id,
                         mode=enums.Mode.LIVE, reason="old", active=False))
    session.flush()
    halts = reports.active_halts(session)
    assert len(halts) == 1
    assert halts[0]["scope"] == enums.HaltScope.GLOBAL_DAILY


def test_kill_switches_read_venue_metadata(session):
    venue = session.scalar(select(Venue).where(Venue.key == "alpaca"))
    venue.metadata_ = {**(venue.metadata_ or {}), "alpaca_live_kill_switch_v1": {
        "active": True, "reason": "dashboard test", "engaged_at": TS.isoformat()}}
    session.flush()
    rows = [r for r in reports.kill_switches(session) if r["switch"] == "alpaca_live_kill_switch_v1"]
    assert rows == [{"venue": "alpaca", "switch": "alpaca_live_kill_switch_v1", "active": True,
                     "reason": "dashboard test", "engaged_at": TS, "cleared_at": None, "cleared_note": None}]
    assert "kill_switches" in reports.dashboard_snapshot(session)


def test_pipeline_status(session):
    status = reports.pipeline_status(session)
    assert status["strategies_by_status"]["idea"] >= 1
    assert status["venues"] >= 4


def test_dashboard_snapshot_shape(session, instrument, strategy):
    snap = reports.dashboard_snapshot(session, mode=enums.Mode.LIVE)
    assert set(snap) >= {
        "generated_at", "mode", "modes", "leaderboard",
        "backtest_vs_live", "incidents", "active_halts", "pipeline",
    }
    assert snap["mode"] == enums.Mode.LIVE


def test_backtest_trials_lists_completed_with_drawdown_and_regime(session, strategy):
    trial = Trial(
        strategy_id=strategy.id, mode=enums.Mode.BACKTEST,
        status=enums.TrialStatus.COMPLETE,
        params={"side_rule": "buy_favourite", "offset": "0.05", "category": "KXCPI"},
        pnl=D("4.00"), pnl_after_fees=D("4.02"), fees_total=D("-0.02"),
        trade_count=1, max_drawdown=D("0"), luck_p_value=None,
        completed_ts=TS,
        metrics={
            "by_regime": {"2026-07": {"trade_count": 1, "pnl_after_fees": "4.02",
                                       "max_drawdown": "0", "luck_p_value": None}},
            "max_drawdown": "0",
        },
    )
    session.add(trial)
    session.flush()

    # Large limit: the shared DB may hold many committed research trials.
    rows = reports.backtest_trials(session, limit=5000)
    row = next(r for r in rows if r["trial_id"] == trial.id)
    assert row["strategy"] == "longshot"
    assert row["trade_count"] == 1
    assert row["max_drawdown"] == D("0")
    assert "buy_favourite" in row["variant"] and "KXCPI" in row["variant"]
    assert row["regimes"] == "2026-07"


def test_dashboard_snapshot_includes_backtest_trials(session, instrument, strategy):
    snap = reports.dashboard_snapshot(session, mode=enums.Mode.LIVE)
    assert "backtest_trials" in snap
    assert isinstance(snap["backtest_trials"], list)
    assert "final_holdouts" in snap


def test_final_holdout_stats_are_per_trial_and_read_only(session, strategy):
    from types import SimpleNamespace
    start = datetime(2026, 1, 5, 21, tzinfo=timezone.utc)
    source = SimpleNamespace(data_start=start, data_end=start+timedelta(days=3),
        holdout_start=start-timedelta(days=1), code_version="c05-amendment21-v1", params={"slot_usd": "100"},
        max_drawdown=D(11), metrics={"complete_execution": True, "daily_exposure": [
            {"date": (start+timedelta(days=i)).date().isoformat(), "marked_equity_usd": value}
            for i, value in enumerate(("100", "110", "99", "108.9"))]})
    key = "report-statistics-" + uuid4().hex
    session.add(BacktestDataset(key=key, data_start=source.data_start-timedelta(days=365),
                               holdout_start=source.holdout_start, data_end=source.data_end+timedelta(days=1)))
    session.flush()
    final = Trial(strategy_id=strategy.id, mode="backtest", status="complete",
        code_version=source.code_version, data_start=source.data_start, data_end=source.data_end,
        dataset_key=key, strategy_version=key, holdout_start=source.holdout_start, final_holdout=True,
        params=source.params, metrics=source.metrics, max_drawdown=source.max_drawdown,
        pnl_after_fees=D("8.9"), trade_count=0, completed_ts=TS)
    session.add(final); session.flush()
    before = (final.metrics.copy(), final.sharpe, final.win_rate, final.pnl_after_fees)
    rows = reports.backtest_trials(session, final_only=True)
    row = next(r for r in rows if r["trial_id"] == final.id)
    assert row["partition"] == "Final holdout"
    assert abs(row["statistics"]["oos_t_stat"] - .5) < 1e-12
    assert row["statistics"]["sharpe_samples"] == 3
    assert "Recorded final" in row["evidence"]
    assert before == (final.metrics, final.sharpe, final.win_rate, final.pnl_after_fees)
    assert final not in session.dirty
