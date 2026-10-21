"""C05 forward source/account readiness; GET-only, never a strategy replay/order.

Ordinary-distribution helpers distinguish receivables, modeled payable cash and
observed broker credits. They do not mutate the shared paper cash book. A capture
can only append a failed preparation, not activate a strategy or consume a final.
"""
from __future__ import annotations

import argparse
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal as D
import json
from pathlib import Path
import subprocess
from time import monotonic

import requests
from sqlalchemy import select, text

from tradingbot.connectors.alpaca_api import AlpacaPaperAPI
from tradingbot.connectors.alpaca_paper import AlpacaPaperConnector
from tradingbot.connectors.cash import MarketSession, NEW_YORK, amount, timestamp
from tradingbot.data.alpaca_history import ACTIONS, AlpacaHistoryAPI
from tradingbot.data.archive import Request
from tradingbot.data.disk_budget import CaptureDiskBudget
from tradingbot.data.free_history import USER_AGENT, YAHOO_CHART
from tradingbot.db.models import Trial
from tradingbot.db.session import SessionLocal
from tradingbot.forward.c08_readiness import (
    digest, encoded, local_paper_evidence, quote_evidence,
    release_after_completion,
)
from tradingbot.research.equity_fees import EquityFeeBook
from tradingbot.risk.limits import API_ERROR_MAX_PER_MINUTE, API_ERROR_WINDOW_SECONDS

ROOT = Path(__file__).resolve().parents[3]
ARCHIVE = ROOT / "data/forward/c05-readiness"
NAME = "c05_forward_readiness_v1"
FAMILY = "sweep_c05_commodity_trend_blackout_v1"
VERSION = "de0dad8696f3603a0ebcde01bbe2f9333e037db5a22d03b4e7c01f8336924320"
SOURCE = "05774a5a2f1ccbfef2898471f32311874e67298fc2bbbb6efb39b1cda893cb7c"
REACTOR = "66da5a97b2d40138a578198c331f5fcad774cc912944b5d7633624db53321778"
FEE_CODE = "09dba3aca3596d754bd6501171e1a1c5ce3a93ae87a65b57fad85bddfe62ed11"
SYMBOLS = ("GLD", "SLV", "USO", "UNG", "DBA")
ZERO = D(0)
PARAMS = {"symbols": list(SYMBOLS), "variant": "total_return_126_positive",
          "sleeve_weight": ".19", "cash_reserve_weight": ".05", "slot_usd": "140",
          "buy_fee_reserve_usd": ".01", "quantity_step": ".000000001", "source_receipt": SOURCE}
PUBLIC = {
    "paper-specification": "https://docs.alpaca.markets/us/docs/paper-trading",
    "account-activities": "https://docs.alpaca.markets/us/docs/account-activities",
    "activity-api": "https://docs.alpaca.markets/us/reference/getaccountactivities-2",
    "action-api": "https://docs.alpaca.markets/us/reference/corporateactions-1",
    "fee-schedule": "https://files.alpaca.markets/disclosures/library/BrokFeeSched.pdf",
}
BLOCKERS = [
    "No C05 durable monthly close/open runner or order/fill reconciliation is activated",
    "Consistent adjusted-close vintage and issuer action/ordinary-distribution review need admission",
    "Shared connector releases sales earlier; conservative completion cash is not integrated",
    "Paper omits dividends and regulatory fees; separate income/fee book is not integrated",
    "Connector marks one instrument; C05 requires complete simultaneous portfolio risk/equity marks",
    "No C05 fractional opening fills, partial/forced exits or actual dividend/share-credit evidence",
]


def dependencies():
    # Shared holdout infrastructure may legitimately change; never replay a final
    # to recover an old dependency hash. Bind only what this preparation executes.
    names = ("forward/c05_readiness.py", "forward/c08_readiness.py", "connectors/alpaca_api.py",
             "connectors/alpaca_paper.py", "connectors/cash.py", "data/alpaca_history.py",
             "data/disk_budget.py", "data/free_history.py", "risk/limits.py",
             "strategy/c05_commodity_trend.py", "research/equity_fees.py")
    return {n: digest((ROOT / "src/tradingbot" / n).read_bytes()) for n in names}


def write_once(path, value, *, raw=False):
    path = Path(path)
    body = value if raw else encoded(value)
    with CaptureDiskBudget(ROOT / "data").reserve(3 * len(body) + 65536):
        with path.open("xb") as output:
            output.write(body)
    return {"path": str(path.relative_to(ROOT)), "sha256": digest(body)}


