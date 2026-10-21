from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from tradingbot.connectors.cash import MarketSession, timestamp
from tradingbot.db.models import Strategy, Trial
from tradingbot.db.session import get_engine
from tradingbot.forward import c05_readiness as c05


def test_historical_evidence_decimal_luck_survives_exact_receipt_roundtrip():
    params = {**c05.PARAMS, "_holdout": {"identity": {"key": c05.FAMILY,
        "code": {"strategy/c05_commodity_trend.py": c05.REACTOR},
        "execution_params": {"run": {"cost_bp_per_side": 10}}}}}
    rows = {iid: SimpleNamespace(id=iid, mode="backtest", status="complete",
        strategy_id=iid, strategy_version=c05.VERSION, final_holdout=final,
        params=params, pnl_after_fees=D("30"), fees_total=D("3"), trade_count=57,
        dataset_key="synthetic", holdout_start=timestamp("2021-02-14T14:24:00Z"),
        max_drawdown=D("49"), luck_p_value=None if final else D("0.263874"))
        for iid, final in ((3959, False), (3964, True))}
    session = SimpleNamespace(execute=lambda *a: None, get=lambda model, iid: rows[iid],
        scalar=lambda query, params: json.dumps({"id": params["id"]}),
        scalars=lambda query: [rows[3964]])
    result = c05.historical_evidence(session)
    assert result == json.loads(c05.encoded(result))
    assert result["rows"][0]["luck_p_value"] == "0.263874"
    assert result["rows"][1]["luck_p_value"] is None


def sessions():
    return [MarketSession.from_api({"date": day, "settlement_date": settled,
        "open": "09:30", "close": "16:00"}) for day, settled in [
        ("2026-10-01", "2026-10-02"), ("2026-10-02", "2026-10-05"),
        ("2026-10-09", "2026-10-13"), ("2026-10-12", "2026-10-13"),
        ("2026-10-13", "2026-10-14"), ("2026-10-14", "2026-10-15")]]


def quotes(at="2026-10-01T18:00:00Z"):
    return {s: {"t": at, "bp": "100", "ap": "100.02"} for s in c05.SYMBOLS}


def test_all_five_quotes_are_reaged_at_common_batch_time():
    rows = quotes()
    rows["GLD"]["t"] = "2026-10-01T17:59:39Z"
    assert c05.quote_batch(rows, "2026-10-01T18:00:09Z", sessions())["all_fresh_regular"]
    result = c05.quote_batch(rows, "2026-10-01T18:00:10Z", sessions())
    assert not result["all_fresh_regular"]
    assert result["quotes"]["GLD"]["age_seconds"] == 31
    assert result["quotes"]["DBA"]["fresh"]
    assert not result["fill_evidence"] and not result["opening_reference"]
    assert not result["risk_marks_complete_for_other_strategies"]


def test_incomplete_future_and_closed_session_quotes_are_not_admitted():
    rows = quotes()
    del rows["DBA"]
    with pytest.raises(ValueError, match="five-symbol"):
        c05.quote_batch(rows, "2026-10-01T18:00:00Z", sessions())
    assert not c05.quote_batch(quotes("2026-10-01T18:00:01Z"), "2026-10-01T18:00:00Z", sessions())["all_fresh_regular"]
    assert not c05.quote_batch(quotes("2026-10-01T21:00:00Z"), "2026-10-01T21:00:00Z", sessions())["all_fresh_regular"]
    assert not c05.quote_batch(quotes("2026-10-01T13:29:50Z"), "2026-10-01T13:30:05Z", sessions())["all_fresh_regular"]
    assert c05.quote_batch(quotes("2026-10-01T13:30:00Z"), "2026-10-01T13:30:05Z", sessions())["all_fresh_regular"]


def fills():
    return [
        {"id": "a", "symbol": "DBA", "fill_at": "2026-10-01T13:30:00Z", "side": "buy", "quantity": "0.8", "price": "25"},
        {"id": "b", "symbol": "DBA", "fill_at": "2026-10-02T13:30:00Z", "side": "sell", "quantity": "0.8", "price": "26"},
        {"id": "c", "symbol": "DBA", "fill_at": "2026-10-02T13:30:00Z", "side": "buy", "quantity": "0.2", "price": "26"},
    ]


