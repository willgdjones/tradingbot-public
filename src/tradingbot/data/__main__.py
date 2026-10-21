"""Run with uv run python -m tradingbot.data --help."""

import argparse
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from .transport import FetchError, RetryingGetter


def timestamp(value: str) -> int:
    try:
        result = int(value)
    except ValueError:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise argparse.ArgumentTypeError("use Unix seconds or an ISO timestamp") from error
        if parsed.tzinfo is None:
            raise argparse.ArgumentTypeError("timestamp needs an explicit UTC offset")
        result = int(parsed.timestamp())
    if result < 0:
        raise argparse.ArgumentTypeError("timestamp must not precede the Unix epoch")
    return result


FILTERS = {
    "kalshi": {
        "markets": {"series", "ticker"}, "trades": {"ticker", "start", "end"},
        "events": {"series"}, "series": set(), "series-fees": {"series"},
        "event-fees": {"event"},
    },
    "polymarket-us": {
        "markets": {"slug", "closed", "category"}, "prices": {"slug", "start", "end"},
        "settlement": {"slug"},
    },
    "polymarket-intl": {
        "markets": {"slug", "closed"}, "events": {"slug", "closed"},
        "prices": {"token", "start", "end", "bucket_seconds"},
        "trades": {"condition"}, "resolutions": {"condition"},
    },
}


def main():
    parser = argparse.ArgumentParser(description="Public history to raw Parquet; no DB writes or trading.")
    parser.add_argument("venue", choices=list(FILTERS))
    parser.add_argument("kind", help="kalshi: markets/trades/events/series/series-fees/event-fees; "
                        "polymarket-us: markets/prices/settlement; "
                        "polymarket-intl: markets/events/prices/trades/resolutions")
    parser.add_argument("--output", type=Path, default=Path("data"))
    parser.add_argument("--run", required=True, help="Snapshot name. Same name+query resumes; new name refreshes.")
    for name in ("series", "ticker", "event", "slug", "token", "condition", "category"):
        parser.add_argument("--" + name)
    parser.add_argument("--closed", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--start", type=timestamp)
    parser.add_argument("--end", type=timestamp)
    parser.add_argument("--bucket-seconds", type=int, help="International price sampling resolution")
    parser.add_argument("--page-size", type=int, default=1000)
    parser.add_argument("--max-pages", type=int, help="Bound each endpoint this invocation; rerun to resume.")
    args = parser.parse_args()
    if args.kind not in FILTERS[args.venue]:
        parser.error(f"{args.venue} does not support {args.kind}")
    allowed = FILTERS[args.venue][args.kind]
    for name in ("series", "ticker", "event", "slug", "token", "condition", "category", "closed",
                 "start", "end", "bucket_seconds"):
        if getattr(args, name) is not None and name not in allowed:
            parser.error(f"--{name.replace('_', '-')} is not supported for {args.venue} {args.kind}")
    load_dotenv(override=False)  # No credentials consumed; never display environment values.
    if args.venue == "kalshi":
        from .kalshi import KalshiPublic as Client, download
    elif args.venue == "polymarket-us":
        from .polymarket import USPublic as Client, download_us as download
    else:
        from .polymarket import InternationalPublic as Client, download_international as download
    client = Client()
    try:
        filters = {name: getattr(args, name) for name in allowed}
        progress = download(args.output, args.run, RetryingGetter(client), args.kind,
                            page_size=args.page_size, max_pages=args.max_pages, **filters)
        for item in progress:
            print(json.dumps(asdict(item), default=str))
    except (ValueError, FetchError, BlockingIOError) as error:
        parser.exit(1, f"Download stopped; valid checkpoints retained: {error}\n")
    finally:
        client.close()


if __name__ == "__main__":
    main()
