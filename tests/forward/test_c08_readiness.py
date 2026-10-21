from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
import json
from pathlib import Path

import pytest

from tradingbot.connectors.cash import MarketSession, timestamp
from tradingbot.forward import c08_readiness as c08


def sessions():
    # Synthetic calendar includes a trading-but-not-settlement holiday.
    return [MarketSession.from_api({"date": day, "settlement_date": settled,
        "open": "09:30", "close": "16:00"}) for day, settled in [
        ("2026-10-01", "2026-10-02"), ("2026-10-02", "2026-10-05"),
        ("2026-10-09", "2026-10-13"), ("2026-10-12", "2026-10-13"),
        ("2026-10-13", "2026-10-14"), ("2026-10-14", "2026-10-15")]]


@pytest.mark.parametrize("validated,expected", [
    ("2026-09-30T14:45:00Z", "2026-10-01T13:30:00Z"),
    ("2026-10-01T13:29:59Z", "2026-10-01T13:30:00Z"),
    ("2026-10-01T13:30:00Z", "2026-10-02T13:30:00Z"),
    ("2026-10-01T18:00:00Z", "2026-10-02T13:30:00Z"),
])
def test_publication_and_actual_validation_both_precede_open(validated, expected):
    available, opens = c08.first_eligible_open(date(2026, 9, 30), validated, sessions())
    assert opens == timestamp(expected)
    assert available >= timestamp(validated)
    assert available >= timestamp("2026-10-01T04:00:00Z")


def test_future_publication_or_insufficient_calendar_never_backfills():
    with pytest.raises(ValueError, match="Future-dated"):
        c08.first_eligible_open(date(2026, 10, 2), "2026-10-01T20:00:00Z", sessions())
    with pytest.raises(ValueError, match="cover"):
        c08.first_eligible_open(date(2026, 10, 14), "2026-10-15T20:00:00Z", sessions())
    with pytest.raises(ValueError):
        c08.first_eligible_open(date(2026, 9, 30), "2026-10-01T18:00:00", sessions())


def test_cash_waits_past_documented_completion_and_weekend():
    assert c08.release_after_completion(date(2026, 10, 1), sessions()) == timestamp("2026-10-02T13:30:00Z")
    assert c08.release_after_completion(date(2026, 10, 9), sessions()) == timestamp("2026-10-12T13:30:00Z")
    # Friday Oct 9 nominal settlement is Tuesday Oct 13. If documented complete
    # on Oct 13, Oct 12's trading session cannot accelerate release.
    assert c08.release_after_completion(date(2026, 10, 13), sessions()) == timestamp("2026-10-14T13:30:00Z")
    with pytest.raises(ValueError, match="cover"):
        c08.release_after_completion(date(2026, 10, 14), sessions())


def cash_rows():
    return [
        {"fill_at": "2026-10-01T13:30:00Z", "side": "buy", "notional": "133", "fee": ".01"},
        {"fill_at": "2026-10-09T13:30:00Z", "side": "sell", "notional": "134", "fee": ".03",
         "cash_release_at": "2026-10-14T13:30:00Z"},
    ]


def test_cash_bridge_holds_sale_proceeds_and_debits_fees_and_reservations():
    assert c08.conservative_cash("140", cash_rows(), "2", "2026-10-13T13:30:00Z") == D("4.96")
    assert c08.conservative_cash("140", cash_rows(), "2", "2026-10-14T13:29:59Z") == D("4.96")
    assert c08.conservative_cash("140", cash_rows(), "2", "2026-10-14T13:30:00Z") == D("138.96")


@pytest.mark.parametrize("field,value", [("fee", "NaN"), ("notional", "-1"),
    ("side", "dividend"), ("fill_at", "2027-01-01T00:00:00Z"),
    ("cash_release_at", "2026-10-01T00:00:00Z")])
