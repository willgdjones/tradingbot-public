from datetime import UTC, date, datetime, timedelta
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import uuid

from alembic.migration import MigrationContext
from alembic.operations import Operations
import httpx
import pytest
from sqlalchemy import create_engine, event, func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from tradingbot.data import event_feeds as feed
from tradingbot.data.disk_budget import DiskBudgetExceeded
from tradingbot.db.event_models import EventFeedSnapshot
from tradingbot.db.models import Incident
from tradingbot.db.session import get_engine

NOW = datetime(2026, 10, 2, 15, tzinfo=UTC)
SECOND = timedelta(seconds=1)


@pytest.fixture
def session():
    schema = "test_events_" + uuid.uuid4().hex
    # A private engine: the forward-paper fixture redirects the cached one to
    # its own schema for the rest of a whole-suite run (DuplicateTable).
    base = create_engine(get_engine().url)
    spec = importlib.util.spec_from_file_location("event_migration", Path(feed.__file__).parents[1] /
        "db/migrations/versions/2026_10_02_1915-eventfeed01_event_feeds.py")
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with base.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        connection.execute(text(f'CREATE TABLE "{schema}".incidents (LIKE public.incidents INCLUDING ALL)'))
    engine = create_engine(base.url, execution_options={"schema_translate_map": {None: schema}})
    try:
        with Session(engine, expire_on_commit=False) as value:
            yield value
    finally:
        engine.dispose()
        with base.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        base.dispose()


def receipt(at=NOW):
    return {"received_at": at.isoformat(), "sha256": "a" * 64, "url": "https://example.test"}


def article(id=1, **updates):
    return {"id": id, "created_at": (NOW - timedelta(minutes=1)).isoformat(),
            "updated_at": (NOW - timedelta(minutes=1)).isoformat(),
            "symbols": ["AAPL"], "headline": "Company announces an event", **updates}


def page(rows=None, token=None):
    return json.dumps({"news": [article()] if rows is None else rows, "next_page_token": token})


def news_event(**updates):
    return feed.parse_news(page([article(**updates)]), NOW)[0][0]


def put(session, source, scope="all", at=NOW, events=(), *, error=None):
    return feed.store_snapshot(session, source, scope, at, list(events), [receipt(at)], error=error)


def macro_event(kind="cpi", day="2026-10-14", clock="12:30:00"):
    return {"id": kind + ":" + day, "kind": kind, "title": kind,
            "event_at": day + "T" + clock + "+00:00"}


def populate_calendars(session):
    put(session, feed.BLS, "2026-10", events=[macro_event()])
    put(session, feed.BLS, "2026-11", events=[macro_event(day="2026-11-13", clock="13:30:00")])
    put(session, feed.BEA, events=[macro_event("gdp", "2026-10-29")])
    put(session, feed.FED, events=[macro_event("fomc_minutes", "2026-10-07", "18:00:00")])
    for i in range(feed.EARNINGS_DAYS + 1):
        day = (NOW.date() + timedelta(days=i)).isoformat()
        events = [] if i != 27 else [{"id": "AAPL:" + day, "kind": "earnings", "symbol": "AAPL",
                    "event_date": day, "time_bucket": "unknown", "precision": "day", "confirmed": False}]
        put(session, feed.EARNINGS, day, events=events)


def bls_body(month="October", jobs_day=2, cpi_day=14, year=2026):
    def row(day, title):
        d = datetime.strptime(f"{year} {month} {day}", "%Y %B %d")
        return (f'<tr><td class="date-cell"><p>{d:%A, %B %d, %Y}</p></td>'
                f'<td class="time-cell">08:30 AM</td><td class="desc-cell"><strong>{title}</strong></td></tr>')
    return '<table class="release-list">' + row(jobs_day, "Employment Situation") + row(cpi_day, "Consumer Price Index") + '</table>'


def test_bls_explicit_times_dst_and_wrong_scope():
    october = feed.parse_bls(bls_body(), "2026-10")
    november = feed.parse_bls(bls_body("November", 6, 13), "2026-11")
    assert october[0]["event_at"] == "2026-10-02T12:30:00+00:00"
    assert november[0]["event_at"] == "2026-11-06T13:30:00+00:00"
    with pytest.raises(ValueError):
        feed.parse_bls(bls_body(), "2026-11")
    with pytest.raises(ValueError):
        feed.parse_bls(bls_body().replace("Consumer Price Index", "Other release"), "2026-10")
    with pytest.raises(ValueError):
        feed.parse_bls("<h1>Access denied</h1>", "2026-10")


