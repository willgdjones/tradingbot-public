"""Kalshi public history for research. No account, signing, or trading methods."""

from urllib.parse import urlencode

import urllib3
from kalshi_python import ApiClient, Configuration
from kalshi_python.exceptions import ApiException

from .archive import RawArchive, Request, cursor_pages, single_page
from .transport import FetchError

BASE = "https://external-api.kalshi.com/trade-api/v2"


class KalshiPublic:
    def __init__(self):
        config = Configuration(host=BASE)
        config.retries = 0  # Retry/pacing is handled once, by RetryingGetter.
        self.client = ApiClient(config)

    def __call__(self, request: Request) -> str:
        if not request.url.startswith(BASE + "/"):
            raise ValueError("unexpected Kalshi public URL")
        try:
            response = self.client.call_api(
                "GET", request.url + ("?" + urlencode(request.params) if request.params else ""),
                header_params={"Accept": "application/json"}, _request_timeout=(10, 30),
            )
            response.read()
            if response.status != 200:
                raise FetchError(response.status, response.getheader("Retry-After"))
            return response.data.decode("utf-8")
        except ApiException as error:
            raise FetchError(error.status or None, (error.headers or {}).get("Retry-After")) from None
        except urllib3.exceptions.HTTPError:
            raise FetchError(None) from None

    def close(self):
        self.client.rest_client.pool_manager.clear()


def download(root, run, get, kind, *, series=None, ticker=None, event=None, start=None,
             end=None, page_size=1000, max_pages=None):
    if not 1 <= page_size <= 1000:
        raise ValueError("Kalshi page size must be 1..1000")
    if kind == "trades" and (start is None or end is None or start >= end):
        raise ValueError("trades require start < end (Unix seconds)")
    if kind == "markets" and ticker and series:
        raise ValueError("market ticker and series filters are mutually exclusive")
    jobs = []
    if kind in {"markets", "trades"}:
        # Save cutoff evidence but query BOTH tiers: no assumptions about archival time.
        def cutoff(request, payload):
            if not isinstance(payload, dict) or not all(
                isinstance(payload.get(k), str) for k in ("market_settled_ts", "trades_created_ts")
            ):
                raise ValueError("invalid Kalshi cutoff response")
            return 1, None
        jobs.append(("cutoff", Request(BASE + "/historical/cutoff", {}), cutoff))
        params = {"limit": page_size}
        if kind == "markets":
            if series:
                params["series_ticker"] = series
            if ticker:
                params["tickers"] = ticker
            paths = ["/markets", "/historical/markets"]
        else:
            params.update(min_ts=start, max_ts=end)
            if ticker:
                params["ticker"] = ticker
            paths = ["/markets/trades", "/historical/trades"]
        for path in paths:
            tier = "historical" if "/historical/" in path else "recent"
            jobs.append((kind + "_" + tier, Request(BASE + path, params), cursor_pages(kind)))
    elif kind == "events":
        params = {"limit": min(page_size, 200)}
        if series:
            params["series_ticker"] = series
        jobs.append((kind, Request(BASE + "/events", params), cursor_pages(kind)))
    elif kind == "series":
        jobs.append((kind, Request(BASE + "/series", {}), single_page("series")))
    elif kind == "series-fees":
        params = {"show_historical": "true"}
        if series:
            params["series_ticker"] = series
        jobs.append((kind, Request(BASE + "/series/fee_changes", params), single_page("series_fee_change_arr")))
    elif kind == "event-fees":
        params = {"limit": page_size}
        if event:
            params["event_ticker"] = event
        jobs.append((kind, Request(BASE + "/events/fee_changes", params), cursor_pages("event_fee_changes")))
    else:
        raise ValueError("unknown Kalshi dataset")
    return [RawArchive(root, "kalshi", dataset, run, request,
                       semantics="public research snapshot; raw pages; deduplicate at load time")
            .capture(get, advance, max_pages=max_pages)
            for dataset, request, advance in jobs]
