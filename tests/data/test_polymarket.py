import json
from decimal import Decimal

import httpx
import pyarrow.parquet as pq
import pytest

from tradingbot.data.archive import Request
from tradingbot.data.polymarket import (
    DATA, GAMMA, US, InternationalPublic, USPublic, download_international, download_us,
)
from tradingbot.data.transport import FetchError


def response(data, cursor=None):
    return json.dumps({'data': data, 'pagination': {'next_cursor': cursor}})


def test_us_offset_short_page_and_repeated_page_after_resume(tmp_path):
    seen = []
    def capped(r):
        seen.append(r.params['offset'])
        return json.dumps({'markets': [{'id': str(r.params['offset'])}] if r.params['offset'] < 2 else []})
    progress = download_us(tmp_path, 'short', capped, 'markets', page_size=100)
    assert progress[0].complete and seen == [0, 1, 2]
    first = download_us(tmp_path, 'repeat', lambda r: '{"markets":[{"id":"x"}]}', 'markets', max_pages=1)
    with pytest.raises(ValueError, match='repeated record page'):
        download_us(tmp_path, 'repeat', lambda r: '{"markets":[{"id":"x"}]}', 'markets', max_pages=1)
    assert len(list(first[0].directory.glob('*.parquet'))) == 1


def test_us_windows_and_scope_survive_resume(tmp_path):
    seen = []
    def fetch(r):
        seen.append(r)
        return '{"history":[{"timestamp":1,"longPrice":0.61,"shortPrice":0.41}]}'
    first = download_us(tmp_path, 'run', fetch, 'prices', slug='test', start=0, end=172801, max_pages=1)[0]
    second = download_us(tmp_path, 'run', fetch, 'prices', slug='test', start=0, end=172801)[0]
    assert not first.complete and second.complete and second.pages_written == 2
    assert [(r.params['timestamp.startTimestamp'], r.params['timestamp.endTimestamp']) for r in seen] == [
        (0, 86400), (86400, 172800), (172800, 172801)]
    different = download_us(tmp_path, 'run', fetch, 'prices', slug='test', start=0, end=200000, max_pages=1)[0]
    assert different.directory != first.directory  # Same first window, different overall scope.
    assert 'display_prices' in first.directory.parts
    manifest = json.loads((first.directory / 'manifest.json').read_text())
    assert 'NOT trades' in manifest['semantics']


def test_international_window_exhausts_cursor_before_advancing(tmp_path):
    seen = []
    def fetch(r):
        seen.append(r)
        return response([{'timestamp': r.params['start'], 'price': '0.1'}],
                        None if r.params.get('cursor') else 'opaque-token')
    progress = download_international(tmp_path, 'run', fetch, 'prices', token='123',
                                      start=0, end=15 * 86400 + 10)
    assert progress[0].complete and len(seen) == 4
    assert [(r.params['start'], r.params['end']) for r in seen] == [
        (0, 1296000), (0, 1296000), (1296000, 1296010), (1296000, 1296010)]
    assert 'cursor' not in seen[2].params
    assert all(r.params['token_id'] == '123' for r in seen)


def test_gamma_keyset_retains_raw_nonbinary_markets(tmp_path):
    seen = []
    def fetch(r):
        seen.append(r)
        return json.dumps({'markets': [{'id': 'm', 'outcomes': '["A","B","C"]'}],
                           'next_cursor': None if 'after_cursor' in r.params else 'gamma-token'})
    progress = download_international(tmp_path, 'run', fetch, 'markets', closed=True)
    assert progress[0].complete and seen[1].params['after_cursor'] == 'gamma-token'
    row = pq.read_table(progress[0].directory / 'page-00000000.parquet').to_pylist()[0]
    assert json.loads(row['response_json'])['markets'][0]['outcomes'] == '["A","B","C"]'


