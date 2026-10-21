"""Account-wide modeled costs, income and conservative cash for forward paper.

The connector owns transactions and the venue lock. This module never funds a
book, fabricates a fill, queries a broker on construction or changes risk limits.
Model income affects P&L; it cannot increase the transport's actual cash book.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal as D
from hashlib import sha256
import json
from pathlib import Path

from sqlalchemy import select, text

from tradingbot.connectors.alpaca_paper import ACTIVE, NAME as CONNECTOR
from tradingbot.connectors.cash import NEW_YORK, amount, timestamp
from tradingbot.db.models import Fill, Instrument, Order, Position, Quote, Strategy, Trial, Venue
from tradingbot.research.equity_fees import EquityFeeBook
from tradingbot.risk import limits

NAME = "paper_evidence_v1"
ZERO = D(0)
ROOT = Path(__file__).resolve().parents[3]


def receipt(ref):
    """Verify an archived local source; paths must remain inside data/forward."""
    path = (ROOT / ref["path"]).resolve()
    if not path.is_relative_to(ROOT / "data/forward") or not path.is_file():
        raise ValueError("Evidence must name an archived forward source")
    body = path.read_bytes()
    if sha256(body).hexdigest() != ref["sha256"]:
        raise ValueError("Evidence receipt hash changed")
    return body


def required_instrument_ids(session, additional=()):
    """Every paper holding/pending order, including other strategies/venues."""
    held = session.scalars(select(Position.instrument_id).where(
        Position.mode == "paper", Position.quantity != 0))
    pending = session.scalars(select(Order.instrument_id).where(
        Order.mode == "paper", Order.status.in_(ACTIVE)))
    # Unattributed fills do not materialize Positions. Their presence must not
    # let the global mark check silently ignore exposure.
    anonymous = list(session.scalars(select(Fill).where(
        Fill.mode == "paper", Fill.strategy_id.is_(None))))
    quantities = {}
    for fill in anonymous:
        quantities[fill.instrument_id] = quantities.get(fill.instrument_id, ZERO) + (
            fill.size if fill.side == "buy" else -fill.size)
    return set(held) | set(pending) | set(additional) | {k for k, v in quantities.items() if v}


def fresh_marks(session, quotes, now, market_session, additional=()):
    """Recheck coverage under the venue lock after the network capture."""
    now = timestamp(now)
    required = required_instrument_ids(session, additional)
    if not required <= set(quotes):
        raise ValueError("Missing full-portfolio held/pending marks")
    if not market_session.is_open(now):
        raise ValueError("Portfolio marks require a regular session")
    marks = {}
    for iid, row in quotes.items():
        bid, ask = amount(str(row["bp"]), positive=True), amount(str(row["ap"]), positive=True)
        when = timestamp(row["t"])
        if (ask < bid or not market_session.is_open(when)
                or not 0 <= (now - when).total_seconds() <= limits.STALE_DATA_MAX_SECONDS):
            raise ValueError("Stale, future, crossed or nonregular portfolio mark")
        marks[iid] = (bid + ask) / 2
    return marks


def _release(proof, fill, sessions, now):
    if proof is None:
        return None
    completed = timestamp(proof["completed_at"])
    observed = timestamp(proof["observed_at"])
    nominal = date.fromisoformat(fill["settlement_date"])
    if (proof.get("kind") != "broker_settlement_completion" or proof.get("fill_id") != fill["id"]
            or completed < timestamp(fill["fill_at"]) or completed > observed or observed > now
            or completed.astimezone(NEW_YORK).date() < nominal):
        raise ValueError("Settlement evidence is not documented completion of this fill")
    # Deliberately later than both the documented completion date and our
    # observation. A late receipt cannot backdate spendable cash.
    eligible = [s.opens_at for s in sessions
                if s.trade_date > completed.astimezone(NEW_YORK).date() and s.opens_at >= observed]
    if not eligible:
        return None
    return min(eligible)


@dataclass(frozen=True)
class AccountEvidence:
    cash_available: D
    strategy_cash_by_id: dict[int, D]
    strategy_offsets: dict[int, D]
    daily_pnl_offset: D
    details: dict

    def strategy_cash(self, strategy_id):
        return max(ZERO, self.strategy_cash_by_id.get(strategy_id, ZERO))

    def strategy_pnl_offset(self, strategy_id):
        return self.strategy_offsets.get(strategy_id, ZERO)


def build_evidence(*, initial, allocations, fills, orders, incomes, settlements, sessions, now):
    """Pure deterministic model over the complete, attributed venue ledger.

    Actual ledger fees are already in ledger P&L. Only incremental modeled
    fees are offsets. Sale cash without completion evidence stays unavailable.
    Each partial execution is charged at its own timestamp in one account book.
    """
    now = timestamp(now)
    midnight = datetime.combine(now.astimezone(UTC).date(), time.min, UTC)
    cash, daily, fees, income_cash = amount(initial), ZERO, EquityFeeBook(), ZERO
    strategy_cash = {int(k): amount(v) for k, v in allocations.items()}
    offsets = {sid: ZERO for sid in strategy_cash}
    fee_rows, withheld, seen = [], [], set()
    fills = sorted(fills, key=lambda r: (timestamp(r["fill_at"]), int(r["id"])))
    for row in fills:
        iid, sid, at = row["id"], row["strategy_id"], timestamp(row["fill_at"])
        if iid in seen or sid not in strategy_cash or at > now:
            raise ValueError("Duplicate, unattributed or future account fill")
        seen.add(iid)
        price, qty, actual = amount(row["price"], positive=True), amount(row["quantity"], positive=True), amount(row["fee"])
        modeled, policy = fees.charge(day=at.astimezone(NEW_YORK).date(), side=row["side"], price=price, size=qty)
        extra = max(ZERO, modeled - actual)
        total_fee = actual + extra
        cash -= total_fee
        strategy_cash[sid] -= total_fee
        offsets[sid] -= extra
        if at >= midnight:
            daily -= extra
        release = None
        if row["side"] == "buy":
            cash -= price * qty
            strategy_cash[sid] -= price * qty
        else:
            release = _release(settlements.get(str(iid)), row, sessions, now)
            if release is not None and release <= now:
                cash += price * qty
                strategy_cash[sid] += price * qty
            else:
                withheld.append(iid)
        fee_rows.append({"fill_id": iid, "strategy_id": sid, "actual_fee_usd": str(actual),
                         "modeled_fee_usd": str(modeled), "extra_fee_usd": str(extra),
                         "cash_release_at": release.isoformat() if release else None, "evidence": policy})
    reserved, seen_orders = ZERO, set()
    for row in orders:
        if row["id"] in seen_orders or row["strategy_id"] not in strategy_cash:
            raise ValueError("Duplicate or unattributed account order")
        seen_orders.add(row["id"])
        if row["side"] not in {"buy", "sell"}:
            raise ValueError("Unknown order side")
        if row["side"] == "buy":
            # Each active order holds a conservative fee reserve even when the
            # account's eventual daily rounding increment may be zero.
            value = amount(row["remaining"]) * amount(row["limit_price"], positive=True) + D(".01")
            cash -= value
            reserved += value
            strategy_cash[row["strategy_id"]] -= value
    identities, receivable = set(), ZERO
    for row in incomes:
        sid, identity = row["strategy_id"], (row["strategy_id"], row["event_id"])
        recognized, released = timestamp(row["recognized_at"]), timestamp(row["modeled_release_at"])
        if (identity in identities or sid not in strategy_cash or released <= recognized
                or row.get("execution_fill") is not False or row.get("broker_credit_verified") is not False):
            raise ValueError("Duplicate or invalid modeled entitlement")
        identities.add(identity)
        credit = amount(row["cash_amount"])
        if credit != amount(row["amount_per_share"], positive=True) * amount(row["quantity_before_ex_open"]):
            raise ValueError("Income differs from issuer rate times entitled shares")
        if timestamp(row["source_observed_at"]) > recognized:
            raise ValueError("Late income evidence cannot be backdated")
        if recognized > now:
            continue
        offsets[sid] += credit
        if recognized >= midnight:
            daily += credit
        if released <= now:
            strategy_cash[sid] += credit
            income_cash += credit
        else:
            receivable += credit
    return AccountEvidence(max(ZERO, cash), strategy_cash, offsets, daily, {
        "policy": fees.policy, "fees": fee_rows, "withheld_sale_fill_ids": withheld,
        "reserved_with_fee_usd": str(reserved), "income_receivable_usd": str(receivable),
        "modeled_payable_cash_usd": str(income_cash), "actual_income_credit_usd": "0",
        "initial_shared_cash_usd": str(initial), "cash_available_usd": str(max(ZERO, cash)),
        "daily_pnl_offset_usd": str(daily), "as_of": now.isoformat()})


def account_evidence(session, venue, now, sessions, *, verify_receipts=True):
    """Use only under the connector's venue lock; no commit or HTTP here."""
    book = (venue.metadata_ or {}).get(CONNECTOR)
    if not book or venue.key != "alpaca":
        raise ValueError("Existing Alpaca paper cash book required")
    state = (venue.metadata_ or {}).get(NAME, {})
    settlements, incomes = state.get("settlements", {}), list(state.get("incomes", []))
    scheduled = state.get("scheduled_income", [])
    if verify_receipts:
        for proof in list(settlements.values()) + incomes + scheduled:
            receipt(proof["source_receipt"])
    strategies = list(session.scalars(select(Strategy).where(Strategy.venue_id == venue.id)))
    fills = []
    for fill in session.scalars(select(Fill).join(Instrument).where(
            Instrument.venue_id == venue.id, Fill.mode == "paper")):
        meta = fill.metadata_ or {}
        if meta.get("connector") != CONNECTOR:
            raise ValueError("Unmanaged fill outside the shared evidence book")
        fills.append({"id": fill.id, "strategy_id": fill.strategy_id, "instrument_id": fill.instrument_id,
                      "fill_at": fill.fill_ts,
                      "price": fill.price, "quantity": fill.size, "fee": fill.fee,
                      "side": fill.side, "settlement_date": meta["settlement_date"]})
    orders = []
    for order in session.scalars(select(Order).join(Instrument).where(
            Instrument.venue_id == venue.id, Order.mode == "paper", Order.status.in_(ACTIVE))):
        if (order.metadata_ or {}).get("connector") != CONNECTOR:
            raise ValueError("Unmanaged order outside the shared evidence book")
        orders.append({"id": order.id, "strategy_id": order.strategy_id, "side": order.side,
                       "remaining": order.size - order.filled_size, "limit_price": order.limit_price})
    seen_events = set()
    for event in scheduled:
        if event["event_id"] in seen_events:
            raise ValueError("Duplicate scheduled income event")
        seen_events.add(event["event_id"])
        ex = timestamp(event["recognized_at"])
        if timestamp(event["scheduled_at"]) >= ex or timestamp(event["source_observed_at"]) >= ex:
            raise ValueError("Income was not admitted before ex-open")
        if timestamp(now) < ex:
            continue
        if session.scalar(select(Order.id).where(Order.instrument_id == event["instrument_id"],
                Order.mode == "paper", Order.status.in_(ACTIVE), Order.created_ts < ex)):
            raise ValueError("Unresolved pre-ex order prevents shared income ownership")
        quantities = {}
        for fill in sorted(fills, key=lambda r: (timestamp(r["fill_at"]), r["id"])):
            if fill["instrument_id"] != event["instrument_id"] or timestamp(fill["fill_at"]) >= ex:
                continue
            sid = fill["strategy_id"]
            if sid is None:
                raise ValueError("Unattributed scheduled income ownership")
            quantities[sid] = quantities.get(sid, ZERO) + (fill["quantity"] if fill["side"] == "buy" else -fill["quantity"])
            if quantities[sid] < 0:
                raise ValueError("Scheduled income ownership cannot be short")
        for sid, quantity in quantities.items():
            if quantity == 0:
                continue
            row = {k: event[k] for k in ("event_id", "symbol", "recognized_at", "modeled_release_at",
                    "amount_per_share", "source_observed_at", "source_receipt")}
            row.update(strategy_id=sid, quantity_before_ex_open=str(quantity),
                       cash_amount=str(quantity * D(event["amount_per_share"])),
                       execution_fill=False, broker_credit_verified=False)
            old = [r for r in incomes if (r["strategy_id"], r["event_id"]) == (sid, row["event_id"])]
            facts = ("amount_per_share", "quantity_before_ex_open", "cash_amount", "recognized_at", "modeled_release_at")
            if old:
                if len(old) != 1 or any(D(old[0][k]) != D(row[k]) if k in facts[:3]
                                      else timestamp(old[0][k]) != timestamp(row[k]) for k in facts):
                    raise ValueError("Scheduled and recorded income entitlements differ")
            else:
                incomes.append(row)
    return build_evidence(initial=book["initial_cash"], allocations={s.id: s.allocation_usd for s in strategies},
                          fills=fills, orders=orders, incomes=incomes, settlements=settlements,
                          sessions=sessions, now=now)


