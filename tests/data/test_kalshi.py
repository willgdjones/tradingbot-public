import json

from tradingbot.data.kalshi import download


def test_both_tiers_and_time_filter_retained_on_resume(tmp_path):
    seen = []
    def fetch(r):
        seen.append(r)
        if r.url.endswith('cutoff'):
            return '{"market_settled_ts":"2026-01-01T00:00:00Z","trades_created_ts":"2026-02-01T00:00:00Z"}'
        return json.dumps({'trades': [{'trade_id': 'overlap', 'count_fp': '0.25'}],
                           'cursor': '' if r.params.get('cursor') else 'abc'})
    initial = download(tmp_path, 'test', fetch, 'trades', ticker='CPI', start=100, end=200, max_pages=1)
    assert [p.complete for p in initial] == [True, False, False]
    final = download(tmp_path, 'test', fetch, 'trades', ticker='CPI', start=100, end=200)
    assert all(p.complete for p in final)
    trades = [r for r in seen if r.url.endswith('trades')]
    assert len(trades) == 4
    assert all(r.params['min_ts'] == 100 and r.params['max_ts'] == 200 and r.params['ticker'] == 'CPI' for r in trades)
    assert '/markets/trades' in trades[0].url
    assert '/historical/trades' in trades[1].url


def test_sdk_http_status_reaches_retry_layer():
    from types import SimpleNamespace
    import pytest
    from tradingbot.data.archive import Request
    from tradingbot.data.kalshi import BASE, KalshiPublic
    from tradingbot.data.transport import FetchError
    response = SimpleNamespace(status=429, data=b'{"error":"rate limited"}',
                               read=lambda: None, getheader=lambda name: '2')
    client = KalshiPublic()
    client.client.call_api = lambda *args, **kwargs: response
    try:
        with pytest.raises(FetchError) as raised:
            client(Request(BASE + '/markets', {}))
        assert raised.value.status == 429 and raised.value.retry_after == '2'
    finally:
        client.close()
