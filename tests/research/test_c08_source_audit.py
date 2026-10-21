"""C08 publication/source admission and durable failed-trial invariants."""
from datetime import UTC, date, datetime
import json
from types import SimpleNamespace
import uuid

import pytest

from tradingbot.backtest.holdout import HoldoutSplit
from tradingbot.research.c08_source_audit import (
    END, START, action_evidence, eia_layout, load_capture, record_failure,
    sha, uso_params, uso_source,
)
from tradingbot.data.free_history import YAHOO_CHART


def page(observation='September 4, 2020', release='September 10, 2020'):
    return (f'<p>Data for week ending {observation} | Release Date: {release} | full report</p>'
            '<a href="csv/table1.csv">CSV</a>'
            '<p>Crude Oil Production Re-benchmarking Notice</p>').encode()


def test_actual_thursday_publication_is_not_wednesday_or_observation_date():
    probe = eia_layout(page(), 'https://www.eia.gov/archive/2020/wpsr.php')
    assert probe['observation_date'] == '2020-09-04'
    assert probe['release_date'] == '2020-09-10' and probe['release_weekday'] == 'Thursday'
    assert probe['earliest_calendar_date_for_execution'] == '2020-09-11'
    assert probe['table1_url'] == 'https://www.eia.gov/archive/2020/csv/table1.csv'
    assert probe['first_release_vintage_verified'] is False
    assert probe['notice'] == 'Production re-benchmarking is not an inventory correction'


def test_delayed_release_weekend_rule_is_calendar_bound_not_an_invented_session():
    probe = eia_layout(page('June 17, 2022', 'June 29, 2022'), 'https://www.eia.gov/a/b.php')
    assert probe['earliest_calendar_date_for_execution'] == '2022-06-30'
    probe = eia_layout(page('November 3, 2023', 'November 10, 2023'), 'https://www.eia.gov/a/b.php')
    assert probe['earliest_calendar_date_for_execution'] == '2023-11-11'
    # Saturday is only a lower bound; a real replay still needs its session calendar.
    assert 'execution_session' not in probe and 'scarcity' not in probe


@pytest.mark.parametrize('raw', [
    page(release='September 4, 2020'), page() + page(), b'<p>Undated data</p>',
    page().replace(b'csv/table1.csv', b'csv/table2.csv'),
    page() + b'<a href="other/csv/table1.csv">Other table</a>',
])
def test_ambiguous_or_invalid_eia_layout_rejected(raw):
    with pytest.raises(ValueError):
        eia_layout(raw, 'https://www.eia.gov/a/b.php')


def write_capture(directory, raw, **extra):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'raw').write_bytes(raw)
    receipt = {'key': 'USO', 'request_url': YAHOO_CHART.format(symbol='USO'),
               'sha256': sha(raw), 'bytes': len(raw), 'status_code': 200, 'params': uso_params(), **extra}
    (directory / 'manifest.json').write_text(json.dumps(receipt))


def test_exact_candidate_request_bounds_and_source_checksum(tmp_path):
    directory = tmp_path / 'USO'
    stamp = int(datetime(2018, 1, 2, 14, 30, tzinfo=UTC).timestamp())
    raw = json.dumps({'chart': {'result': [{'meta': {'symbol': 'USO'}, 'timestamp': [stamp],
        'indicators': {'quote': [{'open': [10], 'high': [12], 'low': [9], 'close': [11], 'volume': [100]}],
                       'adjclose': [{'adjclose': [11]}]}, 'events': {}}], 'error': None}}).encode()
    write_capture(directory, raw)
    sessions = {date(y, 1, 2): SimpleNamespace(closes_at=datetime(y, 1, 2, 21, tzinfo=UTC)) for y in (2008, 2018)}
    _, result = uso_source(tmp_path, sessions)
    assert result['coverage_ok'] and result['expected_sessions'] == 1
    assert HoldoutSplit('c08-test', START, END).holdout_start == datetime(2024, 2, 15, 12, tzinfo=UTC)
    (directory / 'raw').write_bytes(raw + b' ')
    with pytest.raises(ValueError, match='checksum'):
        load_capture(directory, 'USO', YAHOO_CHART.format(symbol='USO'))
    write_capture(directory, raw, params={**uso_params(), 'period1': 0})
    with pytest.raises(ValueError, match='exact C08 interval'):
        uso_source(tmp_path, sessions)


def test_conflicting_broker_evidence_does_not_invent_quantity_or_cash():
    docs = {k: ({'status_code': 200}, v.encode()) for k, v in {
        'uso-2020-issuer-release': 'April 29, 2020 one-for-eight cash in lieu',
        'alpaca-corporate-actions': 'reverse splits cash from DTC',
        'alpaca-2021-fractionals': 'August 2nd, 2021 removing cash-in-lieu transactions',
    }.items()}
    result = action_evidence(docs)
    assert result['current_account_fractional_treatment'] is None and result['cash_credit_date'] is None
    assert result['split_ratio'] == '0.125'
    docs['uso-2020-issuer-release'][0]['status_code'] = 403
    with pytest.raises(ValueError, match='evidence incomplete'):
        action_evidence(docs)


def test_data_failure_is_idempotent_null_and_never_claims_holdout():
    from sqlalchemy.orm import Session
    from tradingbot.db.session import get_engine
    identity = {'test': uuid.uuid4().hex}
    split = HoldoutSplit('c08-audit-test:' + identity['test'], START, END)
    result = {'status': 'DATA_FAIL', 'identity': identity, 'split': split.metadata(),
              'code_sha256': {'test': 'a' * 64}, 'failed_prerequisites': ['test action policy unresolved']}
    with get_engine().connect() as connection:
        tx = connection.begin()
        try:
            with Session(bind=connection) as session:
                trial = record_failure(session, result, 'test-commit')
                assert record_failure(session, result, 'test-commit').id == trial.id
                assert trial.status == 'failed' and trial.final_holdout is False
                assert trial.pnl_after_fees is None and trial.trade_count is None
                assert trial.max_drawdown is None and trial.luck_p_value is None
                assert trial.metrics['training_cases_attempted'] == trial.metrics['final_holdout_attempts'] == 0
                result['failed_prerequisites'] = []
                with pytest.raises(ValueError, match='concrete data failure'):
                    record_failure(session, result, 'test-commit')
        finally:
            tx.rollback()
