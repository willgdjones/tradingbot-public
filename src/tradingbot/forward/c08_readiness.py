"""C08 read-only capture and explicit ledger receipt. Never submits orders.

Capture uses existing paper credentials and public dated EIA evidence. A capture
is an immutable readiness receipt, not a paper experiment or proof of execution.
"""
from __future__ import annotations

import argparse
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal as D
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import urljoin, urlparse

from sqlalchemy import select, text

from tradingbot.connectors.alpaca_api import AlpacaPaperAPI
from tradingbot.connectors.alpaca_paper import ACTIVE, NAME as CONNECTOR, AlpacaPaperConnector
from tradingbot.connectors.cash import CashMovement, MarketSession, NEW_YORK, cash_balance, timestamp
from tradingbot.data.alpaca_history import ACTIONS, AlpacaHistoryAPI
from tradingbot.data.archive import Request
from tradingbot.data.disk_budget import CaptureDiskBudget
from tradingbot.db.models import Fill, Instrument, Order, Position, Strategy, Trial, Venue
from tradingbot.db.session import SessionLocal
from tradingbot.research.c08_blackout import (
    STOCK_DEFINITION, capture, dated_attachment_urls, pdf_stock_check, pdf_text, stock_fields,
)
from tradingbot.research.c08_source_audit import EIA_ROOT, Links, document_text, eia_layout, load_capture
from tradingbot.risk import limits

ROOT = Path(__file__).resolve().parents[3]
ARCHIVE = ROOT / "data/forward/c08-readiness"
NAME = "c08_forward_readiness_v1"
VERSION = "739e205972e6208c07c0fc0618946a1813a877e7c775d4d737237f54c9183376"
SOURCE = "63c4d561929099ae039a8a67a0deace1991b08d6e3dacef55c6c2de481b99ca5"
REACTOR = "599442d4d877d32c5a1a82edd0abcc1036cc2ff8b10f62ae00201dddd69f87cc"
ZERO = D(0)


def digest(body):
    return sha256(body).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2, default=str) + "\n").encode()


def write_once(path, value):
    raw = encoded(value)
    with CaptureDiskBudget(ROOT / "data").reserve(3 * len(raw) + 65536):
        with Path(path).open("xb") as output:
            output.write(raw)
    return {"path": str(Path(path).relative_to(ROOT)), "sha256": digest(raw)}


def first_eligible_open(release_date, validated_at, sessions):
    """Never backdate a newly collected/validated report to an earlier open."""
    validated_at = timestamp(validated_at)
    boundary = datetime.combine(release_date + timedelta(days=1), time.min, NEW_YORK)
    if release_date > validated_at.astimezone(NEW_YORK).date():
        raise ValueError("Future-dated publication")
    available = max(boundary, validated_at)
    opens = [s.opens_at for s in sessions if s.opens_at > available]
    if not opens:
        raise ValueError("Calendar does not cover the next eligible open")
    return available, min(opens)


def release_after_completion(completed_on, sessions):
    """The evaluated C08 policy: first regular open AFTER completion date.

    completed_on must come from documented settlement evidence. A nominal T+1
    label alone is not evidence of completion and must not be passed as such.
    """
    opens = [s.opens_at for s in sessions if s.trade_date > completed_on]
    if not opens:
        raise ValueError("Calendar does not cover post-completion cash release")
    return min(opens)


def conservative_cash(initial, movements, reserved, now):
    """Independent C08 spendability bridge for a future runner.

    Each row supplies actual fill time, side, notional, fee and (for sells) an
    explicit audited release timestamp. No missing release falls back to T+1.
    Fee estimates may exceed actual broker fees, but must never double count.
    """
    now = timestamp(now)
    cash = D(initial)
    reserve = D(reserved)
    if any(not x.is_finite() or x < 0 for x in (cash, reserve)):
        raise ValueError("Invalid initial cash or reservation")
    for row in movements:
        fill_at = timestamp(row["fill_at"])
        if fill_at > now:
            raise ValueError("Future fill in cash evidence")
        notional, fee = D(row["notional"]), D(row["fee"])
        if any(not x.is_finite() or x < 0 for x in (notional, fee)):
            raise ValueError("Invalid cash movement")
        cash -= fee
        if row["side"] == "buy":
            cash -= notional
        elif row["side"] == "sell":
            release = timestamp(row["cash_release_at"])
            if release <= fill_at:
                raise ValueError("Sale cash cannot precede settlement completion")
            if now >= release:
                cash += notional
        else:
            raise ValueError("Invalid cash side")
    return max(ZERO, cash - reserve)