def event():
    return {"symbol": "DBA", "ex_date": "2026-10-02", "record_date": "2026-10-02",
            "payable_date": "2026-10-09", "amount_per_share": "0.5", "currency": "USD",
            "kind": "ordinary_cash", "source_observed_at": "2026-10-01T17:00:00Z", "source_sha256": "a" * 64}


def entitlement():
    return c05.distribution_entitlement(event(), fills(), sessions(), "2026-10-02T14:00:00Z")


def test_prior_owner_entitled_even_if_sold_at_ex_open_and_new_buyer_is_not():
    row = entitlement()
    assert row["quantity_before_ex_open"] == "0.8" and row["cash_amount"] == "0.40"
    assert not row["execution_fill"] and not row["broker_credit_verified"]
    assert c05.quantity_before_ex_open("DBA", fills()[1:2], "2026-10-02T13:30:00Z") == 0
    assert c05.quantity_before_ex_open("DBA", fills()[2:], "2026-10-02T13:30:00Z") == 0
    assert row["modeled_release_at"] == "2026-10-12T09:30:00-04:00"
    # A vendor row using record date must reconcile to this same ex-date event.
    variant = {**event(), "record_date": "2026-10-05"}
    assert c05.distribution_entitlement(variant, fills(), sessions(), "2026-10-02T14:00:00Z")["event_id"] == row["event_id"]


def test_receivable_waits_until_open_after_payable_and_never_becomes_broker_cash():
    row = entitlement()
    before = c05.distribution_balances([row], now="2026-10-12T13:29:59Z")
    after = c05.distribution_balances([row], now="2026-10-12T13:30:00Z")
    assert before["receivable_usd"] == "0.40" and before["modeled_payable_cash_usd"] == "0"
    assert after["receivable_usd"] == "0" and after["modeled_payable_cash_usd"] == "0.40"
    assert after["broker_credit_verified_usd"] == "0" and not after["may_increase_shared_cash_book"]
    with pytest.raises(ValueError, match="Duplicate distribution"):
        c05.distribution_balances([row, row], now="2026-10-12T14:00:00Z")
    with pytest.raises(ValueError, match="differs from entitlement"):
        c05.distribution_balances([{**row, "cash_amount": "2"}], now="2026-10-12T14:00:00Z")


@pytest.mark.parametrize("changes", [
    {"currency": "GBP"}, {"kind": "stock_dividend"}, {"payable_date": "2026-10-01"},
    {"source_sha256": "missing"}, {"source_observed_at": "2026-10-02T13:30:01Z"},
    {"symbol": "QQQ"},
])
def test_unsupported_or_late_distribution_cannot_backdate_entitlement(changes):
    with pytest.raises(ValueError):
        c05.distribution_entitlement({**event(), **changes}, fills(), sessions(), "2026-10-02T14:00:00Z")


def test_duplicate_ownership_rows_and_future_recognition_are_rejected():
    with pytest.raises(ValueError, match="Duplicate"):
        c05.quantity_before_ex_open("DBA", fills() + [fills()[0]], "2026-10-02T13:30:00Z")
    with pytest.raises(ValueError, match="not yet recognized"):
        c05.distribution_entitlement(event(), fills(), sessions(), "2026-10-01T20:00:00Z")


