"""Read-only, bounded free-IEX capture and point-in-time feature snapshots.

The recorder does not call models, create strategies, fund books or place orders.
Polling receipts never manufacture a fresh exchange timestamp. Bars have explicit
receipt-time revisions; downstream models can only see versions already known.
"""
from __future__ import annotations

import argparse
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import time
from zoneinfo import ZoneInfo

from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.trading.client import TradingClient
from requests.adapters import HTTPAdapter
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert

from tradingbot.config import get_settings
from tradingbot.db.iex_models import IexBar, IexRecorderHealth, IexSnapshot
from tradingbot.db.models import Incident, Instrument, Market, Quote, Venue
from tradingbot.db.session import SessionLocal, get_engine
from tradingbot.risk.limits import STALE_DATA_MAX_SECONDS

from .disk_budget import DATA_MAX_BYTES, DiskBudget, DiskBudgetExceeded, WRITE_HEADROOM

SYMBOLS = tuple("SPY QQQ IWM DIA XLK XLF XLE XLV XLI XLY XLP XLU XLB XLRE XLC GLD SLV TLT USO UNG "
                "AAPL MSFT NVDA AMZN GOOGL META TSLA AVGO JPM V UNH XOM LLY MA COST HD PG JNJ NFLX AMD".split())
NY = ZoneInfo("America/New_York")
MINUTE = timedelta(minutes=1)
QUARTER = timedelta(minutes=15)
POLL_SECONDS = 15
MAX_PAGES = 4
MAX_BODY_BYTES = 4_000_000
LOCK_ID = 0x4945583430
SOURCE = "alpaca-iex-intraday-v1"


def utc(value: str | datetime) -> datetime:
    value = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone required")
    return value.astimezone(UTC)


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def number(value, *, positive=False) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError("invalid number")
    result = Decimal(str(value))
    if not result.is_finite() or result < 0 or (positive and result == 0):
        raise ValueError("invalid number")
    return result


def minute_bar(payload: dict, observed_at: datetime) -> tuple[datetime, dict]:
    start = utc(payload["t"])
    if start.second or start.microsecond or start + MINUTE > observed_at:
        raise ValueError("incomplete or unaligned minute")
    values = {key: number(payload[key], positive=key in "ohlc") for key in ("o", "h", "l", "c", "v", "n")}
    if (values["l"] > min(values["o"], values["c"]) or
            values["h"] < max(values["o"], values["c"]) or values["h"] < values["l"] or
            values["v"] != values["v"].to_integral_value() or
            values["n"] != values["n"].to_integral_value()):
        raise ValueError("invalid OHLC or volume")
    values["vw"] = number(payload["vw"], positive=True)
    return start, {"t": start.isoformat(), **{key: str(value) for key, value in values.items()}}


def quote(payload: dict, observed_at: datetime) -> dict:
    stamp = utc(payload["t"])
    bid, ask = number(payload["bp"], positive=True), number(payload["ap"], positive=True)
    if stamp > observed_at or bid > ask:
        raise ValueError("future or crossed quote")
    return {"t": stamp.isoformat(), "bp": str(bid), "ap": str(ask),
            "bs": str(number(payload["bs"])), "as": str(number(payload["as"])),
            "size_unit": "round_lots", "source_timestamp": payload["t"], "observed_at": observed_at.isoformat()}


class _ReadOnlyAdapter(HTTPAdapter):
    def send(self, request, **kwargs):
        if request.method != "GET":
            raise ValueError("IEX capture permits GET only")
        kwargs["timeout"] = (5, 15)
        return super().send(request, **kwargs)


