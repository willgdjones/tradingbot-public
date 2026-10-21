from datetime import date
from decimal import Decimal as D
from html import escape
import json
from types import SimpleNamespace

import pytest

from tradingbot.research.c06_sources import ishares_distributions, reconcile_distributions
from tradingbot.data.c04_sources import Distribution


def source(change=None, parallel_change=None):
    values = {'recordDate': ('Record Date', 20240903), 'exDate': ('Ex-Date', 20240903),
              'payableDate': ('Payable Date', 20240906), 'totalDistribution': ('Total Distribution', '0.123456'),
              'incomeAmount': ('Income', '0.123456'), 'shortTermCapitalGain': ('ST Cap Gains', '0'),
              'longTermCapitalGain': ('LT Cap Gains', '0'), 'returnOnCapital': ('Return of Capital', '0')}
    table = [{'name': k, 'label': label, 'value': [value]} for k, (label, value) in values.items()]
    if change:
        change(table)
    parallel = {v['name']: json.loads(json.dumps(v)) for v in table}
    if parallel_change:
        parallel_change(parallel)
    views = [{'distributionTableData': table}, {'containersByNameMap': {'distributions': {
        'subContainersByNameMap': {'table': {'dataPointsByNameMap': parallel}}}}}]
    return ''.join('<walrus-render-on-client componentprops="' + escape(json.dumps(view), quote=True)
                   + '"></walrus-render-on-client>' for view in views)


def test_exact_issuer_amount_and_dates():
    row = ishares_distributions(source())[date(2024, 9, 3)]
    assert row == Distribution(date(2024, 9, 3), date(2024, 9, 3), date(2024, 9, 6), D('.123456'))


@pytest.mark.parametrize('change', [
    lambda t: t[2]['value'].__setitem__(0, 20240902),
    lambda t: t[3]['value'].__setitem__(0, '.123457'),
    lambda t: t[4]['value'].__setitem__(0, 'NaN'),
    lambda t: t[0]['value'].append(20240904),
    lambda t: t[1]['value'].__setitem__(0, '20240903'),
    lambda t: t.append(t[0]),
])
def test_invalid_issuer_rows_fail(change):
    with pytest.raises(ValueError):
        ishares_distributions(source(change))


def test_embedded_views_must_agree():
    with pytest.raises(ValueError, match='views'):
        ishares_distributions(source(parallel_change=lambda p: p['totalDistribution']['value'].__setitem__(0, '.5')))


def test_duplicate_ex_dates_and_ambiguous_tables_fail():
    with pytest.raises(ValueError, match='duplicated'):
        ishares_distributions(source(lambda t: [c['value'].append(c['value'][0]) for c in t]))
    with pytest.raises(ValueError, match='ambiguous'):
        ishares_distributions(source() + source())


def test_reconciliation_allows_only_rounding_and_exact_dates():
    distributions = ishares_distributions(source())
    bar = SimpleNamespace(date=date(2024, 9, 3), dividend=D('.123'))
    issuer, differences = reconcile_distributions([bar], distributions)
    assert issuer == distributions and len(differences) == 1
    bar.dividend = D('.122')
    with pytest.raises(ValueError, match='beyond rounding'):
        reconcile_distributions([bar], distributions)
    bar.dividend = D('.123')
    bar.date = date(2024, 9, 4)
    with pytest.raises(ValueError, match='ex-date'):
        reconcile_distributions([bar], distributions)
