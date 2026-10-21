import json

import pytest
import requests

from tradingbot.forward.c05_readiness import ProbeBudget, ProbeHalted

from tradingbot.research import c12_capture as c


def test_fixed_public_source_boundary_excludes_credentials_queries_and_other_services():
    assert c.permitted(c.INDEXES['empsit'])
    assert c.permitted(c.EXAMPLES['empsit-20061208-pdf'])
    for url in ('https://www.bls.gov.attacker.test/news.release/archives/cpi_01192012.htm',
                'https://secret@www.bls.gov/news.release/archives/cpi_01192012.htm',
                'https://www.bls.gov/news.release/archives/cpi_01192012.htm?token=secret',
                'http://www.bls.gov/news.release/archives/cpi_01192012.htm',
                'https://paper-api.alpaca.markets/v2/orders'):
        assert not c.permitted(url)


def test_index_only_discovers_correct_family_and_frozen_interval_without_inventing_links():
    raw = b'''<a href="/news.release/archives/empsit_12082006.pdf">PDF</a>
    <a href="http://www.bls.gov/news.release/archives/empsit_12082006.txt">TXT</a>
    <a href="/news.release/archives/cpi_01192012.htm">Other family</a>
    <a href="/news.release/archives/empsit_10022026.htm">After endpoint</a>
    <a href="/news.release/archives/empsit_11042005.txt">Before metadata scope</a>'''
    rows = c.release_links(raw, 'empsit')
    assert len(rows) == 1 and rows[0]['release_date_from_url'] == '2006-12-08'
    assert rows[0]['url'] == 'https://www.bls.gov/news.release/archives/empsit_12082006.txt'
    with pytest.raises(ValueError, match='error page'):
        c.release_links(b'Access denied', 'empsit')


def test_existing_capture_is_immutable_and_bound_to_url(tmp_path):
    raw = b'official body'
    url = c.EXAMPLES['fed-advance-2006']
    (tmp_path / 'raw').write_bytes(raw)
    (tmp_path / 'manifest.json').write_text(json.dumps({'url': url, 'sha256': c.sha(raw), 'bytes': len(raw)}))
    assert c.load(tmp_path, url)[1] == raw
    with pytest.raises(ValueError, match='identity'):
        c.load(tmp_path, c.INDEXES['cpi'])
    (tmp_path / 'raw').write_bytes(raw + b'altered')
    with pytest.raises(ValueError, match='bytes'):
        c.load(tmp_path, url)


def test_path_escape_is_rejected_before_network(tmp_path):
    with pytest.raises(ValueError, match='key'):
        c.capture('../outside', c.INDEXES['cpi'], budget=None, archive=tmp_path)


def test_transport_boundary_rejects_broker_and_bls_before_network(tmp_path):
    with pytest.raises(ValueError, match='transport'):
        c.capture('one', c.INDEXES['cpi'], budget=None, archive=tmp_path, transport='urllib')


def test_network_failure_is_preserved_and_budget_halts_without_retries(tmp_path, monkeypatch):
    calls = []
    def fail(*args, **kwargs):
        calls.append(args)
        raise requests.ConnectionError('synthetic connection failure')
    monkeypatch.setattr(c.requests, 'get', fail)
    budget = ProbeBudget(clock=lambda: 1)
    for i in range(5):
        meta, raw = c.capture(str(i), c.INDEXES['cpi'], budget=budget, archive=tmp_path)
        assert meta['status'] is None and raw == b'' and meta['error_type'] == 'ConnectionError'
    assert len(calls) == 5
    assert c.capture('0', c.INDEXES['cpi'], budget=budget, archive=tmp_path)[1] == b''
    assert len(calls) == 5
    with pytest.raises(ProbeHalted):
        c.capture('sixth', c.INDEXES['cpi'], budget=budget, archive=tmp_path)
    assert not (tmp_path / 'sixth').exists()


def test_response_limit_rejects_oversize_before_persisting(tmp_path, monkeypatch):
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def iter_content(self, size): yield b'123456'
    monkeypatch.setattr(c.requests, 'get', lambda *args, **kwargs: Response())
    with pytest.raises(ValueError, match='bounded'):
        c.capture('large', c.INDEXES['cpi'], budget=ProbeBudget(), archive=tmp_path, limit=5)
    assert not (tmp_path / 'large').exists()
