"""US display-price history and international research history, kept separate."""

from urllib.parse import quote, urlsplit

import httpx
from polymarket.clients._transport import SyncTransport, TransportOptions
from polymarket.errors import RateLimitError, RequestRejectedError, TransportError
from polymarket_us import PolymarketUS
from polymarket_us.errors import APIConnectionError, APIStatusError, APITimeoutError

from .archive import RawArchive, Request, canonical, records_in, single_page
from .transport import FetchError

US = "https://gateway.polymarket.us"
GAMMA = "https://gamma-api.polymarket.com"
DATA = "https://data-api.polymarket.com"


class USPublic:
    """Use the official SDK, capturing text before its JSON float conversion."""

    def __init__(self):
        self.client = PolymarketUS(max_retries=0, timeout=30)
        self.body = None
        # The SDK exposes JSON only. This small transport hook preserves wire text.
        self.client._http.event_hooks["response"].append(self._capture)

    def _capture(self, response: httpx.Response):
        response.read()
        self.body = response.text

    def __call__(self, request: Request) -> str:
        if not request.url.startswith(US + "/v1/"):
            raise ValueError("unexpected Polymarket US public URL")
        self.body = None
        try:
            self.client.get(request.url[len(US):], query=request.params, authenticated=False)
        except APIStatusError as error:
            raise FetchError(error.status_code, error.response.headers.get("retry-after")) from None
        except (APIConnectionError, APITimeoutError):
            raise FetchError(None) from None
        if self.body is None:
            raise ValueError("SDK raw-response hook did not run")
        return self.body

    def close(self):
        self.client.close()


class InternationalPublic:
    """Official py-sdk raw transports; no signer, wallet or secure client."""

    def __init__(self):
        options = TransportOptions(timeout=httpx.Timeout(30))
        self.clients = {base: SyncTransport(base_url=base, options=options)
                        for base in (GAMMA, DATA)}

    def __call__(self, request: Request) -> str:
        parts = urlsplit(request.url)
        base = f"{parts.scheme}://{parts.netloc}"
        if base not in self.clients or parts.query or parts.fragment:
            raise ValueError("unexpected Polymarket international public URL")
        try:
            return self.clients[base].get_bytes(parts.path, params=request.params).decode("utf-8")
        except RateLimitError as error:
            raise FetchError(429, str(error.retry_after) if error.retry_after is not None else None) from None
        except RequestRejectedError as error:
            raise FetchError(error.status, str(error.retry_after) if error.retry_after is not None else None) from None
        except TransportError:
            raise FetchError(None) from None

    def close(self):
        for client in self.clients.values():
            client.close()


def gamma_pages(key):
    def advance(request, payload):
        rows = records_in(payload, key)
        cursor = payload.get("next_cursor")  # Gamma omits it on the terminal page.
        if cursor is not None and (not isinstance(cursor, str) or not cursor):
            raise ValueError("invalid Gamma next_cursor")
        params = {**request.params, "after_cursor": cursor}
        return len(rows), Request(request.url, params) if cursor else None
    return advance


def data_pages(request, payload):
    rows = records_in(payload, "data")
    pagination = payload.get("pagination")
    if not isinstance(pagination, dict) or "next_cursor" not in pagination:
        raise ValueError("missing Data API pagination.next_cursor")
    cursor = pagination["next_cursor"]
    if cursor is not None and (not isinstance(cursor, str) or not cursor):
        raise ValueError("invalid Data API next_cursor")
    return len(rows), Request(request.url, {**request.params, "cursor": cursor}) if cursor else None


def us_offset_pages(request, payload):
    rows = records_in(payload, "markets")
    # Continue until an EMPTY page, not a short one: the API may cap page size.
    if not rows:
        return 0, None
    params = {**request.params, "offset": request.params["offset"] + len(rows)}
    return len(rows), Request(request.url, params)


def _us_page_key(payload):
    rows = records_in(payload, "markets")
    if not rows:
        return None
    if any("id" not in row for row in rows):
        raise ValueError("market page is missing IDs")
    return canonical(sorted(str(row["id"]) for row in rows))


def _single_object(required):
    def advance(request, payload):
        if not isinstance(payload, dict) or not all(key in payload for key in required):
            raise ValueError("invalid market details/settlement response")
        return 1, None
    return advance


def _range(start, end):
    if (start is None) != (end is None) or (start is not None and (start < 0 or start >= end)):
        raise ValueError("supply both start and end, with 0 <= start < end")


def _windows(advance, *, start_key, end_key, final_end, window_seconds):
    def next_page(request, payload):
        count, next_request = advance(request, payload)
        if next_request is not None:
            return count, next_request
        until = request.params[end_key]
        if until >= final_end:
            return count, None
        params = {k: v for k, v in request.params.items() if k != "cursor"}
        params.update({start_key: until, end_key: min(until + window_seconds, final_end)})
        return count, Request(request.url, params)
    return next_page