def historical_evidence(session):
    session.execute(text("SET LOCAL TIME ZONE 'UTC'"))
    if digest((ROOT / "src/tradingbot/strategy/c05_commodity_trend.py").read_bytes()) != REACTOR:
        raise ValueError("Evaluated C05 reactor changed")
    if digest((ROOT / "src/tradingbot/research/equity_fees.py").read_bytes()) != FEE_CODE:
        raise ValueError("Evaluated C05 fee scenario changed")
    rows = []
    for iid, final in ((3959, False), (3964, True)):
        trial = session.get(Trial, iid)
        if (trial is None or trial.mode != "backtest" or trial.status != "complete"
                or trial.strategy_version != VERSION or trial.final_holdout != final
                or trial.pnl_after_fees is None or trial.pnl_after_fees <= 0):
            raise ValueError("Frozen profitable C05 evidence is absent or changed")
        params = trial.params
        identity = params.get("_holdout", {}).get("identity", {})
        if (any(params.get(k) != v for k, v in PARAMS.items()) or identity.get("key") != FAMILY
                or identity.get("code", {}).get("strategy/c05_commodity_trend.py") != REACTOR
                or identity.get("execution_params", {}).get("run", {}).get("cost_bp_per_side") != 10):
            raise ValueError("Frozen C05 execution identity changed")
        raw = session.scalar(text("SELECT row_to_json(t)::text FROM trials t WHERE id=:id"), {"id": iid})
        rows.append({"trial_id": iid, "strategy_id": trial.strategy_id, "full_row_sha256": digest(raw.encode()),
                     "final_holdout": final, "dataset_key": trial.dataset_key,
                     "holdout_start": trial.holdout_start.isoformat(), "net_usd": str(trial.pnl_after_fees),
                     "fees_usd": str(trial.fees_total), "round_trips": trial.trade_count,
                     "max_drawdown_usd": str(trial.max_drawdown),
                     "luck_p_value": str(trial.luck_p_value) if trial.luck_p_value is not None else None})
    if any(rows[0][k] != rows[1][k] for k in ("dataset_key", "holdout_start")):
        raise ValueError("C05 training/final identity mismatch")
    finals = []
    for trial in session.scalars(select(Trial).where(Trial.final_holdout).order_by(Trial.id)):
        family = (trial.params or {}).get("_holdout", {}).get("identity", {}).get("key")
        if family == FAMILY or trial.strategy_version == VERSION:
            finals.append(trial.id)
    if finals != [3964]:
        raise ValueError("Unexpected C05 family final attempt")
    return {"strategy_version": VERSION, "reactor_sha256": REACTOR, "fee_code_sha256": FEE_CODE,
            "source_receipt": SOURCE, "params": PARAMS, "rows": rows,
            "family_final_attempt_ids": finals, "replayed": False}


def quote_batch(rows, as_of, sessions):
    """Re-age all five observations at one time; never imply simultaneous fills."""
    as_of = timestamp(as_of)
    if set(rows) != set(SYMBOLS):
        raise ValueError("Complete C05 five-symbol quote batch required")
    active = [s for s in sessions if s.is_open(as_of)]
    evidence = {s: quote_evidence(rows[s], as_of) for s in SYMBOLS}
    for symbol, value in evidence.items():
        bid, ask = D(value["bid"]), D(value["ask"])
        value["full_spread_bp"] = str((ask - bid) / ((ask + bid) / 2) * 10000)
        value["regular_session"] = len(active) == 1 and active[0].is_open(timestamp(rows[symbol]["t"]))
    return {"as_of": as_of.isoformat(), "quotes": evidence,
            "all_fresh_regular": all(v["fresh"] and v["regular_session"] for v in evidence.values()),
            "opening_reference": False, "fill_evidence": False,
            "risk_marks_complete_for_other_strategies": False}


def quantity_before_ex_open(symbol, fills, ex_open):
    """A flat-start C05 fill ledger; same-ex-open buys receive no entitlement."""
    if symbol not in SYMBOLS:
        raise ValueError("Unknown C05 distribution symbol")
    ex_open = timestamp(ex_open)
    quantity, seen = ZERO, set()
    ordered = sorted(fills, key=lambda r: (timestamp(r["fill_at"]), r["id"]))
    for row in ordered:
        if not row.get("id") or row["id"] in seen:
            raise ValueError("Duplicate or missing fill identity")
        seen.add(row["id"])
        if row["symbol"] not in SYMBOLS or row["side"] not in {"buy", "sell"}:
            raise ValueError("Invalid C05 fill")
        size = amount(row["quantity"], positive=True)
        if row["symbol"] != symbol or timestamp(row["fill_at"]) >= ex_open:
            continue
        quantity += size if row["side"] == "buy" else -size
        if quantity < 0:
            raise ValueError("Distribution ownership cannot be short")
    return quantity


