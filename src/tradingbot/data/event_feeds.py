"""Free, read-only event feeds with immutable receipt-time evidence.

Headlines are untrusted data. No article URLs are followed, no full stories are
requested and no text is interpreted as instructions. Provider timestamps never
backdate when this system knew a revision. No model or trading calls live here.
"""
from __future__ import annotations

import argparse
from datetime import UTC, date, datetime, timedelta
from html import unescape
from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path
import re
import time
import unicodedata
from urllib.parse import urlsplit

from alpaca.data.historical.news import NewsClient
import httpx
from requests.adapters import HTTPAdapter
from sqlalchemy import func, select, text

from tradingbot.config import get_settings
from tradingbot.db.event_models import EventFeedSnapshot
from tradingbot.db.models import Incident
from tradingbot.db.session import SessionLocal, get_engine
from tradingbot.risk.limits import API_ERROR_MAX_PER_MINUTE, API_ERROR_WINDOW_SECONDS
from .disk_budget import DiskBudgetExceeded
from .iex_intraday import NY, SYMBOLS, StorageBudget, canonical, digest, utc

BLS = "bls"
BEA = "bea"
FED = "fed"
EARNINGS = "nasdaq-earnings"
NEWS = "alpaca-news"
SOURCES = (NEWS, BLS, BEA, FED, EARNINGS)
BEA_URL = "https://apps.bea.gov/API/signup/release_dates.json"
FED_URL = "https://www.federalreserve.gov/json/calendar.json"
EARNINGS_URL = "https://api.nasdaq.com/api/calendar/earnings"
NEWS_URL = "https://data.alpaca.markets/v1beta1/news"
MAX_BYTES = 4_000_000
MAX_NEWS_PAGES = 20
EARNINGS_DAYS = 45
NEWS_POLL = timedelta(seconds=60)
CALENDAR_POLL = timedelta(hours=6)
NEWS_MAX_AGE = timedelta(seconds=120)
CALENDAR_MAX_AGE = timedelta(hours=26)
LOCK_ID = 0x45564E543031
ETF_SYMBOLS = frozenset(SYMBOLS[:20])


def validate_scope(source, scope):
    if source not in SOURCES:
        raise ValueError("unsupported source")
    if source == BLS:
        if not re.fullmatch(r"20[0-9]{2}-[0-9]{2}", scope):
            raise ValueError("invalid BLS month")
        date.fromisoformat(scope + "-01")
    elif source == EARNINGS:
        if date.fromisoformat(scope).isoformat() != scope:
            raise ValueError("invalid earnings date")
    elif scope != "all":
        raise ValueError("invalid source scope")


class _PlainText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def plain(value, limit=400):
    if not isinstance(value, str) or len(value) > 100_000:
        raise ValueError("invalid text")
    parser = _PlainText()
    parser.feed(unescape(value))
    value = "".join(c for c in "".join(parser.parts) if not unicodedata.category(c).startswith("C"))
    return " ".join(value.split())[:limit]


def next_month(day):
    return date(day.year + (day.month == 12), day.month % 12 + 1, 1)


def month_scopes(at):
    day = utc(at).astimezone(NY).date().replace(day=1)
    return (day.strftime("%Y-%m"), next_month(day).strftime("%Y-%m"))


def ny_time(day, clock):
    # Official schedules explicitly use Eastern Time; zoneinfo handles DST.
    clock = clock.strip().lower().replace("a.m.", "am").replace("p.m.", "pm")
    parsed = datetime.strptime(day.isoformat() + " " + clock, "%Y-%m-%d %I:%M %p")
    return parsed.replace(tzinfo=NY).astimezone(UTC)


