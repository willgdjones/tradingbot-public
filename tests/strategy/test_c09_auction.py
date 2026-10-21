from datetime import datetime
from decimal import Decimal as D
from zoneinfo import ZoneInfo

from tradingbot.strategy.c09_auction import AuctionRecovery
from tradingbot.strategy.interface import MarketEvent

NY = ZoneInfo('America/New_York')
WINDOW = {'id':'auction-a','decision':'2026-02-13','entry':'2026-02-17','exit':'2026-02-24'}


class Context:
    def __init__(self):
        self.quantity, self.cash, self.equity, self.book = D(0), D(140), D(140), None
    def position(self, iid): return self.quantity
    def available_cash(self, iid): return self.cash
    def marked_equity(self): return self.equity
    def snapshot(self, iid): return self.book


def setup(windows=None):
    bot=AuctionRecovery({'instrument_id':1,'slot_usd':'140','windows':windows or [WINDOW]})
    ctx=Context();bot.on_start(ctx)
    return bot,ctx


def emit(bot,ctx,day,phase,price='100',**meta):
    stamp=datetime.fromisoformat(day+('T09:30:00' if phase=='open' else 'T16:00:00')).replace(tzinfo=NY)
    event=MarketEvent.quote(1,stamp,mid=D(price),bid=D(price),ask=D(price),
        meta={'phase':phase,'admitted_windows':[w['id'] for w in bot.params['windows']],**meta})
    ctx.book=event.as_snapshot()
    return bot.on_event(ctx,event)


def test_causal_close_freezes_target_and_original_exit():
    bot,ctx=setup()
    assert emit(bot,ctx,WINDOW['entry'],'open')==[]
    emit(bot,ctx,WINDOW['decision'],'close')
    ctx.equity=ctx.cash=D(1000)
    buy,=emit(bot,ctx,WINDOW['entry'],'open','101')
    assert D('132.999')<buy.size*buy.limit_price<=133
    assert emit(bot,ctx,WINDOW['entry'],'open')==[]
    ctx.quantity=buy.size
    assert emit(bot,ctx,'2026-02-23','open')==[]
    sell,=emit(bot,ctx,WINDOW['exit'],'open')
    assert sell.size==buy.size and sell.side=='sell'


def test_cash_delay_has_no_lookahead_and_never_extends_exit():
    bot,ctx=setup();emit(bot,ctx,WINDOW['decision'],'close')
    ctx.cash=D('7.50')
    assert emit(bot,ctx,WINDOW['entry'],'open')==[]
    assert 'cash delay' in bot.skips[-1]['reason']
    ctx.cash=D(100)
    buy,=emit(bot,ctx,'2026-02-18','open')
    assert buy.size*buy.limit_price==D('92.99')
    assert bot.skips[-1]['fixed_exit']==WINDOW['exit']
    ctx.quantity=buy.size
    sell,=emit(bot,ctx,WINDOW['exit'],'open')
    assert sell.side=='sell'


def test_cash_unavailable_until_exit_cancels_without_entry():
    bot,ctx=setup();emit(bot,ctx,WINDOW['decision'],'close')
    ctx.cash=D(0)
    assert emit(bot,ctx,WINDOW['entry'],'open')==[]
    ctx.cash=D(140)
    assert emit(bot,ctx,WINDOW['exit'],'open')==[]
    assert bot.pending is None
    assert emit(bot,ctx,'2026-02-25','open')==[]


def test_overlap_during_pending_and_hold_keeps_first_exit():
    second={**WINDOW,'id':'auction-b'}
    third={**WINDOW,'id':'auction-c','decision':'2026-02-18','entry':'2026-02-19','exit':'2026-03-03'}
    bot,ctx=setup([WINDOW,second,third]);emit(bot,ctx,WINDOW['decision'],'close')
    assert len(bot.decisions)==1 and bot.skips[-1]['id']=='auction-b'
    buy,=emit(bot,ctx,WINDOW['entry'],'open');ctx.quantity=buy.size
    emit(bot,ctx,third['decision'],'close')
    assert bot.active_exit==WINDOW['exit'] and bot.active_id==WINDOW['id']
    assert len(bot.skips)==2 and all('overlap' in s['reason'] for s in bot.skips)


def test_partition_and_terminal_are_liquidation_only():
    bot,ctx=setup();emit(bot,ctx,WINDOW['decision'],'close',admitted_windows=[])
    assert not bot.decisions and emit(bot,ctx,WINDOW['entry'],'open')==[]
    bot,ctx=setup();emit(bot,ctx,WINDOW['decision'],'close')
    assert emit(bot,ctx,WINDOW['entry'],'open',terminal_open=True)==[]
    ctx.quantity=D('.3')
    sell,=emit(bot,ctx,WINDOW['entry'],'open',terminal_open=True)
    assert sell.reason=='C09 terminal liquidation' and sell.size==D('.3')


def test_full_position_uses_slot_cap_and_preserves_adjusted_price_precision():
    bot,ctx=setup();ctx.cash=ctx.equity=D(1000)
    emit(bot,ctx,WINDOW['decision'],'close')
    buy,=emit(bot,ctx,WINDOW['entry'],'open','63.12345678')
    assert buy.limit_price==D('63.12345678') and D('139.9999')<buy.size*buy.limit_price<=140