def quote_evidence(row, observed_at):
    at = timestamp(row["t"])
    bid, ask = D(str(row["bp"])), D(str(row["ap"]))
    if any(not x.is_finite() or x <= 0 for x in (bid, ask)) or ask < bid:
        raise ValueError("Invalid IEX market")
    age = (timestamp(observed_at) - at).total_seconds()
    return {"feed": "iex", "quote_at": at.isoformat(), "observed_at": observed_at.isoformat(),
            "bid": str(bid), "ask": str(ask), "age_seconds": age,
            "fresh": 0 <= age <= limits.STALE_DATA_MAX_SECONDS,
            "at_session_open": False, "fill_evidence": False}


def historical_evidence(session):
    """Only read recorded trial rows. No research runner import or feed iteration."""
    session.execute(text("SET LOCAL TIME ZONE 'UTC'"))
    if digest((ROOT / "src/tradingbot/strategy/c08_inventory.py").read_bytes()) != REACTOR:
        raise ValueError("C08 evaluated reactor changed")
    rows = []
    for iid, final in ((3907, False), (3910, True)):
        trial = session.get(Trial, iid)
        if (trial is None or trial.mode != "backtest" or trial.status != "complete"
                or trial.strategy_version != VERSION or trial.final_holdout != final
                or trial.pnl_after_fees is None or trial.pnl_after_fees <= 0):
            raise ValueError("Frozen profitable C08 evidence is absent or changed")
        params = trial.params
        identity = params.get("_holdout", {}).get("identity", {})
        if (identity.get("key") != "sweep_c08_inventory_blackout_v1"
                or identity.get("execution_params", {}).get("run", {}).get("cost_bp_per_side") != 10
                or identity.get("code", {}).get("strategy/c08_inventory.py") != REACTOR):
            raise ValueError("C08 historical execution identity changed")
        for key, value in {"threshold": "-0.05", "target_weight": ".95", "slot_usd": "140",
                           "buy_fee_reserve_usd": ".01", "quantity_step": ".000000001",
                           "source_receipt": SOURCE}.items():
            if params.get(key) != value:
                raise ValueError("Frozen C08 parameters changed")
        raw = session.scalar(text("SELECT row_to_json(t)::text FROM trials t WHERE id=:id"), {"id": iid})
        rows.append({"trial_id": iid, "strategy_id": trial.strategy_id,
                     "full_row_sha256": digest(raw.encode()), "final_holdout": final,
                     "dataset_key": trial.dataset_key, "holdout_start": trial.holdout_start.isoformat(),
                     "net_usd": str(trial.pnl_after_fees), "fees_usd": str(trial.fees_total),
                     "round_trips": trial.trade_count, "max_drawdown_usd": str(trial.max_drawdown),
                     "luck_p_value": trial.luck_p_value})
    if rows[0]["dataset_key"] != rows[1]["dataset_key"] or rows[0]["holdout_start"] != rows[1]["holdout_start"]:
        raise ValueError("C08 training/final identity mismatch")
    finals = list(session.scalars(select(Trial.id).where(Trial.strategy_version == VERSION, Trial.final_holdout)))
    if finals != [3910]:
        raise ValueError("Unexpected C08 final attempt")
    return {"strategy_version": VERSION, "reactor_sha256": REACTOR, "source_receipt": SOURCE,
            "rows": rows, "final_attempt_ids": finals, "replayed": False,
            "threshold": "-0.05", "slot_usd": "140", "target_weight": ".95"}


