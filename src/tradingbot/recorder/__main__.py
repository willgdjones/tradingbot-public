"""Run the live recorder: ``uv run python -m tradingbot.recorder --slug SLUG ...``.

Requires ``POLYMARKET_US_KEY_ID`` / ``POLYMARKET_US_SECRET`` in ``.env`` (the
market websocket is authenticated) and ``DATABASE_URL`` for the hypertables.
Writes only ``quotes`` / ``trades`` and the incident log; it never places orders.
"""

from __future__ import annotations

import argparse
import asyncio

from dotenv import load_dotenv

from ..config import get_settings
from ..db import enums
from ..db.session import SessionLocal
from ..risk.engine import RiskEngine
from .recorder import MarketDataRecorder
from .store import DbSink, resolve_subscriptions


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Record live Polymarket US order book and trades into TimescaleDB.",
    )
    parser.add_argument(
        "--slug", action="append", dest="slugs", metavar="SLUG", required=True,
        help="Market slug to record. Repeat for several markets.",
    )
    parser.add_argument(
        "--lite", action="store_true",
        help="Subscribe to best-price (lite) book updates instead of full depth.",
    )
    parser.add_argument(
        "--tick-seconds", type=float, default=1.0,
        help="Keep-alive / commit cadence in seconds (default 1.0).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    load_dotenv(override=False)
    settings = get_settings()
    if not settings.polymarket_us_key_id or not settings.polymarket_us_secret:
        _build_parser().error(
            "POLYMARKET_US_KEY_ID and POLYMARKET_US_SECRET must be set in .env "
            "(the market websocket is authenticated)"
        )

    from polymarket_us.websocket.markets import MarketsWebSocket

    session = SessionLocal()
    try:
        subscriptions = resolve_subscriptions(session, args.slugs)
        sink = DbSink(session, subscriptions)
        risk = RiskEngine(session)
        recorder = MarketDataRecorder(sink=sink, risk=risk, mode=enums.Mode.LIVE)

        def ws_factory():
            return MarketsWebSocket(
                key_id=settings.polymarket_us_key_id,
                secret_key=settings.polymarket_us_secret,
            )

        print(f"recording {len(subscriptions)} market(s): {', '.join(subscriptions)}")
        try:
            asyncio.run(
                recorder.run(
                    ws_factory=ws_factory,
                    slugs=list(args.slugs),
                    want_lite=args.lite,
                    tick_seconds=args.tick_seconds,
                )
            )
        except KeyboardInterrupt:
            print("stopping recorder")
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
