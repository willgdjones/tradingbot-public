from datetime import datetime
from decimal import Decimal as D
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from tradingbot.strategy.eod_letf import EodLetf
from tradingbot.strategy.interface import MarketEvent

NY=ZoneInfo('America/New_York')


def setup():
    strategy=EodLetf({'instrument_ids':[1], 'session_closes':{'2026-09-28':'16:00','2026-09-29':'16:00'},
                      'previous_session':{'2026-09-29':'2026-09-28'}, 'threshold':'.01'})
    strategy.on_start(None)
    return strategy


def event(strategy, at, price, qty='0', **meta):
    ts=datetime.fromisoformat(at).replace(tzinfo=NY)
    observation=MarketEvent.quote(1,ts,bid=D(price),ask=D(price),mid=D(price),meta=meta)
    ctx=SimpleNamespace(now=ts,snapshot=lambda _:observation.as_snapshot(),position=lambda _:D(qty))
    return strategy.on_event(ctx,observation)


def test_signal_uses_only_observed_previous_close_and_current_open_reference():
    strategy=setup()
    assert event(strategy,'2026-09-28T16:00:00','500')==[]
    # A later close or the current bar high/close is not a decision input.
    orders=event(strategy,'2026-09-29T15:30:00','505',future_close='400',bar_high='900')
    assert len(orders)==1 and orders[0].side=='buy'
    assert orders[0].size*orders[0].limit_price<=D('24.90')
    assert event(strategy,'2026-09-29T15:30:01','505')==[]
    assert event(strategy,'2026-09-29T15:58:00','506','.049')==[]
    assert event(strategy,'2026-09-29T15:59:00','506','.049')[0].size==D('.049')


def test_negative_moves_are_counted_without_shorting_and_missing_prior_is_not_filled():
    strategy=setup()
    assert event(strategy,'2026-09-29T15:30:00','500')==[]
    assert strategy.decisions==[]
    strategy=setup()
    event(strategy,'2026-09-28T16:00:00','500')
    assert event(strategy,'2026-09-29T15:30:00','494')==[]
    assert strategy.decisions[0]['signal']=='short_unavailable'
    assert event(strategy,'2026-09-29T15:59:00','490')==[]


def test_early_close_session_is_skipped():
    strategy=setup()
    strategy.params['session_closes']['2026-09-29']='13:00'
    event(strategy,'2026-09-28T16:00:00','500')
    assert event(strategy,'2026-09-29T15:30:00','510')==[]