def local_paper_evidence(session, now):
    venue = session.scalar(select(Venue).where(Venue.key == "alpaca"))
    if venue is None or not (venue.metadata_ or {}).get(CONNECTOR):
        raise ValueError("Existing Alpaca paper cash book absent")
    book = venue.metadata_[CONNECTOR]
    orders = list(session.scalars(select(Order).join(Instrument).where(
        Instrument.venue_id == venue.id, Order.mode == "paper")))
    fills = list(session.scalars(select(Fill).join(Instrument).where(
        Instrument.venue_id == venue.id, Fill.mode == "paper")))
    if any((r.metadata_ or {}).get("connector") != CONNECTOR for r in [*orders, *fills]):
        raise ValueError("Unmanaged paper cash activity")
    reserved = sum(((o.size - o.filled_size) * o.limit_price for o in orders
                    if o.status in ACTIVE and o.side == "buy"), ZERO)
    movements = [CashMovement(f.side, f.price * f.size, f.fee,
                 date.fromisoformat(f.metadata_["settlement_date"])) for f in fills]
    cash = cash_balance(D(book["initial_cash"]), movements, reserved, now)
    running = list(session.scalars(select(Trial).join(Strategy).where(
        Strategy.venue_id == venue.id, Trial.mode == "paper", Trial.status == "running")))
    positions = list(session.scalars(select(Position).join(Instrument).where(
        Instrument.venue_id == venue.id, Position.mode == "paper", Position.status == "open")))
    return {"as_of": now.isoformat(), "initial_virtual_cash": book["initial_cash"],
            "account_fingerprint": book["account"],  # removed before the report is written
            "available_under_existing_connector": str(cash.available), "reserved": str(cash.reserved),
            "unsettled": str(cash.unsettled), "orders": len(orders), "fills": len(fills),
            "open_positions": len(positions), "running_paper_trials": [t.id for t in running],
            "cash_scope": "one venue-wide book, not an independent $140 for each strategy",
            "c08_settlement_fidelity": False,
            "difference": "connector releases at NY settlement-date midnight; C08 first open after completion date"}


def capture_paper(api, directory, start, through, *, expected_account=None):
    receipts, values = {}, {}
    calls = {"account": api.account, "asset": lambda: api.asset("USO"),
             "calendar": lambda: api.calendar_range(start, through), "quote": lambda: api.quote("USO")}
    for key, call in calls.items():
        began = datetime.now(UTC)
        try:
            value = call()
            audit = None
            # Never save account numbers, credentials, or complete account response.
            if key == "account":
                AlpacaPaperConnector._account_ok(value)
                audit = {"connector_account_checks_pass": True,
                         "matches_existing_cash_book": (AlpacaPaperConnector._fingerprint(value) == expected_account
                                                        if expected_account is not None else None)}
                value = {k: value.get(k) for k in ("status", "currency", "trading_blocked", "account_blocked", "trade_suspended_by_user")}
            elif key == "asset":
                value = {k: value.get(k) for k in ("symbol", "status", "tradable", "fractionable", "exchange")}
            ended = datetime.now(UTC)
            body = {"started_at": began, "observed_at": ended, "response": value}
            if audit is not None:
                body["audit"] = audit
            if key == "quote":
                body["audit"] = quote_evidence(value, ended)
            values[key] = body
        except Exception as exc:
            values[key] = {"started_at": began, "observed_at": datetime.now(UTC), "error": type(exc).__name__}
        receipts[key] = write_once(directory / (key + ".json"), values[key])
    return values, receipts


def capture_actions(api, directory, start, through):
    pages, token, seen, count = [], None, set(), 0
    for number in range(20):
        params = {"symbols": "USO", "start": start.isoformat(), "end": through.isoformat(),
                  "data_quality": "all", "limit": 1000, "sort": "asc"}
        if token:
            params["page_token"] = token
        raw = api(Request(ACTIONS + "/corporate-actions", params))
        row = json.loads(raw)
        groups = row["corporate_actions"]
        if not isinstance(groups, dict) or any(not isinstance(v, list) for v in groups.values()):
            raise ValueError("Unexpected corporate-action response")
        count += sum(len(v) for v in groups.values())
        pages.append(write_once(directory / f"actions-{number}.json", {
            "request": params, "observed_at": datetime.now(UTC), "response": row}))
        token = row.get("next_page_token")
        if not token:
            return {"pages": pages, "records": count, "exhausted": True,
                    "advance_notice_guaranteed": False, "known_empty_is_no_future_guarantee": True}
        if token in seen:
            raise ValueError("Corporate-action pagination loop")
        seen.add(token)
    raise ValueError("Corporate-action page budget exhausted")


