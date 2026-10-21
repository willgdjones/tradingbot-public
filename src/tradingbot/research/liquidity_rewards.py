"""Reward evidence/ranking and ledger receipts; never create incentive income."""
from dataclasses import dataclass, replace
from datetime import timedelta
from decimal import Decimal
import hashlib
import json
import re

from sqlalchemy import func, select

from tradingbot.db.models import Fill, Strategy as StrategyRow, Trial
from tradingbot.risk import limits
from tradingbot.strategy.interface import Strategy
from tradingbot.strategy.liquidity_rewards import Terms, dec, instant, qualifying_book

ZERO = Decimal(0)
BASELINE = {"clip": "5", "offset_ticks": 0, "max_fills": 1,
            "fill_window_seconds": 60, "blackout_seconds": 300, "inventory_cap_usd": "15"}


@dataclass(frozen=True)
class RankedMarket:
    instrument_id: int
    market_slug: str
    program_id: str
    period_start: str
    period_end: str
    pool: str
    competing_depth: str
    pool_per_depth: str
    ranked_at: str


def rank_markets(candidates, *, at):
    """One explicit daily snapshot, excluding unknown/unsafe/unqualified rows.

    candidates require per-market period terms and full depth observed by `at`.
    Duplicate copies of a period are rejected; repeated pool values are never
    summed. Use the highest-ranked eligible period for each market.
    """
    at = instant(at)
    output, excluded, seen = {}, [], set()
    for row in candidates:
        iid = row.get("instrument_id")
        try:
            terms = Terms.from_dict(row["terms"])
            key = (row["market_slug"], terms.program_id, terms.start, terms.end)
            if key in seen:
                raise ValueError("Duplicate market-period terms")
            seen.add(key)
            if (type(iid) is not int or iid <= 0 or not isinstance(row.get("market_slug"), str)
                    or not row["market_slug"] or row.get("reviewed_non_sports") is not True
                    or row.get("insider_exposed") is not False or not row.get("review_note")):
                raise ValueError("Explicit non-sports/insider review required")
            if not terms.observed_at <= at or not terms.start <= at < terms.end:
                raise ValueError("Inactive/future-known period")
            book = row["book"]
            if not 0 <= (at - instant(book["observed_at"])).total_seconds() <= limits.STALE_DATA_MAX_SECONDS:
                raise ValueError("Fresh full depth required")
            buy, sell = qualifying_book(book, terms)
            if buy is None or sell is None:
                raise ValueError("Both sides must qualify for the initial two-sided ranking")
            depth = buy.raw_size + sell.raw_size
            ranked = RankedMarket(iid, row["market_slug"], terms.program_id,
                terms.start.isoformat(), terms.end.isoformat(), str(terms.pool), str(depth),
                str(terms.pool / depth), at.isoformat())
            previous = output.get(iid)
            if previous is None or Decimal(ranked.pool_per_depth) > Decimal(previous.pool_per_depth):
                output[iid] = ranked
        except (KeyError, TypeError, ValueError) as exc:
            excluded.append({"instrument_id": iid, "reason": str(exc)})
    return sorted(output.values(), key=lambda r: (-Decimal(r.pool_per_depth), r.market_slug, r.program_id)), excluded


def public_programs(html):
    """Read public Next.js hydration as JSON data, never execute page scripts.

    Discovery only: template rows omit per-market period timestamps/eligibility.
    Schema drift raises rather than inventing an empty eligible universe.
    """
    matches = []
    for raw in re.findall(r'self\.__next_f\.push\((\[.*?\])\)</script>', html, re.S):
        try:
            payload = json.loads(raw, parse_float=Decimal)
        except ValueError:
            continue
        if len(payload) > 1 and isinstance(payload[1], str) and '"programs":' in payload[1]:
            text = payload[1]
            offset = text.index('"programs":') + len('"programs":')
            data = json.JSONDecoder(parse_float=Decimal).raw_decode(text[offset:].lstrip())[0]
            if not isinstance(data, list):
                raise ValueError("Unexpected public programs schema")
            matches.append(data)
    if len(matches) != 1:
        raise ValueError("Expected one public programs payload")
    return matches[0]


def discovery_summary(html, *, observed_at):
    rows = public_programs(html)
    non_sports = [r for r in rows if r.get("category") in {"POL", "CRY", "CUL", "CLI", "MAC", "TECH", "GEO", "SCI"}]
    return {"observed_at": instant(observed_at).isoformat(), "source": "https://polymarket.us/rewards",
        "html_sha256": hashlib.sha256(html.encode()).hexdigest(), "program_groups": len(rows),
        "non_sports_groups": len(non_sports), "symbol_occurrences": sum(len(r.get("symbols", [])) for r in rows),
        "promoted": False, "account_eligibility_verified": False,
        "non_sports": [{k: (str(v) if isinstance(v, Decimal) else v) for k, v in r.items() if k != "symbols"}
                        | {"symbol_count": len(r.get("symbols", []))} for r in non_sports]}


