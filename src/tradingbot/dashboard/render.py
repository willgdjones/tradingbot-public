"""Pure HTML rendering for the dashboard (no I/O, so it is unit-testable).

Takes the dicts from :mod:`tradingbot.dashboard.reports` and returns an HTML
string. Deliberately dependency-free: server-rendered tables, dark-mode aware,
auto-refreshing. Charts can come later.
"""

from __future__ import annotations

import html
from datetime import date, datetime
from decimal import Decimal
from ..ledger.report_stats import NOTICE, empty_statistics, scope_text

REFRESH_SECONDS = 30

_CSS = """
:root { color-scheme: light dark; --fg:#111; --muted:#666; --line:#ddd; --bg:#fff;
        --pos:#0a7d2c; --neg:#c02626; --warn:#b8860b; --crit:#c02626; }
@media (prefers-color-scheme: dark) {
  :root { --fg:#e6e6e6; --muted:#9aa0a6; --line:#333; --bg:#14161a;
          --pos:#4ade80; --neg:#f87171; --warn:#facc15; --crit:#f87171; } }
* { box-sizing: border-box; }
body { font: 14px/1.45 -apple-system, system-ui, Segoe UI, Roboto, sans-serif;
       color: var(--fg); background: var(--bg); margin: 0; padding: 24px; }
h1 { font-size: 20px; margin: 0 0 2px; }
h2 { font-size: 15px; margin: 28px 0 8px; }
.meta { color: var(--muted); font-size: 12px; margin-bottom: 8px; }
table { border-collapse: collapse; width: 100%; margin-top: 4px; }
th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--line);
         white-space: nowrap; }
th { color: var(--muted); font-weight: 600; font-size: 12px; text-transform: uppercase;
     letter-spacing: .03em; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
.pos { color: var(--pos); } .neg { color: var(--neg); }
.pill { display:inline-block; padding:1px 8px; border-radius:10px; font-size:12px;
        border:1px solid var(--line); }
.sev-critical { color: var(--crit); font-weight: 600; }
.sev-warning { color: var(--warn); }
.empty { color: var(--muted); font-style: italic; padding: 8px 0; }
.banner { padding:8px 12px; border-radius:6px; border:1px solid var(--crit);
          color:var(--crit); margin: 8px 0 4px; font-weight:600; }
footer { color: var(--muted); font-size: 12px; margin-top: 32px; }
.table-wrap { overflow-x: auto; max-width: 100%; }
.stats-scope, .evidence { white-space: normal; min-width: 180px; max-width: 360px; }
.stats-scope details[open] { min-width: 280px; }
.stats-scope summary { cursor: pointer; white-space: nowrap; }
"""


def _esc(v) -> str:
    return html.escape("" if v is None else str(v))


def fmt_money(v: Decimal | None) -> str:
    if v is None:
        return "—"
    v = Decimal(v)
    sign = "-" if v < 0 else ""
    return f"{sign}${abs(v):,.2f}"


def money_cell(v: Decimal | None) -> str:
    cls = ""
    if v is not None and v != 0:
        cls = "pos" if v > 0 else "neg"
    return f'<td class="num {cls}">{_esc(fmt_money(v))}</td>'


def fmt_luck(p: float | None) -> str:
    if p is None:
        return "—"
    return f"{p:.3f}"


def fmt_ts(ts) -> str:
    if ts is None:
        return "—"
    if isinstance(ts, (datetime,)):
        return ts.strftime("%Y-%m-%d %H:%M:%S%z") or ts.isoformat()
    if isinstance(ts, date):
        return ts.isoformat()
    return _esc(ts)


def _statistics_cells(row):
    stats = row.get("statistics") or empty_statistics()
    ratio = lambda value: "—" if value is None else f"{value:.2f}"
    hit = "—" if stats["hit_rate"] is None else f"{stats['hit_rate']:.1%}"
    return (f"<td class='num'>{_esc(ratio(stats['sharpe']))}</td>"
            f"<td class='num'>{_esc(hit)}</td>"
            f"<td class='num'>{_esc(ratio(stats['oos_t_stat']))}</td>"
            f"<td class='stats-scope'><details><summary>Basis &amp; samples</summary>"
            f"{_esc(scope_text(stats))}</details></td>")