def latest_archive_url(raw, today):
    links = Links()
    links.feed(raw.decode("utf-8"))
    dated = []
    for href in links.hrefs:
        url = urljoin(EIA_ROOT, href)
        parsed = urlparse(url)
        match = re.fullmatch(r"/petroleum/supply/weekly/archive/(\d{4})/(\d{4}_\d{2}_\d{2})/wpsr_\2\.(php|html)", parsed.path)
        if not match:
            continue
        day = datetime.strptime(match[2], "%Y_%m_%d").date()
        if day > today or (today - day).days > 30:
            continue
        if parsed.scheme != "https" or parsed.netloc != "www.eia.gov" or parsed.query or parsed.fragment:
            raise ValueError("EIA archive link left primary source")
        if int(match[1]) != day.year:
            raise ValueError("EIA archive path years disagree")
        dated.append((day, url))
    if not dated:
        raise ValueError("No recent dated EIA archive publication")
    return max(dated)[1]  # link date selects a file; page/PDF establish publication


def capture_eia(directory, sessions):
    receipts = {}
    def get(key, url):
        receipts[key] = capture(key, url, archive=directory)
        receipt, raw = load_capture(directory / key, key, url)
        if receipt["status_code"] != 200 or urlparse(receipt["response_url"]).netloc != "www.eia.gov":
            raise ValueError("EIA source unavailable or redirected off primary host")
        return raw
    index = get("eia-index", EIA_ROOT)
    url = latest_archive_url(index, datetime.now(UTC).astimezone(NEW_YORK).date())
    page = get("eia-page", url)
    layout = eia_layout(page, url)
    csvs = dated_attachment_urls(page, url, "csv/table1.csv")
    pdfs = dated_attachment_urls(page, url, "pdf/table1.pdf")
    if len(csvs) != 1 or len(pdfs) != 1:
        raise ValueError("Dated Table 1 attachments missing")
    csv = get("eia-csv", csvs[0])
    get("eia-pdf", pdfs[0])
    fields = stock_fields(csv, date.fromisoformat(layout["observation_date"]))
    rendered = pdf_text(directory / "eia-pdf/raw")
    check = pdf_stock_check(rendered, fields)
    fields["units_verified"] = True
    if STOCK_DEFINITION not in " ".join(rendered.split()):
        raise ValueError("Commercial crude stock definition changed")
    validated = datetime.now(UTC)
    available, opens = first_eligible_open(date.fromisoformat(layout["release_date"]), validated, sessions)
    return {"layout": layout, "fields": fields, "pdf_check": check, "receipts": receipts,
            "validated_at": validated.isoformat(), "available_at": available.isoformat(),
            "earliest_eligible_open": opens.isoformat(), "source_url": url,
            "first_release_vintage_verified": False,
            "signal_admitted": False,
            "new_publication_notice_review_required": True,
            "signal_computed": False, "earlier_session_backfill_permitted": False}


def capture_readiness(directory):
    directory = directory.resolve()
    if not directory.is_relative_to(ARCHIVE) or directory == ARCHIVE:
        raise ValueError("Use a new capture directory under data/forward/c08-readiness")
    CaptureDiskBudget(ROOT / "data").check()
    directory.mkdir(parents=True, exist_ok=False)
    began = datetime.now(UTC)
    with SessionLocal() as session:
        session.execute(text("SET TRANSACTION READ ONLY"))
        history = historical_evidence(session)
        local = local_paper_evidence(session, began)
        expected_account = local.pop("account_fingerprint")
    api = AlpacaPaperAPI.from_env()
    try:
        paper, receipts = capture_paper(api, directory, began.date(), began.date() + timedelta(days=45),
                                        expected_account=expected_account)
    finally:
        api.close()
    api = AlpacaHistoryAPI()
    try:
        actions = capture_actions(api, directory, began.date() - timedelta(days=30), began.date() + timedelta(days=45))
    except Exception as exc:
        actions = {"error": type(exc).__name__, "exhausted": False}
    finally:
        api.close()
    try:
        sessions = [MarketSession.from_api(r) for r in paper["calendar"]["response"]]
        eia = capture_eia(directory, sessions)
    except Exception as exc:
        eia = {"error": type(exc).__name__, "admitted": False}
    ended = datetime.now(UTC)
    report = {"schema": NAME, "started_at": began, "completed_at": ended,
              "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
              "capture_code_sha256": digest(Path(__file__).read_bytes()),
              "historical_evidence": history, "local_paper": local, "paper_probes": paper,
              "probe_receipts": receipts, "corporate_actions": actions, "eia": eia,
              "decision": "hold_before_ordering_paper", "ready_for_live": False,
              "paper_runner_activated": False, "orders_submitted": 0,
              "blockers": ["C08 open/close runner and durable reactor state are not integrated",
                  "Conservative post-completion cash bridge is not integrated with actual broker activities",
                  "Issuer announcement review and dated action blackout watch are not operational",
                  "No C08 forward fills, fees, opening-slippage or forced-exit evidence yet"],
              "allocation_policy": "$140 maximum shared virtual book; no cash reset or increase"}
    report["probe_failures"] = [key for key, value in paper.items() if "error" in value]
    if paper.get("account", {}).get("audit", {}).get("matches_existing_cash_book") is not True:
        report["probe_failures"].append("paper_account_identity")
    if "error" in actions:
        report["probe_failures"].append("corporate_actions")
    if "error" in eia:
        report["probe_failures"].append("eia")
    report["report_receipt"] = write_once(directory / "readiness.json", report)
    return report


