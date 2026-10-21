"""Deterministic PM US reward quoting on the shared Strategy contract.

Requires explicit dated terms, full depth and complete own-fill receipts. No
venue/DB access, reward credits, mode branches or changes to PRD §6 limits.
"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_FLOOR
from zoneinfo import ZoneInfo

from tradingbot.fees.core import aware, decimal_input
from tradingbot.risk import limits
from .interface import CancelOrder, PlaceOrder, Strategy
from .registry import register

ZERO, ONE = Decimal(0), Decimal(1)
INVENTORY_CAP = Decimal(15)  # PRD §5 strategy #2, not a replacement for the §6 gate
ET = ZoneInfo("America/New_York")


def dec(value, *, positive=False):
    result = decimal_input(value)
    if positive and result <= 0:
        raise ValueError("Positive amount required")
    return result


def instant(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    aware(result)
    return result


@dataclass(frozen=True)
class Terms:
    program_id: str
    start: datetime
    end: datetime
    observed_at: datetime
    pool: Decimal
    target: Decimal
    discount: Decimal
    tick: Decimal
    max_spread: Decimal | None = None

    @classmethod
    def from_dict(cls, raw):
        if not isinstance(raw["program_id"], str) or not raw["program_id"].strip():
            raise ValueError("Program ID required")
        result = cls(raw["program_id"], instant(raw["start"]), instant(raw["end"]),
            instant(raw["observed_at"]), dec(raw["pool"], positive=True), dec(raw["target"], positive=True),
            dec(raw["discount"], positive=True), dec(raw["tick"], positive=True),
            dec(raw["max_spread"], positive=True) if raw.get("max_spread") is not None else None)
        if (not result.program_id or result.end <= result.start or result.discount > 1 or result.tick >= 1
                or raw.get("status") != "active" or raw.get("pool_scope") != "verified_market_period"):
            raise ValueError("Verified active market-period terms required")
        return result


@dataclass(frozen=True)
class SideDepth:
    best: Decimal
    cutoff: Decimal
    raw_size: Decimal
    score: Decimal
    levels: tuple[tuple[Decimal, Decimal], ...]


def side_depth(levels, *, side, terms):
    """Full price levels through the raw-size target; never truncate last level."""
    if side not in ("buy", "sell"):
        raise ValueError("Invalid side")
    by_price = defaultdict(lambda: ZERO)
    for raw in levels:
        price, size = dec(raw[0], positive=True), dec(raw[1], positive=True)
        if not 0 < price < 1 or price % terms.tick:
            raise ValueError("Invalid depth price/tick")
        by_price[price] += size
    levels = sorted(by_price.items(), reverse=side == "buy")
    if not levels:
        return None
    total, chosen = ZERO, []
    for price, size in levels:
        total += size
        chosen.append((price, size))
        if total >= terms.target:
            break
    if total < terms.target:
        return None
    best = chosen[0][0]
    score = sum(size * terms.discount ** int(abs(price - best) / terms.tick) for price, size in chosen)
    return SideDepth(best, chosen[-1][0], total, score, tuple(chosen))


def qualifying_book(raw, terms):
    if raw.get("state") != "open":
        raise ValueError("Open full book required")
    # BBO validity is checked even if one side cannot reach target depth.
    bids, asks = raw["bids"], raw["asks"]
    bid = max((dec(p) for p, _ in bids), default=ZERO)
    ask = min((dec(p) for p, _ in asks), default=ONE)
    if bid >= ask:
        raise ValueError("Crossed/locked book")
    buy = side_depth(bids, side="buy", terms=terms)
    sell = side_depth(asks, side="sell", terms=terms)
    if terms.max_spread is not None and (buy is None or sell is None or sell.cutoff - buy.cutoff > 2 * terms.max_spread):
        return None, None
    return buy, sell


def score_share(depth, *, side, price, quantity, terms):
    """Per-side instantaneous share estimate; excludes reward dollars/payouts.

    Rewalk the book including this hypothetical order, since it can change the
    eligible target-depth cutoff. The caller must separately retest Max Spread.
    """
    price, quantity = dec(price, positive=True), dec(quantity, positive=True)
    new = side_depth([*depth, (price, quantity)], side=side, terms=terms)
    if new is None or (side == "buy" and price < new.cutoff) or (side == "sell" and price > new.cutoff):
        return ZERO
    score = quantity * terms.discount ** int(abs(price - new.best) / terms.tick)
    return score / new.score


@register
class LiquidityRewards(Strategy):
    key = "rewards"

    def __init__(self, params=None):
        super().__init__(params)
        self.clip = dec(self.params.get("clip", "5"), positive=True)
        self.offset = self.params.get("offset_ticks", 0)
        self.fill_cap = self.params.get("max_fills", 1)
        self.window = self.params.get("fill_window_seconds", 60)
        self.blackout = self.params.get("blackout_seconds", 300)
        if any(type(v) is not int for v in (self.offset, self.fill_cap, self.window, self.blackout)) or min(
                self.fill_cap, self.window, self.blackout) <= 0 or self.offset < 0:
            raise ValueError("Positive fill/time guards and nonnegative integer tick offset required")
        self.markets = {int(i): dict(v) for i, v in self.params.get("markets", {}).items()}
        if not self.markets:
            raise ValueError("Explicit reviewed market universe required")
        if len({m["market_id"] for m in self.markets.values()}) != len(self.markets):
            raise ValueError("Use one canonical YES instrument per market")
        self.terms = {i: Terms.from_dict(m["terms"]) for i, m in self.markets.items()}

    def on_start(self, ctx):
        if any(ctx.position(i) for i in self.markets):
            raise ValueError("Start flat or explicitly restore prior strategy state")
        self.positions = dict.fromkeys(self.markets, ZERO)
        self.seen_fills, self.fill_times = {}, defaultdict(list)
        self.books, self.desired = {}, {}
        self.generation = 0
        self.execution_unknown = False
        self.history_loaded = False
        self.last_reason = None

    def _receipts(self, ctx, event):
        if event.meta.get("own_fills_complete") is not True:
            self.execution_unknown = True
            self.last_reason = "Complete own-fill evidence is required"
            return
        delta = dict.fromkeys(self.markets, ZERO)
        try:
            history = event.meta.get("own_fill_history", []) if not self.history_loaded else []
            self.history_loaded = True
            rows = [(row, True) for row in history] + [(row, False) for row in event.meta.get("own_fills", [])]
            for row, historical in rows:
                iid, fid = int(row["instrument_id"]), str(row["id"])
                qty, at = dec(row["size"], positive=True), instant(row["time"])
                side = row["side"]
                if iid not in self.markets or not fid or side not in ("buy", "sell") or at > ctx.now:
                    raise ValueError("Invalid own fill")
                economics = (iid, side, qty, at)
                if fid in self.seen_fills:
                    if self.seen_fills[fid] != economics:
                        raise ValueError("Conflicting fill receipt")
                    continue
                self.seen_fills[fid] = economics
                if not historical:
                    delta[iid] += qty if side == "buy" else -qty
                self.fill_times[iid].append(at)
            for iid in self.markets:
                held = dec(ctx.position(iid))
                if held != self.positions[iid] + delta[iid]:
                    raise ValueError("Position and own-fill receipts disagree")
                self.positions[iid] = held
        except (KeyError, TypeError, ValueError):
            self.execution_unknown = True
            self.last_reason = "Invalid or incomplete own-fill evidence"

    def _eligible(self, iid, ctx):
        m, terms = self.markets[iid], self.terms[iid]
        now = instant(ctx.now)
        cutoff = now - timedelta(seconds=self.window)
        self.fill_times[iid] = [t for t in self.fill_times[iid] if t > cutoff]
        if self.execution_unknown or len(self.fill_times[iid]) >= self.fill_cap:
            return False
        if (m.get("reviewed_non_sports") is not True or m.get("insider_exposed") is not False
                or not m.get("review_note") or m.get("selected") is not True):
            return False
        if not terms.start <= now < terms.end or terms.observed_at > now:
            return False
        ranked = instant(m["ranked_at"])
        if ranked > now or ranked.astimezone(ET).date() != now.astimezone(ET).date():
            return False
        if instant(m["events_reviewed_through"]) < terms.end:
            return False
        for at in m["event_times"]:
            # Stop through program end after a scheduled event. Re-entry needs
            # a separately reviewed later period, not an arbitrary cool-down.
            if now >= instant(at) - timedelta(seconds=self.blackout):
                return False
        return True

    def _quotes(self, iid, ctx):
        raw = self.books.get(iid)
        if raw is None or not 0 <= (ctx.now - instant(raw["observed_at"])).total_seconds() <= limits.STALE_DATA_MAX_SECONDS:
            return ()
        terms, market = self.terms[iid], self.markets[iid]
        buy, sell = qualifying_book(raw, terms)
        if not raw["bids"] or not raw["asks"]:
            return ()
        bid = max(dec(p) for p, _ in raw["bids"])
        ask = min(dec(p) for p, _ in raw["asks"])
        held = self.positions[iid]
        inventory = held * ask if held >= 0 else -held * (1 - bid)
        sides = ("sell",) if inventory >= INVENTORY_CAP and held > 0 else ("buy",) if inventory >= INVENTORY_CAP and held < 0 else ("buy", "sell")
        # Ordinary operation is two-sided. A cap-constrained reducing quote may
        # still qualify on its own where the period has no Max Spread.
        if len(sides) == 2 and (buy is None or sell is None):
            return ()
        wanted = []
        for side in sides:
            depth = buy if side == "buy" else sell
            if depth is None:
                continue
            price = bid - self.offset * terms.tick if side == "buy" else ask + self.offset * terms.tick
            if not 0 < price < 1 or (side == "buy" and price < depth.cutoff) or (side == "sell" and price > depth.cutoff):
                continue
            capacity = INVENTORY_CAP / ask - held if side == "buy" else INVENTORY_CAP / (1 - bid) + held
            size = min(self.clip, max(ZERO, capacity))
            if len(sides) == 1:
                size = min(size, abs(held))  # reduce only, never flip to the other side
            size = size.quantize(Decimal(".0000000001"), rounding=ROUND_FLOOR)
            if size >= dec(market["minimum_quantity"], positive=True):
                wanted.append((side, price, size))
        return tuple(wanted)

    def on_event(self, ctx, event):
        self._receipts(ctx, event)
        if event.instrument_id in self.markets and event.is_quote and "full_book" in event.meta:
            self.books[event.instrument_id] = event.meta["full_book"]
        intents = []
        # Guard all markets on every callback, including explicit clock callbacks.
        # The runtime must supply timer events for pre-event cancellation in quiet periods.
        for iid in self.markets:
            tags = ctx.resting_tags(iid)
            try:
                desired = self._quotes(iid, ctx) if self._eligible(iid, ctx) else ()
            except (KeyError, TypeError, ValueError):
                desired = ()
                self.last_reason = "Missing/invalid market, calendar or depth evidence"
            if tags:
                if desired != self.desired.get(iid) or not desired:
                    intents.extend(CancelOrder(tag=t) for t in tags)
                continue  # cancellation must be acknowledged before replacement
            self.desired[iid] = desired
            if not desired:
                continue
            self.generation += 1
            for side, price, size in desired:
                intents.append(PlaceOrder(instrument_id=iid, side=side, size=size, limit_price=price,
                    intended_liquidity="maker", tag=f"lr-{iid}-{self.generation}-{side}",
                    reason=f"ranked rewards period {self.terms[iid].program_id}; inventory bounded at $15"))
        return intents