def _leaderboard_table(rows: list[dict]) -> str:
    if not rows:
        return '<div class="empty">No strategies.</div>'
    head = (
        "<tr><th>Strategy</th><th>Status</th><th>Alloc</th>"
        "<th>Trades</th><th>Fills</th><th>P&amp;L after fees</th>"
        "<th>Fees</th><th>Luck p</th><th>Open</th><th>Realized drawdown</th>"
        "<th>Sharpe</th><th>Hit rate</th><th>OOS t</th><th>Statistic scope</th></tr>"
    )
    body = []
    for r in rows:
        body.append(
            "<tr>"
            f"<td>{_esc(r['name'])} <span class='pill'>{_esc(r['key'])}</span></td>"
            f"<td>{_esc(r['status'])}</td>"
            f"{money_cell(r['allocation_usd'])}"
            f"<td class='num'>{_esc(r['trade_count'])}</td>"
            f"<td class='num'>{_esc(r['fill_count'])}</td>"
            f"{money_cell(r['pnl_after_fees'])}"
            f"{money_cell(r['fees_total'])}"
            f"<td class='num'>{_esc(fmt_luck(r['luck_p_value']))}</td>"
            f"<td class='num'>{_esc(r['open_positions'])}</td>"
            f"<td class='num'>{_esc(fmt_money((r.get('statistics') or {}).get('max_drawdown')))}</td>"
            f"{_statistics_cells(r)}"
            "</tr>"
        )
    return f"<div class='table-wrap'><table>{head}{''.join(body)}</table></div>"


def _gap_table(rows: list[dict]) -> str:
    if not rows:
        return '<div class="empty">No backtest or live activity yet.</div>'
    head = (
        "<tr><th>Strategy</th><th>Backtest P&amp;L</th><th>BT trades</th>"
        "<th>Live P&amp;L</th><th>Live trades</th><th>Gap (live−bt)</th></tr>"
    )
    body = []
    for r in rows:
        body.append(
            "<tr>"
            f"<td>{_esc(r['name'])} <span class='pill'>{_esc(r['key'])}</span></td>"
            f"{money_cell(r['backtest_pnl_after_fees'])}"
            f"<td class='num'>{_esc(r['backtest_trade_count'])}</td>"
            f"{money_cell(r['live_pnl_after_fees'])}"
            f"<td class='num'>{_esc(r['live_trade_count'])}</td>"
            f"{money_cell(r['gap'])}"
            "</tr>"
        )
    return f"<table>{head}{''.join(body)}</table>"


def _halts_section(halts: list[dict]) -> str:
    if not halts:
        return '<div class="empty">No active halts. Trading permitted.</div>'
    banner = f'<div class="banner">⛔ {len(halts)} active halt(s) — trading vetoed</div>'
    head = "<tr><th>Scope</th><th>Strategy</th><th>Mode</th><th>Since</th><th>P&amp;L</th><th>Reason</th></tr>"
    body = []
    for h in halts:
        body.append(
            "<tr>"
            f"<td>{_esc(h['scope'])}</td>"
            f"<td>{_esc(h['strategy_id'])}</td>"
            f"<td>{_esc(h['mode'])}</td>"
            f"<td>{_esc(fmt_ts(h['triggered_ts']))}</td>"
            f"{money_cell(h['pnl_at_trigger'])}"
            f"<td>{_esc(h['reason'])}</td>"
            "</tr>"
        )
    return banner + f"<table>{head}{''.join(body)}</table>"


def _kill_switch_section(switches: list[dict]) -> str:
    if not switches:
        return '<div class="empty">No connector kill switch has been set.</div>'
    engaged = [s for s in switches if s["active"]]
    banner = (f'<div class="banner">⛔ {len(engaged)} kill switch(es) engaged — live orders refused</div>'
              if engaged else "")
    head = "<tr><th>Venue</th><th>Switch</th><th>State</th><th>Engaged</th><th>Reason</th><th>Cleared</th><th>Note</th></tr>"
    body = []
    for s in switches:
        state = "<td class='sev-critical'>ENGAGED</td>" if s["active"] else "<td>clear</td>"
        body.append(
            "<tr>"
            f"<td>{_esc(s['venue'])}</td>"
            f"<td>{_esc(s['switch'])}</td>"
            f"{state}"
            f"<td>{_esc(fmt_ts(s['engaged_at']))}</td>"
            f"<td>{_esc(s['reason'])}</td>"
            f"<td>{_esc(fmt_ts(s['cleared_at']))}</td>"
            f"<td>{_esc(s['cleared_note'])}</td>"
            "</tr>"
        )
    return banner + f"<table>{head}{''.join(body)}</table>"


def _incidents_table(incidents: list[dict]) -> str:
    if not incidents:
        return '<div class="empty">No incidents logged.</div>'
    head = "<tr><th>Time</th><th>Severity</th><th>Category</th><th>Mode</th><th>Message</th><th>Resolved</th></tr>"
    body = []
    for inc in incidents:
        body.append(
            "<tr>"
            f"<td>{_esc(fmt_ts(inc['ts']))}</td>"
            f"<td class='sev-{_esc(inc['severity'])}'>{_esc(inc['severity'])}</td>"
            f"<td>{_esc(inc['category'])}</td>"
            f"<td>{_esc(inc['mode'])}</td>"
            f"<td>{_esc(inc['message'])}</td>"
            f"<td>{'yes' if inc['resolved'] else 'no'}</td>"
            "</tr>"
        )
    return f"<table>{head}{''.join(body)}</table>"