def download_us(root, run, get, kind, *, slug=None, closed=None, category=None, start=None,
                end=None, page_size=100, max_pages=None):
    if not 1 <= page_size <= 1000:
        raise ValueError("US page size must be 1..1000")
    _range(start, end)
    scope = None
    if kind == "markets":
        params = {"limit": page_size, "offset": 0, "orderBy": ["id"], "orderDirection": "asc"}
        if slug:
            params["slug"] = [slug]
        if closed is not None:
            params["closed"] = closed
        if category:
            params["categories"] = [category]
        request = Request(US + "/v1/markets", params)
        advance, dataset = us_offset_pages, "markets"
        semantics = "market metadata snapshot; offset pagination; not point-in-time consistent"
    elif kind == "settlement":
        if not slug:
            raise ValueError("US settlement requires --slug")
        request = Request(US + f"/v1/markets/{quote(slug, safe='')}/settlement", {})
        advance, dataset = _single_object(("slug", "settlement")), "settlements"
        semantics = "US settlement price returned by venue; 404 is not settled or unknown"
    elif kind == "prices":
        if not slug:
            raise ValueError("US prices requires --slug")
        params = {"symbol": slug}
        advance = single_page("history")
        if start is None:
            params.update(fixedInterval="INTERVAL_ALL", fidelity=180)
        else:
            params.update({"timestamp.startTimestamp": start,
                           "timestamp.endTimestamp": min(start + 86400, end), "fidelity": 1})
            scope = {"start": start, "end": end}
            advance = _windows(advance, start_key="timestamp.startTimestamp",
                               end_key="timestamp.endTimestamp", final_end=end, window_seconds=86400)
        request = Request(US + "/v1/price-history", params)
        dataset = "display_prices"
        semantics = ("US book-derived Yes ask / No one-minus-bid display prices, NOT trades; "
                     "ALL is 3-hour/daily sampled; custom windows <=24h; empty may mean unknown symbol")
    else:
        raise ValueError("US supports markets, prices and settlement; no public historical trade tape is documented")
    return [RawArchive(root, "polymarket_us", dataset, run, request, semantics=semantics, scope=scope)
            .capture(get, advance, max_pages=max_pages,
                     page_key=_us_page_key if kind == "markets" else None)]


def download_international(root, run, get, kind, *, slug=None, closed=None,
                           token=None, condition=None, start=None, end=None,
                           bucket_seconds=None, page_size=1000, max_pages=None):
    if not 1 <= page_size <= 1000:
        raise ValueError("international page size must be 1..1000")
    _range(start, end)
    scope = None
    if kind in {"markets", "events"}:
        params = {"limit": page_size}
        if slug:
            params["slug"] = slug
        if closed is not None:
            params["closed"] = closed
        request = Request(GAMMA + f"/{kind}/keyset", params)
        advance, dataset = gamma_pages(kind), kind
        semantics = "international research metadata snapshot; raw Gamma records including nonbinary markets"
    elif kind == "trades":
        if not condition:
            raise ValueError("international trades requires --condition (condition ID)")
        if start is not None:
            raise ValueError("market-wide public trades do not support historical time bounds")
        request = Request(DATA + "/v2/trades", {"condition": condition, "limit": page_size,
                                                "taker_only": False})
        advance, dataset = data_pages, "trades_recent"
        semantics = "international recent public trade feed; NOT a complete historical tape; no time filtering"
    elif kind == "resolutions":
        if not condition:
            raise ValueError("resolutions requires --condition (condition ID)")
        request = Request(DATA + "/v2/resolutions", {"condition": condition})
        advance, dataset = single_page("data"), "resolutions"
        semantics = "international research resolution records / payouts returned by venue"
    elif kind == "prices":
        if not token:
            raise ValueError("international prices requires --token (outcome token ID, not condition ID)")
        params = {"token_id": token, "limit": page_size}
        advance = data_pages
        if bucket_seconds is not None:
            minimum = 600 if start is None else 60
            if not minimum <= bucket_seconds <= 86400:
                raise ValueError(f"bucket_seconds must be {minimum}..86400 for this range")
            params["bucket_seconds"] = bucket_seconds
        if start is None:
            params["interval"] = "max"
        else:
            params.update(start=start, end=min(start + 15 * 86400, end))
            scope = {"start": start, "end": end}
            advance = _windows(advance, start_key="start", end_key="end", final_end=end,
                               window_seconds=15 * 86400)
        request = Request(DATA + "/v2/prices-history", params)
        dataset = "price_history"
        semantics = ("international sampled historical prices in USDC; NOT trades; "
                     "max defaults to 12-hour buckets; finer full-history widths may cover only last 30 days")
    else:
        raise ValueError("unknown international dataset")
    return [RawArchive(root, "polymarket_intl", dataset, run, request, semantics=semantics, scope=scope)
            .capture(get, advance, max_pages=max_pages)]
