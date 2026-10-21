"""Official alpaca-py transport, pinned to paper trading and raw decimal strings.

No account creation/configuration, transfer, withdrawal or live endpoint exists
in this adapter. Automatic HTTP retries are disabled, including POST retries.
"""

from datetime import date, datetime
from pathlib import Path
from typing import Protocol

from alpaca.data.enums import DataFeed
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest
from alpaca.trading.client import TradingClient
from dotenv import dotenv_values
from requests.adapters import HTTPAdapter


class PaperAPI(Protocol):
    def account(self) -> dict: ...
    def asset(self, symbol: str) -> dict: ...
    def calendar(self, day: date) -> list[dict]: ...
    def calendar_range(self, start: date, end: date) -> list[dict]: ...
    def quote(self, symbol: str) -> dict: ...
    def submit(self, payload: dict) -> dict: ...
    def order(self, client_order_id: str) -> dict: ...
    def cancel(self, venue_order_id: str) -> None: ...
    def activities(self, after: datetime, page_token: str | None = None) -> list[dict]: ...


class _TimeoutAdapter(HTTPAdapter):
    def send(self, request, **kwargs):
        if kwargs.get("timeout") is None:
            kwargs["timeout"] = (5, 20)
        return super().send(request, **kwargs)


class AlpacaPaperAPI:
    def __init__(self, key: str, secret: str) -> None:
        self._trading = TradingClient(key, secret, paper=True, raw_data=True)
        self._data = StockHistoricalDataClient(key, secret, raw_data=True)
        for client in (self._trading, self._data):
            client._retry = 0
            client._session.mount("https://", _TimeoutAdapter(max_retries=0))

    @classmethod
    def from_env(cls, path: str | Path = ".env") -> "AlpacaPaperAPI":
        values = dotenv_values(path)
        key, secret = values.get("ALPACA_PAPER_KEY"), values.get("ALPACA_PAPER_SECRET")
        if not key or not secret:
            raise ValueError("Set ALPACA_PAPER_KEY and ALPACA_PAPER_SECRET in .env")
        return cls(key, secret)

    def account(self) -> dict:
        return self._trading.get_account()

    def asset(self, symbol: str) -> dict:
        return self._trading.get_asset(symbol)

    def calendar(self, day: date) -> list[dict]:
        # The SDK Calendar model drops settlement_date; retain the raw response.
        return self.calendar_range(day, day)

    def calendar_range(self, start: date, end: date) -> list[dict]:
        return self._trading.get("/calendar", {"start": start.isoformat(), "end": end.isoformat()})

    def quote(self, symbol: str) -> dict:
        quotes = self._data.get_stock_latest_quote(
            StockLatestQuoteRequest(symbol_or_symbols=symbol, feed=DataFeed.IEX)
        )
        return quotes[symbol]

    def quotes(self, symbols: list[str]) -> dict[str, dict]:
        """One free-IEX request for a frozen universe/complete risk portfolio."""
        if not symbols:
            return {}
        return self._data.get_stock_latest_quote(
            StockLatestQuoteRequest(symbol_or_symbols=sorted(set(symbols)), feed=DataFeed.IEX)
        )

    def submit(self, payload: dict) -> dict:
        # OrderRequest coerces quantities to float. SDK raw POST preserves the
        # documented decimal-string wire representation for fractional shares.
        return self._trading.post("/orders", payload)

    def order(self, client_order_id: str) -> dict:
        return self._trading.get_order_by_client_id(client_order_id)

    def cancel(self, venue_order_id: str) -> None:
        self._trading.cancel_order_by_id(venue_order_id)

    def activities(self, after: datetime, page_token: str | None = None) -> list[dict]:
        params = {"after": after.isoformat(), "direction": "asc", "page_size": 100}
        if page_token is not None:
            params["page_token"] = page_token
        return self._trading.get("/account/activities/FILL", params)

    def close(self) -> None:
        self._trading._session.close()
        self._data._session.close()