def test_cash_bridge_keeps_settlement_holiday_and_reservations():
    movements = [
        {"id": "buy", "fill_at": "2026-10-01T13:30:00Z", "side": "buy", "notional": "100", "fee": ".01"},
        {"id": "sell", "fill_at": "2026-10-09T13:30:00Z", "side": "sell", "notional": "101", "fee": ".03",
         "cash_release_at": "2026-10-14T13:30:00Z"},
    ]
    assert c05.c05_trade_cash("140", movements, "5", "2026-10-13T13:30:00Z") == D("34.96")
    assert c05.c05_trade_cash("140", iter(movements), "5", "2026-10-13T13:30:00Z") == D("34.96")
    assert c05.c05_trade_cash("140", movements, "5", "2026-10-14T13:30:00Z") == D("135.96")
    with pytest.raises(ValueError, match="Duplicate"):
        c05.c05_trade_cash("140", movements + [movements[1]], "0", "2026-10-14T13:30:00Z")
    del movements[1]["cash_release_at"]
    with pytest.raises(KeyError):
        c05.c05_trade_cash("140", movements, "0", "2026-10-14T13:30:00Z")


def test_modeled_fees_share_one_five_sleeve_book_and_do_not_claim_broker_charge():
    rows = [{"id": s, "symbol": s, "fill_at": "2026-10-01T13:30:00Z",
             "side": "buy", "quantity": "0.1", "price": "100"} for s in c05.SYMBOLS]
    result = c05.fee_scenario(rows)
    assert result["total_usd"] == "0.01"  # daily CAT rounds once, not once per sleeve
    assert not result["broker_charged_fees"]
    with pytest.raises(ValueError, match="Duplicate"):
        c05.fee_scenario(rows + [rows[0]])


class NoBudget:
    def __init__(self, *args):
        pass
    def check(self, *args):
        pass


def capture_fixture(monkeypatch):
    writes = {}
    monkeypatch.setattr(c05, "CaptureDiskBudget", NoBudget)
    def save(path, value, **kwargs):
        writes[path.name] = json.loads(c05.encoded(value))
        return {"path": path.name, "sha256": "fixture"}
    monkeypatch.setattr(c05, "write_once", save)
    return writes


class PaperAPI:
    def account(self):
        return {"status": "ACTIVE", "currency": "USD", "id": "private-id", "account_number": "private-number",
                "cash": "100000", "buying_power": "200000", "trading_blocked": False,
                "account_blocked": False, "trade_suspended_by_user": False}
    def asset(self, symbol):
        return {"id": "public-asset-id", "symbol": symbol, "class": "us_equity", "status": "active",
                "fractionable": True, "tradable": True, "exchange": "ARCA"}
    def calendar_range(self, start, end):
        return [{"date": "2026-10-01", "settlement_date": "2026-10-02", "open": "09:30", "close": "16:00"}]
    def quote(self, symbol):
        return {"bp": "100", "ap": "100.02", "t": datetime.now(UTC).isoformat()}
    def submit(self, *args):
        raise AssertionError("Readiness cannot submit")
    def cancel(self, *args):
        raise AssertionError("Readiness cannot cancel")


def test_account_bound_five_asset_capture_redacts_identity_and_enforces_fractional(monkeypatch, tmp_path):
    writes = capture_fixture(monkeypatch)
    probes, _, _ = c05.capture_paper(PaperAPI(), tmp_path, date(2026, 10, 1), date(2026, 11, 1),
                                    expected_account=c05.digest(b"private-id"))
    assert probes["account"]["audit"]["matches_existing_cash_book"]
    assert "private" not in json.dumps(writes)
    assert all(probes["asset-" + s]["audit"]["eligible_fractional_us_equity"] for s in c05.SYMBOLS)
    class Bad(PaperAPI):
        def asset(self, symbol):
            return {**super().asset(symbol), "fractionable": symbol != "DBA"}
    probes, _, _ = c05.capture_paper(Bad(), tmp_path, date(2026, 10, 1), date(2026, 11, 1), expected_account="wrong")
    assert "error" in probes["account"] and "error" in probes["asset-DBA"]
    with pytest.raises(ValueError, match="binding"):
        c05.capture_paper(PaperAPI(), tmp_path, date(2026, 10, 1), date(2026, 11, 1), expected_account=None)