def distribution_entitlement(event, fills, sessions, observed_at):
    """Build an issuer-backed receivable without a fake trade or broker credit.

    Event identity is symbol/ex-date/ordinary-cash, independent of vendor record
    date, so duplicate record-date rows cannot be another payment. Late source
    evidence stops admission instead of backdating an ex-open receivable.
    """
    observed_at = timestamp(observed_at)
    symbol, ex = event["symbol"], date.fromisoformat(event["ex_date"])
    payable = date.fromisoformat(event["payable_date"])
    matches = [s for s in sessions if s.trade_date == ex]
    if symbol not in SYMBOLS or len(matches) != 1 or event.get("currency") != "USD":
        raise ValueError("Invalid distribution symbol/currency/ex session")
    if event.get("kind") != "ordinary_cash" or payable < ex:
        raise ValueError("Unsupported distribution kind or payment ordering")
    sha = event["source_sha256"]
    if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        raise ValueError("Missing primary distribution receipt")
    opened = matches[0].opens_at
    first_seen = timestamp(event["source_observed_at"])
    if first_seen > opened or first_seen > observed_at or opened > observed_at:
        raise ValueError("Distribution source is late or event is not yet recognized")
    quantity = quantity_before_ex_open(symbol, fills, opened)
    rate = amount(event["amount_per_share"], positive=True)
    available = release_after_completion(payable, sessions)
    return {"event_id": f"{symbol}:{ex}:ordinary_cash", "symbol": symbol,
            "ex_date": str(ex), "payable_date": str(payable), "source_sha256": sha,
            "source_observed_at": first_seen.isoformat(), "recognized_at": opened.isoformat(),
            "amount_per_share": str(rate), "quantity_before_ex_open": str(quantity),
            "cash_amount": str(quantity * rate), "modeled_release_at": available.isoformat(),
            "execution_fill": False, "broker_credit_verified": False}


def distribution_balances(entitlements, *, now):
    """Model-only balances. Missing paper dividends never become broker cash."""
    now = timestamp(now)
    seen, receivable, modeled_cash = set(), ZERO, ZERO
    for row in entitlements:
        identity = row["event_id"]
        if identity in seen:
            raise ValueError("Duplicate distribution identity; reconcile a correction instead")
        seen.add(identity)
        recognized, release = timestamp(row["recognized_at"]), timestamp(row["modeled_release_at"])
        if recognized > now or release <= recognized or row.get("execution_fill") is not False:
            raise ValueError("Invalid distribution recognition/release")
        credit = amount(row["cash_amount"])
        if credit != amount(row["amount_per_share"], positive=True) * amount(row["quantity_before_ex_open"]):
            raise ValueError("Distribution credit differs from entitlement")
        if now < release:
            receivable += credit
        else:
            modeled_cash += credit
    return {"receivable_usd": str(receivable), "modeled_payable_cash_usd": str(modeled_cash),
            "broker_credit_verified_usd": "0", "may_increase_shared_cash_book": False}


def c05_trade_cash(initial, movements, reserved, now):
    """Reuse the evaluated conservative trade timing with unique fill evidence.

    This excludes all distributions. A nominal T+1 label is not an audited
    cash_release_at. The future runner must still cap this by shared cash,
    remaining strategy allocation and broker cash/buying power.
    """
    from tradingbot.forward.c08_readiness import conservative_cash
    movements = list(movements)
    seen = set()
    for row in movements:
        if not row.get("id") or row["id"] in seen:
            raise ValueError("Duplicate or missing trade cash identity")
        seen.add(row["id"])
    return conservative_cash(initial, movements, reserved, now)


def fee_scenario(fills):
    """One dated book across all C05 sleeves, independent of broker zero fees."""
    book, seen, output = EquityFeeBook(), set(), []
    for row in sorted(fills, key=lambda r: (timestamp(r["fill_at"]), r["id"])):
        if not row.get("id") or row["id"] in seen or row["symbol"] not in SYMBOLS:
            raise ValueError("Duplicate/missing fee fill or symbol outside C05")
        seen.add(row["id"])
        fee, evidence = book.charge(day=timestamp(row["fill_at"]).astimezone(NEW_YORK).date(),
            side=row["side"], price=amount(row["price"], positive=True),
            size=amount(row["quantity"], positive=True))
        output.append({"fill_id": row["id"], "modeled_fee_usd": str(fee), "evidence": evidence})
    return {"policy": book.policy, "fills": output, "broker_charged_fees": False,
            "total_usd": str(sum((D(r["modeled_fee_usd"]) for r in output), ZERO)),
            "scope": "isolated C05 scenario; real per-account totals must include other strategies"}


class ProbeHalted(RuntimeError):
    """No further remote requests within this capture after the risk threshold."""


class ProbeBudget:
    def __init__(self, clock=monotonic):
        self.clock, self.errors, self.halted, self.attempts = clock, [], False, 0

    def failure(self):
        now = self.clock()
        self.errors = [at for at in self.errors if now - at <= API_ERROR_WINDOW_SECONDS]
        self.errors.append(now)
        self.halted = self.halted or len(self.errors) >= API_ERROR_MAX_PER_MINUTE

    def call(self, callback):
        if self.halted:
            raise ProbeHalted("Capture API error threshold reached")
        self.attempts += 1
        try:
            return callback()
        except Exception:
            self.failure()
            raise


