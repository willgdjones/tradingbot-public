"""Frozen C08 clock, serializable reactor state and causal notice adaptation."""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta
from decimal import Decimal as D

from tradingbot.connectors.cash import MarketSession, NEW_YORK, timestamp
from tradingbot.forward.c08_readiness import digest, encoded
from tradingbot.research.action_blackout import CorporateAction, plan_blackouts
from tradingbot.strategy.c08_inventory import InventoryScarcity

NAME = "c08_forward_v1"
PARAMS = {"threshold": "-0.05", "target_weight": ".95", "slot_usd": "140",
          "buy_fee_reserve_usd": ".01", "quantity_step": ".000000001"}
WINDOW = timedelta(seconds=60)


def calendar_plan(rows, *, start, through):
    start = timestamp(start)
    sessions = [MarketSession.from_api(row) for row in rows]
    days = [s.trade_date for s in sessions]
    if days != sorted(set(days)) or len(days) < 3:
        raise ValueError("Ordered unique official calendar required")
    if any((b - a).days > 7 for a, b in zip(days, days[1:])):
        raise ValueError("Calendar gap requires review")
    future = [s for s in sessions if s.opens_at > start and s.trade_date <= through]
    if len(future) < 2 or through not in days or future[-1].trade_date != through:
        raise ValueError("Two future sessions and an explicit terminal trading date required")
    if days[0] >= future[0].trade_date or days[-1] <= through:
        raise ValueError("Calendar must extend before start and after terminal for action/cash evidence")
    return {"calendar": rows, "calendar_sha256": digest(encoded(rows)),
            "start": start.isoformat(), "session_dates": [str(s.trade_date) for s in future],
            "terminal_date": str(through), "opening_window_seconds": 60,
            "close_window_seconds": 60}


def phases(params):
    if digest(encoded(params["calendar"])) != params["calendar_sha256"]:
        raise ValueError("Frozen calendar changed")
    selected = set(params["session_dates"])
    result = []
    for row in params["calendar"]:
        session = MarketSession.from_api(row)
        if str(session.trade_date) in selected:
            result.append((f"{session.trade_date}:open", "open", session.opens_at, session))
            if str(session.trade_date) != params["terminal_date"]:
                result.append((f"{session.trade_date}:close", "close", session.closes_at, session))
    if len(result) != 2 * len(selected) - 1:
        raise ValueError("Frozen phase schedule is incomplete")
    return result


def dump_core(core):
    pending = deepcopy(core.pending)
    if pending is not None:
        for key in ("target", "reserve", "decision_equity"):
            pending[key] = str(pending[key])
    return {"latest": deepcopy(core.latest), "pending": pending,
            "attempted": sorted(core.attempted), "blackout_decisions": sorted(core.blackout_decisions),
            "after_forced_exit": core.after_forced_exit,
            "decisions": deepcopy(core.decisions), "skips": deepcopy(core.skips)}


def restore_core(params, saved=None):
    if any(params.get(k) != v for k, v in PARAMS.items()):
        raise ValueError("C08 reactor parameters differ from the evaluated rule")
    core = InventoryScarcity(params)
    core.on_start(None)
    if saved is None:
        return core
    core.latest = deepcopy(saved["latest"])
    core.pending = deepcopy(saved["pending"])
    if core.pending is not None:
        for key in ("target", "reserve", "decision_equity"):
            value = D(core.pending[key])
            if not value.is_finite() or value < 0:
                raise ValueError("Invalid durable pending target")
            core.pending[key] = value
    core.attempted = set(saved["attempted"])
    core.blackout_decisions = set(saved["blackout_decisions"])
    core.after_forced_exit = saved["after_forced_exit"]
    if not isinstance(core.after_forced_exit, bool):
        raise ValueError("Invalid durable forced-exit flag")
    core.decisions, core.skips = deepcopy(saved["decisions"]), deepcopy(saved["skips"])
    return core


def action_plans(actions, sessions, *, as_of):
    """Only first-seen, reviewed advance notices can create prior-close plans."""
    as_of = timestamp(as_of)
    by_day = {s.trade_date: s for s in sessions}
    result, identities = [], set()
    for row in actions:
        if row["symbol"] != "USO" or not row.get("identity") or row["identity"] in identities:
            raise ValueError("Invalid or repeated USO action identity")
        identities.add(row["identity"])
        announced = timestamp(row["announced_at"])
        observed, reviewed = timestamp(row["observed_at"]), timestamp(row["reviewed_at"])
        if announced > observed or observed > reviewed or reviewed > as_of:
            raise ValueError("Action timing cannot be observed/reviewed retroactively")
        if row["kind"] == "ordinary_cash":
            ex, payable = date.fromisoformat(row["ex_date"]), date.fromisoformat(row["payable_date"])
            value = D(row["amount_per_share"])
            if (row.get("currency") != "USD" or not value.is_finite() or value <= 0
                    or ex not in by_day or payable < ex or max(announced, observed, reviewed) >= by_day[ex].opens_at
                    or not any(day > payable for day in by_day)):
                raise ValueError("Ordinary income lacks causal rate/date/session evidence")
            continue  # The income adapter separately derives ownership and recognition.
        action = CorporateAction("USO", row["kind"], announced.astimezone(NEW_YORK).date(),
            date.fromisoformat(row["ex_date"]), date.fromisoformat(row["payable_date"]), row["identity"])
        plans = plan_blackouts([action], list(by_day))
        if len(plans) != 1:
            raise ValueError("Unknown corporate action requires explicit resolution")
        plan = plans[0]
        if max(announced, observed, reviewed) > by_day[plan.decision].closes_at:
            raise ValueError("Action notice arrived after its safe exit decision")
        result.append({"identity": row["identity"], "decision": str(plan.decision),
                       "exit": str(plan.exit), "reentry": str(plan.reentry),
                       "reviewed_at": reviewed.isoformat()})
    return sorted(result, key=lambda r: (r["exit"], r["identity"]))


def eligible_release(eia, *, reviewed_at, scheduled_open):
    """Original stale-report policy stays in the reactor; never use mid-window data."""
    reviewed, opened = timestamp(reviewed_at), timestamp(scheduled_open)
    available = max(timestamp(eia["available_at"]), reviewed)
    if available >= opened:
        return None
    layout, fields = eia["layout"], eia["fields"]
    if fields.get("units_verified") is not True:
        raise ValueError("Commercial-stock units were not verified")
    observation, release = date.fromisoformat(layout["observation_date"]), date.fromisoformat(layout["release_date"])
    if observation >= release or release >= opened.date():
        raise ValueError("Invalid EIA observation/publication ordering")
    for key in ("commercial_current", "commercial_year_ago"):
        value = D(fields[key])
        if not value.is_finite() or value <= 0:
            raise ValueError("Invalid EIA stock denominator or numerator")
    return {"key": layout["release_date"] + ":" + layout["observation_date"],
            "observation_date": str(observation), "release_date": str(release),
            "available_at": available.isoformat(), "commercial_current": fields["commercial_current"],
            "commercial_year_ago": fields["commercial_year_ago"],
            "first_release_vintage_verified": eia["first_release_vintage_verified"]}