def _state_token(venue):
    return sha256(json.dumps((venue.metadata_ or {}).get(NAME, {}), sort_keys=True).encode()).hexdigest()


class EvidenceGuard:
    """Explicit network capture followed by a pure locked connector callback.

    Construction does no reconciliation or I/O. The runner calls ``capture``
    before known-intent submit/refresh, with its frozen execution deadline.
    An exposure/evidence change during network reads fails the locked gate.
    """
    key = NAME

    def __init__(self, sessions, *, additional=()):
        self.sessions = tuple(sessions)
        self.additional = set(additional)
        self.quotes = None
        self.market_session = None
        self.deadline = None
        self.evidence_token = None

    def capture(self, connector, *, valid_until=None):
        self.quotes = None  # never reuse the last successful batch after failure
        now = connector.now()
        session = connector._calendar(now.astimezone(NEW_YORK).date())
        expected = [s for s in self.sessions if s.trade_date == session.trade_date]
        if expected != [session] or not session.is_open(now):
            raise ValueError("Evidence calendar changed or is outside regular session")
        venue = connector._venue()
        state = (venue.metadata_ or {}).get(NAME, {})
        for proof in list(state.get("settlements", {}).values()) + state.get("incomes", []) + state.get("scheduled_income", []):
            receipt(proof["source_receipt"])
        token = _state_token(venue)
        ids = required_instrument_ids(connector.session, self.additional)
        instruments = [connector.session.get(Instrument, iid) for iid in sorted(ids)]
        if any(i is None or i.venue_id != venue.id or i.instrument_type != "equity" for i in instruments):
            raise ValueError("Unsupported portfolio exposure needs its own admitted mark source")
        symbols = {i.id: i.symbol for i in instruments}
        connector.session.commit()  # no venue lock spans remote quote requests
        rows = {iid: connector._call(connector.api.quote, symbol) for iid, symbol in symbols.items()}
        at = connector.now()
        fresh_marks(connector.session, rows, at, session, self.additional)
        for iid, row in rows.items():
            connector.session.add(Quote(instrument_id=iid, time=timestamp(row["t"]),
                bid=D(str(row["bp"])), ask=D(str(row["ap"])),
                metadata_={"connector": CONNECTOR, "feed": "iex", "kind": NAME}))
        connector.session.commit()
        self.quotes, self.market_session, self.evidence_token = rows, session, token
        deadlines = [session.closes_at]
        deadlines += [timestamp(r["t"]) + timedelta(seconds=limits.STALE_DATA_MAX_SECONDS) for r in rows.values()]
        if valid_until is not None:
            deadlines.append(timestamp(valid_until))
        self.deadline = min(deadlines)
        if at >= self.deadline:
            self.quotes = None
            raise ValueError("Evidence execution window elapsed")
        return rows

    def __call__(self, connector, context):
        from tradingbot.connectors.alpaca_paper import PaperGuardResult

        if (self.quotes is None or self.market_session is None or self.deadline is None
                or context.now >= self.deadline or _state_token(context.venue) != self.evidence_token):
            raise ValueError("Fresh unchanged account evidence capture required")
        if context.market_session is not None and context.market_session != self.market_session:
            raise ValueError("Submission calendar differs from evidence capture")
        additional = self.additional | ({context.instrument_id} if context.instrument_id else set())
        marks = fresh_marks(connector.session, self.quotes, context.now, self.market_session, additional)
        # Sources were verified outside the lock and the complete metadata token
        # is unchanged; this callback has no filesystem or network side effects.
        evidence = account_evidence(connector.session, context.venue, context.now, self.sessions,
                                    verify_receipts=False)
        fee_reserve = ZERO
        if context.side == "buy":
            fee_reserve, _ = EquityFeeBook().charge(day=context.now.astimezone(NEW_YORK).date(),
                side="buy", price=context.limit_price, size=context.quantity)
        details = {**evidence.details, "quote_batch": self.quotes,
                   "proposed_fee_reserve_usd": str(fee_reserve), "evidence_state_sha256": self.evidence_token}
        return PaperGuardResult(cash_available=max(ZERO, evidence.cash_available - fee_reserve),
            strategy_cash=(max(ZERO, evidence.strategy_cash(context.strategy_id) - fee_reserve)
                           if context.strategy_id is not None else None),
            marks=marks, strategy_pnl_offsets=evidence.strategy_offsets,
            daily_pnl_offset=evidence.daily_pnl_offset, details=details, valid_until=self.deadline)


