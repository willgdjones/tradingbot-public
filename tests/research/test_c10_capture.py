import json

import pytest

from tradingbot.research import c10_capture as c


def test_capture_must_stay_within_owned_archive_and_registered_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(c, 'ARCHIVE', tmp_path / 'archive')
    with pytest.raises(ValueError, match='within'):
        c.capture(tmp_path, c.PUBLIC['tlt-issuer'][0])
    with pytest.raises(ValueError, match='Unregistered'):
        c.capture(tmp_path / 'archive' / 'one', 'https://unregistered.example')


def test_existing_receipt_reuse_is_bound_to_request_and_raw_content(tmp_path):
    raw = b'unchanged source'
    (tmp_path / 'raw').write_bytes(raw)
    metadata = {'url': 'https://example.org', 'params': {'symbol': 'TLT'},
                'sha256': c.sha(raw), 'bytes': len(raw)}
    (tmp_path / 'manifest.json').write_text(json.dumps(metadata))
    assert c.read(tmp_path, metadata['url'], metadata['params'])[1] == raw
    with pytest.raises(ValueError, match='identity'):
        c.read(tmp_path, metadata['url'], {'symbol': 'IEF'})
    (tmp_path / 'raw').write_bytes(b'changed')
    with pytest.raises(ValueError, match='content'):
        c.read(tmp_path, metadata['url'], metadata['params'])