class ReadOnlyPaper(AlpacaPaperAPI):
    """Only used for probes. Existing connector's FILL polling is unchanged."""
    def nontrade_activities(self, after, until, page_token=None):
        params = {"category": "non_trade_activity", "after": after.isoformat(),
                  "until": until.isoformat(), "direction": "asc", "page_size": 100}
        if page_token:
            params["page_token"] = page_token
        return self._trading.get("/account/activities", params)

    def submit(self, payload):
        raise ValueError("C05 readiness cannot submit orders")

    def cancel(self, venue_order_id):
        raise ValueError("C05 readiness cannot cancel orders")


def capture_paper(api, directory, start, through, *, expected_account, budget=None):
    budget = budget or ProbeBudget()
    if not expected_account:
        raise ValueError("Existing cash-book account binding required")
    values, receipts, quote_rows = {}, [], {}
    calls = {"account": api.account, "calendar": lambda: api.calendar_range(start, through)}
    for symbol in SYMBOLS:
        calls["asset-" + symbol] = lambda s=symbol: api.asset(s)
    for symbol in SYMBOLS:
        calls["quote-" + symbol] = lambda s=symbol: api.quote(s)
    for key, call in calls.items():
        began = datetime.now(UTC)
        try:
            CaptureDiskBudget(ROOT / "data").check()
            row = budget.call(call)
            audit = {}
            if key == "account":
                AlpacaPaperConnector._account_ok(row)
                if row.get("currency") != "USD" or AlpacaPaperConnector._fingerprint(row) != expected_account:
                    raise ValueError("Paper account does not match USD cash book")
                audit = {"matches_existing_cash_book": True, "connector_account_checks_pass": True,
                         "cash_only_local_policy": True, "broker_cash_account_type_proven": False}
                row = {k: row.get(k) for k in ("status", "currency", "trading_blocked", "account_blocked", "trade_suspended_by_user")}
            elif key.startswith("asset-"):
                symbol = key.removeprefix("asset-")
                AlpacaPaperConnector._asset_ok(row, symbol)
                if row.get("fractionable") is not True:
                    raise ValueError("C05 asset is not fractionable")
                audit = {"eligible_fractional_us_equity": True}
                row = {k: row.get(k) for k in ("id", "symbol", "class", "status", "tradable", "fractionable", "exchange")}
            elif key.startswith("quote-"):
                quote_rows[key.removeprefix("quote-")] = row
            value = {"started_at": began.isoformat(), "observed_at": datetime.now(UTC).isoformat(),
                     "response": row, "audit": audit}
        except Exception as exc:
            value = {"started_at": began.isoformat(), "observed_at": datetime.now(UTC).isoformat(),
                     "error": type(exc).__name__}
        values[key] = value
        receipts.append(write_once(directory / (key + ".json"), value))
    batch_at = datetime.now(UTC)
    try:
        sessions = [MarketSession.from_api(r) for r in values["calendar"]["response"]]
        batch = quote_batch(quote_rows, batch_at, sessions)
    except Exception as exc:
        batch = {"error": type(exc).__name__, "all_fresh_regular": False}
    receipts.append(write_once(directory / "quote-batch.json", batch))
    return values, batch, receipts


def capture_nontrade(api, directory, after, until, *, budget=None):
    budget = budget or ProbeBudget()
    pages, seen, cursor, relevant, count = [], {}, None, [], 0
    for number in range(20):
        CaptureDiskBudget(ROOT / "data").check()
        rows = budget.call(lambda: api.nontrade_activities(after, until, cursor))
        if not isinstance(rows, list) or len(rows) > 100:
            raise ValueError("Invalid nontrade activity page")
        clean = []
        for row in rows:
            iid = row.get("id")
            if not isinstance(iid, str) or not iid or row.get("activity_type") == "FILL":
                raise ValueError("Invalid nontrade identity/category")
            row_hash = digest(encoded(row))
            if iid in seen:
                raise ValueError("Repeated or conflicting nontrade activity identity")
            seen[iid] = row_hash
            count += 1
            # Account-specific IDs and free text are not persisted. Keep public
            # symbol amounts/dates only for C05; other activity counts still matter.
            item = {"activity_id_sha256": digest(iid.encode()), "response_row_sha256": row_hash,
                    "activity_type": row.get("activity_type"), "c05_symbol": row.get("symbol") in SYMBOLS}
            if item["c05_symbol"]:
                for key in ("symbol", "date", "created_at", "settle_date", "qty", "net_amount", "per_share_amount", "status"):
                    if key in row:
                        item[key] = row[key]
                relevant.append(item)
            clean.append(item)
        observed = datetime.now(UTC)
        pages.append(write_once(directory / f"nontrade-{number}.json", {
            "endpoint": "/account/activities", "category": "non_trade_activity",
            "after": after.isoformat(), "until": until.isoformat(), "direction": "asc", "page_size": 100,
            "observed_at": observed.isoformat(), "page_token_sha256": digest(cursor.encode()) if cursor else None,
            "response": clean, "account_bound": True}))
        if len(rows) < 100:
            return {"pages": pages, "records": count, "c05_records": relevant, "exhausted": True,
                    "broker_dividend_fidelity": False, "empty_is_not_no_entitlement": True,
                    "query_time_basis": "creation time, not proven settlement completion"}
        cursor = rows[-1]["id"]
    raise ValueError("Nontrade activity page budget exhausted")