def test_remote_error_messages_are_never_written(monkeypatch, tmp_path):
    writes = capture_fixture(monkeypatch)
    class Bad(PaperAPI):
        def account(self):
            raise RuntimeError("private-secret-account-id")
    probes, _, _ = c05.capture_paper(Bad(), tmp_path, date(2026, 10, 1), date(2026, 11, 1), expected_account="bound")
    assert probes["account"]["error"] == "RuntimeError"
    assert "private-secret" not in json.dumps(writes)


def test_nontrade_pages_are_bounded_deduplicated_and_empty_is_not_payment(monkeypatch, tmp_path):
    writes = capture_fixture(monkeypatch)
    calls = []
    class API:
        def nontrade_activities(self, after, until, cursor):
            calls.append(cursor)
            if len(calls) > 1:
                return []
            return [{"id": f"private-{n}", "activity_type": "DIV", "symbol": "DBA", "date": "2026-09-01",
                     "qty": "1", "net_amount": "0.5", "description": "private text"} for n in range(100)]
    result = c05.capture_nontrade(API(), tmp_path, timestamp("2026-01-01T00:00:00Z"), timestamp("2026-10-01T00:00:00Z"))
    assert result["exhausted"] and result["records"] == 100 and calls == [None, "private-99"]
    assert not result["broker_dividend_fidelity"] and "private" not in json.dumps(writes)
    class Empty:
        def nontrade_activities(self, *args):
            return []
    result = c05.capture_nontrade(Empty(), tmp_path, timestamp("2026-01-01T00:00:00Z"), timestamp("2026-10-01T00:00:00Z"))
    assert result["records"] == 0 and result["empty_is_not_no_entitlement"]
    class Repeated:
        def nontrade_activities(self, *args):
            return [{"id": "same", "activity_type": "DIV"}] * 2
    with pytest.raises(ValueError, match="Repeated or conflicting"):
        c05.capture_nontrade(Repeated(), tmp_path, timestamp("2026-01-01T00:00:00Z"), timestamp("2026-10-01T00:00:00Z"))


def test_action_capture_exact_universe_all_types_and_pagination(monkeypatch, tmp_path):
    capture_fixture(monkeypatch)
    calls = []
    def api(request):
        calls.append(request.params)
        return json.dumps({"corporate_actions": {}, "next_page_token": "next" if len(calls) == 1 else None})
    result = c05.capture_actions(api, tmp_path, date(2026, 1, 1), date(2026, 12, 1))
    assert set(calls[0]["symbols"].split(",")) == set(c05.SYMBOLS)
    assert "types" not in calls[0] and calls[0]["data_quality"] == "all"
    assert result["exhausted"] and result["empty_is_not_action_clearance"]
    assert not result["issuer_review_complete"]
    with pytest.raises(ValueError, match="loop"):
        c05.capture_actions(lambda request: '{"corporate_actions":{},"next_page_token":"repeat"}', tmp_path,
                            date(2026, 1, 1), date(2026, 12, 1))


def close_source():
    # Pure synthetic exchange calendar, not a real holiday model.
    dates = [date(2026, 1, 1) + timedelta(days=n) for n in range(127)]
    cal = [MarketSession.from_api({"date": str(d), "settlement_date": str(d + timedelta(days=1)),
                                  "open": "09:30", "close": "16:00"}) for d in dates]
    result = {"meta": {"symbol": "DBA", "currency": "USD"},
              "timestamp": [int(s.opens_at.timestamp()) for s in cal],
              "indicators": {"quote": [{"close": [25] * 127}], "adjclose": [{"adjclose": [24] * 127}]},
              "events": {"dividends": {}}}
    return cal, result


def test_close_window_is_exactly_127_completed_same_vintage_without_signal():
    cal, result = close_source()
    now = cal[-1].closes_at + timedelta(seconds=1)
    raw = c05.encoded({"chart": {"result": [result]}})
    evidence = c05.close_window_evidence(raw, "DBA", cal, now)
    assert evidence["completed_closes"] == 127 and evidence["single_adjustment_vintage"]
    assert not evidence["signal_computed"] and not evidence["signal_admitted"]
    with pytest.raises(ValueError, match="127 completed"):
        c05.close_window_evidence(raw, "DBA", cal, cal[-1].closes_at)
    result["timestamp"][-1] = result["timestamp"][-2]
    with pytest.raises(ValueError, match="repeated close"):
        c05.close_window_evidence(c05.encoded({"chart": {"result": [result]}}), "DBA", cal, now)