def _pipeline_section(pipeline: dict) -> str:
    counts = pipeline["strategies_by_status"]
    pills = " ".join(
        f"<span class='pill'>{_esc(status)}: {_esc(n)}</span>"
        for status, n in counts.items()
        if n
    ) or "<span class='empty'>no strategies</span>"
    trials = pipeline["trials"]
    if trials:
        rows = "".join(
            f"<tr><td>{_esc(t['mode'])}</td><td>{_esc(t['status'])}</td>"
            f"<td class='num'>{_esc(t['count'])}</td></tr>"
            for t in trials
        )
        trials_html = f"<table><tr><th>Mode</th><th>Trial status</th><th>Count</th></tr>{rows}</table>"
    else:
        trials_html = '<div class="empty">No trials recorded yet.</div>'
    return f"<div>{pills}</div>{trials_html}"


def _backtest_trials_table(rows: list[dict]) -> str:
    if not rows:
        return '<div class="empty">No completed backtest trials yet.</div>'
    head = (
        "<tr><th>Trial</th><th>Strategy</th><th>Variant</th><th>Trades</th>"
        "<th>Partition</th><th>P&amp;L after fees</th><th>Max drawdown</th><th>Luck p</th><th>Regimes</th>"
        "<th>Sharpe</th><th>Hit rate</th><th>OOS t</th><th>Statistic scope</th><th>Evidence</th></tr>"
    )
    body = []
    for r in rows:
        body.append(
            "<tr>"
            f"<td class='num'>{_esc(r['trial_id'])}</td>"
            f"<td><span class='pill'>{_esc(r['strategy'])}</span></td>"
            f"<td>{_esc(r['variant'])}</td>"
            f"<td class='num'>{_esc(r['trade_count'])}</td>"
            f"<td>{_esc(r.get('partition', 'Training / other'))}</td>"
            f"{money_cell(r['pnl_after_fees'])}"
            f"<td class='num'>{_esc(fmt_money(r['max_drawdown']))}</td>"
            f"<td class='num'>{_esc(fmt_luck(r['luck_p_value']))}</td>"
            f"<td>{_esc(r['regimes'])}</td>"
            f"{_statistics_cells(r)}"
            f"<td class='evidence'>{_esc(r.get('evidence', 'Review gates'))}</td>"
            "</tr>"
        )
    return f"<div class='table-wrap'><table>{head}{''.join(body)}</table></div>"


def render_dashboard(snapshot: dict) -> str:
    """Render a full snapshot dict (from ``reports.dashboard_snapshot``) to HTML."""
    mode = snapshot["mode"]
    generated = fmt_ts(snapshot["generated_at"])
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="{REFRESH_SECONDS}">
<title>tradingbot dashboard</title>
<style>{_CSS}</style>
</head><body>
<h1>tradingbot dashboard</h1>
<div class="meta">read-only · mode: <b>{_esc(mode)}</b> · generated {_esc(generated)} · auto-refresh {REFRESH_SECONDS}s</div>

<h2>Risk / kill-switch</h2>
{_halts_section(snapshot["active_halts"])}
{_kill_switch_section(snapshot.get("kill_switches", []))}

<h2>Leaderboard — {_esc(mode)} (P&amp;L after fees, trade count, luck odds)</h2>
<p class="meta">{_esc(NOTICE)}</p>
<p class="meta">All-time realized ledger scope; hit rate uses completed execution round trips after fees.
Drawdown includes open-entry fees but excludes unrealized marks. Backtest strategy totals may include
separate experiments; assess individual trial rows below. Open “Basis &amp; samples” for definitions.</p>
{_leaderboard_table(snapshot["leaderboard"])}

<h2>Backtest vs live</h2>
{_gap_table(snapshot["backtest_vs_live"])}

<h2>Backtest trials (P&amp;L, drawdown, regime)</h2>
{_backtest_trials_table(snapshot.get("backtest_trials", []))}

<h2>Recorded final holdouts</h2>
<p class="meta">Every recorded final, including failures. Statistics do not clear a failed audit or
turn previously inspected outcomes into untouched confirmation.</p>
{_backtest_trials_table(snapshot.get("final_holdouts", []))}

<h2>Pipeline</h2>
{_pipeline_section(snapshot["pipeline"])}

<h2>Incidents</h2>
{_incidents_table(snapshot["incidents"])}

<footer>tradingbot · localhost read-only dashboard · PRD §7. Luck p tests a zero-mean null; it is not the probability a strategy is luck.</footer>
</body></html>"""