def capture_actions(api, directory, start, through, *, budget=None):
    budget = budget or ProbeBudget()
    pages, token, seen, count = [], None, set(), 0
    for number in range(20):
        params = {"symbols": ",".join(SYMBOLS), "start": start.isoformat(), "end": through.isoformat(),
                  "data_quality": "all", "limit": 1000, "sort": "asc"}
        if token:
            params["page_token"] = token
        CaptureDiskBudget(ROOT / "data").check()
        raw = budget.call(lambda: api(Request(ACTIONS + "/corporate-actions", params)))
        row = json.loads(raw)
        pages.append(write_once(directory / f"actions-{number}.json", {
            "request": params, "observed_at": datetime.now(UTC).isoformat(),
            "raw_response_sha256": digest(raw.encode()), "raw_response": raw, "response": row}))
        groups = row["corporate_actions"]
        if not isinstance(groups, dict) or any(not isinstance(v, list) for v in groups.values()):
            raise ValueError("Invalid corporate-action groups")
        count += sum(len(v) for v in groups.values())
        token = row["next_page_token"]
        if token is None:
            return {"pages": pages, "records": count, "exhausted": True,
                    "symbols": list(SYMBOLS), "issuer_review_complete": False,
                    "advance_notice_guaranteed": False, "empty_is_not_action_clearance": True}
        if not isinstance(token, str) or not token or token in seen:
            raise ValueError("Corporate-action pagination loop or invalid token")
        seen.add(token)
    raise ValueError("Corporate-action page budget exhausted")


def capture_http(directory, key, url, *, params=None, budget=None):
    budget = budget or ProbeBudget()
    allowed = set(PUBLIC.values()) | {YAHOO_CHART.format(symbol=s) for s in SYMBOLS}
    if url not in allowed:
        raise ValueError("Public capture URL is outside frozen allowlist")
    CaptureDiskBudget(ROOT / "data").check()
    def fetch():
        with requests.get(url, params=params, headers={"User-Agent": USER_AGENT},
                          timeout=(5, 25), stream=True, allow_redirects=False) as response:
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > 4_000_000:
                    raise ValueError("Public capture exceeds bounded response size")
                chunks.append(chunk)
            raw = b"".join(chunks)
            meta = {"request_url": url, "params": params, "response_url": response.url,
                    "status_code": response.status_code, "observed_at": datetime.now(UTC).isoformat(),
                    "raw_sha256": digest(raw), "bytes": len(raw), "content_type": response.headers.get("content-type")}
        return meta, raw
    meta, raw = budget.call(fetch)
    if meta["status_code"] != 200:
        budget.failure()
    receipts = [write_once(directory / (key + ".raw"), raw, raw=True),
                write_once(directory / (key + ".json"), meta)]
    return meta, raw, receipts


def close_window_evidence(raw, symbol, sessions, observed_at):
    """127 completed closes from ONE capture, no signal/return computation."""
    observed_at = timestamp(observed_at)
    result = json.loads(raw)["chart"]["result"][0]
    if result["meta"].get("symbol") != symbol or result["meta"].get("currency") != "USD":
        raise ValueError("Close-source identity differs")
    stamps = result["timestamp"]
    prices = result["indicators"]["quote"][0]["close"]
    adjusted = result["indicators"]["adjclose"][0]["adjclose"]
    if len(stamps) != len(prices) or len(stamps) != len(adjusted) or stamps != sorted(set(stamps)):
        raise ValueError("Incomplete or repeated close source")
    expected = sorted((s for s in sessions if s.closes_at < observed_at), key=lambda s: s.trade_date)[-127:]
    if len(expected) != 127:
        raise ValueError("Calendar lacks required 127 completed closes")
    rows = {}
    calendar = {s.trade_date: s for s in sessions}
    ignored_incomplete = 0
    for stamp, close, adj in zip(stamps, prices, adjusted):
        day = datetime.fromtimestamp(stamp, NEW_YORK).date()
        if day not in calendar:
            raise ValueError("Price day outside captured session calendar")
        if calendar[day].closes_at >= observed_at:
            ignored_incomplete += 1
            continue
        if day in rows:
            raise ValueError("Repeated daily close")
        rows[day] = (amount(str(close), positive=True), amount(str(adj), positive=True))
    if any(s.trade_date not in rows for s in expected):
        raise ValueError("Missing required completed close")
    events = result.get("events", {})
    if any(v for k, v in events.items() if k not in {"dividends", "splits"}):
        raise ValueError("Unreviewed action group")
    return {"symbol": symbol, "completed_closes": 127,
            "first_session": str(expected[0].trade_date), "last_session": str(expected[-1].trade_date),
            "latest_session_close_at": expected[-1].closes_at.isoformat(),
            "available_at": observed_at.isoformat(),
            "source_observed_at": observed_at.isoformat(), "raw_sha256": digest(raw),
            "single_adjustment_vintage": True, "incomplete_rows_ignored": ignored_incomplete,
            "action_counts": {k: len(v) for k, v in events.items()},
            "signal_computed": False, "signal_admitted": False,
            "limitation": "coverage only; adjusted history/action continuity and independent prices still require admission"}