def test_international_missing_cursor_does_not_silently_complete(tmp_path):
    with pytest.raises(ValueError, match='pagination.next_cursor'):
        download_international(tmp_path, 'run', lambda r: '{"data":[]}', 'trades', condition='0x123')
    assert not list(tmp_path.rglob('*.parquet'))


@pytest.mark.parametrize('download,kwargs', [
    (download_us, {'kind': 'prices', 'slug': 'x', 'start': 0}),
    (download_us, {'kind': 'trades'}),
    (download_international, {'kind': 'prices'}),
    (download_international, {'kind': 'trades', 'condition': 'x', 'start': 1, 'end': 2}),
    (download_international, {'kind': 'prices', 'token': '1', 'bucket_seconds': 1}),
])
def test_invalid_requests_do_not_fetch(tmp_path, download, kwargs):
    with pytest.raises(ValueError):
        download(tmp_path, 'run', lambda r: pytest.fail('must validate first'), **kwargs)


def test_us_sdk_wire_text_no_auth_and_error_mapping():
    body = '{"history":[{"longPrice":0.1234567890123456789}]}'
    requests = []
    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(200, text=body)
        return httpx.Response(429, json={'message': 'slow down'}, headers={'Retry-After': '3'})
    client = USPublic()
    client.client._http.close()
    client.client._http = httpx.Client(transport=httpx.MockTransport(handler),
                                     event_hooks={'response': [client._capture]})
    try:
        assert client(Request(US + '/v1/price-history', {'symbol': 'test'})) == body
        with pytest.raises(FetchError) as raised:
            client(Request(US + '/v1/markets', {}))
        assert raised.value.status == 429 and raised.value.retry_after == '3'
        assert all('authorization' not in r.headers for r in requests)
        assert client.client.key_id is None and client.client.secret_key is None
    finally:
        client.close()


def test_international_sdk_transport_preserves_wire_text():
    body = '{"data":[{"price":0.1234567890123456789}],"pagination":{"next_cursor":null}}'
    from polymarket.clients._transport import SyncTransport
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, text=body)
    client = InternationalPublic()
    client.close()
    http = httpx.Client(base_url=DATA, transport=httpx.MockTransport(handler))
    client.clients = {DATA: SyncTransport(base_url=DATA, client=http)}
    try:
        captured = client(Request(DATA + '/v2/prices-history', {'token_id': '123'}))
        assert captured == body
        assert json.loads(captured, parse_float=Decimal)['data'][0]['price'] == Decimal('0.1234567890123456789')
        assert requests[0].method == 'GET' and 'authorization' not in requests[0].headers
    finally:
        client.close()
        http.close()


def test_cli_rejects_unimplemented_filters(monkeypatch):
    from tradingbot.data.__main__ import main
    monkeypatch.setattr('sys.argv', ['history', 'polymarket-intl', 'trades', '--run', 'test',
                                    '--condition', '0x123', '--start', '1', '--end', '2'])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2


def test_us_settlement_preserves_decimal_value(tmp_path):
    progress = download_us(tmp_path, 'run', lambda r: '{"slug":"crypto-test","settlement":0.125}',
                           'settlement', slug='crypto-test')[0]
    row = pq.read_table(progress.directory / 'page-00000000.parquet').to_pylist()[0]
    assert json.loads(row['response_json'], parse_float=Decimal)['settlement'] == Decimal('0.125')


def test_gamma_resume_uses_server_cursor_and_filter(tmp_path):
    requests = []
    def fetch(r):
        requests.append(r)
        if 'after_cursor' not in r.params:
            return '{"markets":[],"next_cursor":"empty-page-still-has-more"}'
        return '{"markets":[]}'
    first = download_international(tmp_path, 'run', fetch, 'markets', closed=True, max_pages=1)[0]
    assert not first.complete
    assert download_international(tmp_path, 'run', fetch, 'markets', closed=True)[0].complete
    assert requests[1].params == {'limit': 1000, 'closed': True, 'after_cursor': 'empty-page-still-has-more'}
