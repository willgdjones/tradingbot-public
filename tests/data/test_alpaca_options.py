from datetime import UTC, date, datetime
import json

import pyarrow.parquet as pq
import pytest

from tradingbot.data.alpaca_options import (DATA, PAPER, advance_for, audit, build_request,
    capture, endpoint, symbols)
from tradingbot.data.archive import Request

SPY = 'SPY240216C00490000'
PUT = 'SPY240216P00490000'


def history(kind='trades'):
    return build_request(kind, option_symbols=SPY+','+PUT, start='2024-02-01T00:00:00Z',
                         end='2024-02-16T23:59:59Z', now=datetime(2026,10,1,tzinfo=UTC))


def test_free_get_allowlist_has_no_account_or_order_surface():
    assert endpoint(history()) == ('data', '/options/trades')
    assert endpoint(Request(PAPER, {})) == ('trading', '/options/contracts')
    for request in [Request(DATA+'/quotes/latest', {'feed':'opra'}),
                    Request(DATA+'/bars', {'feed':'indicative'}),
                    Request('https://api.alpaca.markets/v2/orders', {}),
                    Request(DATA+'/snapshots/../../orders', {'feed':'indicative'})]:
        with pytest.raises(ValueError): endpoint(request)


def test_explicit_chain_bounds_and_indicative_feed():
    r=build_request('chain',underlying='SPY',expiry_from=date(2026,10,1),expiry_to=date(2026,10,16))
    assert r.params['feed']=='indicative' and r.params['expiration_date_lte']=='2026-10-16'
    assert not any(k in r.params for k in ('asof','start','end'))
    r=build_request('contracts',underlying='SPY',expiry_from=date(2024,2,1),expiry_to=date(2024,2,16),status='inactive')
    assert r.params['status']=='inactive' and r.params['show_deliverables'] is True
    with pytest.raises(ValueError): build_request('chain',underlying='SPY')


@pytest.mark.parametrize('start,end', [('2023-12-01T00:00:00Z','2024-02-01T00:00:00Z'),
    ('2024-02-01','2024-02-02'),('2026-10-01T00:00:00Z','2026-10-01T00:01:00Z')])
def test_historical_floor_timezone_and_free_delay(start,end):
    with pytest.raises(ValueError):
        build_request('bars',option_symbols=SPY,start=start,end=end,now=datetime(2026,10,1,tzinfo=UTC))


def test_exact_raw_price_and_symbol_first_pagination_resume(tmp_path):
    request=history(); calls=[]
    pages=['{"trades":{"'+SPY+'":[{"t":"2024-02-01T14:30:00.123456789Z","i":1,"p":1.1234567890123456789}]},"next_page_token":"more"}',
           json.dumps({'trades':{PUT:[{'t':'2024-02-01T14:31:00Z','i':2,'p':2}]},'next_page_token':None})]
    def get(r): calls.append(r); return pages[len(calls)-1]
    first=capture(get,tmp_path/'options','test','trades',request,budget_root=tmp_path,max_pages=1)
    assert not first.complete and not audit(first.directory)['complete']
    second=capture(get,tmp_path/'options','test','trades',request,budget_root=tmp_path,max_pages=1)
    report=audit(second.directory)
    assert report['complete'] and report['records']==2 and len(report['symbols'])==2
    assert not report['historical_bbo'] and not report['executable_fill_evidence']
    assert calls[1].params['page_token']=='more'
    assert pq.ParquetFile(first.directory/'page-00000000.parquet').read().to_pylist()[0]['response_json']==pages[0]
    capture(get,tmp_path/'options','test','trades',request,budget_root=tmp_path)
    assert len(calls)==2


def test_empty_history_is_explicit_not_zero_price(tmp_path):
    result=capture(lambda _: '{"trades":null,"next_page_token":null}',tmp_path,'empty','trades',history(),budget_root=tmp_path)
    report=audit(result.directory)
    assert report['complete'] and report['records']==0
    assert report['requested_symbols_with_no_records']==sorted([SPY,PUT])


