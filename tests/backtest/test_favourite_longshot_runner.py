"""End-to-end tests for the strategy #1 backtest driver (tradingbot-0s0).

Synthesises one settled Kalshi market with a maker-fillable tape, then checks the
driver: category selection, PM US fees on the fills, one trial per variant in the
ledger, the per-category side pick, and that each variant's orders/fills/positions
are rolled back (only trial summaries persist). Uses the rolled-back ``session``
fixture from tests/backtest/conftest.py."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from tradingbot.backtest.favourite_longshot import (
    eligible_instruments,
    run_favourite_longshot,
)
from tradingbot.db import enums
from tradingbot.backtest.holdout import HoldoutSplit
from tradingbot.db.models import Fill, Instrument, Market, Order, Position, Strategy, Trial, Venue

D = Decimal
CLOSE = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
RESOLVE = CLOSE + timedelta(minutes=18)
SPLIT = HoldoutSplit("test-longshot-fixture", CLOSE - timedelta(days=1), CLOSE + timedelta(days=9))


def _t(minutes: int) -> datetime:
    # Comfortably inside [RESOLVE - 7d, CLOSE): a few hours before close.
    return CLOSE - timedelta(hours=5) + timedelta(minutes=minutes)


@pytest.fixture()
def kalshi_market(session, add_trade):
    """A settled Kalshi binary market (yes settles 0, no settles 1) with a tape
    that goes *through* a resting maker on each side within the 7-day window."""
    kalshi = session.scalar(select(Venue).where(Venue.key == "kalshi"))
    market = Market(
        venue_id=kalshi.id, external_id="TESTSERIES-26AUG",
        market_type=enums.MarketType.BINARY, status=enums.MarketStatus.SETTLED,
        close_ts=CLOSE, resolve_ts=RESOLVE,
        metadata_={"historical": {"state": {"series_ticker": "TESTSERIES"}}},
    )
    session.add(market)
    session.flush()

    def _inst(outcome, itype, payout):
        inst = Instrument(
            venue_id=kalshi.id, market_id=market.id,
            external_id=f"TESTSERIES-26AUG-T0:{outcome}", symbol="TESTSERIES-26AUG-T0",
            instrument_type=itype, outcome=outcome,
            price_min=D("0"), price_max=D("1"), contract_multiplier=D("1"),
            metadata_={"historical": {"state": {"status": "settled", "payout": payout}}},
        )
        session.add(inst)
        session.flush()
        return inst

    yes = _inst("yes", enums.InstrumentType.BINARY_YES, "0.0000")  # longshot, loses
    no = _inst("no", enums.InstrumentType.BINARY_NO, "1.0000")     # favourite, wins

    meta = {"historical": {"maker_fill_eligible": True}}
    # ts0: set references (no=0.60 favourite, yes=0.40 longshot).
    add_trade(no.id, _t(0), price=D("0.60"), size=D("10"), metadata=meta)
    add_trade(yes.id, _t(0), price=D("0.40"), size=D("10"), metadata=meta)
    # ts1: a 0.50 print goes through a resting buy-no (<=0.58) and sell-yes (>=0.45).
    add_trade(no.id, _t(1), price=D("0.50"), size=D("10"), metadata=meta)
    add_trade(yes.id, _t(1), price=D("0.50"), size=D("10"), metadata=meta)
    # ts2: more tape after the cap is hit (should not create new fills).
    add_trade(no.id, _t(2), price=D("0.60"), size=D("10"), metadata=meta)
    add_trade(yes.id, _t(2), price=D("0.40"), size=D("10"), metadata=meta)
    return {"market": market, "yes": yes, "no": no}


def test_eligible_instruments_groups_by_series(session, kalshi_market):
    insts = eligible_instruments(session, venues=("kalshi",), categories=("TESTSERIES",))
    ours = [i for i in insts if i.market_id == kalshi_market["market"].id]
    assert len(ours) == 2
    assert {i.category for i in ours} == {"TESTSERIES"}
    assert {i.payout for i in ours} == {D("0.0000"), D("1.0000")}


def test_driver_writes_one_trial_per_variant_and_picks_a_side(session, kalshi_market):
    strat_id = session.scalar(select(Strategy.id).where(Strategy.key == "longshot"))

    summary = run_favourite_longshot(session, split=SPLIT, venues=("kalshi",), categories=("TESTSERIES",), max_fills_per_market=1)

    # Six variants (2 side rules x 3 offsets) -> six trials.
    assert summary["trials_written"] == 6
    (cat,) = summary["categories"]
    assert cat["venue"] == "kalshi" and cat["category"] == "TESTSERIES"

    # The backtest picks a profitable side for the category (the market resolves
    # cleanly: the favourite wins / the longshot loses).
    chosen = cat["chosen"]
    assert chosen is not None
    assert D(chosen["pnl_after_fees"]) > 0
    assert chosen["side_rule"] in ("buy_favourite", "sell_longshot")
    assert chosen["trade_count"] >= 1

    # One trial row per variant persisted (scoped to this run's trial ids, since
    # the shared DB also holds real longshot backtests from prior runs).
    variant_trial_ids = [v["trial_id"] for v in cat["variants"]]
    assert len(variant_trial_ids) == 6 and len(set(variant_trial_ids)) == 6
    persisted = session.scalars(
        select(Trial).where(Trial.id.in_(variant_trial_ids))
    ).all()
    assert len(persisted) == 6
    assert all(
        t.strategy_id == strat_id
        and t.mode == enums.Mode.BACKTEST
        and t.status == enums.TrialStatus.COMPLETE
        for t in persisted
    )


def test_pm_us_maker_rebate_is_applied_to_the_fills(session, kalshi_market):
    strat_id = session.scalar(select(Strategy.id).where(Strategy.key == "longshot"))
    summary = run_favourite_longshot(session, split=SPLIT, venues=("kalshi",), categories=("TESTSERIES",), max_fills_per_market=1)
    chosen_trial_id = summary["categories"][0]["chosen"]["trial_id"]

    trial = session.get(Trial, chosen_trial_id)
    # PM US maker fee is a rebate (negative), so net-of-fees beats gross and the
    # fee total is <= 0 — proof the PM US schedule, not Kalshi's, was charged.
    assert trial.fees_total <= 0
    assert trial.pnl_after_fees > trial.pnl
    assert trial.metrics["fee_basis"] == "pm-us-standard-applied-to-history"


def test_variant_internals_are_rolled_back(session, kalshi_market):
    """Only trial summaries persist; each variant's orders/fills/positions are
    rolled back so they neither persist nor contaminate the next variant."""
    strat_id = session.scalar(select(Strategy.id).where(Strategy.key == "longshot"))
    run_favourite_longshot(session, split=SPLIT, venues=("kalshi",), categories=("TESTSERIES",), max_fills_per_market=1)

    for model in (Order, Fill, Position):
        n = session.scalar(
            select(func.count()).select_from(model).where(model.strategy_id == strat_id)
        )
        assert n == 0, f"{model.__name__} rows leaked from a rolled-back variant"


def test_training_does_not_score_a_market_resolving_in_holdout(session, kalshi_market):
    split = HoldoutSplit("test-longshot-held-out-settlement", CLOSE - timedelta(days=7), CLOSE + timedelta(days=3))
    summary = run_favourite_longshot(session, split=split, venues=("kalshi",), categories=("TESTSERIES",))
    assert summary["trials_written"] == 0


def test_unknown_resolution_time_is_not_replaced_with_scheduled_close(session, kalshi_market):
    kalshi_market["market"].resolve_ts = None
    session.flush()
    assert not [i for i in eligible_instruments(session, venues=("kalshi",), categories=("TESTSERIES",))
                if i.market_id == kalshi_market["market"].id]


def test_final_admission_precedes_price_feed_loading(session, kalshi_market, monkeypatch):
    from tradingbot.backtest import engine, favourite_longshot as driver
    from tradingbot.backtest.holdout import HoldoutViolation
    reads = []
    original = driver.market_events
    def observed_feed(*args, **kwargs):
        reads.append(True)
        yield from original(*args, **kwargs)
    def refuse_admission(*args, **kwargs):
        assert not reads
        raise HoldoutViolation('synthetic admission refusal')
    monkeypatch.setattr(driver, 'market_events', observed_feed)
    monkeypatch.setattr(engine, 'claim_final', refuse_admission)
    split = HoldoutSplit('test-driver-admission', CLOSE - timedelta(days=8), CLOSE + timedelta(days=2))
    with pytest.raises(HoldoutViolation, match='synthetic admission refusal'):
        run_favourite_longshot(session, split=split, final_holdout=True, venues=('kalshi',),
                               categories=('TESTSERIES',), offsets=('.02',), side_rules=('buy_favourite',))
    assert not reads