class _BlsTable(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active, self.cell, self.row, self.rows = False, None, {}, []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "table" and attrs.get("class") == "release-list":
            self.active = True
        if self.active and tag == "tr":
            self.row = {}
        if self.active and tag == "td":
            self.cell = attrs.get("class")
            if self.cell in self.row:
                raise ValueError("duplicate BLS column")
            self.row[self.cell] = ""

    def handle_data(self, data):
        if self.active and self.cell is not None:
            self.row[self.cell] += data

    def handle_endtag(self, tag):
        if tag == "td":
            self.cell = None
        if self.active and tag == "tr" and self.row:
            self.rows.append(self.row)
        if tag == "table":
            self.active = False


def parse_bls(body, scope):
    table = _BlsTable()
    table.feed(body)
    if not table.rows:
        raise ValueError("missing BLS release table")
    events = []
    for row in table.rows:
        title = plain(row["desc-cell"])
        if not (title.startswith("Consumer Price Index") or title.startswith("Employment Situation")):
            continue
        day = datetime.strptime(row["date-cell"].strip(), "%A, %B %d, %Y").date()
        if day.strftime("%Y-%m") != scope:
            raise ValueError("wrong BLS month")
        kind = "cpi" if title.startswith("Consumer Price Index") else "jobs"
        events.append({"id": kind + ":" + day.isoformat(), "kind": kind, "title": title,
                       "event_at": ny_time(day, row["time-cell"]).isoformat()})
    if not {"cpi", "jobs"}.issubset({e["kind"] for e in events}):
        raise ValueError("BLS target releases missing")
    return events


def parse_bea(body):
    rows = json.loads(body)["Gross Domestic Product"]["release_dates"]
    if not isinstance(rows, list) or not rows or len(rows) > 1000:
        raise ValueError("BEA GDP dates missing")
    result = []
    for value in rows:
        stamp = utc(value)
        result.append({"id": "gdp:" + stamp.isoformat(), "kind": "gdp",
                       "title": "Gross Domestic Product", "event_at": stamp.isoformat()})
    return result


def parse_fed(body):
    records = json.loads(body)["events"]
    if not isinstance(records, list) or len(records) > 10_000:
        raise ValueError("invalid Fed events")
    events = []
    for row in records:
        if row.get("type") != "FOMC":
            continue
        title = plain(row["title"])
        kinds = {"fomc meeting": "fomc", "fomc minutes": "fomc_minutes",
                 "fomc press conference": "fomc_press_conference"}
        if title.lower() not in kinds:
            raise ValueError("unknown FOMC event")
        for value in row["days"].split(","):
            day = date.fromisoformat(row["month"] + "-" + value.strip().zfill(2))
            events.append({"id": kinds[title.lower()] + ":" + day.isoformat(), "kind": kinds[title.lower()],
                           "title": title, "event_at": ny_time(day, row["time"]).isoformat()})
    if not events:
        raise ValueError("Fed FOMC dates missing")
    return events


def parse_earnings(body, scope):
    data = json.loads(body)
    if data["status"]["rCode"] != 200 or not isinstance(data.get("data"), dict):
        raise ValueError("earnings source unavailable")
    data = data["data"]
    if datetime.strptime(data["asOf"], "%a, %b %d, %Y").date().isoformat() != scope:
        raise ValueError("wrong earnings date")
    rows = data["rows"]
    if rows is None:
        rows = []  # Nasdaq explicitly returns null rows on empty dated calendars.
    if not isinstance(rows, list) or len(rows) > 5000:
        raise ValueError("invalid earnings rows")
    buckets = {"time-pre-market": "before_open", "time-after-hours": "after_close",
               "time-not-supplied": "unknown"}
    result = []
    for row in rows:
        symbol = row["symbol"]
        if symbol not in SYMBOLS or symbol in ETF_SYMBOLS:
            continue
        result.append({"id": symbol + ":" + scope, "kind": "earnings", "symbol": symbol,
                       "event_date": scope, "time_bucket": buckets[row["time"]],
                       "precision": "day", "confirmed": False, "title": "Estimated earnings date"})
    return result


def parse_news(body, observed_at):
    data = json.loads(body)
    rows = data["news"]
    if not isinstance(rows, list) or len(rows) > 50:
        raise ValueError("invalid news page")
    result = []
    for row in rows:
        created, updated = utc(row["created_at"]), utc(row["updated_at"])
        if not created <= updated <= observed_at:
            raise ValueError("future or reversed news timestamps")
        if type(row["id"]) is not int or row["id"] <= 0 or not isinstance(row["symbols"], list):
            raise ValueError("invalid news identity")
        symbols = sorted(set(row["symbols"]).intersection(SYMBOLS))
        if not symbols:
            raise ValueError("news outside requested universe")
        headline = plain(row["headline"])
        if not headline:
            raise ValueError("empty headline")
        result.append({"id": str(row["id"]), "kind": "news", "symbols": symbols,
                       "created_at": created.isoformat(), "updated_at": updated.isoformat(),
                       "headline": headline, "untrusted": True})
    token = data["next_page_token"]
    if token is not None and (not isinstance(token, str) or not token or len(token) > 2048):
        raise ValueError("invalid news page token")
    return result, token


class _NewsAdapter(HTTPAdapter):
    def send(self, request, **kwargs):
        url = urlsplit(request.url)
        if (request.method != "GET" or url.scheme != "https" or url.netloc != "data.alpaca.markets"
                or url.path != "/v1beta1/news"):
            raise ValueError("news transport permits only the news GET endpoint")
        kwargs["timeout"] = (5, 15)
        return super().send(request, **kwargs)


class FeedAPI:
    """Public calendars and official Alpaca SDK, using existing paper keys only."""
    def __init__(self, root=Path("data/forward/events/raw"), *, now=lambda: datetime.now(UTC)):
        self.root, self.now = root, now
        self.public = httpx.Client(timeout=httpx.Timeout(15, connect=5), follow_redirects=False,
                                   headers={"User-Agent": "tradingbot research calendar reader", "Accept": "*/*"})
        settings = get_settings()
        if not settings.alpaca_paper_key or not settings.alpaca_paper_secret:
            raise ValueError("existing paper credentials required")
        self.news = NewsClient(settings.alpaca_paper_key, settings.alpaca_paper_secret, raw_data=True)
        self.news._retry = 0
        self.news._session.mount("https://", _NewsAdapter(max_retries=0))
        self.news._session.hooks["response"].append(self._capture_news)
        self.body = None

    def _capture_news(self, response, *args, **kwargs):
        if response.status_code != 200 or len(response.content) > MAX_BYTES:
            raise ValueError("news response unavailable or oversized")
        self.body = response.content
        return response

    def _receipt(self, body, url, params, received):
        checksum = hashlib.sha256(body).hexdigest()
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / (checksum + ".body")
        if path.exists():
            if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != checksum:
                raise ValueError("raw archive hash mismatch")
        else:
            with path.open("xb") as output:
                output.write(body)
        return body.decode("utf-8-sig"), {"url": url, "params": params,
                "received_at": utc(received).isoformat(), "sha256": checksum, "path": str(path)}

    def get(self, source, scope, *, params=None):
        validate_scope(source, scope)
        params = params or {}
        if source == NEWS:
            self.body = None
            self.news.get("/news", params)
            if self.body is None:
                raise ValueError("missing SDK response")
            return self._receipt(self.body, NEWS_URL, params, self.now())
        if source == BLS:
            year, month = scope.split("-")
            url = f"https://www.bls.gov/schedule/{year}/{month}_sched_list.htm"
        elif source == BEA:
            url = BEA_URL
        elif source == FED:
            url = FED_URL
        elif source == EARNINGS:
            url, params = EARNINGS_URL, {"date": scope}
        else:
            raise ValueError("unsupported source")
        # Match the existing free Nasdaq research client's browser-compatible
        # header; the generic calendar reader header times out on this endpoint.
        headers = {"User-Agent": "Mozilla/5.0"} if source == EARNINGS else None
        with self.public.stream("GET", url, params=params, headers=headers) as response:
            if response.status_code != 200:
                raise ValueError("calendar source unavailable")
            chunks, size = [], 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ValueError("calendar response oversized")
                chunks.append(chunk)
        return self._receipt(b"".join(chunks), url, params, self.now())

    def close(self):
        self.public.close()
        self.news._session.close()


def latest(session, source, scope, at):
    row = session.scalar(select(EventFeedSnapshot).where(
        EventFeedSnapshot.source == source, EventFeedSnapshot.scope == scope,
        EventFeedSnapshot.observed_at < utc(at),
    ).order_by(EventFeedSnapshot.observed_at.desc()).limit(1))
    if row is not None and digest(row.payload) != row.digest:
        raise ValueError("event snapshot digest mismatch")
    return row


def recent_failures(session, at):
    at = utc(at)
    return session.scalar(select(func.count()).select_from(EventFeedSnapshot).where(
        EventFeedSnapshot.status == "unavailable", EventFeedSnapshot.observed_at < at,
        EventFeedSnapshot.observed_at >= at - timedelta(seconds=API_ERROR_WINDOW_SECONDS)))


def store_snapshot(session, source, scope, at, events, receipts, *, error=None):
    validate_scope(source, scope)
    at = utc(at)
    if error and events or not error and not receipts:
        raise ValueError("invalid event evidence")
    prior = latest(session, source, scope, at)
    old = {row["id"]: row for row in prior.payload["events"]} if prior and prior.status == "ok" else {}
    seen, normalized = set(), []
    for event in events:
        event = dict(event)
        key = event["id"]
        if key in seen:
            raise ValueError("duplicate event identity")
        seen.add(key)
        previous = old.get(key)
        if previous and source == NEWS and utc(event["updated_at"]) < utc(previous["updated_at"]):
            raise ValueError("news revision moved backwards")
        unchanged = previous and {k: v for k, v in previous.items() if k != "known_at"} == event
        event["known_at"] = previous["known_at"] if unchanged else at.isoformat()
        normalized.append(event)
    for receipt in receipts:
        if utc(receipt["received_at"]) > at:
            raise ValueError("future source receipt")
    payload = {"source": source, "scope": scope, "observed_at": at.isoformat(),
               "events": normalized, "receipts": receipts, "error": error}
    row = EventFeedSnapshot(source=source, scope=scope, observed_at=at,
                            status="unavailable" if error else "ok", payload=payload, digest=digest(payload))
    session.add(row)
    session.flush()
    return row


class Recorder:
    def __init__(self, session, api, *, now=lambda: datetime.now(UTC), budget=None):
        self.session, self.api, self.now = session, api, now
        self.budget = budget or StorageBudget()

    def capture(self, source, scope):
        receipts, events = [], []
        self.budget.check(self.session)
        try:
            start = utc(self.now())
            if source == NEWS:
                params = {"symbols": ",".join(SYMBOLS), "start": (start - timedelta(days=1)).isoformat(),
                          "end": start.isoformat(), "sort": "desc", "limit": 50, "include_content": False}
                tokens = set()
                for _ in range(MAX_NEWS_PAGES):
                    self.budget.check(self.session)
                    body, receipt = self.api.get(source, scope, params=params.copy())
                    receipts.append(receipt)
                    rows, token = parse_news(body, utc(receipt["received_at"]))
                    events.extend(rows)
                    if token is None:
                        break
                    if token in tokens:
                        raise ValueError("repeated news page token")
                    tokens.add(token)
                    params["page_token"] = token
                else:
                    raise ValueError("incomplete news pagination")
            else:
                body, receipt = self.api.get(source, scope)
                receipts.append(receipt)
                if source == BLS:
                    events = parse_bls(body, scope)
                elif source == BEA:
                    events = parse_bea(body)
                elif source == FED:
                    events = parse_fed(body)
                else:
                    events = parse_earnings(body, scope)
            end = utc(self.now())
            # Keep published macro history outside the model's bounded horizon.
            if source in (BEA, FED):
                events = [e for e in events if start - timedelta(days=1) <= utc(e["event_at"]) <= start + timedelta(days=120)]
                if not any(utc(e["event_at"]) >= start for e in events):
                    raise ValueError("calendar has no current coverage")
            if end - start > NEWS_MAX_AGE and source == NEWS:
                raise ValueError("news capture took too long")
            self.budget.check(self.session)
            row = store_snapshot(self.session, source, scope, end, events, receipts)
            self.session.commit()
            return row
        except Exception as exc:
            self.session.rollback()
            if isinstance(exc, DiskBudgetExceeded):
                raise
            end = utc(self.now())
            prior = latest(self.session, source, scope, end)
            if prior is None or prior.status != "unavailable":
                self.session.add(Incident(severity="warning", category="api_error",
                    message="Event feed unavailable", details={"source": source, "scope": scope}))
            # Sanitized durable failure supersedes a previously usable source.
            row = store_snapshot(self.session, source, scope, end, [], receipts, error="capture_failed")
            self.session.commit()
            return row

    def step(self, *, force=False):
        now = utc(self.now())
        day = now.astimezone(NY).date()
        tasks = [(NEWS, "all"), *[(BLS, scope) for scope in month_scopes(now)], (BEA, "all"), (FED, "all")]
        tasks.extend((EARNINGS, (day + timedelta(days=i)).isoformat()) for i in range(EARNINGS_DAYS + 1))
        result, failures = {}, recent_failures(self.session, now)
        if failures >= API_ERROR_MAX_PER_MINUTE:
            return result
        for source, scope in tasks:
            now = utc(self.now())
            # A full earnings horizon can take minutes. Keep the news heartbeat
            # current while those independent dated calendars are collected.
            if source != NEWS:
                news = latest(self.session, NEWS, "all", now)
                if news is not None and now - news.observed_at >= NEWS_POLL:
                    row = self.capture(NEWS, "all")
                    result[NEWS + ":all"] = {"status": row.status, "events": len(row.payload["events"])}
                    failures += row.status != "ok"
                    if failures >= API_ERROR_MAX_PER_MINUTE:
                        break
                    now = utc(self.now())
            last = latest(self.session, source, scope, now)
            interval = NEWS_POLL if source == NEWS else CALENDAR_POLL
            # Calendar failures retry only once per hour, not each loop.
            if last and last.status != "ok" and source != NEWS:
                interval = timedelta(hours=1)
            if not force and last is not None and now - last.observed_at < interval:
                continue
            row = self.capture(source, scope)
            result[source + ":" + scope] = {"status": row.status, "events": len(row.payload["events"])}
            if row.status != "ok":
                failures += 1
                if failures >= API_ERROR_MAX_PER_MINUTE:
                    break  # Bounded outage traffic; no new entries rely on failed/missing feeds.
        return result


def _usable(row, at, age):
    return row is not None and row.status == "ok" and timedelta(0) < utc(at) - row.observed_at <= age


def _once(shared, key, read):
    if shared is None:
        return read()
    if key not in shared:
        shared[key] = read()
    return shared[key]


def events_asof(session, symbol, at, *, shared=None):
    """Bounded state-builder input; explicit unknowns never mean no event risk.

    ``shared`` (a dict owned by one observation) memoizes the reads that do
    not depend on the symbol. Keys include the as-of instant, so every symbol
    of one observation sees the same snapshots, read once instead of 40 times.
    """
    at = utc(at)
    if symbol not in SYMBOLS:
        raise ValueError("symbol outside universe")
    day = at.astimezone(NY).date()
    snapshot = lambda source, scope: _once(shared, ("latest", source, scope, at),
                                           lambda: latest(session, source, scope, at))
    halted = _once(shared, ("failures", at), lambda: recent_failures(session, at)) >= API_ERROR_MAX_PER_MINUTE
    news_row = snapshot(NEWS, "all")
    news_ok = not halted and _usable(news_row, at, NEWS_MAX_AGE)
    news = [] if not news_ok else [dict(e) for e in news_row.payload["events"]
        if symbol in e["symbols"] and utc(e["known_at"]) < at and at - timedelta(days=1) <= utc(e["created_at"]) < at]
    news.sort(key=lambda e: (e["updated_at"], e["id"]), reverse=True)
    macro_rows = [snapshot(BLS, scope) for scope in month_scopes(at)]
    macro_rows += [snapshot(source, "all") for source in (BEA, FED)]
    macro_ok = not halted and all(_usable(row, at, CALENDAR_MAX_AGE) for row in macro_rows)
    known_macro = sorted([dict(e, source=row.source) for row in macro_rows if _usable(row, at, CALENDAR_MAX_AGE)
        for e in row.payload["events"] if utc(e["known_at"]) < at],
        key=lambda e: e["event_at"])
    macro = [e for e in known_macro if utc(e["event_at"]) >= at]
    previous = [e for e in known_macro if utc(e["event_at"]) <= at]
    # At regular-session decisions, current-month coverage includes the whole
    # preceding 15 minutes. Across a month boundary that guarantee is absent.
    month_start = datetime.combine(day.replace(day=1), datetime.min.time(), tzinfo=NY)
    recent_complete = macro_ok and at - timedelta(minutes=15) >= month_start
    earnings_rows = [snapshot(EARNINGS, (day + timedelta(days=i)).isoformat())
                     for i in range(EARNINGS_DAYS + 1)] if symbol not in ETF_SYMBOLS else []
    earnings_ok = not halted and all(_usable(row, at, CALENDAR_MAX_AGE) for row in earnings_rows)
    upcoming = [dict(e) for row in earnings_rows if _usable(row, at, CALENDAR_MAX_AGE)
                for e in row.payload["events"] if e["symbol"] == symbol and utc(e["known_at"]) < at]
    upcoming.sort(key=lambda e: e["event_date"])
    earning = upcoming[0] if upcoming else None
    # Missing earlier daily calendars could hide an earlier event. Return the
    # known candidate, but withhold a reliable numeric days-to-event value.
    earnings_status = ("not_applicable" if symbol in ETF_SYMBOLS else "unavailable" if not earnings_ok
                       else "scheduled_estimate" if earning else "unknown")
    snapshots = [news_row, *macro_rows, *earnings_rows]
    return {"asof": at.isoformat(), "symbol": symbol, "collection_halted": halted,
        "news": {"status": "ok" if news_ok else "unavailable", "untrusted": True, "items": news[:5]},
        "macro": {"status": "ok" if macro_ok and macro else "unavailable", "next_known": macro[0] if macro else None,
                  "minutes_to_next": (utc(macro[0]["event_at"]) - at).total_seconds() / 60 if macro_ok and macro else None,
                  "minutes_since_previous": (at - utc(previous[-1]["event_at"])).total_seconds() / 60
                      if recent_complete and previous else None,
                  "recent_window_complete": recent_complete},
        "earnings": {"status": earnings_status, "next_known": earning,
                     "days_to_earnings": (date.fromisoformat(earning["event_date"]) - day).days
                         if earnings_ok and earning else None},
        "receipts": [{"source": row.source, "scope": row.scope, "observed_at": row.observed_at.isoformat(),
                      "digest": row.digest, "status": row.status} for row in snapshots if row is not None]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--refresh", action="store_true", help="refresh all scopes once after a source fix")
    args = parser.parse_args(argv)
    if args.refresh and not args.once:
        parser.error("--refresh requires --once")
    api = None
    with get_engine().connect() as lock, SessionLocal() as session:
        if not lock.scalar(text("SELECT pg_try_advisory_lock(:id)"), {"id": LOCK_ID}):
            raise SystemExit("Event recorder already running")
        try:
            api = FeedAPI()
            recorder = Recorder(session, api)
            while True:
                started = time.monotonic()
                state = recorder.step(force=args.refresh)
                if state or args.once:
                    print(canonical(state), flush=True)
                if args.once:
                    return int(any(row["status"] != "ok" for row in state.values()))
                time.sleep(max(1, 30 - (time.monotonic() - started)))
        except Exception:
            # Never print exception bodies, request headers, keys or headlines.
            print(canonical({"status": "event_recorder_failed"}), flush=True)
            return 1
        finally:
            if api is not None:
                api.close()
            lock.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": LOCK_ID})


if __name__ == "__main__":
    raise SystemExit(main())