def test_cash_bridge_rejects_invalid_or_future_evidence(field, value):
    rows = cash_rows()
    rows[1][field] = value
    with pytest.raises(ValueError):
        c08.conservative_cash("140", rows, "0", "2026-10-14T14:00:00Z")


def test_missing_sale_release_cannot_inherit_faster_connector_rule():
    rows = cash_rows()
    del rows[1]["cash_release_at"]
    with pytest.raises(KeyError):
        c08.conservative_cash("140", rows, "0", "2026-10-14T14:00:00Z")


@pytest.mark.parametrize("age,fresh", [(0, True), (30, True), (30.001, False), (-1, False)])
def test_quote_freshness_has_unchanged_30_second_boundary(age, fresh):
    now = datetime(2026, 10, 1, 18, tzinfo=UTC)
    row = {"t": (now - timedelta(seconds=age)).isoformat(), "bp": "149.10", "ap": "149.16"}
    result = c08.quote_evidence(row, now)
    assert result["fresh"] is fresh
    assert not result["fill_evidence"]
    assert not result["at_session_open"]


@pytest.mark.parametrize("bid,ask", [("NaN", "1"), ("1", "Infinity"), ("2", "1"), ("0", "1")])
def test_bad_quote_cannot_be_fresh(bid, ask):
    with pytest.raises(ValueError):
        c08.quote_evidence({"t": "2026-10-01T18:00:00Z", "bp": bid, "ap": ask}, timestamp("2026-10-01T18:00:01Z"))


def test_eia_latest_comes_from_actual_dated_primary_links():
    raw = b'<a href="2026/2026_09_30/wpsr_2026_09_30.php">new</a><a href="2026/2026_10_07/wpsr_2026_10_07.php">future</a>'
    assert c08.latest_archive_url(raw, date(2026, 10, 1)).endswith("2026_09_30.php")
    bad = raw.replace(b'2026/2026_09_30', b'https://example.org/petroleum/supply/weekly/archive/2026/2026_09_30')
    with pytest.raises(ValueError, match="primary"):
        c08.latest_archive_url(bad, date(2026, 10, 1))
    with pytest.raises(ValueError, match="No recent"):
        c08.latest_archive_url(b"no releases", date(2026, 10, 1))
    with pytest.raises(ValueError, match="years disagree"):
        c08.latest_archive_url(raw.replace(b'2026/2026_09_30', b'2025/2026_09_30'), date(2026, 10, 1))


def test_read_only_capture_redacts_account_and_does_not_submit(tmp_path, monkeypatch):
    writes = {}
    def save(path, value):
        writes[path.name] = json.loads(c08.encoded(value))
        return {"path": path.name, "sha256": "test"}
    monkeypatch.setattr(c08, "write_once", save)
    class API:
        def account(self):
            return {"status": "ACTIVE", "currency": "USD", "id": "private-id", "account_number": "private-number",
                    "cash": "100000", "buying_power": "200000", "trading_blocked": False,
                    "account_blocked": False, "trade_suspended_by_user": False}
        def asset(self, symbol):
            assert symbol == "USO"
            return {"symbol": symbol, "fractionable": True}
        def calendar_range(self, start, end):
            return []
        def quote(self, symbol):
            return {"bp": "149", "ap": "150", "t": datetime.now(UTC).isoformat()}
        def submit(self, *args):
            raise AssertionError("Readiness cannot submit")
    probes, receipts = c08.capture_paper(API(), tmp_path, date(2026, 10, 1), date(2026, 11, 1),
                                       expected_account=c08.digest(b"private-id"))
    assert set(receipts) == {"account", "asset", "calendar", "quote"}
    assert "private" not in json.dumps(writes)
    assert probes["quote"]["audit"]["fresh"]
    assert probes["account"]["audit"]["matches_existing_cash_book"] is True
    probes, _ = c08.capture_paper(API(), tmp_path, date(2026, 10, 1), date(2026, 11, 1), expected_account="different")
    assert probes["account"]["audit"]["matches_existing_cash_book"] is False


