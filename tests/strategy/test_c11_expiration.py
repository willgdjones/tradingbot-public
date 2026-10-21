from datetime import datetime
from decimal import Decimal as D
from zoneinfo import ZoneInfo

from tradingbot.strategy.c11_expiration import ExpirationWeek
from tradingbot.strategy.interface import MarketEvent

NY = ZoneInfo('America/New_York')
WINDOW = {'decision': '2026-02-13', 'entry': '2026-02-17', 'exit': '2026-02-20', 'exit_phase': 'close'}


class Context:
    def __init__(self):
        self.quantity, self.cash, self.equity, self.book = D(0), D(140), D(140), None
    def position(self, iid): return self.quantity
    def available_cash(self, iid): return self.cash
    def marked_equity(self): return self.equity
    def snapshot(self, iid): return self.book


def setup(exit_phase='close'):
    bot = ExpirationWeek({'instrument_id': 1, 'slot_usd': '140', 'windows': [{**WINDOW, 'exit_phase': exit_phase}]})
    ctx = Context(); bot.on_start(ctx)
    return bot, ctx


def emit(bot, ctx, day, phase, price='100', **meta):
    ts = datetime.fromisoformat(day+('T09:30:00' if phase == 'open' else 'T16:00:00')).replace(tzinfo=NY)
    event = MarketEvent.quote(1, ts, bid=D(price), ask=D(price), mid=D(price),
        meta={'phase': phase, 'window_complete_in_partition': True, **meta})
    ctx.book = event.as_snapshot()
    return bot.on_event(ctx, event)


def test_no_entry_without_prior_completed_close_and_frozen_target():
    bot, ctx = setup()
    assert emit(bot, ctx, WINDOW['entry'], 'open') == []
    assert emit(bot, ctx, WINDOW['decision'], 'close') == []
    ctx.equity = ctx.cash = D(1000)
    order, = emit(bot, ctx, WINDOW['entry'], 'open', '101')
    assert D('132.999') < order.size*order.limit_price <= 133
    assert emit(bot, ctx, WINDOW['entry'], 'open') == []
    ctx.quantity = order.size
    assert emit(bot, ctx, WINDOW['exit'], 'open') == []
    sell, = emit(bot, ctx, WINDOW['exit'], 'close')
    assert sell.size == order.size and sell.side == 'sell'
    assert emit(bot, ctx, WINDOW['exit'], 'close') == []


def test_partition_complete_gate_and_terminal_prohibit_entry():
    bot, ctx = setup()
    emit(bot, ctx, WINDOW['decision'], 'close', window_complete_in_partition=False)
    assert not bot.decisions
    assert emit(bot, ctx, WINDOW['entry'], 'open') == []
    bot, ctx = setup()
    emit(bot, ctx, WINDOW['decision'], 'close')
    assert emit(bot, ctx, WINDOW['entry'], 'open', terminal_open=True) == []
    ctx.quantity = D('.3')
    sell, = emit(bot, ctx, WINDOW['entry'], 'open', terminal_open=True)
    assert sell.size == D('.3') and sell.reason == 'C11 terminal liquidation'


def test_cash_reserve_and_slot_cap_are_independent():
    bot, ctx = setup('open')
    emit(bot, ctx, WINDOW['decision'], 'close')
    ctx.cash = D(100)
    order, = emit(bot, ctx, WINDOW['entry'], 'open')
    assert order.size*order.limit_price == D('92.99')
    ctx.quantity = order.size
    sell, = emit(bot, ctx, WINDOW['exit'], 'open')
    assert sell.side == 'sell'
    bot, ctx = setup()
    ctx.equity = ctx.cash = D(1000)
    emit(bot, ctx, WINDOW['decision'], 'close')
    order, = emit(bot, ctx, WINDOW['entry'], 'open')
    assert order.size*order.limit_price == 140


def test_cash_exhaustion_records_skip_without_short_or_roll():
    bot, ctx = setup()
    emit(bot, ctx, WINDOW['decision'], 'close')
    ctx.cash = D('7.50')
    assert emit(bot, ctx, WINDOW['entry'], 'open') == []
    assert bot.skips
    ctx.cash = D(140)
    assert emit(bot, ctx, '2026-02-18', 'open') == []
