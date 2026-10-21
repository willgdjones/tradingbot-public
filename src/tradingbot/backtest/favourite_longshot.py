"""Backtest driver for PRD §5 strategy #1 (favourite–longshot bias).

Runs the :class:`~tradingbot.strategy.favourite_longshot.FavouriteLongshotBias`
reactor over the historical tape in TimescaleDB, **by category**, maker-only,
holding to settlement, over markets that resolve within 7 days — and scores it
**after exact Polymarket US fees**, because that is where strategy #1 trades
live (PRD §5). Every variant tried is written to the trials ledger, including
the ones that make nothing (PRD §4).

Two deliberate modelling choices, both forced by the PRD and the data:

* **PM US fees on whatever tape fills.** The only maker-fillable tape in the
  current capture is Kalshi (public history is research evidence for the bias,
  PRD §5); PM US ships display prices with no trades, so a maker order there
  never fills. We therefore charge the *current PM US* maker/taker coefficients
  on every simulated fill regardless of the instrument's native venue, via
  :class:`_PmUsFeeLedger`. The PM US maker coefficient is a **rebate** (negative
  fee), so a filled maker is paid to provide liquidity.
* **"Resolves within 7 days" = only the last 7 days before resolution are
  tradeable.** For each market we feed events in ``[resolution - 7d, close)``
  and settle at the payout, so the strategy only ever holds a position for up to
  a week — the spirit of PRD §5's 7-day rule.

Isolation: each variant runs inside a SAVEPOINT that is rolled back, so its
orders / fills / positions never persist or contaminate the next variant (the
positions table is keyed by strategy+mode+instrument, not by trial — see
:mod:`tradingbot.backtest.engine`). Only a clean :class:`Trial` summary row per
variant is kept, which *is* the trials ledger.

Run it::

    uv run python -m tradingbot.backtest.favourite_longshot
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..db import enums
from ..db.models import Strategy as StrategyRow
from ..db.models import Trial
from ..fees import PM_US_STANDARD_2026_09_25 as _PM_STD
from ..fees import PolymarketUSSchedule
from ..ledger.ledger import Ledger
from ..strategy.favourite_longshot import SIDE_RULES, FavouriteLongshotBias
from .engine import Backtester, Settlement
from .feed import market_events
from .holdout import HoldoutSplit, register_split
from .report import drawdown_regime_report

STRATEGY_KEY = "longshot"
DEFAULT_VENUES = ("kalshi", "polymarket_us")
DEFAULT_OFFSETS = ("0.01", "0.02", "0.05")
WITHIN_DAYS = 7

# Current PM US coefficients, but dated early enough to cover the historical tape.
# Scoring the Kalshi research tape "as if traded on PM US" (PRD §5) needs the
# coefficients without the live schedule's 2026-09-25 start-date guard.
PM_US_RESEARCH_SCHEDULE = PolymarketUSSchedule(
    schedule_id="pm-us-standard-applied-to-history",
    effective_from=datetime(2025, 1, 1, tzinfo=ZoneInfo("America/New_York")),
    taker_coefficient=_PM_STD.taker_coefficient,
    maker_coefficient=_PM_STD.maker_coefficient,
)


class _PmUsFeeLedger(Ledger):
    """Charge the current Polymarket US fee on every fill, whatever the native
    venue — strategy #1 researches on the Kalshi tape but trades on PM US, so the
    honest after-fees figure is after PM US fees (PRD §5)."""

    def _info(self, instrument_id: int) -> tuple[str, Decimal]:
        _venue_key, multiplier = super()._info(instrument_id)
        return ("polymarket_us", multiplier)


# ---------------------------------------------------------------------------
# Market selection
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class _Inst:
    instrument_id: int
    market_id: int
    venue: str
    category: str
    payout: Decimal
    close_ts: datetime
    resolution_ts: datetime

    @property
    def window_start(self) -> datetime:
        return self.resolution_ts - timedelta(days=WITHIN_DAYS)

    @property
    def window_end(self) -> datetime:
        return self.close_ts


_ELIGIBLE_SQL = text(
    """
    SELECT v.key AS venue,
           COALESCE(m.metadata->'historical'->'state'->>'series_ticker',
                    m.category, 'uncategorized') AS category,
           i.id AS instrument_id,
           i.market_id AS market_id,
           (i.metadata->'historical'->'state'->>'payout')::numeric AS payout,
           m.close_ts AS close_ts,
           m.resolve_ts AS resolution_ts
    FROM instruments i
    JOIN markets m ON m.id = i.market_id
    JOIN venues v ON v.id = i.venue_id
    WHERE v.key = ANY(:venues)
      AND (:all_categories OR COALESCE(m.metadata->'historical'->'state'->>'series_ticker',
                                       m.category, 'uncategorized') = ANY(:categories))
      AND i.metadata->'historical'->'state'->>'status' = 'settled'
      AND i.metadata->'historical'->'state'->>'payout' IS NOT NULL
      AND m.resolve_ts IS NOT NULL
      AND (
        EXISTS (SELECT 1 FROM trades t
                 WHERE t.instrument_id = i.id
                   AND t.time >= m.resolve_ts - make_interval(days => :within)
                   AND t.time <  m.close_ts)
        OR EXISTS (SELECT 1 FROM quotes q
                 WHERE q.instrument_id = i.id
                   AND q.time >= m.resolve_ts - make_interval(days => :within)
                   AND q.time <  m.close_ts)
      )
    ORDER BY v.key, category, i.id
    """
)


def eligible_instruments(
    session: Session,
    *,
    venues: tuple[str, ...] = DEFAULT_VENUES,
    categories: tuple[str, ...] | None = None,
) -> list[_Inst]:
    """Settled instruments with a known payout and at least one market-data event
    in their tradeable 7-day window — the only markets we can both fill and score.

    ``categories`` restricts to those category names (Kalshi series tickers or the
    PM/intl category column), for re-running or testing a single category."""
    rows = session.execute(
        _ELIGIBLE_SQL, {"venues": list(venues), "within": WITHIN_DAYS,
                        "all_categories": categories is None, "categories": list(categories or ())}
    ).all()
    wanted = set(categories) if categories is not None else None
    return [
        _Inst(
            instrument_id=r.instrument_id,
            market_id=r.market_id,
            venue=r.venue,
            category=r.category,
            payout=Decimal(r.payout),
            close_ts=r.close_ts,
            resolution_ts=r.resolution_ts,
        )
        for r in rows
        if wanted is None or r.category in wanted
    ]


@dataclass
class _Category:
    venue: str
    category: str
    insts: list[_Inst] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.venue}:{self.category}"


def _by_category(insts: list[_Inst]) -> list[_Category]:
    cats: dict[str, _Category] = {}
    for inst in insts:
        cat = cats.setdefault(
            f"{inst.venue}:{inst.category}", _Category(inst.venue, inst.category)
        )
        cat.insts.append(inst)
    return list(cats.values())


# ---------------------------------------------------------------------------
# Running the grid
# ---------------------------------------------------------------------------
def _json_safe(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def _reference_maps(cat: _Category) -> dict:
    """market_of / siblings / event_ts the strategy needs, built from public
    reference data (never a settlement value)."""
    by_market: dict[int, list[int]] = {}
    for inst in cat.insts:
        by_market.setdefault(inst.market_id, []).append(inst.instrument_id)
    market_of = {str(i.instrument_id): i.market_id for i in cat.insts}
    siblings = {
        str(i.instrument_id): [j for j in by_market[i.market_id] if j != i.instrument_id]
        for i in cat.insts
    }
    event_ts = {str(i.instrument_id): i.close_ts.isoformat() for i in cat.insts}
    return {"market_of": market_of, "siblings": siblings, "event_ts": event_ts}


def _category_feed(session: Session, cat: _Category, split: HoldoutSplit, final_holdout=False):
    """The merged, time-ordered event stream and the settlement list for a whole
    category (each instrument windowed to its own last 7 days before resolution)."""
    settlements = []
    windows = []
    for inst in cat.insts:
        if not split.contains(inst.resolution_ts, final_holdout=final_holdout):
            continue
        lower = split.holdout_start if final_holdout else split.data_start
        windows.append((inst.instrument_id, max(inst.window_start, lower), inst.window_end))
        settlements.append(
            Settlement(inst.instrument_id, inst.payout, inst.resolution_ts)
        )
    def events():
        # Do not read prices until Backtester has durably admitted the final.
        # A fresh iterator is needed for each training variant.
        import heapq
        yield from heapq.merge(
            *(market_events(session, [iid], start=start, end=end) for iid, start, end in windows),
            key=lambda e: (e.time, 0 if e.is_trade else 1),
        )
    return events, settlements


@dataclass
class VariantResult:
    category: str
    venue: str
    side_rule: str
    offset: str
    trial_id: int
    pnl_after_fees: Decimal
    trade_count: int
    fills: int
    orders_placed: int
    orders_rejected: int
    luck_p_value: float | None


def run_favourite_longshot(
    session: Session,
    *,
    split: HoldoutSplit,
    final_holdout: bool = False,
    venues: tuple[str, ...] = DEFAULT_VENUES,
    categories: tuple[str, ...] | None = None,
    offsets: tuple[str, ...] = DEFAULT_OFFSETS,
    side_rules: tuple[str, ...] = SIDE_RULES,
    size: str = "10",
    max_fills_per_market: int = 3,
) -> dict:
    """Backtest strategy #1 across every category, writing one trial per variant.

    Returns a structured summary with the side the backtest picks per category.
    Does not commit — the caller owns the transaction (trials persist on commit;
    each variant's orders/fills roll back via a savepoint)."""
    if final_holdout and (len(offsets) != 1 or len(side_rules) != 1):
        raise ValueError("final holdout requires one frozen side/offset, not a tuning grid")
    if not final_holdout:
        register_split(session, split)  # Keep this outside the per-variant SAVEPOINT.
    strat_row = session.scalar(select(StrategyRow).where(StrategyRow.key == STRATEGY_KEY))
    if strat_row is None:
        raise RuntimeError(
            f"strategy {STRATEGY_KEY!r} not seeded; run `python -m tradingbot.db.seed`"
        )
    strategy_id = strat_row.id

    cats_list = _by_category(
        eligible_instruments(session, venues=venues, categories=categories)
    )
    summary: dict = {
        "strategy_id": strategy_id,
        "within_days": WITHIN_DAYS,
        "fee_basis": PM_US_RESEARCH_SCHEDULE.schedule_id,
        "venues": list(venues),
        "categories": [],
        "trials_written": 0,
        "holdout": {**split.metadata(), "final_holdout": final_holdout},
    }

    for cat in cats_list:
        events, settlements = _category_feed(session, cat, split, final_holdout)
        if not settlements:
            continue
        ref_maps = _reference_maps(cat)
        variants: list[VariantResult] = []

        for side_rule in side_rules:
            for offset in offsets:
                tuning = {
                    "side_rule": side_rule,
                    "offset": offset,
                    "size": size,
                    "max_fills_per_market": max_fills_per_market,
                    "within_days": WITHIN_DAYS,
                    "category": cat.category,
                    "venue": cat.venue,
                }
                run_params = {**tuning, **ref_maps}

                sp = session.begin_nested()
                try:
                    strat = FavouriteLongshotBias(run_params)
                    bt = Backtester(session, strategy=strat, strategy_id=strategy_id)
                    bt.ledger = _PmUsFeeLedger(
                        session, auto_fee=True,
                        fee_schedules={"polymarket_us": PM_US_RESEARCH_SCHEDULE},
                    )
                    result = bt.run(
                        events(), settlements=settlements, params=run_params,
                        split=split, final_holdout=final_holdout,
                        version_params={"fee_basis": PM_US_RESEARCH_SCHEDULE.schedule_id},
                        notes=f"strategy#1 {cat.key} {side_rule} offset={offset}",
                    )
                    report = dict(result.report)
                    replay_trial = session.get(Trial, result.trial_id)
                    data_start, data_end = replay_trial.data_start, replay_trial.data_end
                    audit_fields = {name: getattr(replay_trial, name) for name in
                                    ("params", "dataset_key", "holdout_start", "strategy_version", "final_holdout")}
                    placed, rejected, fills = (
                        result.orders_placed, result.orders_rejected, result.fills,
                    )
                    # Drawdown + per-regime breakdown while the fills still exist
                    # (they roll back with the savepoint). The scalar drawdown is
                    # already in report["max_drawdown"]; this adds the regime split.
                    by_regime = drawdown_regime_report(
                        session, strategy_id=strategy_id,
                        mode=enums.Mode.BACKTEST, trial_id=result.trial_id,
                    )["by_regime"]
                finally:
                    sp.rollback()
                session.expunge_all()

                lp = report["luck_p_value"]
                trial_fields = dict(
                    strategy_id=strategy_id,
                    mode=enums.Mode.BACKTEST,
                    data_start=data_start,
                    data_end=data_end,
                    status=enums.TrialStatus.COMPLETE,
                    pnl=report["pnl"],
                    pnl_after_fees=report["pnl_after_fees"],
                    fees_total=report["fees_total"],
                    trade_count=report["trade_count"],
                    max_drawdown=report["max_drawdown"],
                    luck_p_value=Decimal(str(lp)) if lp is not None else None,
                    metrics=_json_safe(
                        {
                            "venue": cat.venue,
                            "category": cat.category,
                            "side_rule": side_rule,
                            "offset": offset,
                            "fill_count": report["fill_count"],
                            "orders_placed": placed,
                            "orders_rejected": rejected,
                            "fills": fills,
                            "n_markets": len({i.market_id for i in cat.insts}),
                            "n_instruments": len(cat.insts),
                            "fee_basis": PM_US_RESEARCH_SCHEDULE.schedule_id,
                            "max_drawdown": report["max_drawdown"],
                            "by_regime": by_regime,
                        }
                    ),
                    notes=(
                        f"Strategy #1 favourite-longshot, {cat.key}, {side_rule}, "
                        f"offset={offset}, maker-only, hold-to-settlement, "
                        f"<= {WITHIN_DAYS}d, PM US fees."
                    ),
                )
                trial_fields.update(audit_fields)
                if final_holdout:
                    trial = session.get(Trial, result.trial_id)
                    for name, value in trial_fields.items():
                        setattr(trial, name, value)
                else:
                    trial = Trial(**trial_fields)
                session.add(trial)
                session.flush()
                summary["trials_written"] += 1

                variants.append(
                    VariantResult(
                        category=cat.category, venue=cat.venue, side_rule=side_rule,
                        offset=offset, trial_id=trial.id,
                        pnl_after_fees=report["pnl_after_fees"],
                        trade_count=report["trade_count"], fills=fills,
                        orders_placed=placed, orders_rejected=rejected,
                        luck_p_value=lp,
                    )
                )

        traded = [v for v in variants if v.trade_count > 0]
        chosen = max(traded, key=lambda v: v.pnl_after_fees) if traded else None
        summary["categories"].append(
            {
                "category": cat.category,
                "venue": cat.venue,
                "n_markets": len({i.market_id for i in cat.insts}),
                "n_instruments": len(cat.insts),
                "chosen": (
                    None
                    if chosen is None
                    else {
                        "side_rule": chosen.side_rule,
                        "offset": chosen.offset,
                        "pnl_after_fees": str(chosen.pnl_after_fees),
                        "trade_count": chosen.trade_count,
                        "luck_p_value": chosen.luck_p_value,
                        "trial_id": chosen.trial_id,
                    }
                ),
                "variants": [
                    {
                        "side_rule": v.side_rule,
                        "offset": v.offset,
                        "pnl_after_fees": str(v.pnl_after_fees),
                        "trade_count": v.trade_count,
                        "fills": v.fills,
                        "orders_placed": v.orders_placed,
                        "orders_rejected": v.orders_rejected,
                        "luck_p_value": v.luck_p_value,
                        "trial_id": v.trial_id,
                    }
                    for v in variants
                ],
            }
        )

    return summary


def _print_summary(summary: dict) -> None:
    print(f"\nStrategy #1 favourite-longshot backtest "
          f"(strategy_id={summary['strategy_id']}, "
          f"fees={summary['fee_basis']}, <= {summary['within_days']}d, "
          f"{summary['trials_written']} trials written)")
    if not summary["categories"]:
        print("  No eligible categories: no settled market with a payout and "
              "market-data in its tradeable 7-day window.")
        return
    for cat in summary["categories"]:
        chosen = cat["chosen"]
        pick = (
            "no fillable edge (0 round trips in any variant)"
            if chosen is None
            else (f"PICK {chosen['side_rule']} offset={chosen['offset']} -> "
                  f"${chosen['pnl_after_fees']} after fees over "
                  f"{chosen['trade_count']} round trips "
                  f"(luck p={chosen['luck_p_value']})")
        )
        print(f"\n  [{cat['venue']}:{cat['category']}] "
              f"{cat['n_markets']} market(s), {cat['n_instruments']} instrument(s): {pick}")
        for v in cat["variants"]:
            print(f"      {v['side_rule']:<14} off={v['offset']:<5} "
                  f"pnl_af=${v['pnl_after_fees']:<10} trips={v['trade_count']:<3} "
                  f"fills={v['fills']:<3} placed={v['orders_placed']:<3} "
                  f"rej={v['orders_rejected']:<3} trial={v['trial_id']}")


def main() -> None:
    import argparse
    import sys
    from ..db.session import session_scope

    if len(sys.argv) > 1 and sys.argv[1] == "full-history":
        from .longshot_history import main as full_history_main
        full_history_main(sys.argv[2:])
        return

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-key", required=True)
    parser.add_argument("--data-start", type=datetime.fromisoformat, required=True)
    parser.add_argument("--data-end", type=datetime.fromisoformat, required=True)
    parser.add_argument("--final-holdout", action="store_true")
    parser.add_argument("--side-rule", choices=SIDE_RULES)
    parser.add_argument("--offset")
    args = parser.parse_args()
    if args.final_holdout and (args.side_rule is None or args.offset is None):
        parser.error("--final-holdout requires --side-rule and --offset")
    split = HoldoutSplit(args.dataset_key, args.data_start, args.data_end)
    with session_scope() as session:
        summary = run_favourite_longshot(session, split=split, final_holdout=args.final_holdout,
                                        side_rules=(args.side_rule,) if args.side_rule else SIDE_RULES,
                                        offsets=(args.offset,) if args.offset else DEFAULT_OFFSETS)
        _print_summary(summary)
        # session_scope commits: the trial summaries persist (variant internals
        # were rolled back per-savepoint).


if __name__ == "__main__":
    main()