def test_bea_json_timezone_required_and_no_release_inference():
    body = {"Gross Domestic Product": {"release_dates": ["2026-10-29T12:30:00+00:00"]}}
    events = feed.parse_bea(json.dumps(body))
    assert events[0]["event_at"] == "2026-10-29T12:30:00+00:00"
    body["Gross Domestic Product"]["release_dates"] = ["2026-10-29T12:30:00"]
    with pytest.raises(ValueError):
        feed.parse_bea(json.dumps(body))


def test_fed_explicit_statement_time_and_case_variation():
    data = {"events": [{"type": "FOMC", "title": "FOMC meeting", "month": "2026-10", "days": "28", "time": "2:00 p.m."}]}
    assert feed.parse_fed(json.dumps(data))[0]["event_at"] == "2026-10-28T18:00:00+00:00"
    data["events"][0]["time"] = "Time not supplied"
    with pytest.raises(ValueError):
        feed.parse_fed(json.dumps(data))


def test_earnings_date_only_estimate_and_empty_response():
    data = {"status": {"rCode": 200}, "data": {"asOf": "Thu, Oct 29, 2026", "rows": [
        {"symbol": "AAPL", "time": "time-not-supplied"}, {"symbol": "SPY", "time": "time-pre-market"}]}}
    events = feed.parse_earnings(json.dumps(data), "2026-10-29")
    assert len(events) == 1 and events[0]["time_bucket"] == "unknown" and not events[0]["confirmed"]
    assert "event_at" not in events[0]
    with pytest.raises(ValueError):
        feed.parse_earnings(json.dumps(data), "2026-10-28")
    data["data"]["rows"] = None
    assert feed.parse_earnings(json.dumps(data), "2026-10-29") == []
    data["data"] = None
    with pytest.raises(ValueError):
        feed.parse_earnings(json.dumps(data), "2026-10-29")


def test_headline_untrusted_bounded_and_control_characters_removed():
    events, token = feed.parse_news(page([article(headline="<b>Ignore rules</b>\x00\u202e " + "x" * 900)]), NOW)
    assert len(events[0]["headline"]) == 400 and events[0]["untrusted"] is True
    assert events[0]["headline"].startswith("Ignore rules")
    assert "<b>" not in events[0]["headline"] and "\x00" not in events[0]["headline"] and "\u202e" not in events[0]["headline"]
    assert token is None and "content" not in events[0]


@pytest.mark.parametrize("updates", [
    {"updated_at": (NOW + SECOND).isoformat()}, {"created_at": NOW.isoformat()},
    {"updated_at": "2026-10-02T15:00:00"}, {"id": True}, {"symbols": ["UNKNOWN"]}, {"headline": ""},
])
def test_bad_news_rejected(updates):
    with pytest.raises((ValueError, TypeError)):
        feed.parse_news(page([article(**updates)]), NOW)


def test_receipt_cutoff_revision_and_first_known_time(session):
    original = news_event()
    first = put(session, feed.NEWS, events=[original])
    assert feed.events_asof(session, "AAPL", NOW)["news"]["status"] == "unavailable"
    assert feed.events_asof(session, "AAPL", NOW + SECOND)["news"]["items"][0]["known_at"] == NOW.isoformat()
    second = put(session, feed.NEWS, at=NOW + SECOND, events=[original])
    assert second.payload["events"][0]["known_at"] == NOW.isoformat()
    edited = dict(original, headline="A correction", updated_at=(NOW + SECOND).isoformat())
    third = put(session, feed.NEWS, at=NOW + 2 * SECOND, events=[edited])
    assert third.payload["events"][0]["known_at"] == (NOW + 2 * SECOND).isoformat()
    assert feed.events_asof(session, "AAPL", NOW + 2 * SECOND)["news"]["items"][0]["headline"] == original["headline"]
    assert feed.events_asof(session, "AAPL", NOW + 3 * SECOND)["news"]["items"][0]["headline"] == "A correction"
    assert first.payload["events"][0]["headline"] == original["headline"]
    with pytest.raises(ValueError, match="backwards"):
        put(session, feed.NEWS, at=NOW + 4 * SECOND, events=[original])