def capture_readiness(directory):
    directory = directory.resolve()
    if not directory.is_relative_to(ARCHIVE) or directory == ARCHIVE:
        raise ValueError("Use a new directory under data/forward/c05-readiness")
    CaptureDiskBudget(ROOT / "data").check()
    directory.mkdir(parents=True, exist_ok=False)
    began, receipts, budget = datetime.now(UTC), [], ProbeBudget()
    with SessionLocal() as session:
        session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        history = historical_evidence(session)
        local = local_paper_evidence(session, began)
        expected_account = local.pop("account_fingerprint")
        local.pop("c08_settlement_fidelity")
        local["c05_settlement_fidelity"] = False
        local["difference"] = "connector releases sale cash at settlement-date midnight; C05 waits past documented completion"
    first_day, through = began.astimezone(NEW_YORK).date() - timedelta(days=400), began.date() + timedelta(days=65)
    api = ReadOnlyPaper.from_env()
    try:
        paper, batch, child = capture_paper(api, directory, first_day, through, expected_account=expected_account, budget=budget)
        receipts.extend(child)
        try:
            if paper.get("account", {}).get("audit", {}).get("matches_existing_cash_book") is not True:
                raise ValueError("Nontrade capture requires matching account")
            nontrade = capture_nontrade(api, directory, began - timedelta(days=400), began, budget=budget)
            receipts.extend(nontrade["pages"])
        except Exception as exc:
            nontrade = {"error": type(exc).__name__, "exhausted": False, "broker_dividend_fidelity": False}
    finally:
        api.close()
    api = AlpacaHistoryAPI()
    try:
        actions = capture_actions(api, directory, first_day, through, budget=budget)
        receipts.extend(actions["pages"])
    except Exception as exc:
        actions = {"error": type(exc).__name__, "exhausted": False}
    finally:
        api.close()
    sources = {}
    try:
        sessions = [MarketSession.from_api(r) for r in paper["calendar"]["response"]]
    except Exception:
        sessions = []
    # period2 is today's NY midnight: only previously completed daily bars.
    end = datetime.combine(began.astimezone(NEW_YORK).date(), time.min, NEW_YORK)
    params = {"period1": int(datetime.combine(first_day, time.min, NEW_YORK).timestamp()),
              "period2": int(end.timestamp()), "interval": "1d", "events": "div,split", "includeAdjustedClose": "true"}
    for symbol in SYMBOLS:
        try:
            meta, raw, child = capture_http(directory, "closes-" + symbol, YAHOO_CHART.format(symbol=symbol), params=params, budget=budget)
            receipts.extend(child)
            if meta["status_code"] != 200:
                raise ValueError("Daily source HTTP failure")
            # Period2 deliberately excludes today, even after a late capture.
            sources[symbol] = close_window_evidence(raw, symbol, [s for s in sessions if s.trade_date < end.date()], meta["observed_at"])
        except Exception as exc:
            sources[symbol] = {"error": type(exc).__name__, "signal_admitted": False}
    public = {}
    for key, url in PUBLIC.items():
        try:
            meta, _, child = capture_http(directory, key, url, budget=budget)
            receipts.extend(child)
            public[key] = meta
        except Exception as exc:
            public[key] = {"error": type(exc).__name__}
    ended = datetime.now(UTC)
    failures = [k for k, v in paper.items() if "error" in v]
    if not batch.get("all_fresh_regular"):
        failures.append("common_time_five_quote_batch")
    failures += ["closes-" + k for k, v in sources.items() if "error" in v]
    failures += [k for k, v in (("nontrade", nontrade), ("actions", actions)) if "error" in v]
    failures += [k for k, v in public.items() if v.get("status_code") != 200]
    # Include partial pages from failed bounded probes as well as successful
    # receipts. A later validation failure never discards already saved evidence.
    receipts = [{"path": str(p.relative_to(ROOT)), "sha256": digest(p.read_bytes())}
                for p in sorted(directory.iterdir()) if p.is_file()]
    report = {"schema": NAME, "started_at": began.isoformat(), "completed_at": ended.isoformat(),
              "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
              "dependency_sha256": dependencies(), "historical_evidence": history, "local_paper": local,
              "symbols": list(SYMBOLS), "paper_probes": paper, "quote_batch": batch,
              "nontrade_activities": nontrade, "corporate_actions": actions, "close_sources": sources,
              "public_documentation": public, "receipts": receipts, "probe_failures": failures,
              "api_budget": {"attempts": budget.attempts, "halted": budget.halted,
                             "max_errors": API_ERROR_MAX_PER_MINUTE, "window_seconds": API_ERROR_WINDOW_SECONDS},
              "decision": "hold_before_ordering_paper", "ready_for_live": False,
              "paper_runner_activated": False, "orders_submitted": 0, "signals_computed": False,
              "blockers": BLOCKERS, "real_allocation_usd": "0",
              "allocation_policy": "$140 existing venue-wide virtual cash; no reset or separate duplicate book"}
    report["receipts"].append(write_once(directory / "source-summary.json", {
        key: report[key] for key in SUMMARY_KEYS}))
    receipt = write_once(directory / "readiness.json", report)
    return report, receipt