def record_failed_preparation(session, path):
    """Append a readiness failure; never modify or promote the historical row.

    Caller commits. A transaction lock and receipt-key check make explicit
    retries idempotent. No P&L, drawdown or trading result is invented.
    """
    path = path.resolve()
    if not path.is_relative_to(ARCHIVE) or path.name != "readiness.json":
        raise ValueError("Readiness receipt must be in the capture archive")
    raw = path.read_bytes()
    report = json.loads(raw)
    if (report.get("schema") != NAME or report.get("decision") != "hold_before_ordering_paper"
            or report.get("orders_submitted") != 0 or report.get("ready_for_live") is not False
            or report.get("paper_runner_activated") is not False
            or report.get("capture_code_sha256") != digest(Path(__file__).read_bytes())):
        raise ValueError("Receipt is not a current non-ordering readiness failure")
    history = historical_evidence(session)
    if history != report["historical_evidence"]:
        raise ValueError("Historical evidence changed since capture")
    receipt_hash = digest(raw)
    session.execute(text("SELECT pg_advisory_xact_lock(60427, 8)"))
    old = session.scalar(select(Trial).where(Trial.code_version == NAME,
        Trial.params["readiness_sha256"].as_string() == receipt_hash))
    if old:
        return old.id
    row = Trial(strategy_id=history["rows"][1]["strategy_id"], mode="paper", status="failed",
        code_version=NAME, git_commit=report["git_commit"],
        data_start=timestamp(report["started_at"]), data_end=timestamp(report["completed_at"]),
        completed_ts=datetime.now(UTC), trade_count=0,
        params={"readiness_sha256": receipt_hash, "readiness_path": str(path.relative_to(ROOT)),
                "training_trial": 3907, "historical_final_trial": 3910,
                "historical_strategy_version": VERSION, "threshold": "-0.05", "slot_usd": "140"},
        metrics={"readiness_only": True, "orders_submitted": 0, "promotion_eligible": False,
                 "blockers": report["blockers"], "probe_failures": report["probe_failures"]},
        notes="C08 forward preparation stopped before ordering: cash timing, action watch and durable open runner need integration. No strategy returns or final replay. docs/research/26-c08-forward-readiness.md")
    session.add(row)
    session.flush()
    return row.id


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--output", type=Path)
    operation.add_argument("--record-failed-preparation", type=Path)
    args = parser.parse_args()
    try:
        if args.record_failed_preparation:
            with SessionLocal() as session:
                trial_id = record_failed_preparation(session, args.record_failed_preparation)
                session.commit()
            print(json.dumps({"trial_id": trial_id, "status": "failed", "readiness_only": True}))
            return
        result = capture_readiness(args.output)
    except Exception as exc:
        # Remote exceptions may contain account-specific fields; never print them.
        print(json.dumps({"error": type(exc).__name__, "ready_for_live": False}))
        raise SystemExit(1) from None
    print(json.dumps({"receipt": result["report_receipt"], "decision": result["decision"],
                      "ready_for_live": False, "orders_submitted": 0}))


if __name__ == "__main__":
    main()