def test_close_window_missing_day_or_adjusted_price_never_fills_forward():
    cal, result = close_source()
    result["indicators"]["adjclose"][0]["adjclose"].pop()
    with pytest.raises(ValueError, match="Incomplete"):
        c05.close_window_evidence(c05.encoded({"chart": {"result": [result]}}), "DBA", cal,
                                  cal[-1].closes_at + timedelta(seconds=1))


def ledger_fixture(tmp_path, monkeypatch, strategy_id):
    monkeypatch.setattr(c05, "ROOT", tmp_path)
    monkeypatch.setattr(c05, "ARCHIVE", tmp_path / "captures")
    history = {"rows": [{"strategy_id": strategy_id}, {"strategy_id": strategy_id}]}
    monkeypatch.setattr(c05, "historical_evidence", lambda session: history)
    monkeypatch.setattr(c05, "dependencies", lambda: {"fixture": "bound"})
    path = c05.ARCHIVE / "one" / "readiness.json"
    path.parent.mkdir(parents=True)
    probes = {"account": {"error": "ProbeHalted"}, "calendar": {"error": "ProbeHalted"}}
    probes.update({f"{kind}-{s}": {"error": "ProbeHalted"} for kind in ("asset", "quote") for s in c05.SYMBOLS})
    children = {**probes, "quote-batch": {}}
    receipts = []
    for name, value in children.items():
        child = path.parent / (name + ".json")
        child.write_bytes(c05.encoded(value))
        receipts.append({"path": str(child.relative_to(tmp_path)), "sha256": c05.digest(child.read_bytes())})
    report = {"schema": c05.NAME, "decision": "hold_before_ordering_paper", "orders_submitted": 0,
              "ready_for_live": False, "paper_runner_activated": False, "signals_computed": False,
              "dependency_sha256": c05.dependencies(), "symbols": list(c05.SYMBOLS),
              "historical_evidence": history, "git_commit": "synthetic", "blockers": ["fixture"],
              "probe_failures": [], "started_at": "2026-10-01T18:00:00Z", "completed_at": "2026-10-01T18:01:00Z",
              "receipts": receipts, "paper_probes": probes, "quote_batch": {},
              "close_sources": {s: {"error": "ProbeHalted"} for s in c05.SYMBOLS},
              "public_documentation": {k: {"error": "ProbeHalted"} for k in c05.PUBLIC},
              "nontrade_activities": {"error": "ProbeHalted", "exhausted": False},
              "corporate_actions": {"error": "ProbeHalted", "exhausted": False},
              "api_budget": {"halted": True}}
    report["probe_failures"] = list(probes) + ["common_time_five_quote_batch"] + [
        "closes-" + s for s in c05.SYMBOLS] + ["nontrade", "actions"] + list(c05.PUBLIC)
    child = path.parent / "source-summary.json"
    child.write_bytes(c05.encoded({key: report[key] for key in c05.SUMMARY_KEYS}))
    receipts.append({"path": str(child.relative_to(tmp_path)), "sha256": c05.digest(child.read_bytes())})
    path.write_bytes(c05.encoded(report))
    return path, report


@pytest.mark.parametrize("corruption", ["missing", "tampered", "outside", "unlisted", "inline"])
def test_child_receipts_must_be_complete_confined_and_hash_bound(tmp_path, monkeypatch, corruption):
    path, report = ledger_fixture(tmp_path, monkeypatch, 0)
    c05.verify_receipts(report, path.parent)
    target = path.parent / "asset-DBA.json"
    if corruption == "missing":
        target.unlink()
    elif corruption == "tampered":
        target.write_text('{"changed":true}')
    elif corruption == "outside":
        other = tmp_path / "outside.json"
        other.write_text('{}')
        report["receipts"][0] = {"path": "outside.json", "sha256": c05.digest(other.read_bytes())}
    elif corruption == "unlisted":
        (path.parent / "unlisted.json").write_text('{}')
    else:
        report["paper_probes"]["asset-DBA"] = {"changed": True}
    with pytest.raises(ValueError):
        c05.verify_receipts(report, path.parent)