def save_evidence(venue, *, settlement=None, income=None):
    """Append immutable admitted evidence under the caller's venue lock.

    Conflicting corrections require an explicit review; silently replacing a
    prior entitlement could change past P&L and cash. Caller validates issuer
    facts/ownership (income) or actual broker settlement facts (completion).
    """
    if (settlement is None) == (income is None):
        raise ValueError("Supply exactly one settlement or income record")
    state = json.loads(json.dumps((venue.metadata_ or {}).get(NAME, {})))
    row = settlement if settlement is not None else income
    receipt(row["source_receipt"])
    if settlement is not None:
        items = state.setdefault("settlements", {})
        key = str(settlement["fill_id"])
        if key in items and items[key] != settlement:
            raise ValueError("Conflicting settlement evidence requires review")
        items[key] = settlement
    else:
        items = state.setdefault("incomes", [])
        old = [r for r in items if (r["strategy_id"], r["event_id"]) == (income["strategy_id"], income["event_id"])]
        if old and old != [income]:
            raise ValueError("Conflicting income evidence requires review")
        if not old:
            items.append(income)
    venue.metadata_ = {**(venue.metadata_ or {}), NAME: state}


def schedule_income_event(session, venue, event, sessions, *, instrument_id, now):
    """Queue an admitted ordinary event BEFORE ex-open for every account owner.

    Every consumer's locked account evidence then derives ex-open ownership,
    including while the declaring strategy runner is offline. Recognition does
    not depend on which runner happens to perform the first daily risk check.
    This function owns no transaction and must be called under the venue lock.
    """
    now = timestamp(now)
    instrument = session.get(Instrument, instrument_id)
    if (instrument is None or instrument.venue_id != venue.id or instrument.instrument_type != "equity"
            or instrument.symbol != event["symbol"] or event.get("currency") != "USD"
            or event.get("kind") != "ordinary_cash"):
        raise ValueError("Known USD equity ordinary-income event required")
    ex, payable = date.fromisoformat(event["ex_date"]), date.fromisoformat(event["payable_date"])
    ex_sessions = [s for s in sessions if s.trade_date == ex]
    releases = [s.opens_at for s in sessions if s.trade_date > payable]
    if len(ex_sessions) != 1 or payable < ex or not releases:
        raise ValueError("Income requires an ex session and post-pay opening calendar")
    recognized, release = ex_sessions[0].opens_at, min(releases)
    observed, reviewed = timestamp(event["observed_at"]), timestamp(event["reviewed_at"])
    if not observed <= reviewed <= now:
        raise ValueError("Income source/review is future or inconsistent")
    receipt(event["source_receipt"])
    row = {"event_id": f"{instrument.symbol}:{ex}:ordinary_cash", "instrument_id": instrument_id,
           "symbol": instrument.symbol, "recognized_at": recognized.isoformat(),
           "modeled_release_at": release.isoformat(), "amount_per_share": str(amount(event["amount_per_share"], positive=True)),
           "source_observed_at": observed.isoformat(), "source_receipt": event["source_receipt"],
           "scheduled_at": now.isoformat()}
    state = json.loads(json.dumps((venue.metadata_ or {}).get(NAME, {})))
    items = state.setdefault("scheduled_income", [])
    old = [r for r in items if r["event_id"] == row["event_id"]]
    facts = ("event_id", "instrument_id", "symbol", "recognized_at", "modeled_release_at")
    if old:
        if (len(old) != 1 or any(old[0][k] != row[k] for k in facts)
                or D(old[0]["amount_per_share"]) != D(row["amount_per_share"])):
            raise ValueError("Previously scheduled income facts changed; explicit review required")
        return old[0]
    if not reviewed <= now < recognized:
        raise ValueError("New income must be scheduled before ex-open, never backdated")
    items.append(row)
    venue.metadata_ = {**(venue.metadata_ or {}), NAME: state}
    return row


