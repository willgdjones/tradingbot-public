from datetime import UTC, datetime
from decimal import Decimal

import pytest

from tradingbot.data.normalize import ImportDataError, normalize, number


def test_kalshi_contract_preserves_event_group_and_fractional_settlement():
    raw = {'ticker': 'CPI-JUN-T1', 'event_ticker': 'CPI-JUN', 'status': 'finalized',
           'settlement_value_dollars': '0.25', 'settlement_ts': '2026-07-01T12:00:00Z'}
    batch = normalize('kalshi', 'markets_historical', {'markets': [raw]}, {'params': {'series_ticker': 'CPI'}})
    market, yes, no = batch.references
    assert market.external_id == 'CPI-JUN'
    assert [yes.external_id, no.external_id] == ['CPI-JUN-T1:yes', 'CPI-JUN-T1:no']
    assert yes.state['payout'] == Decimal('.25') and no.state['payout'] == Decimal('.75')
    assert yes.market_external_id == no.market_external_id == market.external_id
    assert yes.state['resolve_ts'] == datetime(2026, 7, 1, 12, tzinfo=UTC)


def test_kalshi_trade_projects_both_sides_with_true_aggressor_and_blocks():
    raw = {'ticker': 'K', 'trade_id': 't', 'created_time': '2026-01-01T00:00:00.123456Z',
           'yes_price_dollars': '.4', 'no_price_dollars': '.6', 'count_fp': '.25',
           'taker_outcome_side': 'no', 'is_block_trade': True}
    yes, no = normalize('kalshi', 'trades_historical', {'trades': [raw]}, {}).points
    assert yes.fields['price'] == Decimal('.4') and no.fields['price'] == Decimal('.6')
    assert yes.fields['aggressor_side'] == 'sell' and no.fields['aggressor_side'] == 'buy'
    assert yes.fields['size'] == Decimal('.25')
    assert not yes.evidence['maker_fill_eligible']


def pm_market(**updates):
    return {'slug': 'test', 'conditionId': 'condition', 'outcomes': '["Yes","No"]',
            'clobTokenIds': '["yes-token","no-token"]', 'outcomePrices': '["0","1"]',
            'closed': True, **updates}


def test_old_gamma_zero_prices_do_not_invent_settlement():
    batch = normalize('polymarket_intl', 'markets', {'markets': [pm_market(outcomePrices='["0","0"]')]}, {})
    assert batch.references[0].fields['status'] == 'closed'
    assert all(r.state['payout'] is None for r in batch.references[1:])


def test_gamma_reversed_outcome_order_stays_with_token():
    raw = pm_market(outcomes='["No","Yes"]', clobTokenIds='["no-token","yes-token"]', umaResolutionStatus='resolved')
    batch = normalize('polymarket_intl', 'markets', {'markets': [raw]}, {})
    assert batch.references[1].fields['instrument_type'] == 'binary_no'
    assert batch.references[1].state['payout'] == 0
    assert batch.references[2].state['payout'] == 1


def test_nonbinary_gamma_outcomes_are_retained():
    raw = pm_market(outcomes=['A', 'B', 'C'], clobTokenIds=['1', '2', '3'], closed=False)
    batch = normalize('polymarket_intl', 'markets', {'markets': [raw]}, {})
    assert batch.references[0].fields['market_type'] == 'categorical'
    assert [r.external_id for r in batch.references[1:]] == ['1', '2', '3']


def test_us_named_sides_follow_explicit_long_mapping():
    raw = pm_market(outcomes=['Short name', 'Long name'], outcomePrices=['0', '1'],
                    status='MARKET_STATUS_RESOLVED', marketSides=[
                        {'long': False, 'description': 'Short name'}, {'long': True, 'description': 'Long name'}])
    batch = normalize('polymarket_us', 'markets', {'markets': [raw]}, {})
    assert batch.references[1].external_id == 'test:yes'
    assert batch.references[1].fields['outcome'] == 'Long name'
    assert batch.references[1].state['payout'] == 1


def test_sampled_and_display_prices_never_masquerade_as_tape_or_bbo():
    batch = normalize('polymarket_us', 'display_prices', {'history': [
        {'timestamp': 1, 'longPrice': Decimal('.61'), 'shortPrice': Decimal('.41')}]}, {'params': {'symbol': 'test'}})
    assert len(batch.points) == 2
    assert all(p.table == 'quote' and set(p.fields) == {'time'} for p in batch.points)
    assert [p.evidence['price'] for p in batch.points] == ['0.61', '0.41']
    assert not batch.points[0].evidence['maker_fill_eligible']
    sample = normalize('polymarket_intl', 'price_history', {'data': [
        {'timestamp': 1, 'price': Decimal('.1'), 'resolution_seconds': 0}]}, {'params': {'token_id': 'token'}}).points[0]
    assert sample.evidence['resolution_seconds'] == 0
    assert sample.evidence['kind'] == 'sampled_price'


