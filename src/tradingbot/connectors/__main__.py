"""Read-only Alpaca paper connectivity check. No CLI order/account writes."""

import argparse
from datetime import date, datetime, timezone
import json

from tradingbot.risk.limits import STALE_DATA_MAX_SECONDS

from .alpaca_api import AlpacaPaperAPI
from .cash import MarketSession, NEW_YORK, timestamp


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="Read account, asset, quote and settlement calendar")
    check.add_argument("--symbol", default="SPY")
    check.add_argument("--date", type=date.fromisoformat)
    args = parser.parse_args()
    api = AlpacaPaperAPI.from_env()
    try:
        now = datetime.now(timezone.utc)
        account, asset = api.account(), api.asset(args.symbol)
        quote = api.quote(args.symbol)
        sessions = [MarketSession.from_api(row) for row in api.calendar(args.date or now.astimezone(NEW_YORK).date())]
        age = (now - timestamp(quote["t"])).total_seconds()
        print(json.dumps({
            "endpoint": "paper", "account_active": account.get("status") == "ACTIVE",
            "trading_blocked": account.get("trading_blocked"),
            "buying_power_present": "buying_power" in account,
            "symbol": args.symbol, "tradable": asset.get("tradable"),
            "fractionable": asset.get("fractionable"), "quote_timestamp": quote["t"],
            "quote_fresh": 0 <= age <= STALE_DATA_MAX_SECONDS,
            "calendar": [{"date": s.trade_date.isoformat(), "settlement_date": s.settlement_date.isoformat()}
                         for s in sessions],
        }, indent=2))
    except Exception as exc:
        # SDK exceptions can carry authenticated request objects; do not print them.
        raise SystemExit(f"Paper check failed ({type(exc).__name__})") from None
    finally:
        api.close()


if __name__ == "__main__":
    main()
