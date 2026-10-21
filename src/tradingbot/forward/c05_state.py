"""Frozen C05 clock, coherent close vintages and durable unchanged-reactor state."""
from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal as D

from tradingbot.connectors.cash import MarketSession, NEW_YORK, amount, timestamp
from tradingbot.forward.c05_readiness import PARAMS, SYMBOLS, digest, encoded
from tradingbot.research.c05_blackout import local_blackout
from tradingbot.strategy import MarketEvent
from tradingbot.strategy.c05_commodity_trend import CommodityTrend

NAME = "c05_forward_v1"
WINDOW = timedelta(seconds=60)
CLOSE_WINDOW = timedelta(minutes=15)


def calendar_plan(rows, *, start, through):
    start = timestamp(start)
    sessions = [MarketSession.from_api(row) for row in rows]
    days = [s.trade_date for s in sessions]
    if days != sorted(set(days)) or any((b - a).days > 7 for a, b in zip(days, days[1:])):
        raise ValueError("Ordered complete official calendar required")
    future = [s for s in sessions if s.opens_at > start and s.trade_date <= through]
    if len(future) < 2 or through not in days or future[-1].trade_date != through:
        raise ValueError("Two future sessions and an explicit terminal date required")
    if len([d for d in days if d < future[0].trade_date]) < 127 or days[-1] <= through:
        raise ValueError("Calendar needs 127 prior sessions and future cash/action coverage")
    return {"calendar": rows, "calendar_sha256": digest(encoded(rows)), "start": start.isoformat(),
            "session_dates": [str(s.trade_date) for s in future], "terminal_date": str(through),
            "opening_window_seconds": 60, "close_window_seconds": 900,
            "next_session": {str(a): str(b) for a, b in zip(days, days[1:])},
            "month_ends": [str(a) for a, b in zip(days, days[1:]) if a.month != b.month]}


def phases(params):
    if (digest(encoded(params["calendar"])) != params["calendar_sha256"]
            or params["opening_window_seconds"] != 60 or params["close_window_seconds"] != 900):
        raise ValueError("Frozen C05 calendar/window changed")
    selected, result = set(params["session_dates"]), []
    for row in params["calendar"]:
        session = MarketSession.from_api(row)
        day = str(session.trade_date)
        if day in selected:
            result.append((day + ":open", "open", session.opens_at, session))
            if day != params["terminal_date"]:
                result.append((day + ":close", "close", session.closes_at, session))
    if len(result) != 2 * len(selected) - 1:
        raise ValueError("Incomplete frozen C05 phase schedule")
    return result


def dump_core(core):
    return {"history": {s: list(map(str, v)) for s, v in core.history.items()},
            "signals": deepcopy(core.signals), "targets": {s: str(v) for s, v in core.targets.items()},
            "pending": sorted(core.pending), "reasons": deepcopy(core.reasons), "reserve": str(core.reserve),
            "decisions": deepcopy(core.decisions), "skips": deepcopy(core.skips),
            "attempted": sorted(core.attempted), "close_seen": sorted(map(list, core.close_seen)),
            "causal_exits": sorted(map(list, core.causal_exits)), "buy_day": core.buy_day,
            "buy_allocations": {s: [str(v), complete] for s, (v, complete) in core.buy_allocations.items()}}


