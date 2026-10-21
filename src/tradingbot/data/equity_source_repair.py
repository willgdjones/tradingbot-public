"""Source-only equity diagnostics. These functions never admit a backtest dataset."""
from datetime import datetime, timedelta
from decimal import Decimal


def primary_closing_price(trades: list[dict], closes_at: datetime, exchange: str) -> Decimal:
    """Require an unambiguous primary-venue closing print in the fixed 10s window.

    CTA condition 6 is a market-center closing trade; M is its official close.
    The caller must independently identify the listing exchange. Other venues,
    ordinary last trades and mixed extended-hours conditions are not substitutes.
    Duplicate dissemination is harmless only when the observed price agrees.
    """
    return _primary_price(trades, closes_at, exchange, {'6', 'M'})


def primary_opening_price(trades: list[dict], opens_at: datetime, exchange: str) -> Decimal:
    """Require a primary O/Q opening print in the same fixed ten-second window.

    O is the market-center opening trade; Q is its official opening report.
    An ordinary first consolidated trade may be from a different exchange and
    is not substituted for the independently identified primary opening print.
    """
    return _primary_price(trades, opens_at, exchange, {'O', 'Q'})


def _primary_price(trades, session_at, exchange, allowed):
    if session_at.tzinfo is None or not exchange:
        raise ValueError('timezone-aware session boundary and primary exchange required')
    prices = set()
    for trade in trades:
        if trade.get('x') != exchange:
            continue
        conditions = set(trade.get('c', [])) - {' ', '@'}
        if not conditions or not conditions <= allowed:
            continue
        when = datetime.fromisoformat(trade['t'].replace('Z', '+00:00'))
        if when.tzinfo is None or not session_at <= when < session_at + timedelta(seconds=10):
            continue
        price = Decimal(str(trade['p']))
        if not price.is_finite() or price <= 0:
            raise ValueError('invalid primary auction price')
        prices.add(price)
    if len(prices) != 1:
        raise ValueError('missing or conflicting primary auction prices')
    return prices.pop()