SUMMARY_KEYS = ("nontrade_activities", "corporate_actions", "close_sources",
                "public_documentation", "probe_failures", "api_budget")


def verify_receipts(report, directory):
    directory = directory.resolve()
    seen = set()
    for child in report["receipts"]:
        path = (ROOT / child["path"]).resolve()
        if not path.is_relative_to(directory) or path.name == "readiness.json" or path in seen:
            raise ValueError("Receipt path is duplicate or outside this capture")
        seen.add(path)
        if not path.is_file() or digest(path.read_bytes()) != child["sha256"]:
            raise ValueError("Missing or changed child receipt")
    required = {"account.json", "calendar.json", "quote-batch.json", "source-summary.json"}
    required |= {f"{kind}-{s}.json" for kind in ("asset", "quote") for s in SYMBOLS}
    if not required <= {p.name for p in seen}:
        raise ValueError("Incomplete capture receipt inventory")
    actual = {p.resolve() for p in directory.iterdir() if p.name != "readiness.json"}
    if actual != seen:
        raise ValueError("Unlisted or missing capture child")
    probes = report["paper_probes"]
    expected = {"account", "calendar"} | {f"{kind}-{s}" for kind in ("asset", "quote") for s in SYMBOLS}
    if set(probes) != expected:
        raise ValueError("Incomplete inline probe universe")
    for key, value in probes.items():
        if json.loads((directory / (key + ".json")).read_bytes()) != value:
            raise ValueError("Inline probe differs from immutable child")
    if json.loads((directory / "quote-batch.json").read_bytes()) != report["quote_batch"]:
        raise ValueError("Inline quote batch differs from immutable child")
    if (any(key not in report for key in SUMMARY_KEYS)
            or json.loads((directory / "source-summary.json").read_bytes()) != {
                key: report[key] for key in SUMMARY_KEYS}):
        raise ValueError("Incomplete or changed source summaries")
    if (set(report["close_sources"]) != set(SYMBOLS)
            or set(report["public_documentation"]) != set(PUBLIC)):
        raise ValueError("Incomplete source universe")

    inventory = {child["path"]: child["sha256"] for child in report["receipts"]}
    def child_json(name):
        path = directory / (name + ".json")
        if path not in seen:
            raise ValueError("Summary references missing child")
        return json.loads(path.read_bytes())

    def http_pair(key, expected_url):
        meta = child_json(key)
        raw_path = directory / (key + ".raw")
        if raw_path not in seen:
            raise ValueError("HTTP source lacks raw receipt")
        raw = raw_path.read_bytes()
        if (meta["raw_sha256"] != digest(raw) or meta["bytes"] != len(raw)
                or meta["request_url"] != expected_url):
            raise ValueError("HTTP metadata differs from raw receipt")
        return meta, raw

    failures = [key for key, value in probes.items() if "error" in value]
    if not report["quote_batch"].get("all_fresh_regular"):
        failures.append("common_time_five_quote_batch")
    for symbol, source in report["close_sources"].items():
        if "error" in source:
            failures.append("closes-" + symbol)
            continue
        meta, raw = http_pair("closes-" + symbol, YAHOO_CHART.format(symbol=symbol))
        if meta["status_code"] != 200 or source["raw_sha256"] != digest(raw):
            raise ValueError("Close summary differs from raw source")
        sessions = [MarketSession.from_api(r) for r in probes["calendar"]["response"]]
        before = datetime.fromtimestamp(meta["params"]["period2"], NEW_YORK).date()
        expected_source = close_window_evidence(raw, symbol,
            [s for s in sessions if s.trade_date < before], meta["observed_at"])
        if source != expected_source:
            raise ValueError("Close summary differs from derived coverage")
    for label, section in (("nontrade", "nontrade_activities"), ("actions", "corporate_actions")):
        value = report[section]
        if "error" in value:
            if value.get("exhausted") is not False:
                raise ValueError("Failed pagination cannot be exhausted")
            failures.append(label)
            continue
        if value.get("exhausted") is not True or not value.get("pages"):
            raise ValueError("Successful pagination lacks exhaustion evidence")
        pages = []
        for number, ref in enumerate(value["pages"]):
            path = (ROOT / ref["path"]).resolve()
            if (inventory.get(ref["path"]) != ref["sha256"] or path not in seen
                    or path.name != f"{label}-{number}.json"):
                raise ValueError("Nested page differs from receipt inventory")
            pages.append(json.loads(path.read_bytes()))
        if label == "actions":
            for page in pages:
                if (digest(page["raw_response"].encode()) != page["raw_response_sha256"]
                        or json.loads(page["raw_response"]) != page["response"]):
                    raise ValueError("Action page differs from raw response")
            count = sum(len(rows) for p in pages for rows in p["response"]["corporate_actions"].values())
            if pages[-1]["response"]["next_page_token"] is not None:
                raise ValueError("Actions not exhausted")
        else:
            count = sum(len(p["response"]) for p in pages)
            if (len(pages[-1]["response"]) >= 100 or value["c05_records"] != [
                    row for p in pages for row in p["response"] if row["c05_symbol"]]):
                raise ValueError("Nontrade summary/exhaustion differs from pages")
        if value["records"] != count:
            raise ValueError("Page count differs from summary")
    for key, value in report["public_documentation"].items():
        if "error" not in value:
            meta, _ = http_pair(key, PUBLIC[key])
            if value != meta:
                raise ValueError("Public source differs from receipt")
        if value.get("status_code") != 200:
            failures.append(key)
    if sorted(failures) != sorted(report["probe_failures"]):
        raise ValueError("Probe failure summary differs from source evidence")