class IexAPI:
    """Official SDK with exact JSON numbers, GET-only transport and no retries."""
    def __init__(self):
        settings = get_settings()
        if not settings.alpaca_paper_key or not settings.alpaca_paper_secret:
            raise ValueError("paper credentials missing")
        self.data = StockHistoricalDataClient(settings.alpaca_paper_key, settings.alpaca_paper_secret, raw_data=True)
        self.trading = TradingClient(settings.alpaca_paper_key, settings.alpaca_paper_secret, paper=True, raw_data=True)
        self.body = None
        for client in (self.data, self.trading):
            client._retry = 0
            client._session.mount("https://", _ReadOnlyAdapter(max_retries=0))
            client._session.hooks["response"].append(self._capture)

    def _capture(self, response, *args, **kwargs):
        if response.status_code != 200 or len(response.content) > MAX_BODY_BYTES:
            raise ValueError("IEX response failed or exceeded bound")
        self.body = response.text
        return response

    def _get(self, client, path, params=None):
        self.body = None
        client.get(path, params or {})
        if self.body is None:
            raise ValueError("missing captured response")
        return json.loads(self.body, parse_float=str)

    def calendar(self, day: date):
        return self._get(self.trading, "/calendar", {"start": day.isoformat(), "end": day.isoformat()})

    def asset(self, symbol):
        if symbol not in SYMBOLS:
            raise ValueError("symbol outside universe")
        return self._get(self.trading, "/assets/" + symbol)

    def quotes(self):
        body = self._get(self.data, "/stocks/quotes/latest", {"symbols": ",".join(SYMBOLS), "feed": "iex"})
        if not isinstance(body.get("quotes"), dict) or set(body["quotes"]) - set(SYMBOLS):
            raise ValueError("malformed quote response")
        return body["quotes"]

    def bars(self, start, end):
        if not start < end or end - start > timedelta(hours=7):
            raise ValueError("unbounded bar request")
        params = {"symbols": ",".join(SYMBOLS), "timeframe": "1Min", "feed": "iex",
                  "adjustment": "raw", "asof": "-", "sort": "asc", "limit": 10000,
                  "start": start.isoformat(), "end": (end - timedelta(microseconds=1)).isoformat()}
        result, seen = {}, set()
        for _ in range(MAX_PAGES):
            body = self._get(self.data, "/stocks/bars", params)
            if not isinstance(body.get("bars"), dict) or set(body["bars"]) - set(SYMBOLS):
                raise ValueError("malformed bar response")
            for symbol, rows in body["bars"].items():
                if not isinstance(rows, list):
                    raise ValueError("malformed bar rows")
                result.setdefault(symbol, []).extend(rows)
            if sum(map(len, result.values())) > 40 * 390:
                raise ValueError("bar count exceeds regular session")
            token = body["next_page_token"]
            if token is None:
                return result
            if not isinstance(token, str) or not token or token in seen:
                raise ValueError("repeated or invalid page token")
            seen.add(token)
            params["page_token"] = token
        raise ValueError("bar page limit reached")

    def close(self):
        for client in (self.data, self.trading):
            client._session.close()


def register_instruments(session, assets: dict) -> dict[str, int]:
    """Use broker asset IDs, matching the paper connector's reference identity."""
    venue = session.scalar(select(Venue).where(Venue.key == "alpaca").with_for_update())
    if venue is None:
        raise ValueError("existing Alpaca venue required")
    result = {}
    for symbol in SYMBOLS:
        asset = assets[symbol]
        if asset.get("symbol") != symbol or asset.get("class") != "us_equity" or not asset.get("id"):
            raise ValueError("invalid Alpaca asset identity")
        instrument = session.scalar(select(Instrument).where(
            Instrument.venue_id == venue.id, Instrument.external_id == asset["id"]))
        if instrument is None:
            market = session.scalar(select(Market).where(Market.venue_id == venue.id, Market.external_id == symbol))
            if market is None:
                market = Market(venue_id=venue.id, external_id=symbol, title=symbol, market_type="equity")
                session.add(market)
                session.flush()
            instrument = Instrument(venue_id=venue.id, market_id=market.id, external_id=asset["id"], symbol=symbol,
                                    instrument_type="equity", currency="USD", contract_multiplier=Decimal(1))
            session.add(instrument)
            session.flush()
        if instrument.symbol != symbol or instrument.instrument_type != "equity":
            raise ValueError("instrument identity conflict")
        result[symbol] = instrument.id
    return result


def bars_asof(session, *, symbol: str, start: datetime, end: datetime, known_before: datetime) -> list[IexBar]:
    """Latest known revision for each completed minute in [start,end)."""
    if symbol not in SYMBOLS:
        raise ValueError("symbol outside universe")
    rows = session.scalars(select(IexBar).where(
        IexBar.symbol == symbol, IexBar.bar_start >= start, IexBar.bar_start < end,
        IexBar.observed_at < known_before, IexBar.bar_start <= known_before - MINUTE,
    ).order_by(IexBar.bar_start, IexBar.observed_at.desc()))
    result = {}
    for row in rows:
        result.setdefault(row.bar_start, row)
    return list(result.values())


