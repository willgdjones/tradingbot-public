import json
from decimal import Decimal

import pyarrow.parquet as pq
import pytest

from tradingbot.data.archive import RawArchive, Request, cursor_pages
from tradingbot.data.transport import FetchError, RetryingGetter


def test_lossless_resume_and_completed_rerun(tmp_path):
    request = Request('https://example.test/markets', {'limit': 1})
    archive = RawArchive(tmp_path, 'kalshi', 'markets', 'test', request, semantics='test')
    body = '{"markets":[{"price":0.1234567890123456789,"unknown":null}],"cursor":"opaque+/="}'
    first = archive.capture(lambda r: body, cursor_pages('markets'), max_pages=1)
    assert not first.complete
    # Temporary files from a killed process do not advance the checkpoint.
    (first.directory / '.partial-killed').write_text('incomplete')
    requested = []
    def finish(r):
        requested.append(r)
        return '{"markets":[],"cursor":""}'
    second = archive.capture(finish, cursor_pages('markets'))
    assert second.complete and second.pages_written == 1
    assert requested[0].params['cursor'] == 'opaque+/='
    row = pq.read_table(first.directory / 'page-00000000.parquet').to_pylist()[0]
    assert row['response_json'] == body
    assert json.loads(row['response_json'], parse_float=Decimal)['markets'][0]['price'] == Decimal('0.1234567890123456789')
    assert row['retrieved_at'].utcoffset().total_seconds() == 0
    assert archive.capture(lambda r: pytest.fail('completed query must not refetch'), cursor_pages('markets')).pages_written == 0


def test_failed_page_can_resume_without_skipping(tmp_path):
    archive = RawArchive(tmp_path, 'kalshi', 'trades', 'run', Request('https://example.test', {}), semantics='test')
    calls = []
    def fetch(r):
        calls.append(r)
        if len(calls) == 2:
            raise FetchError(503)
        return '{"trades":[{"trade_id":"one"}],"cursor":"next"}'
    with pytest.raises(FetchError):
        archive.capture(fetch, cursor_pages('trades'))
    with pytest.raises(ValueError, match='cursor cycle'):
        archive.capture(lambda r: '{"trades":[],"cursor":"next"}', cursor_pages('trades'))
    assert len(list(archive.directory.glob('*.parquet'))) == 1
    archive.capture(lambda r: '{"trades":[],"cursor":""}', cursor_pages('trades'))
    assert len(list(archive.directory.glob('*.parquet'))) == 2


@pytest.mark.parametrize('body', ['{}', '{"markets":[],"cursor":null}', '{"markets":{}}'])
def test_malformed_response_never_checkpoints(tmp_path, body):
    archive = RawArchive(tmp_path, 'kalshi', 'markets', 'run', Request('https://example.test', {}), semantics='test')
    with pytest.raises(ValueError):
        archive.capture(lambda r: body, cursor_pages('markets'))
    assert not list(archive.directory.glob('*.parquet'))


def test_retry_and_permanent_failure():
    attempts, sleeps = [], []
    def fetch(r):
        attempts.append(r)
        if len(attempts) == 1:
            raise FetchError(429, '2')
        return '{}'
    request = Request('https://example.test', {})
    assert RetryingGetter(fetch, sleep=sleeps.append)(request) == '{}'
    assert 2 in sleeps and len(attempts) == 2
    def denied(r):
        raise FetchError(403)
    with pytest.raises(FetchError):
        RetryingGetter(denied, sleep=sleeps.append)(request)
    def unavailable(r):
        raise FetchError(503)
    with pytest.raises(FetchError):
        RetryingGetter(unavailable, attempts=2, sleep=sleeps.append)(request)
