from datetime import datetime
from decimal import Decimal as D
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from tradingbot.strategy.c06_month_end import MonthEndUnderweight
from tradingbot.strategy.interface import MarketEvent

NY = ZoneInfo('America/New_York')
WINDOW = {'month': '2026-02', 'base': '2026-01-30', 'decision': '2026-02-26',
          'entry': '2026-02-27', 'exit': '2026-03-02'}


class Context:
    def __init__(self):
        self.quantity = D(0)
        self.cash = self.equity = D(140)
        self.books = {}

    def position(self, iid): return self.quantity if iid == 1 else D(0)
    def snapshot(self, iid): return self.books.get(iid)
    def available_cash(self, iid): return self.cash
    def marked_equity(self): return self.equity


def setup(threshold='.600'):
    bot = MonthEndUnderweight({'spy_id': 1, 'ief_id': 2, 'threshold': threshold,
        'windows': [WINDOW], 'target_weight': '.95', 'slot_usd': '140',
        'buy_fee_reserve_usd': '.01', 'quantity_step': '.000000001'})
    ctx = Context()
    bot.on_start(ctx)
    return bot, ctx


def emit(bot, ctx, day, phase, price, iid=1, dividend='0', complete=True, terminal=False):
    ts = datetime.fromisoformat(day + ('T09:30:00' if phase == 'open' else 'T16:00:00')).replace(tzinfo=NY)
    p = D(price)
    event = MarketEvent.quote(iid, ts, bid=p if phase == 'open' else None,
        ask=p if phase == 'open' else None, mid=p,
        meta={'phase': phase, 'ex_date_distribution': dividend,
              'window_complete_in_partition': complete, 'terminal_open': terminal})
    ctx.now = ts
    ctx.books[iid] = event.as_snapshot()
    return bot.on_event(ctx, event)


def decision(bot, ctx, spy='99', ief='100', dividend='0', complete=True):
    for iid in [1, 2]:
        emit(bot, ctx, WINDOW['base'], 'close', '100', iid)
    emit(bot, ctx, WINDOW['decision'], 'close', ief, 2, complete=complete)
    return emit(bot, ctx, WINDOW['decision'], 'close', spy, dividend=dividend, complete=complete)


def test_decides_on_completed_closes_and_freezes_budget_before_entry():
    bot, ctx = setup()
    assert decision(bot, ctx) == []
    assert bot.decisions[0]['qualified']
    ctx.equity = ctx.cash = D(1000)  # later wealth cannot change the frozen $133 target
    order, = emit(bot, ctx, WINDOW['entry'], 'open', '102')
    assert order.side == 'buy' and D('132.99') < order.size * order.limit_price <= D(133)
    assert emit(bot, ctx, WINDOW['entry'], 'open', '102') == []
    ctx.quantity = order.size
    sell, = emit(bot, ctx, WINDOW['exit'], 'open', '103')
    assert sell.side == 'sell' and sell.size == order.size
    assert emit(bot, ctx, WINDOW['exit'], 'open', '103') == []


def test_strict_threshold_and_ex_date_distribution_prevent_false_signal():
    bot, ctx = setup()
    decision(bot, ctx, spy='100')
    assert not bot.decisions[0]['qualified']
    assert emit(bot, ctx, WINDOW['entry'], 'open', '1') == []
    bot, ctx = setup()
    decision(bot, ctx, spy='99', dividend='1')
    assert bot.decisions[0]['equity_weight'] == '0.6'
    assert emit(bot, ctx, WINDOW['entry'], 'open', '99') == []


def test_missing_warmup_or_exit_outside_partition_never_signals():
    bot, ctx = setup()
    emit(bot, ctx, WINDOW['decision'], 'close', '100', 2)
    emit(bot, ctx, WINDOW['decision'], 'close', '1')
    assert not bot.decisions and not bot._targets
    bot, ctx = setup()
    decision(bot, ctx, complete=False)
    assert not bot.decisions and not bot._targets


def test_settled_cash_and_reserve_shrink_order_with_no_recomputed_target():
    bot, ctx = setup()
    decision(bot, ctx)
    ctx.cash = D(100)
    order, = emit(bot, ctx, WINDOW['entry'], 'open', '100')
    assert order.size * order.limit_price == D('92.99')
    bot, ctx = setup()
    ctx.equity = ctx.cash = D(1000)
    decision(bot, ctx)
    order, = emit(bot, ctx, WINDOW['entry'], 'open', '100')
    assert order.size * order.limit_price == D(140)


def test_subdollar_and_terminal_entries_skipped_but_terminal_exit_requested():
    bot, ctx = setup()
    decision(bot, ctx)
    ctx.cash = D('7.50')
    assert emit(bot, ctx, WINDOW['entry'], 'open', '100') == []
    assert bot.skips[-1]['reason'].startswith('under $1')
    bot, ctx = setup()
    decision(bot, ctx)
    assert emit(bot, ctx, WINDOW['entry'], 'open', '100', terminal=True) == []
    ctx.quantity = D('.7')
    order, = emit(bot, ctx, '2026-02-28', 'open', '100', terminal=True)
    assert order.side == 'sell' and order.size == D('.7')


def test_compound_distribution_factors_use_each_completed_day_once():
    bot, ctx = setup('.590')
    for iid in [1, 2]:
        emit(bot, ctx, WINDOW['base'], 'close', '100', iid)
    emit(bot, ctx, '2026-02-02', 'close', '98', dividend='1')
    emit(bot, ctx, '2026-02-02', 'close', '101', 2, dividend='.1')
    emit(bot, ctx, WINDOW['decision'], 'close', '102', 2)
    emit(bot, ctx, WINDOW['decision'], 'close', '99')
    expected_spy = D('99') / 100 * D('99') / 98
    assert abs(D(bot.decisions[0]['spy_total_factor']) - expected_spy) < D('1e-25')
