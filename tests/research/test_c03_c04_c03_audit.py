"""Source-only parser checks; never inspect C03 signals or returns."""
from datetime import date
from decimal import Decimal as D
from html import escape
import json

import pytest

from tradingbot.research.c03_c04_c03_audit import (
    efa_distributions, vanguard_distributions, secondary_distributions,
)


def issuer_html(exs, amounts):
    names = {'exDate':'Ex-Date','recordDate':'Record Date','payableDate':'Payable Date',
        'totalDistribution':'Total Distribution','incomeAmount':'Income',
        'shortTermCapitalGain':'ST Cap Gains','longTermCapitalGain':'LT Cap Gains',
        'returnOnCapital':'Return of Capital'}
    values = {k:list(exs) if k.endswith('Date') else list(amounts) if k in
              ('totalDistribution','incomeAmount') else ['0']*len(exs) for k in names}
    columns = [{'name':k,'label':v,'value':values[k]} for k,v in names.items()]
    parallel = {k:{'label':v,'value':values[k]} for k,v in names.items()}
    objects = [{'distributionTableData':columns}, {'containersByNameMap':{'distributions':{
        'subContainersByNameMap':{'table':{'dataPointsByNameMap':parallel}}}}}]
    return ''.join('<walrus-render-on-client componentprops="'+escape(json.dumps(o),quote=True)+'"></walrus-render-on-client>' for o in objects)


def test_efa_old_null_is_excluded_but_in_interval_null_never_admitted():
    raw = issuer_html([20041223,20060620],[None,'1.25'])
    rows = efa_distributions(raw)
    assert list(rows) == [date(2006,6,20)] and rows[date(2006,6,20)].amount == D('1.25')
    with pytest.raises(ArithmeticError):
        efa_distributions(issuer_html([20060620],[None]))


def test_efa_parallel_disagreement_and_duplicate_ex_date_rejected():
    raw = issuer_html([20060620],['1.25'])
    with pytest.raises(ValueError,match='views disagree'):
        efa_distributions(raw.replace('1.25','1.26',1))
    with pytest.raises(ValueError,match='invalid'):
        efa_distributions(issuer_html([20060620,20060620],['1.25','1.25']))


def test_vanguard_components_sum_once_and_date_conflict_rejected():
    def row(kind,amount):return {'typeCode':kind,'amount':amount,'exDividendDate':'2016-12-22',
        'recordDate':'2016-12-27','payableDate':'2016-12-29'}
    rows = [row('INC','1.003224'),row('ROC','.451802'),row('CGLT','.118534'),row('1250','.12144')]
    assert vanguard_distributions(json.dumps(rows))[date(2016,12,22)].amount == D('1.695')
    with pytest.raises(ValueError,match='duplicate'):
        vanguard_distributions(json.dumps(rows+[rows[0]]))
    rows[-1]['payableDate']='2016-12-30'
    with pytest.raises(ValueError,match='disagree'):
        vanguard_distributions(json.dumps(rows))


def test_secondary_estimates_beyond_end_are_excluded_and_amount_conflicts_preserved():
    header=['Ex-Dividend Date','Payout Date','Cash Amount','Change / Status']
    rows=[header,['2027-03-24','2027-03-26','$0.8046','estimated'],
          ['2006-12-22','2006-12-29','$1.133','historical']]
    html=''.join('<tr>'+''.join('<td>'+c+'</td>' for c in row)+'</tr>' for row in rows)
    assert secondary_distributions(html,'dividendhistory') == {
        date(2006,12,22):{'pay_date':'2006-12-29','amount':'1.133'}}
    with pytest.raises(ValueError,match='headers'):
        secondary_distributions(html.replace('Payout Date','Unknown'),'dividendhistory')
