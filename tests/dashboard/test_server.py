"""Dashboard server smoke tests (real HTTP, ephemeral port, localhost)."""

from __future__ import annotations

import http.client
import threading

import pytest

from tradingbot.dashboard.server import make_server


@pytest.fixture()
def live_server():
    httpd = make_server("127.0.0.1", 0)  # port 0 -> ephemeral
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address[0], httpd.server_address[1]
    try:
        yield host, port
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _get(host, port, path):
    conn = http.client.HTTPConnection(host, port, timeout=10)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        return resp.status, resp.headers.get("Content-Type", ""), resp.read()
    finally:
        conn.close()


def test_healthz(live_server):
    host, port = live_server
    status, ctype, body = _get(host, port, "/healthz")
    assert status == 200
    assert b"ok" in body


def test_index_html(live_server):
    host, port = live_server
    status, ctype, body = _get(host, port, "/")
    assert status == 200
    assert "text/html" in ctype
    assert b"tradingbot dashboard" in body


def test_api_snapshot_json(live_server):
    host, port = live_server
    status, ctype, body = _get(host, port, "/api/snapshot?mode=live")
    assert status == 200
    assert "application/json" in ctype
    import json

    data = json.loads(body)
    assert data["mode"] == "live"
    assert "leaderboard" in data


def test_unknown_path_404(live_server, monkeypatch):
    import tradingbot.dashboard.server as server

    monkeypatch.setattr(server, "dashboard_snapshot", lambda *a, **k: pytest.fail("404 built a snapshot"))
    host, port = live_server
    status, _, _ = _get(host, port, "/nope")
    assert status == 404


def test_write_method_rejected(live_server):
    host, port = live_server
    conn = http.client.HTTPConnection(host, port, timeout=10)
    try:
        conn.request("POST", "/", body=b"{}")
        resp = conn.getresponse()
        assert resp.status == 405
    finally:
        conn.close()