CONSUMERS = {"alpaca_tom_forward_v1": (60426, "forward/turn_of_month.py"),
             "c05_forward_v1": (60434, "forward/c05_runner.py"),
             "c08_forward_v1": (60801, "forward/c08_runner.py")}


def migration_identity(session):
    """Read-only snapshot for an explicit one-book accounting migration review."""
    venue = session.scalar(select(Venue).where(Venue.key == "alpaca").execution_options(populate_existing=True))
    book = (venue.metadata_ or {}).get(CONNECTOR) if venue else None
    if not book:
        raise ValueError("Existing paper account required")
    trials, dependencies = [], {"forward/paper_evidence.py", "connectors/alpaca_paper.py", "risk/limits.py"}
    for trial in session.scalars(select(Trial).join(Strategy).where(
            Strategy.venue_id == venue.id, Trial.mode == "paper", Trial.status == "running").order_by(Trial.id)):
        if trial.code_version not in CONSUMERS:
            raise ValueError("Every running account consumer must support the evidence policy")
        dependencies.add(CONSUMERS[trial.code_version][1])
        trials.append({"trial_id": trial.id, "strategy_id": trial.strategy_id,
                       "code_version": trial.code_version,
                       "params_sha256": sha256(json.dumps(trial.params, sort_keys=True).encode()).hexdigest()})
    return {"book": {k: book[k] for k in ("initial_cash", "account", "started_at")},
            "running_trials": trials,
            "dependencies": {p: sha256((ROOT / "src/tradingbot" / p).read_bytes()).hexdigest()
                             for p in sorted(dependencies)}}