def test_deleted_news_and_failed_source_never_fall_back_to_old_good_data(session):
    put(session, feed.NEWS, events=[news_event()])
    put(session, feed.NEWS, at=NOW + SECOND, events=[])
    assert feed.events_asof(session, "AAPL", NOW + 2 * SECOND)["news"] == {"status": "ok", "untrusted": True, "items": []}
    put(session, feed.NEWS, at=NOW + 3 * SECOND, error="capture_failed")
    assert feed.events_asof(session, "AAPL", NOW + 4 * SECOND)["news"]["status"] == "unavailable"
    assert feed.events_asof(session, "AAPL", NOW + SECOND)["news"]["items"]


def test_stale_news_empty_etf_earnings_and_bounded_output(session):
    put(session, feed.NEWS, events=[news_event(id=i) for i in range(1, 11)])
    assert len(feed.events_asof(session, "AAPL", NOW + SECOND)["news"]["items"]) == 5
    assert feed.events_asof(session, "AAPL", NOW + timedelta(seconds=121))["news"]["status"] == "unavailable"
    assert feed.events_asof(session, "SPY", NOW + SECOND)["earnings"]["status"] == "not_applicable"
    assert feed.events_asof(session, "AAPL", NOW + SECOND)["earnings"]["status"] == "unavailable"


def test_calendar_next_event_revision_and_missing_source_withholds_numeric_fields(session):
    populate_calendars(session)
    state = feed.events_asof(session, "AAPL", NOW + SECOND)
    assert state["macro"]["status"] == "ok" and state["macro"]["next_known"]["kind"] == "fomc_minutes"
    assert state["earnings"]["days_to_earnings"] == 27
    put(session, feed.FED, at=NOW + SECOND, events=[macro_event("fomc", "2026-10-28", "18:00:00")])
    assert feed.events_asof(session, "AAPL", NOW + 2 * SECOND)["macro"]["next_known"]["kind"] == "cpi"
    put(session, feed.BLS, "2026-11", at=NOW + 3 * SECOND, error="capture_failed")
    state = feed.events_asof(session, "AAPL", NOW + 4 * SECOND)
    assert state["macro"]["minutes_to_next"] is None and state["macro"]["next_known"]["kind"] == "cpi"
    put(session, feed.EARNINGS, "2026-10-05", at=NOW + 5 * SECOND, error="capture_failed")
    assert feed.events_asof(session, "AAPL", NOW + 6 * SECOND)["earnings"]["days_to_earnings"] is None


def test_no_earnings_match_is_unknown_not_no_event(session):
    populate_calendars(session)
    state = feed.events_asof(session, "MSFT", NOW + SECOND)
    assert state["earnings"]["status"] == "unknown" and state["earnings"]["days_to_earnings"] is None


def test_recent_macro_is_receipt_bound_and_outage_withholds_clear_window(session):
    populate_calendars(session)
    put(session, feed.FED, at=NOW+SECOND,
        events=[macro_event("fomc", "2026-10-02", "15:00:00"),
                macro_event("fomc_minutes", "2026-10-07", "18:00:00")])
    assert feed.events_asof(session, "SPY", NOW+SECOND)["macro"]["minutes_since_previous"] is None
    macro = feed.events_asof(session, "SPY", NOW+2*SECOND)["macro"]
    assert macro["recent_window_complete"] is True
    assert macro["minutes_since_previous"] == 2/60
    assert macro["minutes_to_next"] > 15
    put(session, feed.BEA, at=NOW+3*SECOND, error="source_unavailable")
    macro = feed.events_asof(session, "SPY", NOW+4*SECOND)["macro"]
    assert macro["minutes_since_previous"] is None and macro["recent_window_complete"] is False


def test_month_boundary_does_not_claim_previous_month_calendar_coverage(session):
    at = datetime(2026, 10, 1, 4, 10, tzinfo=UTC)
    for source, scope, events in [
        (feed.BLS, "2026-10", [macro_event()]),
        (feed.BLS, "2026-11", [macro_event(day="2026-11-13")]),
        (feed.BEA, "all", [macro_event("gdp", "2026-10-29")]),
        (feed.FED, "all", [macro_event("fomc", "2026-10-07")]),
    ]:
        put(session, source, scope, at=at-SECOND, events=events)
    macro = feed.events_asof(session, "SPY", at)["macro"]
    assert macro["status"] == "ok" and macro["recent_window_complete"] is False