def test_action_capture_exhausts_pages_and_empty_is_not_clearance(tmp_path, monkeypatch):
    monkeypatch.setattr(c08, "write_once", lambda path, value: {"path": path.name})
    calls = []
    def api(request):
        calls.append(request.params)
        assert request.params["data_quality"] == "all"
        assert request.params["symbols"] == "USO"
        return json.dumps({"corporate_actions": {}, "next_page_token": "next" if len(calls) == 1 else None})
    result = c08.capture_actions(api, tmp_path, date(2026, 10, 1), date(2026, 11, 1))
    assert result["exhausted"] and result["records"] == 0
    assert calls[1]["page_token"] == "next"
    assert not result["advance_notice_guaranteed"]


def test_action_capture_repeated_page_token_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(c08, "write_once", lambda path, value: {})
    def api(request):
        return json.dumps({"corporate_actions": {}, "next_page_token": "repeat"})
    with pytest.raises(ValueError, match="loop"):
        c08.capture_actions(api, tmp_path, date(2026, 10, 1), date(2026, 11, 1))


def test_capture_refuses_unowned_archive_destination(tmp_path):
    with pytest.raises(ValueError, match="new capture directory"):
        c08.capture_readiness(tmp_path)


def test_failed_preparation_receipt_is_append_only_idempotent_and_not_a_result(tmp_path, monkeypatch):
    from uuid import uuid4
    from sqlalchemy.orm import Session
    from tradingbot.db.models import Strategy, Trial
    from tradingbot.db.session import get_engine
    connection = get_engine().connect()
    outer = connection.begin()
    session = Session(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
    try:
        strategy = Strategy(key="c08-readiness-test-" + uuid4().hex, name="Readiness test", status="backtest")
        session.add(strategy)
        session.flush()
        history = {"rows": [{"strategy_id": strategy.id}, {"strategy_id": strategy.id}]}
        monkeypatch.setattr(c08, "ROOT", tmp_path)
        monkeypatch.setattr(c08, "ARCHIVE", tmp_path / "captures")
        monkeypatch.setattr(c08, "historical_evidence", lambda session: history)
        path = c08.ARCHIVE / "one" / "readiness.json"
        path.parent.mkdir(parents=True)
        report = {"schema": c08.NAME, "decision": "hold_before_ordering_paper", "orders_submitted": 0,
                  "ready_for_live": False, "paper_runner_activated": False,
                  "capture_code_sha256": c08.digest(Path(c08.__file__).read_bytes()),
                  "historical_evidence": history, "git_commit": "synthetic", "blockers": ["fixture"],
                  "probe_failures": [], "started_at": "2026-10-01T18:00:00Z", "completed_at": "2026-10-01T18:01:00Z"}
        path.write_bytes(c08.encoded(report))
        iid = c08.record_failed_preparation(session, path)
        session.commit()
        assert c08.record_failed_preparation(session, path) == iid
        row = session.get(Trial, iid)
        assert row.status == "failed" and row.mode == "paper" and row.trade_count == 0
        assert row.pnl_after_fees is None and row.max_drawdown is None and row.luck_p_value is None
        assert row.final_holdout is False and row.strategy_version is None
        assert strategy.status == "backtest" and strategy.allocation_usd == 0
        report["ready_for_live"] = True
        path.write_bytes(c08.encoded(report))
        with pytest.raises(ValueError, match="non-ordering readiness"):
            c08.record_failed_preparation(session, path)
        report["ready_for_live"] = False
        report["historical_evidence"] = {"changed": True}
        path.write_bytes(c08.encoded(report))
        with pytest.raises(ValueError, match="Historical evidence changed"):
            c08.record_failed_preparation(session, path)
    finally:
        session.close()
        assert outer.is_active
        outer.rollback()
        connection.close()
