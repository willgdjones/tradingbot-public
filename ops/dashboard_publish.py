#!/usr/bin/env python3
"""Publish a password-protected static snapshot of the local dashboard.

Renders the dashboard for paper, live and backtest modes into one page,
encrypts it with the weekly page's StatiCrypt pipeline and password, and
deploys it to its own Cloudflare Pages project. Run from the repository:

    ops/with-secrets uv run python ops/dashboard_publish.py [--deploy]
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent))
from weekly_report import ROOT, encrypt, publish  # noqa: E402

from tradingbot.dashboard.render import render_dashboard  # noqa: E402
from tradingbot.dashboard.reports import dashboard_snapshot  # noqa: E402
from tradingbot.db.session import SessionLocal  # noqa: E402

PROJECT = "tradingbot-dashboard"
MODES = ("paper", "live", "backtest")


def page(renders):
    """One static document: the first mode's head, every mode's body, no auto-refresh."""
    head = re.sub(r'<meta http-equiv="refresh"[^>]*>\n?', '', renders[0][1].split('<body>')[0])
    nav = ' · '.join(f'<a href="#{m}">{m}</a>' for m, _ in renders)
    sections = []
    for mode, html in renders:
        body = html.split('<body>', 1)[1].rsplit('</body>', 1)[0]
        body = body.replace(' · auto-refresh 30s', ' · static snapshot')
        sections.append(f'<section id="{mode}">{body}</section><hr>')
    return f'{head}<body>\n<div class="meta">modes: {nav}</div>\n{"".join(sections)}\n</body></html>'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--deploy', action='store_true')
    args = parser.parse_args()
    os.chdir(ROOT)
    os.umask(0o077)
    work = ROOT / 'data/dashboard'
    work.mkdir(parents=True, exist_ok=True)
    with (work / '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        values = dotenv_values(ROOT / '.env')
        password = values.get('WEEKLY_PAGE_PASSWORD')
        if not password:
            raise ValueError('WEEKLY_PAGE_PASSWORD is empty; run under ops/with-secrets')
        renders = []
        with SessionLocal() as session:
            session.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'))
            session.execute(text("SET LOCAL statement_timeout = '120s'"))
            for mode in MODES:
                renders.append((mode, render_dashboard(dashboard_snapshot(session, mode=mode))))
        output = work / 'site'
        digest = encrypt(page(renders), password, output)
        result = {'generated_at': datetime.now(timezone.utc).isoformat(), 'sha256': digest, 'encrypted': True}
        if args.deploy:
            result.update(publish(output, values, project=PROJECT))
        (work / 'last_run.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'Dashboard publish failed: {type(exc).__name__}. No unencrypted page was published.')
        raise SystemExit(1) from None