def record_failed_preparation(session, path):
    path = path.resolve()
    if not path.is_relative_to(ARCHIVE) or path.name != "readiness.json":
        raise ValueError("Receipt must be within C05 readiness archive")
    raw = path.read_bytes()
    report = json.loads(raw)
    if (report.get("schema") != NAME or report.get("decision") != "hold_before_ordering_paper"
            or report.get("orders_submitted") != 0 or report.get("ready_for_live") is not False
            or report.get("paper_runner_activated") is not False or report.get("signals_computed") is not False
            or report.get("symbols") != list(SYMBOLS) or report.get("dependency_sha256") != dependencies()):
        raise ValueError("Receipt is not a current C05 non-ordering preparation")
    verify_receipts(report, path.parent)
    history = historical_evidence(session)
    if history != report["historical_evidence"]:
        raise ValueError("Historical evidence changed since capture")
    receipt_hash = digest(raw)
    session.execute(text("SELECT pg_advisory_xact_lock(60427, 5)"))
    existing = session.scalar(select(Trial).where(Trial.code_version == NAME,
        Trial.params["readiness_sha256"].as_string() == receipt_hash))
    if existing:
        return existing.id
    row = Trial(strategy_id=history["rows"][1]["strategy_id"], mode="paper", status="failed", code_version=NAME,
        git_commit=report["git_commit"], data_start=timestamp(report["started_at"]),
        data_end=timestamp(report["completed_at"]), completed_ts=datetime.now(UTC), trade_count=0,
        params={"readiness_sha256": receipt_hash, "readiness_path": str(path.relative_to(ROOT)),
                "historical_training_trial": 3959, "historical_final_trial": 3964,
                "historical_strategy_version": VERSION, **PARAMS},
        metrics={"readiness_only": True, "orders_submitted": 0, "promotion_eligible": False,
                 "blockers": report["blockers"], "probe_failures": report["probe_failures"]},
        notes="C05 forward preparation held before ordering: source/action watch, income/fees, full marks and cash/open runner need integration. No historical replay or strategy result. docs/research/27-c05-forward-readiness.md")
    session.add(row)
    session.flush()
    return row.id


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--output", type=Path)
    choice.add_argument("--record-failed-preparation", type=Path)
    args = parser.parse_args()
    try:
        if args.record_failed_preparation:
            with SessionLocal() as session:
                iid = record_failed_preparation(session, args.record_failed_preparation)
                session.commit()
            print(json.dumps({"trial_id": iid, "readiness_only": True, "status": "failed"}))
        else:
            _, receipt = capture_readiness(args.output)
            print(json.dumps({"receipt": receipt, "decision": "hold_before_ordering_paper", "orders_submitted": 0}))
    except Exception as exc:
        # Neither remote exception bodies nor account identities enter stdout.
        print(json.dumps({"error": type(exc).__name__, "ready_for_live": False}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
