"""Source integrity only; no candidate return or holdout execution."""
import json
from copy import deepcopy
from uuid import uuid4

import pytest
import requests

from tradingbot.forward.c05_readiness import ProbeBudget, ProbeHalted
from tradingbot.research import c03_repair_capture as c
from tradingbot.research import c03_repair_audit as a


def test_existing_archive_rejects_changed_bytes_and_url(tmp_path):
    folder = tmp_path / 'dividend-com'
    folder.mkdir()
    raw = b'original source'
    meta = {'url': c.SOURCES['dividend-com'], 'bytes': len(raw), 'sha256': c.sha(raw)}
    (folder / 'raw').write_bytes(raw)
    (folder / 'manifest.json').write_text(json.dumps(meta))
    assert c.capture('dividend-com', budget=None, archive=tmp_path)[1] == raw
    (folder / 'raw').write_bytes(raw + b'changed')
    with pytest.raises(ValueError, match='bytes'):
        c.load('dividend-com', tmp_path)
    (folder / 'raw').write_bytes(raw)
    meta['url'] = 'https://example.org/other'
    (folder / 'manifest.json').write_text(json.dumps(meta))
    with pytest.raises(ValueError, match='identity'):
        c.load('dividend-com', tmp_path)


def test_unregistered_key_refuses_before_fetch(tmp_path):
    with pytest.raises(KeyError):
        c.capture('../outside', budget=None, archive=tmp_path)


def test_network_failures_are_archived_once_and_error_budget_halts(tmp_path, monkeypatch):
    calls = []
    def fail(*args, **kwargs):
        calls.append(args)
        raise requests.ConnectionError('synthetic failure')
    monkeypatch.setattr(c.requests, 'get', fail)
    budget = ProbeBudget(clock=lambda: 1)
    for key in list(c.SOURCES)[:5]:
        meta, raw = c.capture(key, budget=budget, archive=tmp_path)
        assert raw == b'' and meta['status'] is None
    assert len(calls) == 5 and budget.halted
    c.capture('dividend-com', budget=budget, archive=tmp_path)
    assert len(calls) == 5
    with pytest.raises(ProbeHalted):
        c.capture('dividend-com', budget=budget, archive=tmp_path / 'another')


def test_oversize_body_is_not_persisted(tmp_path, monkeypatch):
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def iter_content(self, size): yield b'123456'
    monkeypatch.setattr(c.requests, 'get', lambda *a, **k: Response())
    with pytest.raises(ValueError, match='size limit'):
        c.capture('dividend-com', budget=ProbeBudget(), archive=tmp_path, limit=5)
    assert not (tmp_path / 'dividend-com').exists()


def html_table(headers, rows):
    return ('<table><thead>' + ''.join('<th>' + h + '</th>' for h in headers) + '</thead><tbody>'
            + ''.join('<tr>' + ''.join('<td>' + c + '</td>' for c in row) + '</tr>' for row in rows)
            + '</tbody></table>')


def test_components_remain_separate_and_cannot_imply_a_pay_date():
    raw = html_table(['Date', 'Amount', 'Type'], [
        ['Dec 22, 2006', '$1.133', 'OrdinaryDividend'],
        ['Dec 22, 2006', '$0.361', 'CapitalGainLongTerm']])
    rows = a.components(raw)
    assert rows == {'2006-12-22': [{'kind': 'OrdinaryDividend', 'amount': '1.133'},
                                 {'kind': 'CapitalGainLongTerm', 'amount': '0.361'}]}
    assert all('pay_date' not in row for row in rows['2006-12-22'])
    with pytest.raises(ValueError, match='ambiguous'):
        a.components(raw + raw)
    with pytest.raises(ValueError, match='duplicate'):
        a.components(raw.replace('CapitalGainLongTerm', 'OrdinaryDividend'))
    with pytest.raises(ValueError, match='cash amount'):
        a.components(raw.replace('$0.361', '$NaN'))


def test_conflicting_june_date_is_preserved_not_shifted_to_existing_vendor_date():
    raw = html_table(['Ex-Dividend Date', 'Period', 'Dividend', 'Change',
                      'Declaration Date', 'Record Date', 'Payout Date'], [
        ['06/25/2009', 'Quarterly', '$0.48500', '', '', '06/26/2009', '06/30/2009']]).replace('<table>', '<table class="table table-bordered">')
    assert a.full_cash(raw) == {'2009-06-25': {'amount': '0.48500', 'record_date': '2009-06-26',
        'pay_date': '2009-06-30', 'declared_as_reported': None}}
    with pytest.raises(ValueError, match='invalid'):
        a.full_cash(raw.replace('06/30/2009', '06/23/2009'))


def test_full_cash_chronology_includes_observed_headerless_continuation():
    headers = ['Ex-Dividend Date', 'Period', 'Dividend', 'Change',
               'Declaration Date', 'Record Date', 'Payout Date']
    first = html_table(headers, [['06/25/2009', 'Quarterly', '$0.48500', '', '', '06/26/2009', '06/30/2009']])
    second = html_table([], [['12/22/2006', 'Quarterly', '$1.49400', '', '', '12/27/2006', '12/29/2006']])
    raw = (first + second).replace('<table>', '<table class="table table-bordered">')
    assert set(a.full_cash(raw)) == {'2009-06-25', '2006-12-22'}
    with pytest.raises(ValueError, match='unordered'):
        a.full_cash(raw + second.replace('<table>', '<table class="table table-bordered">'))


def test_payment_label_is_never_silently_reinterpreted_as_ex_date():
    raw = html_table(['tipo', 'data com', 'pagamento', 'valor'], [
        ['Dividendos', '26/06/2009', '30/06/2009', '0,48500000']])
    assert a.labeled_payments(raw) == [{'data_com_as_labeled': '2009-06-26',
        'pay_date': '2009-06-30', 'amount': '0.48500000'}]