def test_real_migration_protects_evidence_against_update_delete(session):
    row = put(session, feed.NEWS, events=[news_event()])
    session.commit()
    with pytest.raises(DBAPIError, match="immutable"):
        session.execute(update(EventFeedSnapshot).values(status="unavailable"))
    session.rollback()
    with pytest.raises(DBAPIError, match="immutable"):
        session.delete(row)
        session.flush()
    session.rollback()
    assert feed.latest(session, feed.NEWS, "all", NOW + SECOND).status == "ok"


class FakeAPI:
    def __init__(self, pages):
        self.pages, self.calls = iter(pages), []

    def get(self, source, scope, *, params=None):
        self.calls.append((source, scope, params))
        row = next(self.pages)
        if isinstance(row, Exception):
            raise row
        return row, receipt()


class Budget:
    def check(self, session):
        pass


def test_news_pagination_complete_and_incomplete_capture(session):
    api = FakeAPI([page([article()], "next"), page([article(id=2)])])
    recorder = feed.Recorder(session, api, now=lambda: NOW + SECOND, budget=Budget())
    result = recorder.capture(feed.NEWS, "all")
    assert result.status == "ok" and len(result.payload["events"]) == 2
    assert api.calls[1][2]["page_token"] == "next" and api.calls[0][2]["include_content"] is False
    broken = FakeAPI([page([article()], "loop"), page([article(id=2)], "loop")])
    recorder = feed.Recorder(session, broken, now=lambda: NOW + 2 * SECOND, budget=Budget())
    assert recorder.capture(feed.NEWS, "all").status == "unavailable"
    state = feed.events_asof(session, "AAPL", NOW + 3 * SECOND)
    assert state["news"]["items"] == [] and state["news"]["status"] == "unavailable"


def test_provider_exception_is_sanitized_and_incident_not_repeated(session):
    for i in range(3):
        recorder = feed.Recorder(session, FakeAPI([RuntimeError("SECRET_TOKEN")]),
                                 now=lambda: NOW + i * SECOND, budget=Budget())
        row = recorder.capture(feed.NEWS, "all")
        assert "SECRET_TOKEN" not in feed.canonical(row.payload)
    assert session.scalar(select(func.count()).select_from(Incident)) == 1


def test_disk_failure_stops_before_any_network(session):
    class FullBudget:
        def check(self, session):
            raise DiskBudgetExceeded("full")
    api = FakeAPI([])
    with pytest.raises(DiskBudgetExceeded):
        feed.Recorder(session, api, now=lambda: NOW, budget=FullBudget()).capture(feed.NEWS, "all")
    assert api.calls == []


def test_snapshot_rejects_duplicate_ids_and_missing_receipts(session):
    with pytest.raises(ValueError, match="duplicate"):
        put(session, feed.NEWS, events=[news_event(), news_event()])
    with pytest.raises(ValueError):
        feed.store_snapshot(session, feed.NEWS, "all", NOW, [], [])
    with pytest.raises(ValueError):
        feed.store_snapshot(session, feed.NEWS, "all", NOW, [], [receipt(NOW + SECOND)])


def test_archive_integrity_and_get_scope(tmp_path):
    api = object.__new__(feed.FeedAPI)
    api.root = tmp_path
    body, saved = api._receipt(b'{"ok":true}', "https://example.test", {}, NOW)
    assert body == '{"ok":true}'
    Path(saved["path"]).write_text("tampered")
    with pytest.raises(ValueError, match="hash mismatch"):
        api._receipt(b'{"ok":true}', "https://example.test", {}, NOW)
    with pytest.raises(ValueError):
        api.get(feed.BLS, "../../private")


def test_calendar_transport_redirect_and_size_limits(tmp_path):
    api = object.__new__(feed.FeedAPI)
    api.root, api.now = tmp_path, lambda: NOW
    for response in (httpx.Response(302, headers={"Location": "https://evil.test"}),
                     httpx.Response(200, content=b'x' * (feed.MAX_BYTES + 1))):
        api.public = httpx.Client(transport=httpx.MockTransport(lambda request: response))
        with pytest.raises(ValueError):
            api.get(feed.FED, "all")
        api.public.close()


def test_nasdaq_header_and_request_remain_read_only(tmp_path):
    api = object.__new__(feed.FeedAPI)
    api.root, api.now = tmp_path, lambda: NOW
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={"data": []})
    api.public = httpx.Client(transport=httpx.MockTransport(handle))
    api.get(feed.EARNINGS, "2026-10-29")
    api.public.close()
    assert requests[0].headers["User-Agent"] == "Mozilla/5.0"
    assert requests[0].method == "GET" and requests[0].url.params["date"] == "2026-10-29"