def test_pm_trade_fingerprint_does_not_collapse_transaction_fills():
    raw = {'token_id': 'a', 'timestamp': 100, 'size': '5', 'price': '.2', 'side': 'SELL',
           'transaction_hash': 'tx', 'proxy_wallet': 'wallet', 'condition_id': 'condition', 'outcome_index': 0}
    rows = [raw, {**raw, 'size': '6'}, {**raw, 'proxy_wallet': 'another'}, {**raw, 'token_id': 'b'}]
    points = normalize('polymarket_intl', 'trades_recent', {'data': rows}, {}).points
    assert len({p.key for p in points}) == 4
    assert all(p.fields['aggressor_side'] is None for p in points)
    assert all(not p.evidence['maker_fill_eligible'] for p in points)
    assert normalize('polymarket_intl', 'trades_recent', {'data': [raw]}, {}).points[0].key == points[0].key


def test_unresolved_oracle_sentinel_is_evidence_only():
    ref = normalize('polymarket_intl', 'resolutions', {'data': [
        {'condition_id': 'c', 'status': 'posed', 'price': '69'}]}, {}).references[0]
    assert ref.fields == {} and ref.state == {}
    assert ref.channel == 'resolution_evidence'


@pytest.mark.parametrize('value', [None, True, 0.1, 'NaN', 'Infinity', '-0.1', '1.01'])
def test_invalid_prices_fail(value):
    with pytest.raises(ImportDataError):
        number(value, probability=True)


def test_ambiguous_token_mapping_fails():
    with pytest.raises(ImportDataError):
        normalize('polymarket_intl', 'markets', {'markets': [pm_market(clobTokenIds='["a"]')]}, {})


def test_equivalent_decimal_spellings_share_price_identity():
    def point(price):
        return normalize('polymarket_intl', 'price_history', {'data': [
            {'timestamp': 1, 'price': price, 'resolution_seconds': 0}]},
            {'params': {'token_id': 'token'}}).points[0]
    assert point('0.5').key == point('0.500').key
    assert point('-0.00').key == point('0').key
    assert point('0.12345678901234567890123456789').evidence['price'] == '0.12345678901234567890123456789'


def test_equivalent_decimal_spellings_share_activity_identity():
    raw = {'token_id': 'a', 'timestamp': 100, 'size': '5', 'price': '.2', 'side': 'SELL',
           'transaction_hash': 'tx', 'proxy_wallet': 'wallet', 'condition_id': 'condition', 'outcome_index': 0}
    def key(row):
        return normalize('polymarket_intl', 'trades_recent', {'data': [row]}, {}).points[0].key
    assert key(raw) == key({**raw, 'size': '5.000', 'price': '.200'})


def test_taker_history_direction_requires_verified_request():
    raw = {'token_id': 'a', 'timestamp': 100, 'size': '5', 'price': '.2', 'side': 'SELL',
           'transaction_hash': 'tx', 'proxy_wallet': 'wallet', 'condition_id': 'condition', 'outcome_index': 0}
    request = {'url': 'https://data-api.polymarket.com/v2/trades',
               'params': {'condition': 'condition', 'taker_only': True}}
    point = normalize('polymarket_intl', 'trades_taker_history', {'data': [raw]}, request).points[0]
    assert point.fields['aggressor_side'] == 'sell'
    assert point.evidence['maker_fill_eligible'] is True
    assert point.key.startswith('pm-intl-taker:')
    for bad in [{}, {**request, 'url': 'https://other.invalid/v2/trades'},
                {**request, 'params': {'condition': 'condition', 'taker_only': False}},
                {**request, 'params': {'condition': 'another', 'taker_only': True}}]:
        with pytest.raises(ImportDataError):
            normalize('polymarket_intl', 'trades_taker_history', {'data': [raw]}, bad)
    for side in ['MAKER', None]:
        with pytest.raises(ImportDataError):
            normalize('polymarket_intl', 'trades_taker_history', {'data': [{**raw, 'side': side}]}, request)
    same = {**raw, 'size': '5.0000', 'price': '.200'}
    assert normalize('polymarket_intl', 'trades_taker_history', {'data': [same]}, request).points[0].key == point.key


def test_gamma_event_series_supplies_category_without_rewriting_raw():
    raw = pm_market()
    event = {'id': 'e', 'series': [{'slug': 'nyc-daily-weather'}], 'markets': [raw]}
    batch = normalize('polymarket_intl', 'events', {'events': [event]}, {})
    assert batch.references[0].fields['category'] == 'pm-series:nyc-daily-weather'
    assert 'category' not in raw


def test_only_terminal_resolution_can_supply_lifecycle_time():
    raw = {'condition_id': 'c', 'status': 'resolved', 'price': '1000000000000000000',
           'transaction_hash': 'tx', 'log_index': '3', 'last_update_timestamp': '1756796247'}
    refs = normalize('polymarket_intl', 'resolutions', {'data': [raw]}, {}).references
    assert len(refs) == 2 and refs[1].fields['resolve_ts'].year == 2025
    assert set(refs[1].fields) == {'resolve_ts'}  # No invented oracle-price conversion.
    assert refs[1].state['resolution_time_basis'] == 'resolved_lifecycle_event'
    for status in ['posed', 'proposed', 'disputed']:
        batch = normalize('polymarket_intl', 'resolutions', {'data': [{**raw, 'status': status}]}, {})
        assert len(batch.references) == 1 and not batch.references[0].fields
    native = {**raw, 'resolved_at': '2025-09-02T08:17:27Z', 'last_update_timestamp': '2025-09-02T09:00:00Z'}
    assert normalize('polymarket_intl', 'resolutions', {'data': [native]}, {}).references[1].state['resolution_time_basis'] == 'resolved_at'
