from decimal import Decimal, localcontext

import pytest

from tradingbot.data.xlf_action_amendment import (
    checked_bytes, issuer_terms, nominal_entitlement, provider_conflicts, sha,
)

ISSUER = b'''<p>Shareholders of record on September 21, 2016 (Record Date)
received a distribution of shares of XLRE. For each share of XLF held,
an eligible shareholder received <b>0.139146</b> shares of XLRE.
The special dividend was paid on September 22, 2016.</p>'''


def test_primary_terms_create_units_not_cash_or_extra_xlf():
    action = issuer_terms(ISSUER)
    assert action['distribution_asset'] == 'XLRE'
    assert action['xlf_share_count_multiplier'] == '1'
    assert action['record_date'] == '2016-09-21'
    assert action['ex_date'] == '2016-09-19'
    assert all(action[field] is None for field in (
        'broker_available_at', 'fractional_allocation', 'cash_in_lieu_amount', 'cash_available_at'))
    assert nominal_entitlement(Decimal('100')) == Decimal('13.914600')
    assert nominal_entitlement(Decimal('0.25')) == Decimal('0.03478650')


@pytest.mark.parametrize('raw', [b'blocked', ISSUER + ISSUER,
    ISSUER.replace(b'0.139146', b'1.231'), ISSUER.replace(b'September 21', b'September 19'),
    ISSUER.replace(b'September 22', b'September 23')])
def test_missing_ambiguous_or_changed_primary_evidence_fails(raw):
    with pytest.raises(ValueError):
        issuer_terms(raw)


@pytest.mark.parametrize('quantity', ['-1', 'NaN', 'Infinity', '-Infinity'])
def test_invalid_entitlement_quantity_fails(quantity):
    with pytest.raises(ValueError):
        nominal_entitlement(Decimal(quantity))


def test_entitlement_does_not_round_fraction_to_whole_share_or_cash():
    with localcontext() as ctx:
        ctx.prec = 4
        assert nominal_entitlement(Decimal('123.456789')) == Decimal('17.178518362194')


def test_conflicting_provider_cash_record_is_preserved_and_rejected():
    row = {'symbol': 'XLF', 'ex_date': '2016-09-19', 'rate': 0.139146,
           'record_date': '2016-09-19', 'payable_date': '2016-09-22', 'process_date': '2016-09-22'}
    payload = {'corporate_actions': {'cash_dividends': [row]}}
    result = provider_conflicts(payload)
    assert result['original_record'] == row
    assert set(result['rejected_fields']) == {'cash_dividends.rate', 'record_date', 'process_date'}
    payload['corporate_actions']['cash_dividends'].append(dict(row))
    with pytest.raises(ValueError, match='ambiguous'):
        provider_conflicts(payload)


def test_tampered_source_cannot_reuse_original_hash(tmp_path):
    path = tmp_path / 'raw.html'
    path.write_bytes(ISSUER)
    digest = sha(ISSUER)
    assert checked_bytes(path, digest) == ISSUER
    path.write_bytes(ISSUER.replace(b'0.139146', b'1.231'))
    with pytest.raises(ValueError, match='checksum'):
        checked_bytes(path, digest)