def restore_core(params, saved=None, *, expected_params=PARAMS):
    if any(params.get(k) != v for k, v in expected_params.items()):
        raise ValueError("Frozen C05 rule parameters changed")
    if set(params["instrument_ids"]) != set(SYMBOLS) or len(set(params["instrument_ids"].values())) != 5:
        raise ValueError("Five distinct C05 instrument bindings required")
    core = CommodityTrend(params)
    core.on_start(None)
    if saved is None:
        return core
    if set(saved["history"]) != set(SYMBOLS) or set(saved["signals"]) != set(SYMBOLS):
        raise ValueError("Incomplete durable C05 universe")
    core.history = {s: [amount(v, positive=True) for v in values] for s, values in saved["history"].items()}
    if any(len(v) > 127 for v in core.history.values()) or any(type(v) is not bool for v in saved["signals"].values()):
        raise ValueError("Invalid durable C05 history/signal")
    core.signals = deepcopy(saved["signals"])
    core.targets = {s: amount(v) for s, v in saved["targets"].items()}
    core.pending = set(saved["pending"])
    if not (set(core.targets) | core.pending | set(saved["reasons"])) <= set(SYMBOLS):
        raise ValueError("Unknown durable C05 sleeve")
    core.reasons = deepcopy(saved["reasons"])
    core.reserve = amount(saved["reserve"])
    core.decisions, core.skips = deepcopy(saved["decisions"]), deepcopy(saved["skips"])
    core.attempted = set(saved["attempted"])
    core.close_seen = {tuple(row) for row in saved["close_seen"]}
    core.causal_exits = {tuple(row) for row in saved["causal_exits"]}
    core.buy_day = saved["buy_day"]
    core.buy_allocations = {s: (amount(v[0]), v[1]) for s, v in saved["buy_allocations"].items()}
    if any(type(v[1]) is not bool for v in core.buy_allocations.values()):
        raise ValueError("Invalid durable C05 allocation flag")
    return core


def observe_close(core, ctx, vintage, session):
    """Replace the adjustment basis, then deliver today's completed batch once.

    Earlier closes warm the unchanged 126-session comparison; they are not
    replayed as past decisions. Existing monthly signals/targets survive until
    the next actual scheduled close observation changes them.
    """
    if set(vintage) != set(SYMBOLS):
        raise ValueError("Complete five-fund close vintage required")
    for symbol in SYMBOLS:
        row = vintage[symbol]
        if (row["last_session"] != str(session.trade_date) or len(row["adjusted_closes"]) != 127
                or timestamp(row["observed_at"]) < session.closes_at
                or timestamp(row["observed_at"]) > ctx.now):
            raise ValueError("Close vintage is incomplete, future or not today's close")
        if (symbol, str(session.trade_date)) in core.close_seen:
            raise ValueError("Duplicate completed observation")
        core.history[symbol] = [amount(v, positive=True) for v in row["adjusted_closes"][:-1]]
    for number, symbol in enumerate(SYMBOLS):
        row = vintage[symbol]
        event = MarketEvent.quote(core.ids[symbol], session.closes_at,
            meta={"phase": "close", "adjusted_close": row["adjusted_closes"][-1],
                  "batch_last": number == len(SYMBOLS) - 1})
        if core.on_event(ctx, event):
            raise ValueError("A C05 close unexpectedly requested execution")


def action_plans(actions, sessions, *, as_of):
    """C05-local Amendment 21, including nullable/before-ex payable dates."""
    now = timestamp(as_of)
    by_day = {s.trade_date: s for s in sessions}
    plans, seen = [], set()
    for row in actions:
        identity, symbol = row["identity"], row["symbol"]
        if not identity or identity in seen or symbol not in SYMBOLS:
            raise ValueError("Duplicate or unknown C05 action identity")
        seen.add(identity)
        announced, observed, reviewed = map(timestamp, (row["announced_at"], row["observed_at"], row["reviewed_at"]))
        if not announced <= observed <= reviewed <= now:
            raise ValueError("Action timing cannot be backdated")
        if row["kind"] == "ordinary_cash":
            if reviewed >= by_day[date.fromisoformat(row["ex_date"])].opens_at:
                raise ValueError("Ordinary-income notice review is late")
            continue
        if row["kind"] not in {"split", "reverse_split", "share_exchange"}:
            raise ValueError("Unsupported C05 action requires review")
        plan = local_blackout(symbol=symbol, announced=announced.astimezone(NEW_YORK).date(),
            ex_date=date.fromisoformat(row["ex_date"]), effective=date.fromisoformat(row["effective_date"]),
            payable=date.fromisoformat(row["payable_date"]) if row.get("payable_date") else None,
            delivery=date.fromisoformat(row["expected_delivery_date"]) if row.get("expected_delivery_date") else None,
            sessions=list(by_day))
        if reviewed > by_day[date.fromisoformat(plan["decision"])].closes_at:
            raise ValueError("Action notice arrived after its causal exit decision")
        plans.append({**plan, "identity": identity, "reviewed_at": reviewed.isoformat()})
    return sorted(plans, key=lambda r: (r["exit"], r["symbol"], r["identity"]))
