#!/usr/bin/env python3
"""Read-only weekly ledger review; encrypt, verify, optionally publish to Pages.

Run from the repository: uv run python ops/weekly_report.py [--deploy].
Plaintext exists only inside a mode-0700 temporary directory, never the bundle.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import fcntl
import hashlib
from html import escape
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import tempfile
import time
from zoneinfo import ZoneInfo

from dotenv import dotenv_values, set_key
import httpx
from sqlalchemy import func, or_, select, text

from tradingbot.ai.jev import MONTHLY_CAP_USD
from tradingbot.db.models import Fill, Incident, Instrument, JevRequest, RiskHalt, Strategy, Trial
from tradingbot.db.session import SessionLocal
from tradingbot.ledger.accounting import FillEvent, iter_round_trips
from tradingbot.ledger.stats import luck_probability
from tradingbot.ledger.report_stats import (
    NOTICE, evidence_status, execution_statistics, load_trial_statistics, scope_text,
)

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "ops/weekly"
PROJECT = "tradingbot-weekly"
URL = f"https://{PROJECT}.pages.dev"
LOCAL = ZoneInfo("America/Los_Angeles")
ZERO = Decimal("0")
JEV_CODE_VERSION = "jev_intraday_v1"  # Trial.code_version / metrics key for Jev intraday arms
BUNDLE_FILES = {"index.html", "_headers", "robots.txt"}
HEADERS = """/*
  Cache-Control: no-store
  X-Robots-Tag: noindex, nofollow, noarchive
  X-Content-Type-Options: nosniff
  Referrer-Policy: no-referrer
  Content-Security-Policy: default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; connect-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'
"""


class StatisticScope:
    __slots__ = ("text",)

    def __init__(self, text):
        self.text = text


def within(value, start, end):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value is not None and start <= value < end


def ledger_rows(fills, strategies, start, end, multipliers):
    """Only paper/live; never combine independent backtest variants into returns."""
    grouped = defaultdict(list)
    for fill in fills:
        if fill.mode in ("paper", "live") and fill.fill_ts < end:
            grouped[(fill.strategy_id, fill.mode)].append(fill)
    rows = []
    for (strategy_id, mode), executions in grouped.items():
        by_instrument = defaultdict(list)
        for fill in executions:
            by_instrument[fill.instrument_id].append(fill)
        trips = []
        for instrument_id, values in by_instrument.items():
            events = [FillEvent(side=f.side, price=f.price, size=f.size, fee=f.fee or ZERO,
                                fill_ts=f.fill_ts) for f in sorted(values, key=lambda f: (f.fill_ts, f.id))]
            trips.extend(iter_round_trips(events, multipliers[instrument_id]))
        weekly_trips = [t for t in trips if within(t.exit_ts, start, end)]
        weekly_fills = [f for f in executions if within(f.fill_ts, start, end)]
        net = lambda values: sum(((f.realized_pnl or ZERO) - (f.fee or ZERO) for f in values), ZERO)
        strategy = strategies.get(strategy_id)
        rows.append({"strategy": strategy.name if strategy else "Unattributed",
                     "mode": mode, "weekly_pnl": net(weekly_fills),
                     "pnl": net(executions), "trades": len(weekly_trips),
                     "fills": len(weekly_fills),
                     "luck": luck_probability([t.net_pnl for t in weekly_trips]),
                     "statistics": execution_statistics(weekly_fills, weekly_trips)})
    return sorted(rows, key=lambda r: (r["mode"], -r["weekly_pnl"]))


def read_beads(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def intake_rows(path):
    """The curated intake log is the source; don't execute Markdown or links."""
    log = path.read_text().split("## Log", 1)[1]
    rows = []
    for line in log.splitlines():
        cells = [x.strip() for x in line.strip().strip("|").split("|")]
        if len(cells) == 4 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", cells[0]):
            link = re.search(r"\[[^]]+\]\(([^)]+)\)", cells[1])
            if link:
                evaluation = (path.parent / link.group(1)).resolve()
                if evaluation.is_relative_to(path.parent.resolve()) and evaluation.is_file():
                    verdict = re.search(r"^## Verdict:\s*(.+)$", evaluation.read_text(), re.MULTILINE)
                    if verdict:
                        # The evaluation can supersede a stale index-table verdict.
                        cells[2] = verdict.group(1).replace('**', '')
            rows.append([re.sub(r"\[([^]]+)\]\([^)]+\)", r"\1", c) for c in cells])
    return rows


def snapshot(session, start, end, beads, intake):
    strategies = {s.id: s for s in session.scalars(select(Strategy).order_by(Strategy.id))}
    trials = session.scalars(select(Trial).where(Trial.created_ts < end).order_by(Trial.id.desc())).all()
    new_trials = [t for t in trials if within(t.created_ts, start, end)]
    changed_trials = [t for t in trials if within(t.completed_ts, start, end) and t not in new_trials]
    incidents = session.scalars(select(Incident).where(
        Incident.ts < end, or_(Incident.ts >= start, Incident.resolved_ts.is_(None))
    ).order_by(Incident.ts.desc())).all()
    halts = session.scalars(select(RiskHalt).where(or_(
        RiskHalt.active.is_(True), RiskHalt.triggered_ts >= start
    ), RiskHalt.triggered_ts < end).order_by(RiskHalt.triggered_ts.desc())).all()
    fills = session.scalars(select(Fill).where(Fill.mode.in_(("paper", "live")), Fill.fill_ts < end)).all()
    multipliers = dict(session.execute(select(Instrument.id, Instrument.contract_multiplier).where(
        Instrument.id.in_({f.instrument_id for f in fills}))).all())
    selected_trials = {t.id: t for t in [*new_trials, *changed_trials, *[t for t in trials if t.final_holdout]]}
    statistics = load_trial_statistics(session, selected_trials.values())

    def trial_row(t):
        s = strategies[t.strategy_id]
        stats = statistics[t.id]
        return [t.id, s.name, t.mode, t.status,
                "Final holdout" if t.final_holdout else "Training / other",
                money(t.pnl_after_fees), money(t.max_drawdown), ratio(stats['sharpe']),
                percent(stats['hit_rate']), ratio(stats['oos_t_stat']),
                t.trade_count, probability(t.luck_p_value), evidence_status(t, s), StatisticScope(scope_text(stats))]

    # Preserve heterogeneous runner units rather than guessing that every number
    # is dollars (some older studies store period returns).
    regimes = []
    for t in trials:
        if t not in new_trials and t not in changed_trials and not t.final_holdout:
            continue
        for field in ('by_regime', 'entry_trend_regimes', 'by_year', 'year_by_exit'):
            values = (t.metrics or {}).get(field)
            if isinstance(values, dict):
                for label, metrics in values.items():
                    regimes.append([t.id, field, label, json.dumps(metrics, sort_keys=True)])

    ready = [b for b in beads if b.get("status") in ("open", "in_progress") and
             set(b.get("labels", [])) & {"ready-for-live", "ready:live"}]
    promotions = [b for b in beads if b.get("status") == "closed" and
                  "promotion" in b.get("labels", []) and within(b.get("closed_at"), start, end)]
    pipeline = sorted((b for b in beads if b.get("status") in ("open", "in_progress", "blocked")),
                      key=lambda b: (b.get("priority", 9), b["id"]))

    # --- Jev arms vs controls (information only) ------------------------
    jev_trials = session.scalars(select(Trial).where(Trial.code_version == JEV_CODE_VERSION)).all()
    jev_by_id = {t.id: t for t in jev_trials}
    real_arms = [t for t in jev_trials
                 if not (t.metrics or {}).get(JEV_CODE_VERSION, {}).get("virtual")
                 and (t.metrics or {}).get(JEV_CODE_VERSION, {}).get("arm") in ("J1", "J2", "J3", "J4")]
    jev_arms = []
    for t in sorted(real_arms, key=lambda x: (x.metrics[JEV_CODE_VERSION]["arm"], x.id)):
        meta = t.metrics[JEV_CODE_VERSION]
        jev_arms.append(jev_arm_row(t, meta["arm"], "real", True, strategies))
        for kind in ("random", "ungated"):
            tid = (meta.get("twins") or {}).get(kind)
            twin = jev_by_id.get(tid) or (session.get(Trial, tid) if tid else None)
            if twin is not None:
                jev_arms.append(jev_arm_row(twin, meta["arm"], kind + " twin", False, strategies))

    month = end.date().replace(day=1)
    settled = Decimal(str(session.scalar(select(func.coalesce(func.sum(JevRequest.actual_usd), 0)).where(
        JevRequest.billing_month <= month, JevRequest.completed_month >= month)) or 0))
    outstanding = Decimal(str(session.scalar(select(func.coalesce(func.sum(JevRequest.reserved_usd), 0))) or 0))
    mtd = settled + outstanding
    jev_spend = [[month.isoformat(), money(settled), money(outstanding), money(mtd),
                  money(MONTHLY_CAP_USD), money(MONTHLY_CAP_USD - mtd)]]

    latencies = sorted(v for (v,) in session.execute(select(JevRequest.latency_ms).where(
        JevRequest.latency_ms.is_not(None), JevRequest.completed_ts >= start, JevRequest.completed_ts < end,
        JevRequest.correlation_id.startswith("paper-trial:"))).all())
    jev_latency = [[len(latencies), jev_quantile(latencies, 0.5), jev_quantile(latencies, 0.95)]]
    daily_ai, daily_calibration = daily_ai_rows(trials)
    return {
        "start": start, "end": end, "leaderboard": ledger_rows(fills, strategies, start, end, multipliers),
        "new_trials": [trial_row(t) for t in new_trials],
        "changed_trials": [trial_row(t) for t in changed_trials],
        "holdouts": [trial_row(t) for t in trials if t.final_holdout],
        "regimes": regimes,
        "trial_counts": Counter(t.status for t in new_trials),
        "strategies": Counter(s.status for s in strategies.values()),
        "promotions": [[b["id"], b["title"], b.get("closed_at")] for b in promotions],
        "current_promoted": [[s.name, s.status, money(s.allocation_usd)] for s in strategies.values()
                             if s.status in ("paper", "live")],
        "ready": [[b["id"], b["title"], b.get("assignee") or "Unassigned"] for b in ready],
        "incidents": [[i.id, stamp(i.ts), i.severity, i.mode or "All", i.message,
                       "Resolved" if i.resolved_ts else "Open"] for i in incidents],
        "halts": [[h.scope, h.mode or "All", h.reason, "Active" if h.active else "Cleared"] for h in halts],
        "kills": [[s.name, s.status] for s in strategies.values() if s.status == "killed"],
        "pipeline": [[b["id"], "P" + str(b.get("priority", "?")), b["title"],
                      b.get("status"), b.get("assignee") or "Unassigned",
                      ", ".join(b.get("labels", []))] for b in pipeline],
        "intake": intake,
        "jev_arms": jev_arms, "jev_spend": jev_spend, "jev_latency": jev_latency,
        "daily_ai": daily_ai, "daily_calibration": daily_calibration,
    }


def money(value):
    return "—" if value is None else f"${value:,.2f}"


def probability(value):
    return "—" if value is None else f"{value:.4f}"


def ratio(value):
    return "—" if value is None else f"{value:.2f}"


def percent(value):
    return "—" if value is None else f"{value:.1%}"


def stamp(value):
    return value.astimezone(LOCAL).strftime("%b %d, %Y %H:%M %Z")


def jev_quantile(values, q):
    """Nearest-rank quantile of a sorted list, or an em dash when empty."""
    if not values:
        return "—"
    scaled = q * len(values)
    rank = int(scaled) + (1 if scaled > int(scaled) else 0)  # ceil without importing math
    return values[min(max(rank, 1), len(values)) - 1]


def jev_arm_row(trial, arm, variant, is_real, strategies):
    """One Jev arm/twin row: P&L after costs and trades are cumulative snapshots."""
    meta = (trial.metrics or {}).get(JEV_CODE_VERSION, {})
    strategy = strategies.get(trial.strategy_id)
    cost = meta.get("model_cost_usd")
    return [arm, variant, trial.id, strategy.name if strategy else "—",
            money(trial.pnl_after_fees),
            trial.trade_count if trial.trade_count is not None else "—",
            money(Decimal(str(cost)) if cost is not None else None),
            ("Yes" if meta.get("ready_for_live") else "No") if is_real else "—"]


def daily_ai_rows(trials):
    performance, calibration = [], []
    for trial in sorted(trials, key=lambda t: t.id):
        experiment = {"ai1_daily_gate_v1": "AI-1", "ai2_daily_basket_v2": "AI-2"}.get(trial.code_version)
        if experiment is None:
            continue
        meta = (trial.metrics or {}).get(JEV_CODE_VERSION, {})
        kind, virtual = meta.get("kind", "unknown"), meta.get("virtual", False)
        performance.append([experiment, kind, trial.id, "Virtual" if virtual else "Alpaca paper",
            money(trial.pnl_after_fees), trial.trade_count, money(trial.max_drawdown),
            probability(trial.luck_p_value), "Control" if kind in ("random", "ungated", "benchmark")
            else "Ready" if meta.get("ready_for_live") else "Pending"])
        if kind not in ("jev", "claude"):
            continue
        cal = meta.get("calibration", {})
        sensitivity = meta.get("net_less_claude_list_price_estimate") if kind == "claude" else None
        if experiment == "AI-2" and kind == "claude":
            sensitivity = (meta.get("net_after_known_claude_estimated_cost")
                           if meta.get("claude_unknown_cost_estimates") == 0 else None)
        calibration.append([experiment + " " + kind, cal.get("count", 0), cal.get("brier"),
            cal.get("always_yes_brier"), meta.get("unlabeled_predictions"),
            meta.get("base_signals_last_five_sessions"),
            money(Decimal(sensitivity)) if sensitivity is not None else "—",
            ", ".join(meta.get("current_gate", {}).get("reasons", [])) or "Pending observations"])
    return performance, calibration


def table(headers, rows, empty="None recorded."):
    if not rows:
        return f'<p class="empty">{escape(empty)}</p>'
    def cell(v):
        if isinstance(v, StatisticScope):
            return ('<details class="statistics-scope"><summary>Basis &amp; samples</summary><p>'
                    + escape(v.text) + '</p></details>')
        return escape("—" if v is None else str(v))
    return ('<div class="table-wrap"><table><thead><tr>' +
            "".join(f'<th scope="col">{cell(h)}</th>' for h in headers) +
            '</tr></thead><tbody>' + "".join('<tr>' + "".join(f'<td>{cell(v)}</td>' for v in row) +
                                           '</tr>' for row in rows) + '</tbody></table></div>')


def render(data):
    """Single, self-contained, escaped document; no remote assets or data APIs."""
    parts = ['<!doctype html><html lang="en"><head><meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width, initial-scale=1">',
             '<meta name="robots" content="noindex,nofollow"><title>Trading review</title>',
             '<style>' + (PACKAGE / 'report.css').read_text() + '</style></head><body>',
             '<main id="private-weekly-report"><header><p class="eyebrow">TRADINGBOT / WEEKLY REVIEW</p>',
             f'<h1>{escape(data["end"].astimezone(LOCAL).strftime("%B %d, %Y"))}</h1>',
             f'<p>{escape(stamp(data["start"]))} → {escape(stamp(data["end"]))} (end exclusive)</p></header>']
    parts.append('<div class="summary">' + ''.join(
        f'<div><strong>{value}</strong><span>{label}</span></div>' for label, value in [
            ('New trials', len(data['new_trials'])), ('Final holdouts on record', len(data['holdouts'])),
            ('Open incidents', sum(r[-1] == 'Open' for r in data['incidents'])),
            ('Live strategies', data['strategies'].get('live', 0))]) + '</div>')

    def section(title, headers, rows, note='', empty="None recorded."):
        parts.append('<section><h2>' + escape(title) + '</h2>')
        if note:
            parts.append('<p class="note">' + escape(note) + '</p>')
        parts.append(table(headers, rows, empty) + '</section>')

    board = data['leaderboard']
    parts.append('<p class="note">' + escape(NOTICE) + '</p>')
    for mode in ('live', 'paper'):
        section(mode.title() + ' leaderboard',
                ['Strategy', 'This week: net P&L', 'All-time: net P&L', 'Round trips', 'Executions', 'Luck p',
                 'Realized drawdown', 'Sharpe', 'Hit rate', 'OOS t', 'Statistic scope'],
                [[r['strategy'], money(r['weekly_pnl']), money(r['pnl']), r['trades'], r['fills'],
                  probability(r['luck']), money(r['statistics']['max_drawdown']), ratio(r['statistics']['sharpe']),
                  percent(r['statistics']['hit_rate']), ratio(r['statistics']['oos_t_stat']),
                  StatisticScope(scope_text(r['statistics']))] for r in board if r['mode'] == mode],
                'USD, realized P&L less all execution fees; open-position value is excluded. Counts and luck p cover this week. '
                'Drawdown and hit rate also cover this week; a trade closing this week includes its full entry/exit fees. '
                'Sharpe needs a marked-return series, and OOS t belongs to recorded final trials below. '
                'Luck p is a one-sample test against zero mean, not the probability a strategy is luck.',
                f'No {mode} fills recorded. There is no {mode} performance to report.')
    th = ['Trial', 'Strategy', 'Mode', 'Status', 'Partition', 'Net P&L', 'Max drawdown', 'Sharpe', 'Hit rate',
          'OOS t', 'Trades', 'Luck p', 'Evidence', 'Statistic scope']
    section('New trials', th, data['new_trials'],
            'Every variant, including failures. Results belong to separate experiments and must not be added together. '
            'Trade counts use each runner’s recorded definition; an em dash means unmeasured.')
    section('Previously started trials completed this week', th, data['changed_trials'])
    section('Final holdout results', th, data['holdouts'],
            'All recorded final holdouts, with current audit status. Positive P&L alone does not establish readiness.')
    section('Regime and period breakdowns', ['Trial', 'Breakdown', 'Period / regime', 'Recorded metrics'],
            data['regimes'], 'Available breakdowns for the trials above. Field names and units are preserved from each runner; '
            'C01 scalar regime/year values are net returns. Missing breakdowns remain unmeasured. Failed audits still apply.')
    section('Promotions this week', ['Bead', 'Decision', 'Recorded at'], data['promotions'],
            'Completed beads explicitly labelled promotion. The database has no strategy transition history.')
    section('Current paper and live strategies', ['Strategy', 'Stage', 'Allocation'], data['current_promoted'])
    section('Ready-for-live queue', ['Bead', 'Decision to review', 'Owner'], data['ready'],
            'Explicit ready-for-live or ready:live labels only; no readiness is inferred from returns.')
    section('Jev arms vs controls (information only)',
            ['Arm', 'Variant', 'Trial', 'Strategy', 'Net after costs', 'Trades', 'Model cost', 'Ready for live'],
            data['jev_arms'],
            'Each J1–J4 arm beside its random twin (and the J1 ungated twin). Net after costs and trade counts are '
            'current cumulative paper snapshots, not weekly, and the twins are decision controls that are never funded. '
            'Readiness is the arm’s recorded gate, not an approval.')
    section('Jev month-to-date spend', ['UTC month', 'Settled', 'Outstanding', 'Total', 'Cap', 'Remaining'],
            data['jev_spend'],
            'Global TypeSafe/Jev provider budget across all callers; the cap is a hard UTC calendar-month limit, '
            'separate from this review’s seven-day window.')
    section('Jev decision latency this week', ['Settled calls', 'Median ms', 'p95 ms'], data['jev_latency'],
            'Jev-intraday paper decision calls settled within this review window.')
    section('Daily AI paper comparisons',
            ['Experiment', 'Arm', 'Trial', 'Execution', 'Net after costs', 'Trades', 'Drawdown', 'Luck p', 'Readiness'],
            data.get('daily_ai', []),
            'Current cumulative snapshots. Real and simulated controls have different fill mechanisms. '
            'Readiness is recorded evidence, not live approval; controls never qualify.')
    section('Daily gate calibration',
            ['Arm', 'Labels', 'Brier', 'Always yes', 'Unlabeled', 'Base signals / 5 sessions', 'Net less Claude estimate', 'Gate reasons'],
            data.get('daily_calibration', []),
            'AI-1 labels use completed real ungated trades, including forecasts rejected by each gate. '
            'AI-2 labels use its virtual equal-weight benchmark; its Brier scores are diagnostic, not a pass gate. '
            'Claude primary P&L assumes included subscription usage; its list-price sensitivity is separate. '
            'Missing estimates and outcomes remain unknown.')
    section('Kills', ['Strategy', 'Status'], data['kills'])
    section('Risk halts', ['Scope', 'Mode', 'Reason', 'State'], data['halts'],
            'Active halts plus those triggered during this review window.')
    section('Incidents', ['ID', 'Time', 'Severity', 'Mode', 'Incident', 'State'], data['incidents'],
            'This week’s incidents plus older unresolved incidents.')
    section('Research and delivery pipeline', ['Bead', 'Priority', 'Work', 'State', 'Owner', 'Labels'], data['pipeline'])
    section('Intake verdicts', ['Submitted', 'Submission', 'Current verdict', 'Follow-up'], data['intake'],
            'Complete intake log. Verdict headings in the linked evaluations supersede older index entries.')
    parts.append('<footer>Read-only snapshot of the local ledger, trials, incidents, beads and intake log. '
                 'Weekly publication: Friday 14:00 America/Los_Angeles, after the US close.</footer></main></body></html>')
    return ''.join(parts)


def child_env(**extra):
    # No venue keys, DB password, TLS-disable setting or unrelated secrets reach Node.
    env = {k: os.environ[k] for k in ('PATH', 'HOME', 'TMPDIR', 'SSL_CERT_FILE', 'NODE_EXTRA_CA_CERTS')
           if k in os.environ}
    return env | {"CI": "true", "WRANGLER_SEND_METRICS": "false"} | extra


def checked(command, *, env, cwd, timeout=180):
    result = subprocess.run(command, env=env, cwd=cwd, capture_output=True, text=True,
                            stdin=subprocess.DEVNULL, timeout=timeout)
    if result.returncode:
        # Subprocess output can include credentials, URLs or raw report data.
        raise RuntimeError(f"{Path(command[0]).name} failed (exit {result.returncode}); output withheld")
    return result.stdout


def validate_bundle(path, plaintext, password):
    if {p.name for p in path.iterdir()} != BUNDLE_FILES or any(p.is_symlink() or not p.is_file() for p in path.iterdir()):
        raise ValueError("Bundle must contain only encrypted index.html, _headers and robots.txt")
    html = (path / 'index.html').read_text()
    if 'type="password"' not in html or 'encryptedMsg' not in html:
        raise ValueError("StatiCrypt password prompt or ciphertext missing")
    if 'private-weekly-report' in html or plaintext in html or password in html:
        raise ValueError("Plaintext detected in encrypted report")


def encrypt(plaintext, password, output):
    if len(password) < 12:  # owner-chosen password; StaticCrypt uses PBKDF2
        raise ValueError("WEEKLY_PAGE_PASSWORD must have at least 12 characters")
    output.parent.mkdir(parents=True, exist_ok=True)
    cli = PACKAGE / 'node_modules/.bin/staticrypt'
    if not cli.is_file():
        raise RuntimeError("Install pinned report dependencies with npm ci --prefix ops/weekly")
    with tempfile.TemporaryDirectory(prefix='.weekly-', dir=output.parent) as temp:
        private = Path(temp)
        source = private / 'index.html'
        source.write_text(plaintext)
        target = private / 'encrypted'
        env = child_env(STATICRYPT_PASSWORD=password)
        salt = secrets.token_hex(16)  # Public salt shared by both CLI invocations.
        checked([str(cli), str(source), '--directory', str(target), '--config', 'false',
                 '--salt', salt,
                 '--remember', 'false', '--template-title', 'Trading review',
                 '--template-button', 'Unlock review', '--template-color-primary', '#1b4dff',
                 '--template-color-secondary', '#101827'], env=env, cwd=private)
        (target / '_headers').write_text(HEADERS)
        (target / 'robots.txt').write_text('User-agent: *\nDisallow: /\n')
        validate_bundle(target, plaintext, password)
        decrypted = private / 'decrypted'
        checked([str(cli), str(target / 'index.html'), '--decrypt', '--directory', str(decrypted),
                 '--config', 'false', '--salt', salt], env=env, cwd=private)
        if (decrypted / 'index.html').read_text() != plaintext:
            raise ValueError("Encryption round-trip verification failed")
        if output.exists() and ({p.name for p in output.iterdir()} != BUNDLE_FILES or output.is_symlink()):
            raise ValueError("Refusing to replace an unexpected output directory")
        output.mkdir(exist_ok=True)
        for name in sorted(BUNDLE_FILES):
            os.replace(target / name, output / name)
    validate_bundle(output, plaintext, password)
    return hashlib.sha256((output / 'index.html').read_bytes()).hexdigest()


def publish(output, values, project=PROJECT):
    url = f'https://{project}.pages.dev'
    account = values.get('CLOUDFLARE_ACCOUNT_ID')
    token = values.get('CLOUDFLARE_API_TOKEN')
    if not account or not token:
        raise ValueError("Missing Cloudflare credentials in .env")
    api = f'https://api.cloudflare.com/client/v4/accounts/{account}/pages/projects/{project}'
    auth = {'Authorization': f'Bearer {token}'}
    env = child_env(CLOUDFLARE_API_TOKEN=token, CLOUDFLARE_ACCOUNT_ID=account)
    cli = str(PACKAGE / 'node_modules/.bin/wrangler')
    with httpx.Client(timeout=30) as client:
        response = client.get(api, headers=auth)
        if response.status_code == 404:
            checked([cli, 'pages', 'project', 'create', project, '--production-branch', 'main'],
                    env=env, cwd=PACKAGE)
        elif response.status_code != 200 or not response.json().get('success'):
            raise RuntimeError(f"Cloudflare project lookup failed (HTTP {response.status_code})")
        elif response.json()['result'].get('production_branch') != 'main':
            raise ValueError("Unexpected production branch; no deployment attempted")
        checked([cli, 'pages', 'deploy', str(output), '--project-name', project, '--branch', 'main',
                 '--commit-dirty=true'], env=env, cwd=PACKAGE, timeout=300)
        expected = (output / 'index.html').read_bytes()
        for _ in range(12):
            response = client.get(api, headers=auth)
            deployment = response.json().get('result', {}).get('canonical_deployment') or {}
            state = deployment.get('latest_stage', {}).get('status')
            if state == 'success':
                # Pages appends a suffix when the project name is taken globally.
                subdomain = response.json()['result'].get('subdomain')
                if subdomain:
                    url = f'https://{subdomain}'
                page = client.get(url, headers={'Cache-Control': 'no-cache'})
                if page.status_code == 200 and page.content == expected:
                    return {'url': url, 'deployment_id': deployment['id'], 'verified': True}
            time.sleep(2)
    raise RuntimeError("Deployment did not verify against the encrypted local bundle")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--deploy', action='store_true')
    parser.add_argument('--init-password', action='store_true', help='Generate a local .env password only when empty')
    args = parser.parse_args()
    os.chdir(ROOT)
    os.umask(0o077)
    work = ROOT / 'data/weekly'
    work.mkdir(parents=True, exist_ok=True)
    with (work / '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        values = dotenv_values(ROOT / '.env')
        if args.init_password and not values.get('WEEKLY_PAGE_PASSWORD'):
            password = secrets.token_urlsafe(32)
            set_key(ROOT / '.env', 'WEEKLY_PAGE_PASSWORD', password)
            values['WEEKLY_PAGE_PASSWORD'] = password
        password = values.get('WEEKLY_PAGE_PASSWORD')
        if not password:
            raise ValueError('WEEKLY_PAGE_PASSWORD is empty; initialize it before publication')
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=7)
        with SessionLocal() as session:
            session.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'))
            session.execute(text("SET LOCAL statement_timeout = '60s'"))
            data = snapshot(session, start, end, read_beads(ROOT / '.beads/issues.jsonl'),
                            intake_rows(ROOT / 'docs/strategy-intake/README.md'))
        plaintext = render(data)
        output = work / 'site'
        digest = encrypt(plaintext, password, output)
        result = {'generated_at': end.isoformat(), 'sha256': digest, 'encrypted': True,
                  'new_trials': len(data['new_trials']), 'holdouts': len(data['holdouts'])}
        if args.deploy:
            result.update(publish(output, values))
        (work / 'last_run.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Never include database URLs, source data or subprocess output in launchd logs.
        print(f'Weekly report failed: {type(exc).__name__}. No unencrypted report was published.')
        raise SystemExit(1) from None