def test_failed_preparation_is_idempotent_no_results_no_promotion(tmp_path, monkeypatch):
    connection = get_engine().connect()
    outer = connection.begin()
    session = Session(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
    try:
        strategy = Strategy(key="c05-readiness-test-" + uuid4().hex, name="Readiness test", status="backtest")
        session.add(strategy)
        session.flush()
        path, report = ledger_fixture(tmp_path, monkeypatch, strategy.id)
        iid = c05.record_failed_preparation(session, path)
        session.commit()
        assert c05.record_failed_preparation(session, path) == iid
        row = session.get(Trial, iid)
        assert row.status == "failed" and row.mode == "paper" and row.trade_count == 0
        assert row.pnl is None and row.pnl_after_fees is None and row.fees_total is None
        assert row.max_drawdown is None and row.luck_p_value is None
        assert not row.final_holdout and row.strategy_version is None
        assert strategy.status == "backtest" and strategy.allocation_usd == 0
        report["ready_for_live"] = True
        path.write_bytes(c05.encoded(report))
        with pytest.raises(ValueError, match="non-ordering"):
            c05.record_failed_preparation(session, path)
        report["ready_for_live"] = False
        report["historical_evidence"] = {"changed": True}
        path.write_bytes(c05.encoded(report))
        with pytest.raises(ValueError, match="Historical evidence"):
            c05.record_failed_preparation(session, path)
    finally:
        session.close()
        assert outer.is_active
        outer.rollback()
        connection.close()


def test_capture_cannot_write_outside_owned_archive(tmp_path):
    with pytest.raises(ValueError, match="new directory"):
        c05.capture_readiness(tmp_path)


def test_api_error_budget_is_shared_and_latches_after_fifth_error(monkeypatch, tmp_path):
    capture_fixture(monkeypatch)
    api, invoked, budget = PaperAPI(), [], c05.ProbeBudget(clock=lambda: 0)
    def fail():
        invoked.append(True)
        raise OSError("sensitive remote exception body")
    api.account = fail
    api.calendar_range = lambda *args: fail()
    api.asset = lambda *args: fail()
    values, _, _ = c05.capture_paper(api, tmp_path, date(2026, 1, 1), date(2026, 12, 1),
                                   expected_account="bound", budget=budget)
    assert len(invoked) == budget.attempts == 5 and budget.halted
    assert values["asset-UNG"]["error"] == "ProbeHalted"
    assert values["quote-DBA"]["error"] == "ProbeHalted"
    with pytest.raises(c05.ProbeHalted):
        c05.capture_actions(lambda request: pytest.fail("request six"), tmp_path,
                            date(2026, 1, 1), date(2026, 12, 1), budget=budget)
    with pytest.raises(c05.ProbeHalted):
        c05.capture_http(tmp_path, "paper-specification", c05.PUBLIC["paper-specification"], budget=budget)
    assert "sensitive" not in json.dumps(values)


def test_api_error_window_drops_old_errors_before_threshold():
    now = [0]
    budget = c05.ProbeBudget(clock=lambda: now[0])
    for _ in range(4):
        budget.failure()
    now[0] = 61
    budget.failure()
    assert not budget.halted and budget.errors == [61]


@pytest.mark.parametrize("section", c05.SUMMARY_KEYS)
def test_source_summary_sections_cannot_be_omitted_or_changed(tmp_path, monkeypatch, section):
    path, report = ledger_fixture(tmp_path, monkeypatch, 0)
    del report[section]
    with pytest.raises(ValueError, match="source summaries"):
        c05.verify_receipts(report, path.parent)


@pytest.mark.parametrize("mutation", ["rawhash", "pagepath", "pagehash", "publicstatus", "failures"])
def test_source_summary_mutations_do_not_pass(tmp_path, monkeypatch, mutation):
    path, report = ledger_fixture(tmp_path, monkeypatch, 0)
    if mutation == "rawhash":
        report["close_sources"]["DBA"] = {"raw_sha256": "0" * 64}
    elif mutation in {"pagepath", "pagehash"}:
        report["corporate_actions"] = {"pages": [{"path": "outside.json", "sha256": "changed"}]}
    elif mutation == "publicstatus":
        report["public_documentation"]["fee-schedule"] = {"status_code": 200}
    else:
        report["probe_failures"] = []
    with pytest.raises(ValueError, match="source summaries"):
        c05.verify_receipts(report, path.parent)


@pytest.mark.parametrize("corruption", [None, "close", "actions", "nontrade", "public"])
def test_successful_source_summaries_reconcile_to_raw_children(tmp_path, monkeypatch, corruption):
    path, report = ledger_fixture(tmp_path, monkeypatch, 0)
    directory = path.parent
    def save(name, value, raw=False):
        child = directory / name
        child.write_bytes(value if raw else c05.encoded(value))
        ref = {"path": str(child.relative_to(tmp_path)), "sha256": c05.digest(child.read_bytes())}
        report["receipts"] = [r for r in report["receipts"] if r["path"] != ref["path"]] + [ref]
        return ref
    cal, source = close_source()
    now = cal[-1].closes_at + timedelta(seconds=1)
    report["paper_probes"]["calendar"] = {"response": [{"date": str(s.trade_date),
        "open": "09:30", "close": "16:00", "settlement_date": str(s.settlement_date)} for s in cal]}
    save("calendar.json", report["paper_probes"]["calendar"])
    report["probe_failures"].remove("calendar")
    raw = c05.encoded({"chart": {"result": [source]}})
    meta = {"request_url": c05.YAHOO_CHART.format(symbol="DBA"), "status_code": 200,
            "raw_sha256": c05.digest(raw), "bytes": len(raw), "observed_at": now.isoformat(),
            "params": {"period2": int((now + timedelta(days=1)).timestamp())}}
    save("closes-DBA.raw", raw, raw=True)
    save("closes-DBA.json", meta)
    report["close_sources"]["DBA"] = c05.close_window_evidence(raw, "DBA", cal, now)
    report["probe_failures"].remove("closes-DBA")
    action_raw = '{"corporate_actions": {}, "next_page_token": null}'
    page = save("actions-0.json", {"raw_response": action_raw,
        "raw_response_sha256": c05.digest(action_raw.encode()), "response": json.loads(action_raw)})
    report["corporate_actions"] = {"pages": [page], "records": 0, "exhausted": True}
    report["probe_failures"].remove("actions")
    page = save("nontrade-0.json", {"response": []})
    report["nontrade_activities"] = {"pages": [page], "records": 0, "c05_records": [], "exhausted": True}
    report["probe_failures"].remove("nontrade")
    meta = {"request_url": c05.PUBLIC["fee-schedule"], "status_code": 200,
            "raw_sha256": c05.digest(b"fixture"), "bytes": 7}
    save("fee-schedule.json", meta)
    save("fee-schedule.raw", b"fixture", raw=True)
    report["public_documentation"]["fee-schedule"] = dict(meta)
    report["probe_failures"].remove("fee-schedule")
    if corruption == "close":
        report["close_sources"]["DBA"]["raw_sha256"] = "f" * 64
    elif corruption == "actions":
        report["corporate_actions"]["pages"][0] = {"path": "outside.json", "sha256": "changed"}
    elif corruption == "nontrade":
        report["nontrade_activities"]["records"] = 1
    elif corruption == "public":
        report["public_documentation"]["fee-schedule"]["status_code"] = 500
    save("source-summary.json", {key: report[key] for key in c05.SUMMARY_KEYS})
    if corruption:
        with pytest.raises(ValueError):
            c05.verify_receipts(report, directory)
    else:
        c05.verify_receipts(report, directory)