def test_rounded_source_missing_date_stays_missing():
    raw = html_table(['Name', 'Ex-Dividend Date', 'Dividend', 'Payment Date',
                     'Record Date', 'Declaration Date', 'Frequency'], [
        ['VNQ Paid Vanguard Real Estate ETF 30 Jun 2009', '25 Jun 2009', '$0.48',
         '30 Jun 2009', '-', '-', 'Quarterly']])
    assert a.marketlog(raw)['2009-06-25']['record_date'] is None


def test_corroboration_refuses_incomplete_components_or_unknown_payment():
    vendor = {ex: '1.5' for ex in a.TARGETS}
    ordinary = {ex: {'amount': '1', 'pay_date': ex} for ex in a.TARGETS}
    parts = {ex: [{'kind': 'OrdinaryDividend', 'amount': '1'},
                  {'kind': 'CapitalGainLongTerm', 'amount': '.5'}] for ex in a.TARGETS}
    totals = {ex: {'amount': '1.5', 'pay_date': ex, 'record_date': ex} for ex in a.TARGETS}
    rounded = {ex: {'rounded_amount': '1.50', 'pay_date': ex, 'record_date': ex} for ex in a.TARGETS}
    payments = [{'amount': '1.5', 'pay_date': ex, 'data_com_as_labeled': ex} for ex in a.TARGETS]
    assert all(r['secondary_corroboration'] for r in a.reconcile_2006(vendor, ordinary, parts, totals, rounded, payments))
    parts[a.TARGETS[-1]].pop()
    result = a.reconcile_2006(vendor, ordinary, parts, totals, rounded, payments)
    assert not result[-1]['secondary_corroboration']
    assert not result[-1]['checks']['components_equal_full_total']
    parts[a.TARGETS[-1]].append({'kind': 'CapitalGainLongTerm', 'amount': '.5'})
    result = a.reconcile_2006(vendor, ordinary, parts, totals, rounded, payments[:-1])
    assert not result[-1]['secondary_corroboration']
    assert not result[-1]['checks']['independent_page_full_total_and_payment_match']


def failed_fixture():
    from tradingbot.backtest.holdout import HoldoutSplit
    identity = {'synthetic': str(uuid4())}
    split = HoldoutSplit('c03-source-test:' + identity['synthetic'], a.START, a.END)
    return {'status': 'DATA_FAIL', 'failed_prerequisites': ['synthetic date conflict'],
        'identity': identity, 'code_sha256': {'synthetic': 'a' * 64}, 'split': split.metadata(),
        'dataset_admitted': False, 'strategy_outcomes_inspected': False,
        'planned_configurations': a.configurations(), 'training_cases_attempted': 0,
        'final_holdout_attempts': 0, 'pnl': None, 'fees': None, 'trade_count': None,
        'drawdown': None, 'regimes': None, 'luck_p_value': None}


@pytest.mark.parametrize('field,value', [('status', 'PASS'), ('failed_prerequisites', []),
    ('dataset_admitted', True), ('strategy_outcomes_inspected', True), ('pnl', 0),
    ('trade_count', 0), ('training_cases_attempted', 1), ('final_holdout_attempts', 1),
    ('planned_configurations', [])])
def test_source_failure_never_conceals_performance_or_changed_cases(field, value):
    result = failed_fixture()
    result[field] = value
    with pytest.raises(ValueError, match='without performance'):
        a.record_failure(None, result, 'synthetic')


def test_source_failure_cannot_move_locked_cutoff():
    result = failed_fixture()
    result['split']['holdout_start'] = '2021-01-01T00:00:00+00:00'
    with pytest.raises(ValueError, match='bounds'):
        a.record_failure(None, result, 'synthetic')


def test_idempotent_null_trial_preserves_family_and_all_final_rows():
    from sqlalchemy import select, text
    from sqlalchemy.orm import Session
    from tradingbot.db.models import Trial
    from sqlalchemy import create_engine
    from tradingbot.db.session import get_engine
    # Real rows, so a private engine: in a whole-suite run the forward-paper
    # fixture redirects the cached engine to its disposable schema.
    engine = create_engine(get_engine().url)
    assert engine.url.port == 5433 and engine.url.database == 'tradingbot'
    with engine.connect() as connection:
        outer = connection.begin()
        try:
            with Session(bind=connection) as session:
                before = session.execute(text('SELECT id, row_to_json(t)::text FROM trials t WHERE final_holdout ORDER BY id')).all()
                strategy = session.execute(text('SELECT row_to_json(s)::text FROM strategies s WHERE id=6030')).scalar_one()
                result = failed_fixture()
                trial = a.record_failure(session, result, 'synthetic-commit')
                params = deepcopy(trial.params)
                again = a.record_failure(session, result, 'different-wrapper')
                assert again.id == trial.id and again.params == params
                assert trial.git_commit == 'synthetic-commit' and not trial.final_holdout
                assert all(getattr(trial, key) is None for key in (
                    'pnl', 'pnl_after_fees', 'fees_total', 'trade_count', 'sharpe', 'win_rate',
                    'max_drawdown', 'luck_p_value'))
                assert session.execute(text('SELECT id, row_to_json(t)::text FROM trials t WHERE final_holdout ORDER BY id')).all() == before
                assert session.execute(text('SELECT row_to_json(s)::text FROM strategies s WHERE id=6030')).scalar_one() == strategy
                assert session.scalar(select(Trial.id).where(Trial.strategy_id == trial.strategy_id, Trial.final_holdout)) is None
        finally:
            outer.rollback()
    engine.dispose()
