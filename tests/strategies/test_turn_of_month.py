from datetime import datetime
from decimal import Decimal as D
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from tradingbot.strategy.interface import MarketEvent
from tradingbot.strategy.turn_of_month import TurnOfMonth

NY=ZoneInfo('America/New_York')


def context(at, quantity='0'):
    return SimpleNamespace(now=datetime.fromisoformat(at).replace(tzinfo=NY),
                           snapshot=lambda _:SimpleNamespace(ask=D('500.02'),bid=D('500.00')),
                           position=lambda _:D(quantity))


def test_early_close_and_no_duplicate_entry_intents():
    strategy=TurnOfMonth({'instrument_id':1,'schedule':{'2026-11-27':'buy'},'session_closes':{'2026-11-27':'13:00'}})
    strategy.on_start(None)
    ctx=context('2026-11-27T12:58:59')
    event=MarketEvent.quote(1,ctx.now,mid=D('500'))
    assert strategy.on_event(ctx,event)==[]
    ctx=context('2026-11-27T12:59:00')
    order=strategy.on_event(ctx,event)[0]
    assert order.side=='buy' and order.size*order.limit_price<=D('24.90')
    assert strategy.on_event(ctx,event)==[]
    assert strategy.on_event(context('2026-11-27T13:00:00'),event)==[]


def test_exit_closes_only_owned_position_and_never_opens_short():
    strategy=TurnOfMonth({'instrument_id':1,'schedule':{'2026-12-03':'sell'},'session_closes':{'2026-12-03':'16:00'}})
    strategy.on_start(None)
    ctx=context('2026-12-03T15:59:00')
    event=MarketEvent.quote(1,ctx.now,mid=D('500'))
    assert strategy.on_event(ctx,event)==[]
    order=strategy.on_event(context('2026-12-03T15:59:00','.0498'),event)[0]
    assert order.side=='sell' and order.size==D('.0498')


def test_slot_sizing_uses_settled_cash_and_fee_reserve_and_stays_below_slot():
    params={'instrument_id':1,'schedule':{'2026-11-27':'buy'},'session_closes':{'2026-11-27':'13:00'},
            'entry_notional':'140','use_available_cash':True,'entry_fee_reserve':'.01'}
    for cash, ceiling in [('140','139.99'),('129.25','129.24'),('170','139.99')]:
        strategy=TurnOfMonth(params);strategy.on_start(None)
        ctx=context('2026-11-27T12:59:00');ctx.available_cash=lambda _:D(cash)
        order=strategy.on_event(ctx,MarketEvent.quote(1,ctx.now))[0]
        assert D(ceiling)-D('.000001') < order.size*order.limit_price <= D(ceiling)
    for cash in [None,D('0'),D('.50'),D('NaN')]:
        strategy=TurnOfMonth(params);strategy.on_start(None)
        ctx=context('2026-11-27T12:59:00');ctx.available_cash=lambda _:cash
        assert strategy.on_event(ctx,MarketEvent.quote(1,ctx.now))==[]