def test_missing_cursor_unrequested_symbol_and_repeated_page_fail(tmp_path):
    advance=advance_for('trades')
    with pytest.raises(ValueError,match='pagination'):
        advance(history(),{'trades':{}})
    with pytest.raises(ValueError,match='unrequested'):
        advance(history(),{'trades':{'BAD':[{'t':'2024-02-01T00:00:00Z'}]},'next_page_token':None})
    def get(request):
        return json.dumps({'trades':{SPY:[{'t':'2024-02-01T00:00:00Z','i':1}]},
                           'next_page_token':'next' if 'page_token' not in request.params else 'other'})
    with pytest.raises(ValueError,match='repeated record page'):
        capture(get,tmp_path,'repeat','trades',history(),budget_root=tmp_path)


def test_current_chain_is_observation_not_retrospective_membership(tmp_path):
    req=build_request('chain',underlying='SPY',expiry_from=date(2026,10,1),expiry_to=date(2026,10,16))
    body=json.dumps({'snapshots':{'SPY261016C00600000':{'latestQuote':{'t':'2026-09-30T19:00:00Z','ap':2,'bp':1},'greeks':{'delta':.1}}},'next_page_token':None})
    result=capture(lambda _:body,tmp_path,'now','chain',req,budget_root=tmp_path)
    report=audit(result.directory)
    assert report['records']==1 and report['retrieved_first']
    assert not report['historical_chain_membership']
    assert 'modified quotes' in report['semantics']


def test_archive_cannot_escape_global_data_budget(tmp_path):
    with pytest.raises(ValueError,match='globally budgeted'):
        capture(lambda _:None,tmp_path/'other','test','trades',history(),budget_root=tmp_path/'data')


def test_quote_age_and_contract_deliverables_are_auditable(tmp_path):
    req=build_request('quotes',option_symbols=SPY)
    result=capture(lambda _:json.dumps({'quotes':{SPY:{'t':'2024-02-01T14:30:00Z','bp':1.25,'ap':1.30}}}),
                   tmp_path,'quote','quotes',req,budget_root=tmp_path)
    row=audit(result.directory)['symbols'][SPY]
    assert row['quote']['bp']=='1.25' and row['quote_age_seconds_at_retrieval']>30
    assert row['quote_available_no_earlier_than']
    req=build_request('contracts',underlying='SPY',expiry_from=date(2024,2,1),expiry_to=date(2024,2,16),status='inactive')
    body='{"option_contracts":[{"symbol":"'+SPY+'","underlying_symbol":"SPY","expiration_date":"2024-02-16","size":"100","strike_price":490.001,"deliverables":[{"type":"cash","amount":1.1234567890123456789}]}],"next_page_token":null}'
    result=capture(lambda _:body,tmp_path,'contract','contracts',req,budget_root=tmp_path)
    contract=audit(result.directory)['symbols'][SPY]['contract']
    assert contract['size']=='100' and contract['strike_price']=='490.001'
    assert contract['deliverables'][0]['amount']=='1.1234567890123456789'
    json.dumps(contract)  # audit artifacts remain JSON serializable without losing exact decimals


def test_ignored_history_or_catalog_filters_are_rejected():
    with pytest.raises(ValueError,match='outside'):
        advance_for('trades')(history(),{'trades':{SPY:[{'t':'2026-01-01T00:00:00Z'}]},'next_page_token':None})
    req=build_request('contracts',underlying='SPY',expiry_from=date(2024,2,1),expiry_to=date(2024,2,16),status='inactive')
    for row in [{'symbol':SPY,'underlying_symbol':'OTHER','expiration_date':'2024-02-16'},
                {'symbol':SPY,'underlying_symbol':'SPY','expiration_date':'2026-02-16'}]:
        with pytest.raises(ValueError,match='scope'):
            advance_for('contracts')(req,{'option_contracts':[row],'next_page_token':None})
