from copy import deepcopy
from datetime import date
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from tradingbot.data.archive import SCHEMA, canonical
from tradingbot.research import c11_sources as c


def test_real_sources_keep_coverage_and_execution_failures_visible():
    result = c.audit_sources()
    assert len(result['public_sources']) == 15
    calendar = result['calendar']
    assert calendar['occ_api_years'] == [2025, 2026, 2027]
    assert calendar['frozen_interval_months'] == 249
    assert calendar['months_with_reviewed_calendar_date'] == 33
    assert calendar['grandfathered_spy_contract_month'] == '2015-12'
    assert not calendar['as_of_announcement_and_revision_history_admitted']
    assert '2025-04-17' in calendar['cboe_visually_reviewed_dates']
    assert '2026-06-18' in calendar['cboe_visually_reviewed_dates']
    assert result['spy']['sessions'] == 5218 and result['spy']['distributions'] == 83
    actions = result['spy']['actions']
    assert actions['cash_records'] == 40 and actions['missing_before_first_broker_date'] == 41
    assert actions['missing_on_or_after_first_broker_date'] == ['2018-06-15', '2026-09-18']
    assert not actions['full_interval_share_action_completeness_proven']
    assert not result['execution']['close_variant_admitted']
    assert result['execution']['fractional_order_tif']['CLS'] == ['No'] * 4
    assert not result['price_and_calendar_returns_computed']


def test_occ_uses_monthly_legend_and_preserves_holiday_adjustment():
    _, bodies = c.public_sources()
    dates, payload = c.occ_dates(bodies['occ-calendar-api'])
    assert len(dates) == 36 and date(2026, 6, 18) in dates
    assert date(2026, 6, 19) not in dates
    assert date(2026, 6, 17) not in dates  # VIX expiry cannot become SPY standard expiry.
    payload['data'].append(deepcopy(payload['data'][0]))
    with pytest.raises(ValueError, match='duplicate'):
        c.occ_dates(json.dumps(payload))


def test_unknown_occ_type_and_relabelled_monthly_legend_are_rejected():
    _, bodies = c.public_sources()
    payload = json.loads(bodies['occ-calendar-api'])
    payload['legend'][2]['title'] = 'Weekly options only'
    with pytest.raises(ValueError, match='legend'):
        c.occ_dates(json.dumps(payload))
    payload = json.loads(bodies['occ-calendar-api'])
    payload['data'][0]['events'] = [{'type': 'unreviewed'}]
    with pytest.raises(ValueError, match='unknown'):
        c.occ_dates(json.dumps(payload))


def test_fractional_section_cannot_inherit_whole_share_support():
    _, bodies = c.public_sources()
    raw = bodies['alpaca-orders']
    assert c.fractional_tif(raw)['OPG'] == ['No'] * 4
    with pytest.raises(ValueError, match='missing or ambiguous'):
        c.fractional_tif(raw.replace(b'### Fractional orders (USD)', b'### Other orders'))
    with pytest.raises(ValueError, match='incomplete'):
        c.fractional_tif(raw.replace(b'<b>CLS</b>', b'<b>OTHER</b>'))


def test_empty_noncash_inventory_cannot_become_completeness_proof():
    distributions = [{'ex_date': '2006-03-17', 'amount': '1'}, {'ex_date': '2016-06-17', 'amount': '1'}]
    groups = {'cash_dividends': [{'id': 'one', 'symbol': 'SPY', 'ex_date': '2016-06-17', 'rate': '1'}]}
    result = c.actions_audit(groups, distributions)
    assert result['missing_before_first_broker_date'] == 1
    assert not result['full_interval_share_action_completeness_proven']
    groups['forward_splits'] = []
    with pytest.raises(ValueError, match='noncash'):
        c.actions_audit(groups, distributions)


def test_action_checksum_cursor_and_symbol_are_verified(tmp_path, monkeypatch):
    original, _ = c.action_source()
    source = c.ROOT / original['path']
    manifest = json.loads((source.parent / 'manifest.json').read_bytes())
    directory = tmp_path / 'raw/alpaca/corporate_actions' / c.RUN / source.parent.name
    directory.mkdir(parents=True)
    (directory / 'manifest.json').write_text(canonical(manifest))
    target = directory / source.name
    row = pq.read_table(source).to_pylist()[0]
    pq.write_table(pa.Table.from_pylist([row], schema=SCHEMA), target)
    assert c.action_source(tmp_path, tmp_path)[0]['records'] == 40
    for key, value in [('next_request_json', '{}'), ('record_count', 39),
                       ('response_json', row['response_json'] + ' '),
                       ('request_json', '{}')]:
        pq.write_table(pa.Table.from_pylist([{**row, key: value}], schema=SCHEMA), target)
        with pytest.raises(ValueError, match='changed'):
            c.action_source(tmp_path, tmp_path)
