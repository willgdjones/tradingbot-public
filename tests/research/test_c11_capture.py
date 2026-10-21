import json

import pytest

from tradingbot.research import c11_capture as c


def test_capture_rejects_unregistered_sources_before_network():
    with pytest.raises(ValueError, match='unregistered'):
        c.capture('../outside')


def test_saved_request_and_raw_integrity_are_checked(tmp_path):
    raw = b'original failed HTTP body'
    meta = {'url': 'https://example.invalid', 'method': 'GET', 'params': None,
            'status': 404, 'sha256': c.sha(raw), 'bytes': len(raw)}
    (tmp_path / 'manifest.json').write_text(json.dumps(meta))
    (tmp_path / 'raw').write_bytes(raw)
    assert c.read(tmp_path, meta['url'])[0]['status'] == 404
    with pytest.raises(ValueError, match='identity'):
        c.read(tmp_path, 'https://different.invalid')
    (tmp_path / 'raw').write_bytes(raw + b'changed')
    with pytest.raises(ValueError, match='checksum'):
        c.read(tmp_path, meta['url'])


def test_resume_uses_saved_response_without_network(tmp_path, monkeypatch):
    monkeypatch.setattr(c, 'ARCHIVE', tmp_path)
    folder = tmp_path / 'cboe-2026'
    folder.mkdir()
    raw = b'%PDF-original'
    (folder / 'raw').write_bytes(raw)
    (folder / 'manifest.json').write_text(json.dumps({'url': c.SOURCES['cboe-2026'],
        'method': 'GET', 'params': None, 'sha256': c.sha(raw), 'bytes': len(raw)}))
    monkeypatch.setattr(c.requests, 'get', lambda *a, **k: pytest.fail('network on resume'))
    assert c.capture('cboe-2026')[1] == raw


def test_action_pagination_preserves_all_types_and_scope():
    payload = {'corporate_actions': {'cash_dividends': [{}], 'forward_splits': [{}]},
               'next_page_token': 'next'}
    count, following = c.action_page(c.ACTION_REQUEST, payload)
    assert count == 2
    assert following.url == c.ACTION_REQUEST.url
    assert following.params == {**c.ACTION_REQUEST.params, 'page_token': 'next'}
    assert 'types' not in following.params and following.params['data_quality'] == 'all'
    with pytest.raises(ValueError, match='cursor'):
        c.action_page(c.ACTION_REQUEST, {'corporate_actions': {}, 'next_page_token': 'loop'})
