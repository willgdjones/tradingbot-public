"""Read-only dashboard HTTP server (localhost only).

Stdlib ``http.server`` — no web framework, no new dependencies. It binds to
127.0.0.1, serves only ``GET`` (any write method returns 405), and never commits
to the database. Run it with::

    uv run python -m tradingbot.dashboard            # http://127.0.0.1:8787
    DASHBOARD_PORT=9000 uv run python -m tradingbot.dashboard
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from ..db import enums
from ..db.session import session_scope
from .render import render_dashboard
from .reports import dashboard_snapshot

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787


def _json_default(obj):
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"Not JSON serializable: {type(obj)!r}")


def _resolve_mode(query: dict[str, list[str]]) -> str:
    mode = (query.get("mode", [enums.Mode.LIVE])[0]).lower()
    return mode if mode in enums.Mode.ALL else enums.Mode.LIVE


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "tradingbot-dashboard"

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # Read-only, localhost: forbid caching so refresh always shows fresh data.
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        path = parsed.path.rstrip("/") or "/"

        if path == "/healthz":
            self._send(200, b'{"status":"ok"}', "application/json")
            return

        if path not in ("/", "/api/snapshot"):
            self._send(404, b'{"error":"not found"}', "application/json")
            return

        mode = _resolve_mode(query)
        try:
            with session_scope() as session:
                snapshot = dashboard_snapshot(session, mode=mode)
        except Exception as exc:  # keep the dashboard resilient to DB hiccups
            msg = json.dumps({"error": str(exc)}).encode()
            self._send(503, msg, "application/json")
            return

        if path == "/api/snapshot":
            self._send(200, json.dumps(snapshot, default=_json_default).encode(), "application/json")
        else:
            self._send(200, render_dashboard(snapshot).encode("utf-8"), "text/html; charset=utf-8")

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def _reject_write(self) -> None:
        self._send(405, b'{"error":"read-only dashboard"}', "application/json")

    do_POST = do_PUT = do_DELETE = do_PATCH = _reject_write  # type: ignore[assignment]

    def log_message(self, *args) -> None:  # silence default stderr access log
        pass


def make_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    """Create (but do not start) the dashboard server bound to localhost."""
    return ThreadingHTTPServer((host, port), DashboardHandler)


def serve(host: str | None = None, port: int | None = None) -> None:
    host = host or os.environ.get("DASHBOARD_HOST", DEFAULT_HOST)
    port = port or int(os.environ.get("DASHBOARD_PORT", DEFAULT_PORT))
    httpd = make_server(host, port)
    print(f"tradingbot dashboard (read-only) on http://{host}:{port}  (Ctrl-C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
