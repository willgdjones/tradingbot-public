from datetime import datetime
from decimal import Decimal as D
from zoneinfo import ZoneInfo

import pytest

from tradingbot.strategy.c03_momentum import CrossAssetMomentum, SYMBOLS, allocation
from tradingbot.strategy.interface import MarketEvent

NY = ZoneInfo('America/New_York')


def histories():
    return {s: [D(100)]*13 for s in SYMBOLS}


def test_exact_lookbacks_warmup_and_alphabetical_ties():
    h = histories()
    assert allocation({s: values[:12] for s, values in h.items()}, 'top-one') == ({}, {}, [])
    weights, scores, selected = allocation(h, 'top-two')
    assert selected == ['EFA', 'GLD']
    assert weights['EFA'] == weights['GLD'] == D('.475')
    h['SPY'] = [D(80+i) for i in range(13)]
    weights, scores, selected = allocation(h, 'top-one')
    assert selected == ['SPY'] and weights['SPY'] == D('.95')
    assert scores['SPY'] == sum((D(92)/D(92-lag)-1 for lag in (1,3,6,9,12)), D(0))/5


def test_filter_keeps_failed_half_cash_and_never_promotes_third():
    h = histories()
    h['EFA'] = [D(90)]*3+[D(110)]*9+[D(100)]
    h['GLD'] = [D(80)]*3+[D(90)]*9+[D(100)]
    h['IEF'] = [D(70)]*12+[D(71)]
    weights, _, selected = allocation(h, 'top-two-sma10')
    assert selected == ['GLD', 'IEF']  # Explicit score order, no selection by SMA.
    assert weights['GLD'] == weights['IEF'] == D('.475')
    # An equality at the SMA fails even when that fund wins a score tie.
    weights, _, selected = allocation(histories(), 'top-two-sma10')
    assert selected == ['EFA', 'GLD'] and sum(weights.values()) == 0
    # A high long-term winner below its recent mean is selected but gets no replacement.
    h = {s: [D(100)]*12+[D(99)] for s in SYMBOLS}
    h['EFA'] = [D(10)]*3+[D(110)]*9+[D(100)]
    h['GLD'] = [D(100)]*12+[D(102)]
    weights, _, selected = allocation(h, 'top-two-sma10')
    assert selected == ['EFA', 'GLD']
    assert weights['EFA'] == 0 and weights['GLD'] == D('.475') and sum(weights.values()) == D('.475')


class Context:
    def __init__(self):
        self.books, self.quantities = {}, {}
        self.cash = self.equity = D(140)
    def snapshot(self, iid): return self.books.get(iid)
    def position(self, iid): return self.quantities.get(iid, D(0))
    def available_cash(self, iid): return self.cash
    def marked_equity(self): return self.equity


def setup(variant='top-two'):
    params = {'symbols': list(SYMBOLS), 'instrument_ids': dict(zip(SYMBOLS, range(1,6))),
        'variant': variant, 'lookbacks': [1,3,6,9,12], 'sma_months': 10,
        'slot_usd': '140', 'cash_reserve_weight': '.05', 'quantity_step': '.000000001',
        'buy_fee_reserve_usd': '.01', 'blackouts': [], 'month_ends': ['2026-02-27'],
        'next_session': {'2026-02-27': '2026-03-02'}}
    bot = CrossAssetMomentum(params); ctx = Context(); bot.on_start(ctx)
    return bot, ctx


def batch(bot, ctx, day, phase, prices=None, **meta):
    prices = prices or {s: '100' for s in SYMBOLS}
    stamp = datetime.fromisoformat(day+('T16:00:00' if phase == 'close' else 'T09:30:00')).replace(tzinfo=NY)
    output = []
    for i, s in enumerate(SYMBOLS):
        p = D(prices[s]); iid = bot.ids[s]
        event = MarketEvent.quote(iid, stamp, mid=p, ask=p, bid=p,
            meta={'phase': phase, 'batch_last': i == 4, 'next_open_in_partition': True, **meta})
        ctx.books[iid] = event.as_snapshot()
        output.extend(bot.on_event(ctx, event))
    return output


def test_frozen_targets_and_pro_rata_cash_are_not_recomputed():
    bot, ctx = setup()
    bot.monthly = {s: [D(100)]*12 for s in SYMBOLS}
    assert batch(bot, ctx, '2026-02-27', 'close') == []
    assert bot.targets['EFA'] == bot.targets['GLD'] == D('66.5')
    ctx.equity, ctx.cash = D(1000), D(57)
    batch(bot, ctx, '2026-03-02', 'observe_open')
    batch(bot, ctx, '2026-03-02', 'reduce')
    orders = batch(bot, ctx, '2026-03-02', 'buy')
    assert len(orders) == 2 and all(o.size*o.limit_price == D('24.99') for o in orders)
    assert bot.targets['EFA'] == D('66.5')
    assert set(bot.pending) == {'EFA','GLD'}
    for o in orders: ctx.quantities[o.instrument_id] = o.size
    ctx.cash = D(140)
    batch(bot, ctx, '2026-03-03', 'observe_open')
    later = batch(bot, ctx, '2026-03-03', 'buy')
    assert len(later) == 2 and all(o.size*o.limit_price == D('41.51') for o in later)
    assert not bot.pending


def test_retained_overweight_fund_is_trimmed_and_no_cross_partition_signal():
    bot, ctx = setup()
    bot.monthly = {s: [D(100)]*12 for s in SYMBOLS}
    ctx.quantities[bot.ids['EFA']] = D(1)
    batch(bot, ctx, '2026-02-27', 'close')
    batch(bot, ctx, '2026-03-02', 'observe_open')
    order, = batch(bot, ctx, '2026-03-02', 'reduce')
    assert order.side == 'sell' and order.size == D('.335')
    bot, ctx = setup()
    bot.monthly = {s: [D(100)]*12 for s in SYMBOLS}
    batch(bot, ctx, '2026-02-27', 'close', next_open_in_partition=False)
    assert not bot.targets


def test_full_position_cap_uses_exact_requested_price_and_terminal_liquidates():
    bot, ctx = setup('top-one')
    bot.monthly = {s: [D(100)]*12 for s in SYMBOLS}
    ctx.equity = ctx.cash = D(1000)
    batch(bot, ctx, '2026-02-27', 'close')
    assert bot.targets['EFA'] == D(140)
    ctx.quantities[bot.ids['EFA']] = D('1.3999')
    batch(bot, ctx, '2026-03-02', 'observe_open')
    ctx.books[bot.ids['EFA']] = MarketEvent.quote(bot.ids['EFA'],ctx.books[bot.ids['EFA']].time,
        mid=D(100),bid=D(100),ask=D('100.00123')).as_snapshot()
    allocation_ = bot._allocate_buys(ctx,'2026-03-02')['EFA'][0]
    assert allocation_+ctx.quantities[bot.ids['EFA']]*D('100.00123') <= 140
    orders = batch(bot, ctx, '2026-03-02', 'reduce', terminal_open=True)
    assert len(orders) == 1 and orders[0].size == D('1.3999')
    assert batch(bot, ctx, '2026-03-02', 'buy', terminal_open=True) == []


def test_incomplete_close_batch_refused_before_decision():
    bot, ctx = setup()
    iid = bot.ids['VNQ']
    event = MarketEvent.quote(iid,datetime(2026,2,27,16,tzinfo=NY),mid=D(100),
        meta={'phase':'close','batch_last':True})
    with pytest.raises(ValueError,match='incomplete'):
        bot.on_event(ctx,event)
