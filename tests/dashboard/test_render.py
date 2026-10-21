"""Pure HTML rendering tests (no DB)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from tradingbot.dashboard import render

D = Decimal


def test_fmt_money():
    assert render.fmt_money(D("1.5")) == "$1.50"
    assert render.fmt_money(D("-2")) == "-$2.00"
    assert render.fmt_money(D("1234.5")) == "$1,234.50"
    assert render.fmt_money(None) == "—"


def test_fmt_luck():
    assert render.fmt_luck(None) == "—"
    assert render.fmt_luck(0.0066178) == "0.007"


def test_money_cell_classes():
    assert "pos" in render.money_cell(D("1"))
    assert "neg" in render.money_cell(D("-1"))
    assert "pos" not in render.money_cell(D("0")) and "neg" not in render.money_cell(D("0"))


def _empty_snapshot() -> dict:
    return {
        "generated_at": datetime(2026, 9, 30, 16, 0, tzinfo=timezone.utc),
        "mode": "live",
        "modes": ["backtest", "paper", "live"],
        "leaderboard": [],
        "backtest_vs_live": [],
        "incidents": [],
        "active_halts": [],
        "pipeline": {"strategies_by_status": {}, "trials": [], "venues": 0},
    }


def test_render_empty_snapshot():
    html_out = render.render_dashboard(_empty_snapshot())
    assert "<!doctype html>" in html_out
    assert "tradingbot dashboard" in html_out
    assert "No active halts" in html_out
    assert "No strategies." in html_out


def test_render_with_data_and_halt_banner():
    snap = _empty_snapshot()
    snap["leaderboard"] = [{
        "strategy_id": 1, "key": "longshot", "name": "Favourite–longshot bias",
        "status": "live", "allocation_usd": D("140"), "mode": "live",
        "trade_count": 3, "fill_count": 6, "pnl_after_fees": D("12.34"),
        "fees_total": D("0.50"), "luck_p_value": 0.012, "open_positions": 1,
    }]
    snap["active_halts"] = [{
        "scope": "global_daily", "strategy_id": None, "mode": "live",
        "halt_date": None, "reason": "Daily P&L -60 <= -50", "pnl_at_trigger": D("-60"),
        "triggered_ts": datetime(2026, 9, 30, 15, 0, tzinfo=timezone.utc),
    }]
    html_out = render.render_dashboard(snap)
    assert "longshot" in html_out
    assert "$12.34" in html_out
    assert "active halt" in html_out  # banner
    assert "0.012" in html_out


def test_render_kill_switch_states():
    snap = _empty_snapshot()
    assert "No connector kill switch" in render.render_dashboard(snap)
    snap["kill_switches"] = [{
        "venue": "alpaca", "switch": "alpaca_live_kill_switch_v1", "active": True, "reason": "<drill>",
        "engaged_at": datetime(2026, 10, 17, 14, 0, tzinfo=timezone.utc), "cleared_at": None, "cleared_note": None,
    }]
    html_out = render.render_dashboard(snap)
    assert "1 kill switch(es) engaged" in html_out and "ENGAGED" in html_out
    assert "&lt;drill&gt;" in html_out
    snap["kill_switches"][0].update(active=False, cleared_note="owner, drill over",
                                    cleared_at=datetime(2026, 10, 17, 15, 0, tzinfo=timezone.utc))
    html_out = render.render_dashboard(snap)
    assert "engaged — live orders refused" not in html_out and "owner, drill over" in html_out


def test_render_escapes_html():
    snap = _empty_snapshot()
    snap["incidents"] = [{
        "ts": datetime(2026, 9, 30, tzinfo=timezone.utc), "severity": "warning",
        "category": "api_error", "strategy_id": None, "mode": "live",
        "message": "<script>alert(1)</script>", "resolved": False,
    }]
    html_out = render.render_dashboard(snap)
    assert "<script>alert(1)</script>" not in html_out
    assert "&lt;script&gt;" in html_out


def test_render_backtest_trials_section():
    snap = _empty_snapshot()
    snap["backtest_trials"] = [{
        "trial_id": 842, "strategy": "longshot",
        "variant": "buy_favourite 0.05 KXCPI", "trade_count": 1,
        "pnl_after_fees": D("3.89"), "max_drawdown": D("0"),
        "luck_p_value": None, "regimes": "2026-07",
    }]
    html_out = render.render_dashboard(snap)
    assert "Backtest trials" in html_out
    assert "buy_favourite 0.05 KXCPI" in html_out
    assert "$3.89" in html_out
    assert "2026-07" in html_out


def test_render_backtest_trials_empty_when_absent():
    # A snapshot without the key still renders (defensive .get).
    html_out = render.render_dashboard(_empty_snapshot())
    assert "No completed backtest trials yet." in html_out


def test_statistics_and_evidence_are_visible_scoped_and_escaped():
    from tradingbot.ledger.report_stats import empty_statistics
    snap = _empty_snapshot()
    stats = empty_statistics()
    stats.update(sharpe=1.25, hit_rate=.625, oos_t_stat=-.75,
                 sharpe_basis="<script>bad</script>")
    snap["final_holdouts"] = [{"trial_id": 23, "strategy": "sample", "variant": "fixed",
        "trade_count": 8, "pnl_after_fees": D(4), "max_drawdown": D(2), "luck_p_value": None,
        "regimes": "one", "partition": "Final holdout", "statistics": stats,
        "evidence": "FAILED AUDIT — not promotion evidence"}]
    output = render.render_dashboard(snap)
    assert "1.25" in output and "62.5%" in output and "-0.75" in output
    assert "Basis &amp; samples" in output and "Recorded final holdouts" in output
    assert "FAILED AUDIT" in output and "Informational only" in output
    assert "<script>bad" not in output and "&lt;script&gt;bad" in output
