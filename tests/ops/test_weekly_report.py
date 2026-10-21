"""Accounting boundaries and confidentiality of the weekly publication bundle."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
import importlib.util
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('weekly_report', ROOT / 'ops/weekly_report.py')
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)
START = datetime(2026, 9, 25, tzinfo=timezone.utc)
END = START + timedelta(days=7)


def fill(id, mode, ts, side, price, pnl, instrument=7):
    return NS(id=id, strategy_id=1, instrument_id=instrument, mode=mode, fill_ts=ts,
              side=side, price=D(price), size=D(1), fee=D('0.10'), realized_pnl=D(pnl))


def test_week_boundary_counts_full_cycle_but_only_weeks_cashflows():
    fills = [fill(1, 'live', START - timedelta(hours=1), 'buy', '10', '0'),
             fill(2, 'live', START, 'sell', '12', '200'),
             fill(3, 'backtest', START, 'sell', '10000', '10000'),
             fill(4, 'paper', START, 'buy', '10', '0'),
             fill(5, 'live', END, 'buy', '10', '0')]
    rows = report.ledger_rows(fills, {1: NS(name='Test')}, START, END, {7: D(100)})
    live, paper = rows
    assert live['weekly_pnl'] == D('199.90')
    assert live['pnl'] == D('199.80')
    assert live['trades'] == live['fills'] == 1
    assert paper['trades'] == 0 and paper['pnl'] == D('-0.10')
    assert live['statistics']['hit_rate'] == 1
    assert live['statistics']['max_drawdown'] == 0  # prior entry fee is outside this week's DD
    assert paper['statistics']['hit_rate'] is None
    assert paper['statistics']['max_drawdown'] == D('.1')
    assert live['statistics']['sharpe'] is live['statistics']['oos_t_stat'] is None
    assert all(r['mode'] != 'backtest' for r in rows)


def test_contract_multiplier_used_for_luck_p(monkeypatch):
    seen = []
    monkeypatch.setattr(report, 'luck_probability', lambda values: seen.extend(values))
    report.ledger_rows([fill(1, 'live', START, 'buy', '10', '0'),
                        fill(2, 'live', START + timedelta(hours=1), 'sell', '12', '200')],
                       {}, START, END, {7: D(100)})
    assert seen == [D('199.80')]


def test_audit_failure_overrides_complete_holdout():
    trial = NS(status='complete', final_holdout=True, metrics={})
    strategy = NS(config={'evidence_audit': {'status': 'FAILED_AUDIT', 'promotion_eligible': False}})
    assert report.evidence_status(trial, strategy) == 'FAILED AUDIT — not promotion evidence'
    assert report.evidence_status(NS(status='failed', metrics={'audit_result': 'DATA_FAIL'}),
                                  NS(config={})) == 'DATA_FAIL'


def test_untrusted_incident_or_bead_html_is_escaped():
    html = report.table(['Work'], [['<script>alert(1)</script>'], ['<img src=x onerror=alert(2)>']])
    assert '<script>' not in html and '<img' not in html
    assert '&lt;script&gt;' in html


def test_empty_activity_does_not_manufacture_profit():
    assert report.ledger_rows([], {}, START, END, {}) == []
    assert report.money(None) == '—'
    assert report.probability(None) == '—'


def test_weekly_statistics_render_uses_explicit_scope_and_preserves_escaping():
    board = report.ledger_rows([fill(1, 'paper', START, 'buy', '10', '0'),
        fill(2, 'paper', START+timedelta(hours=1), 'sell', '12', '2')], {1: NS(name='Test')}, START, END, {7: D(1)})
    board[0]['statistics']['sharpe_basis'] = '<script>scope</script>'
    data = {'start': START, 'end': END, 'leaderboard': board, 'strategies': {},
        **{k: [] for k in ('new_trials', 'changed_trials', 'holdouts', 'regimes', 'promotions',
                          'current_promoted', 'ready', 'incidents', 'halts', 'kills', 'pipeline', 'intake',
                          'jev_arms', 'jev_spend', 'jev_latency')}}
    html = report.render(data)
    assert 'Realized drawdown' in html and 'Hit rate' in html and 'OOS t' in html and 'Sharpe' in html
    assert '100.0%' in html and 'Statistic scope' in html and 'Informational only' in html
    assert '&lt;script&gt;scope' in html and '<script>scope' not in html


def test_jev_quantile_nearest_rank_and_empty():
    values = [10, 20, 30, 40, 100]
    assert report.jev_quantile(values, 0.5) == 30
    assert report.jev_quantile(values, 0.95) == 100
    assert report.jev_quantile([], 0.5) == '—'


def test_daily_ai_rows_preserve_controls_and_unknown_calibration_cost():
    trials = [NS(id=1, code_version='ai1_daily_gate_v1', pnl_after_fees=D('1'), trade_count=3,
                 max_drawdown=D('.2'), luck_p_value=None, metrics={'jev_intraday_v1': {
                    'kind': 'claude', 'virtual': False, 'ready_for_live': False,
                    'calibration': {'count': 4, 'brier': '.2', 'always_yes_brier': '.5'},
                    'unlabeled_predictions': 2, 'base_signals_last_five_sessions': 16,
                    'net_less_claude_list_price_estimate': None,
                    'current_gate': {'reasons': ['calibration_not_proven']}}}),
              NS(id=2, code_version='ai1_daily_gate_v1', pnl_after_fees=None, trade_count=0,
                 max_drawdown=None, luck_p_value=None, metrics={'jev_intraday_v1': {'kind': 'random', 'virtual': True}}),
              NS(id=3, code_version='jev_intraday_v1')]
    performance, calibration = report.daily_ai_rows(trials)
    assert len(performance) == 2 and len(calibration) == 1
    assert performance[1][3] == 'Virtual' and performance[1][-1] == 'Control'
    assert calibration[0][1:6] == [4, '.2', '.5', 2, 16]
    assert calibration[0][-2:] == ['—', 'calibration_not_proven']


def test_ai2_known_cost_sum_is_not_presented_as_complete_when_estimates_are_missing():
    trial = NS(id=1, code_version='ai2_daily_basket_v2', pnl_after_fees=D('1'), trade_count=3,
               max_drawdown=D('.2'), luck_p_value=None, metrics={'jev_intraday_v1': {
                   'kind': 'claude', 'virtual': False, 'claude_unknown_cost_estimates': 1,
                   'net_after_known_claude_estimated_cost': '.90', 'calibration': {'count': 3}}})
    performance, calibration = report.daily_ai_rows([trial])
    assert performance[0][0] == 'AI-2' and calibration[0][-2] == '—'
    trial.metrics['jev_intraday_v1']['claude_unknown_cost_estimates'] = 0
    assert report.daily_ai_rows([trial])[1][0][-2] == '$0.90'


def _jev_trial(arm, *, pnl, trades, cost, ready=False, virtual=False, twins=None):
    meta = {'arm': arm, 'model_cost_usd': cost, 'ready_for_live': ready, 'virtual': virtual}
    if twins is not None:
        meta['twins'] = twins
    return NS(id=5, strategy_id=1, trade_count=trades, pnl_after_fees=pnl,
              metrics={'jev_intraday_v1': meta})


def test_jev_arm_row_formats_real_and_twin():
    strategies = {1: NS(name='J1 live arm')}
    real = report.jev_arm_row(_jev_trial('J1', pnl=D('1.50'), trades=3, cost='0.0123', ready=True),
                              'J1', 'real', True, strategies)
    assert real == ['J1', 'real', 5, 'J1 live arm', '$1.50', 3, '$0.01', 'Yes']
    twin = report.jev_arm_row(_jev_trial('J1', pnl=None, trades=None, cost=None),
                              'J1', 'random twin', False, {})
    assert twin == ['J1', 'random twin', 5, '—', '—', '—', '—', '—']


def test_jev_sections_render_and_escape():
    data = {'start': START, 'end': END, 'leaderboard': [], 'strategies': {},
            'jev_arms': [['J1', 'real', 5, '<script>x</script>', '$1.50', 3, '$0.01', 'Yes']],
            'jev_spend': [['2026-09-01', '$0.12', '$0.00', '$0.12', '$20.00', '$19.88']],
            'jev_latency': [[7, 120, 540]],
            **{k: [] for k in ('new_trials', 'changed_trials', 'holdouts', 'regimes', 'promotions',
                              'current_promoted', 'ready', 'incidents', 'halts', 'kills', 'pipeline', 'intake')}}
    html = report.render(data)
    assert 'Jev arms vs controls' in html and 'Jev month-to-date spend' in html
    assert 'Jev decision latency this week' in html
    assert '$19.88' in html and '540' in html and 'Ready for live' in html
    assert '&lt;script&gt;x' in html and '<script>x' not in html


def test_intake_uses_current_evaluation_verdict(tmp_path):
    index = tmp_path / 'README.md'
    index.write_text('## Log\n| 2026-09-30 | [Idea](idea.md) | Park | example-bead |\n')
    (tmp_path / 'idea.md').write_text('## Verdict: **REJECT** (failed, 2026-10-01)\n')
    rows = report.intake_rows(index)
    assert rows[0][2] == 'REJECT (failed, 2026-10-01)'


def test_encrypt_roundtrip_no_plaintext_or_password_in_bundle(tmp_path):
    if not (report.PACKAGE / 'node_modules/.bin/staticrypt').exists():
        pytest.skip('npm ci --prefix ops/weekly required for encryption integration test')
    plaintext = '<!doctype html><main id="private-weekly-report">PRIVATE_TRIAL_CANARY_913</main>'
    password = 'test-only-long-random-password-4901853'
    target = tmp_path / 'site'
    digest = report.encrypt(plaintext, password, target)
    assert len(digest) == 64
    assert {p.name for p in target.iterdir()} == report.BUNDLE_FILES
    assert not list(tmp_path.glob('.weekly-*'))
    for path in target.iterdir():
        assert 'PRIVATE_TRIAL_CANARY_913' not in path.read_text()
        assert password not in path.read_text()
    # A second build is safe and uses a fresh salt/ciphertext.
    assert report.encrypt(plaintext, password, target) != digest
    (target / 'raw.json').write_text('private')
    with pytest.raises(ValueError, match='only encrypted'):
        report.validate_bundle(target, plaintext, password)


def test_short_or_missing_password_refuses_encryption(tmp_path):
    with pytest.raises(ValueError, match='at least 12'):
        report.encrypt('private', '', tmp_path / 'site')
    assert not (tmp_path / 'site').exists()


def test_child_process_receives_only_required_secrets(monkeypatch):
    monkeypatch.setenv('ALPACA_LIVE_SECRET', 'do-not-forward')
    monkeypatch.setenv('NODE_TLS_REJECT_UNAUTHORIZED', '0')
    env = report.child_env(STATICRYPT_PASSWORD='test')
    assert 'ALPACA_LIVE_SECRET' not in env
    assert 'NODE_TLS_REJECT_UNAUTHORIZED' not in env
    assert env['STATICRYPT_PASSWORD'] == 'test'