class WithFillReceipts(Strategy):
    """Runtime adapter: enrich events with actual ledger fills before reaction.

    One active runtime per strategy/mode book, same Session as its engine. The
    inner strategy stays pure and identical in every mode. No commits or network
    calls occur here. Constructor/start does not reconcile a venue.
    """
    def __init__(self, inner, session, *, strategy_id):
        self.key = inner.key
        super().__init__(inner.params)
        self.inner, self.session, self.strategy_id = inner, session, strategy_id
        self.cursor = 0
        self.history_sent = False

    def on_start(self, ctx):
        self.cursor = self.session.scalar(select(func.coalesce(func.max(Fill.id), 0)).where(
            Fill.strategy_id == self.strategy_id, Fill.mode == ctx.mode))
        self.history_sent = False
        self.inner.on_start(ctx)

    def on_event(self, ctx, event):
        rows = list(self.session.scalars(select(Fill).where(Fill.strategy_id == self.strategy_id,
                    Fill.mode == ctx.mode, Fill.id > self.cursor).order_by(Fill.id)))
        own = [{"id": str(f.id), "instrument_id": f.instrument_id, "side": f.side,
                "size": str(f.size), "time": f.fill_ts.isoformat()} for f in rows]
        history = []
        if not self.history_sent:
            prior = self.session.scalars(select(Fill).where(Fill.strategy_id == self.strategy_id,
                Fill.mode == ctx.mode, Fill.id <= self.cursor,
                Fill.fill_ts > ctx.now - timedelta(seconds=self.inner.window), Fill.fill_ts <= ctx.now).order_by(Fill.id))
            history = [{"id": str(f.id), "instrument_id": f.instrument_id, "side": f.side,
                        "size": str(f.size), "time": f.fill_ts.isoformat()} for f in prior]
        enriched = replace(event, meta={**event.meta, "own_fills_complete": True,
                                       "own_fills": own, "own_fill_history": history})
        intents = self.inner.on_event(ctx, enriched)
        self.history_sent = True
        if rows:
            self.cursor = rows[-1].id
        return intents

    def on_finish(self, ctx):
        self.inner.on_finish(ctx)


def record_readiness_failure(session, *, observed_at, snapshot, git_commit):
    """Log the preregistered untestable candidate once; no strategy promotion.

    Explicit caller write, not an import/startup side effect. No fills, orders,
    allocations, P&L or fabricated p-values are created. Caller owns transaction.
    """
    row = session.scalar(select(StrategyRow).where(StrategyRow.key == "rewards"))
    if row is None:
        raise ValueError("Seed rewards strategy first")
    identity = snapshot["html_sha256"]
    old = session.scalar(select(Trial).where(Trial.strategy_id == row.id,
        Trial.metrics["liquidity_rewards"]["discovery_sha256"].as_string() == identity))
    if old:
        return old
    at = instant(observed_at)
    trial = Trial(strategy_id=row.id, mode="backtest", status="failed", params=BASELINE,
        code_version="liquidity-rewards-v1", git_commit=git_commit, created_ts=at, completed_ts=at,
        metrics={"liquidity_rewards": {"discovery_sha256": identity, "readiness": "missing_historical_evidence",
            "program_groups": snapshot["program_groups"], "non_sports_groups": snapshot["non_sports_groups"],
            "promoted": False, "reward_income_credited": "0", "drawdown": None, "regime_results": None}},
        notes="Preregistered baseline cannot be backtested: no dated historical incentive terms plus full-depth seconds/own-order exposure. Public discovery is not account eligibility; auth401 tracked in tradingbot-31w. P&L, drawdown and luck odds are unknown. No promotion.")
    session.add(trial)
    session.flush()
    return trial


def book_from_response(response, *, observed_at):
    """Normalize the public full-book response; a BBO response cannot pass."""
    raw = response["marketData"]
    if raw.get("state") != "MARKET_STATE_OPEN" or not raw.get("marketSlug"):
        raise ValueError("Identified open full book required")
    def levels(items):
        result = []
        for row in items:
            px = row["px"]
            if px.get("currency") != "USD":
                raise ValueError("USD book required")
            price, size = dec(px["value"], positive=True), dec(row["qty"], positive=True)
            if not 0 < price < 1:
                raise ValueError("Binary price out of range")
            result.append([str(price), str(size)])
        return result
    return {"state": "open", "market_slug": raw["marketSlug"], "observed_at": instant(observed_at).isoformat(),
            "bids": levels(raw["bids"]), "asks": levels(raw["offers"]), "venue_time": raw.get("transactTime")}