def store_bars(session, data: dict, observed_at: datetime, start: datetime, end: datetime) -> int:
    if set(data) - set(SYMBOLS):
        raise ValueError("symbol outside universe")
    existing = {}
    for row in session.scalars(select(IexBar).where(IexBar.bar_start >= start, IexBar.bar_start < end)
                              .order_by(IexBar.observed_at.desc())):
        existing.setdefault((row.symbol, row.bar_start), row.digest)
    rows, keys = [], set()
    for symbol, payloads in data.items():
        for payload in payloads:
            stamp, normalized = minute_bar(payload, observed_at)
            if not start <= stamp < end or (symbol, stamp) in keys:
                raise ValueError("out of window or duplicate bar")
            keys.add((symbol, stamp))
            checksum = digest(normalized)
            if existing.get((symbol, stamp)) != checksum:
                rows.append({"observed_at": observed_at, "symbol": symbol, "bar_start": stamp,
                             "payload": normalized, "digest": checksum})
    if rows:
        session.execute(insert(IexBar), rows)
    return len(rows)


def store_quotes(session, data: dict, observed_at: datetime, instruments: dict) -> dict:
    """Keep true quote event times. Invalid quotes are excluded per symbol."""
    states, fresh = {}, 0
    for symbol in SYMBOLS:
        try:
            normalized = quote(data[symbol], observed_at)
            stamp = utc(normalized["t"])
            age = (observed_at - stamp).total_seconds()
            # Do not insert stale quotes, even as alleged heartbeat evidence.
            if age > STALE_DATA_MAX_SECONDS:
                states[symbol] = {"status": "stale", "quote_ts": stamp.isoformat()}
                continue
            iid = instruments[symbol]
            prior = session.scalar(select(Quote).where(Quote.instrument_id == iid).order_by(Quote.time.desc(), Quote.id.desc()).limit(1))
            metadata = {"source": SOURCE, "feed": "iex", **normalized}
            # Include original ns timestamp in comparison: DB timestamps have microseconds.
            if (prior is None or stamp > prior.time or
                    (stamp == prior.time and any((prior.metadata_ or {}).get(k) != normalized[k]
                     for k in ("source_timestamp", "bp", "ap", "bs", "as")))):
                bid, ask = Decimal(normalized["bp"]), Decimal(normalized["ap"])
                session.add(Quote(time=stamp, instrument_id=iid, bid=bid, ask=ask,
                                  # Alpaca sizes are round lots, not share quantities.
                                  # Preserve raw units in metadata instead of inventing a conversion.
                                  mid=(bid + ask) / 2, metadata_=metadata))
            states[symbol] = {"status": "fresh", "quote_ts": stamp.isoformat()}
            fresh += 1
        except (KeyError, TypeError, ValueError, ArithmeticError):
            states[symbol] = {"status": "missing_or_invalid"}
    return {"observed_at": observed_at.isoformat(), "fresh_symbols": fresh, "symbols": states}


def aggregate(rows: list[IexBar], start: datetime, end: datetime) -> dict:
    expected = [start + i * MINUTE for i in range(int((end - start) / MINUTE))]
    present = {row.bar_start for row in rows}
    missing = [stamp.isoformat() for stamp in expected if stamp not in present]
    result = {"start": start.isoformat(), "end": end.isoformat(), "complete": not missing,
              "missing_minutes": missing, "minute_count": len(rows),
              "revisions": [{"bar_start": utc(row.bar_start).isoformat(), "observed_at": utc(row.observed_at).isoformat(),
                             "digest": row.digest} for row in rows], "ohlcv": None}
    if rows:
        volume = sum((Decimal(row.payload["v"]) for row in rows), Decimal(0))
        weighted = sum((Decimal(row.payload["v"]) * Decimal(row.payload["vw"]) for row in rows), Decimal(0))
        result["ohlcv"] = {"o": rows[0].payload["o"], "c": rows[-1].payload["c"],
                           "h": str(max(Decimal(row.payload["h"]) for row in rows)),
                           "l": str(min(Decimal(row.payload["l"]) for row in rows)),
                           "v": str(volume), "vw": str(weighted / volume) if volume else None,
                           "n": str(sum(Decimal(row.payload["n"]) for row in rows))}
    return result