def enable_account_guard(session, review_ref, coordination_connection, *, now):
    """Explicit local migration, while all current runner locks are unoccupied.

    The caller stops existing runners before this call and restarts the same
    trial IDs afterward. No process is stopped here, no broker call is made,
    and no balance, allocation, trial identity or schedule is changed. This is
    not invoked by strategy preparation or source capture.
    """
    review = json.loads(receipt(review_ref))
    now = timestamp(now)
    if (review.get("schema") != NAME + ":migration" or review.get("decision") != "enable_account_guard"
            or not review.get("reviewer") or len(review.get("reason", "")) < 40
            or review.get("modeled_income_is_not_broker_cash") is not True
            or review.get("preserve_existing_trials_and_funding") is not True
            or not now - timedelta(days=1) <= timestamp(review["reviewed_at"]) <= now):
        raise ValueError("A current explicit account integration review is required")
    expected, held = review["identity"], []
    if expected != migration_identity(session):
        raise ValueError("Reviewed account/consumer identity changed")
    # A separate session connection keeps runner locks held across Session
    # commits. Release only locks acquired by this invocation.
    try:
        for trial in expected["running_trials"]:
            key = (CONSUMERS[trial["code_version"]][0], trial["trial_id"])
            if not coordination_connection.scalar(text("SELECT pg_try_advisory_lock(:namespace, :trial)"),
                                                   {"namespace": key[0], "trial": key[1]}):
                raise ValueError("An existing paper runner is active; preserve and stop it before migration")
            held.append(key)
        venue = session.scalar(select(Venue).where(Venue.key == "alpaca").with_for_update()
                               .execution_options(populate_existing=True))
        if expected != migration_identity(session):
            raise ValueError("Account/consumer identity changed during migration")
        book = venue.metadata_[CONNECTOR]
        if book.get("guard_required") not in (None, NAME):
            raise ValueError("Account already uses a different evidence policy")
        venue.metadata_ = {**venue.metadata_, CONNECTOR: {**book, "guard_required": NAME,
            "guard_review": review_ref, "guard_enabled_at": now.isoformat()}}
        session.flush()
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        for namespace, trial_id in reversed(held):
            coordination_connection.execute(text("SELECT pg_advisory_unlock(:namespace, :trial)"),
                                            {"namespace": namespace, "trial": trial_id})