def test_read_only_news_adapter_rejects_mutation_and_wrong_endpoint():
    adapter = feed._NewsAdapter()
    for method, url in (("POST", feed.NEWS_URL), ("GET", "https://paper-api.alpaca.markets/v2/orders"),
                        ("GET", feed.NEWS_URL + "-evil")):
        with pytest.raises(ValueError):
            adapter.send(SimpleNamespace(method=method, url=url))


def test_poll_does_not_repeat_calendar_fetch_and_outage_attempts_are_bounded(session, monkeypatch):
    recorder = feed.Recorder(session, None, now=lambda: NOW, budget=Budget())
    calls = []
    def failed(source, scope):
        calls.append((source, scope))
        return SimpleNamespace(status="unavailable", payload={"events": []})
    monkeypatch.setattr(recorder, "capture", failed)
    assert len(recorder.step()) == len(calls) == 5
    populate_calendars(session)
    put(session, feed.NEWS, events=[])
    recorder.now = lambda: NOW + SECOND
    calls.clear()
    assert recorder.step() == {} and calls == []


def test_slow_calendar_sweep_refreshes_news_between_dates(session, monkeypatch):
    clock, news_times = [NOW], []
    recorder = feed.Recorder(session, None, now=lambda: clock[0], budget=Budget())
    def capture(source, scope):
        row = put(session, source, scope, clock[0])
        if source == feed.NEWS:
            news_times.append(clock[0])
        clock[0] += timedelta(seconds=1 if source == feed.NEWS else 35)
        return row
    monkeypatch.setattr(recorder, "capture", capture)
    recorder.step()
    assert len(news_times) > 1
    assert max(b - a for a, b in zip(news_times, news_times[1:])) < feed.NEWS_MAX_AGE
    assert clock[0] - news_times[-1] < feed.NEWS_MAX_AGE


def test_five_error_halt_survives_restart_and_expires_on_rolling_window(session):
    put(session, feed.NEWS, events=[news_event()])
    for i in range(5):
        put(session, feed.EARNINGS, (NOW.date() + timedelta(days=i)).isoformat(),
            at=NOW + (i + 1) * SECOND, error="capture_failed")
    session.commit()
    api = FakeAPI([])
    recorder = feed.Recorder(session, api, now=lambda: NOW + 6 * SECOND, budget=Budget())
    assert recorder.step() == {} and api.calls == []
    state = feed.events_asof(session, "SPY", NOW + 6 * SECOND)
    assert state["collection_halted"] and state["news"]["status"] == "unavailable"
    assert feed.events_asof(session, "SPY", NOW + 61 * SECOND)["collection_halted"]
    assert not feed.events_asof(session, "SPY", NOW + 62 * SECOND)["collection_halted"]


def test_shared_memo_matches_plain_reads_once_and_never_crosses_instants(session):
    # 2026-10-05: 40 symbols re-read the same snapshots (1,259 queries, 11-26s
    # under afternoon load), consuming the decision's 30s data-age budget.
    populate_calendars(session)
    put(session, feed.NEWS, events=[news_event(id=1), news_event(id=2, symbols=["MSFT"])])
    at, symbols = NOW + SECOND, ("AAPL", "MSFT", "SPY")
    plain = [feed.events_asof(session, s, at) for s in symbols]
    statements = []
    count = lambda *args: statements.append(1)
    event.listen(session.get_bind(), "before_cursor_execute", count)
    try:
        feed.events_asof(session, "AAPL", at)
        single = len(statements)
        statements.clear()
        shared = {}
        assert [feed.events_asof(session, s, at, shared=shared) for s in symbols] == plain
        assert len(statements) == single  # every symbol after the first is a memo hit
        put(session, feed.NEWS, at=NOW + 2 * SECOND, events=[news_event(id=3, headline="Later revision")])
        later = feed.events_asof(session, "AAPL", NOW + 3 * SECOND, shared=shared)
        assert later == feed.events_asof(session, "AAPL", NOW + 3 * SECOND)
        assert later["news"]["items"][0]["headline"] == "Later revision"
    finally:
        event.remove(session.get_bind(), "before_cursor_execute", count)