def snapshot_boundary(now: datetime, opening: datetime, closing: datetime) -> datetime | None:
    elapsed = now - opening
    if elapsed < QUARTER:
        return None
    boundary = opening + (elapsed // QUARTER) * QUARTER
    # Allow a single near-boundary observation, never backdated startup replay.
    if boundary > closing or not timedelta(seconds=5) <= now - boundary <= timedelta(seconds=90):
        return None
    return boundary


def create_snapshots(session, *, boundary: datetime, observed_at: datetime, opening: datetime, instruments: dict) -> int:
    if observed_at <= boundary or boundary - opening < QUARTER:
        raise ValueError("incomplete snapshot interval")
    count = 0
    for symbol in SYMBOLS:
        if session.get(IexSnapshot, (boundary, symbol)) is not None:
            continue
        rows = bars_asof(session, symbol=symbol, start=opening, end=boundary, known_before=observed_at)
        intervals = []
        start = opening
        while start + QUARTER <= boundary:
            end = start + QUARTER
            intervals.append(aggregate([row for row in rows if start <= row.bar_start < end], start, end))
            start = end
        q = session.scalar(select(Quote).where(Quote.instrument_id == instruments[symbol], Quote.time < observed_at)
                           .order_by(Quote.time.desc(), Quote.id.desc()).limit(1))
        current_quote = None
        if q is not None and (q.metadata_ or {}).get("source") == SOURCE:
            known = utc(q.metadata_["observed_at"])
            if known < observed_at and observed_at - q.time <= timedelta(seconds=STALE_DATA_MAX_SECONDS):
                current_quote = {"time": utc(q.time).isoformat(), "observed_at": known.isoformat(),
                                 "bid": str(q.bid), "ask": str(q.ask)}
        payload = {"source": SOURCE, "feed": "iex", "symbol": symbol, "instrument_id": instruments[symbol],
                   "session_open": opening.isoformat(), "boundary": boundary.isoformat(),
                   "observed_at": observed_at.isoformat(), "intervals": intervals, "quote": current_quote}
        session.add(IexSnapshot(boundary=boundary, symbol=symbol, observed_at=observed_at, payload=payload, digest=digest(payload)))
        count += 1
    session.flush()
    return count


def load_snapshot(session, symbol: str, *, decision_at: datetime, boundary: datetime | None = None) -> dict | None:
    """Latest current-session feature input; this is never an execution quote."""
    if symbol not in SYMBOLS:
        raise ValueError("symbol outside universe")
    query = select(IexSnapshot).where(IexSnapshot.symbol == symbol, IexSnapshot.observed_at < utc(decision_at))
    if boundary is not None:
        query = query.where(IexSnapshot.boundary == utc(boundary))
    row = session.scalar(query.order_by(IexSnapshot.boundary.desc()).limit(1))
    if row is None:
        return None
    if (utc(decision_at) - row.boundary > QUARTER + timedelta(seconds=90) or
            row.boundary.astimezone(NY).date() != utc(decision_at).astimezone(NY).date()):
        return None
    if digest(row.payload) != row.digest:
        raise ValueError("snapshot digest mismatch")
    return json.loads(canonical(row.payload))


class StorageBudget:
    def __init__(self, root=Path("data")):
        self.disk = DiskBudget(root)
        self.last_check = 0.0

    def check(self, session):
        self.disk.check_free()
        if time.monotonic() - self.last_check >= 60:
            snapshot = self.disk.check()
            db_bytes = session.scalar(text("SELECT pg_database_size(current_database())"))
            if snapshot.data_bytes + db_bytes + WRITE_HEADROOM >= DATA_MAX_BYTES:
                raise DiskBudgetExceeded("combined archive and database data budget exhausted")
            self.last_check = time.monotonic()


class Recorder:
    def __init__(self, session, api, instruments, *, now=lambda: datetime.now(UTC), budget=None):
        self.session, self.api, self.instruments, self.now = session, api, instruments, now
        self.budget = budget or StorageBudget()
        self.day = None
        self.hours = None
        self.last_bar_end = None

    def health(self, status, **extra):
        now = self.now()
        row = self.session.get(IexRecorderHealth, 1)
        state = {"source": SOURCE, "status": status, **extra}
        if status in {"disk_budget", "capture_failed"} and (row is None or row.state.get("status") != status):
            self.session.add(Incident(severity="warning", category="api_error", message="IEX recorder: " + status,
                                      details={"source": SOURCE, "code": status}))
        if row is None:
            self.session.add(IexRecorderHealth(id=1, updated_at=now, state=state))
        else:
            row.updated_at, row.state = now, state
        self.session.commit()
        return state

    def step(self):
        self.budget.check(self.session)
        now = self.now()
        day = now.astimezone(NY).date()
        if self.day != day:
            calendar = self.api.calendar(day)
            if not isinstance(calendar, list) or len(calendar) > 1:
                raise ValueError("invalid session calendar")
            hours = None
            if calendar:
                row = calendar[0]
                if row["date"] != day.isoformat():
                    raise ValueError("wrong calendar date")
                hours = tuple(datetime.fromisoformat(row["date"] + "T" + row[key]).replace(tzinfo=NY).astimezone(UTC)
                              for key in ("open", "close"))
                if not timedelta(0) < hours[1] - hours[0] <= timedelta(hours=6, minutes=30):
                    raise ValueError("invalid session length")
            self.day, self.hours, self.last_bar_end = day, hours, None
        now = self.now()
        if self.hours is None or not self.hours[0] <= now <= self.hours[1] + timedelta(seconds=90):
            return self.health("outside_regular_session")
        opening, closing = self.hours
        end = min(now.replace(second=0, microsecond=0), closing)
        bar_count = 0
        if end > opening and end != self.last_bar_end:
            start = opening if self.last_bar_end is None else max(opening, self.last_bar_end - timedelta(minutes=3))
            data = self.api.bars(start, end)
            received = self.now()
            self.budget.check(self.session)
            bar_count = store_bars(self.session, data, received, start, end)
            self.session.commit()
            self.last_bar_end = end
        data = self.api.quotes()
        received = self.now()
        self.budget.check(self.session)
        health = store_quotes(self.session, data, received, self.instruments)
        self.session.commit()
        observed_at = self.now()
        boundary = snapshot_boundary(observed_at, opening, closing)
        snapshots = 0 if boundary is None else create_snapshots(self.session, boundary=boundary,
            observed_at=observed_at, opening=opening, instruments=self.instruments)
        return self.health("ok" if health["fresh_symbols"] == len(SYMBOLS) else "partial_quotes",
                           quotes=health, bars_added=bar_count, snapshots_added=snapshots,
                           session_open=opening.isoformat(), session_close=closing.isoformat())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    api = None
    # Session-level advisory lock prevents duplicate daemons, including restarts.
    with get_engine().connect() as lock, SessionLocal() as session:
        if not lock.scalar(text("SELECT pg_try_advisory_lock(:id)"), {"id": LOCK_ID}):
            raise SystemExit("IEX recorder already running")
        lock.commit()  # Hold the session lock without an idle long transaction.
        try:
            api = IexAPI()
            budget = StorageBudget()
            budget.check(session)
            instruments = register_instruments(session, {symbol: api.asset(symbol) for symbol in SYMBOLS})
            session.commit()
            recorder = Recorder(session, api, instruments, budget=budget)
            while True:
                started = time.monotonic()
                try:
                    state = recorder.step()
                    if args.once:
                        print(canonical(state), flush=True)
                except Exception as exc:
                    session.rollback()
                    code = "disk_budget" if isinstance(exc, DiskBudgetExceeded) else "capture_failed"
                    # Exception bodies, headers and URLs may carry credentials.
                    print(canonical({"source": SOURCE, "status": code}), flush=True)
                    recorder.health(code)
                    if args.once or code == "disk_budget":
                        return 1
                if args.once:
                    return 0
                time.sleep(max(1, POLL_SECONDS - (time.monotonic() - started)))
        except Exception:
            print(canonical({"source": SOURCE, "status": "startup_failed"}), flush=True)
            return 1
        finally:
            if api is not None:
                api.close()
            lock.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": LOCK_ID})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
