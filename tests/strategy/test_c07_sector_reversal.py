from datetime import datetime
from decimal import Decimal as D

import pytest

from tradingbot.research.turn_of_month import scenario_quote
from tradingbot.strategy.c07_sector_reversal import SectorReversal, rank_losers, total_return_factor

SYMBOLS = ('XLB', 'XLE', 'XLF', 'XLI', 'XLK', 'XLP', 'XLU', 'XLV', 'XLY')


class Context:
    def __init__(self, day='2020-01-13'):
        self.quantities = {i: D(0) for i in range(1, 10)}
        self.cash, self.equity = D(140), D(140)
        self.refs = {i: scenario_quote(i, datetime.fromisoformat(day+'T09:30:00-05:00'), D(10), 10).as_snapshot()
                     for i in range(1, 10)}
    def position(self, iid): return self.quantities[iid]
    def snapshot(self, iid): return self.refs[iid]
    def available_cash(self, _): return self.cash
    def marked_equity(self): return self.equity


def simple_bot():
    params = {'symbols': list(SYMBOLS), 'instrument_ids': dict(zip(SYMBOLS, range(1, 10))),
        'spy_reference_id': 10, 'lookback_sessions': 5, 'top_n': 3,
        'target_weight': '.95', 'cash_reserve_weight': '.05', 'slot_usd': '140',
        'buy_fee_reserve_usd': '.01', 'quantity_step': '.000000001', 'blackouts': [], 'cycles': {}}
    bot, ctx = SectorReversal(params), Context()
    bot.on_start(ctx)
    bot.history = {s: [D(1)]*6 for s in (*SYMBOLS, 'SPY')}
    bot.history['XLB'][-1] = bot.history['XLE'][-1] = D('.9')
    bot.history['XLF'][-1] = D('.95')
    return bot, ctx


def test_total_return_uses_true_split_and_economic_in_kind_without_cash():
    assert total_return_factor(D(10), D(5), split=D(2)) == 1
    assert total_return_factor(D(10), D('9.9'), distribution=D('.1')) == 1
    assert total_return_factor(D(30), D('25.5'), in_kind=D('4.5')) == 1
    with pytest.raises(ValueError):
        total_return_factor(D(0), D(1))


def test_rank_needs_lag_plus_one_closes_and_negative_residuals_only():
    bot, _ = simple_bot()
    assert rank_losers({s: h[:5] for s, h in bot.history.items()}, SYMBOLS, 5, 3) == ([], {})
    chosen, _ = rank_losers(bot.history, SYMBOLS, 5, 3)
    assert chosen == ['XLB', 'XLE', 'XLF']
    assert rank_losers(bot.history, SYMBOLS, 5, 1)[0] == ['XLB']
    bot.history['XLF'][-1] = D(1)
    assert rank_losers(bot.history, SYMBOLS, 5, 3)[0] == ['XLB', 'XLE']
    bot.history['SPY'][-1] = D('.5')
    assert rank_losers(bot.history, SYMBOLS, 5, 3)[0] == []


def test_targets_and_reserve_remain_frozen_during_settlement_delay():
    bot, ctx = simple_bot()
    cycle = {'entry': '2020-01-13', 'exit': '2020-01-21'}
    bot._freeze_week(ctx, '2020-01-10', cycle, True)
    target = D(133)/3
    assert bot.targets == dict.fromkeys(['XLB', 'XLE', 'XLF'], target)
    ctx.equity, ctx.cash = D(200), D(10)
    budgets = bot._allocate_buys(ctx, '2020-01-13')
    assert all(abs(v[0]-D('.99')) < D('1e-24') for v in budgets.values())
    ctx.cash = D(200)
    assert all(v[0] == target for v in bot._allocate_buys(ctx, '2020-01-13').values())
    assert bot.reserve == 7 and bot.plan['exit'] == '2020-01-21'


def test_repeated_name_still_exits_and_delayed_entry_keeps_new_original_exit():
    bot, ctx = simple_bot()
    bot._freeze_week(ctx, '2020-01-10', {'entry': '2020-01-13', 'exit': '2020-01-21'}, True)
    ctx.quantities[1], bot.expiries['XLB'] = D(4), '2020-01-13'
    event = scenario_quote(1, ctx.refs[1].time, D(10), 10, phase='reduce')
    [sell] = bot.on_event(ctx, event)
    assert sell.side == 'sell' and sell.size == 4 and sell.reason == 'C07 scheduled weekly exit'
    ctx.quantities[1], ctx.cash = D(0), D(7)
    assert bot.on_event(ctx, scenario_quote(1, event.time, D(10), 10, phase='buy')) == []
    ctx.cash = D(140)
    for i in ctx.refs:
        ctx.refs[i] = scenario_quote(i, datetime.fromisoformat('2020-01-15T09:30:00-05:00'), D(10), 10).as_snapshot()
    [buy] = bot.on_event(ctx, scenario_quote(1, ctx.refs[1].time, D(10), 10, phase='buy'))
    assert bot.order_context[buy.tag]['original_scheduled_exit'] == '2020-01-21'
    assert bot.order_context[buy.tag]['initial_entry_session'] == '2020-01-13'


def test_blackout_slot_stays_cash_without_promoting_other_names_and_expires():
    bot, ctx = simple_bot()
    bot.params['blackouts'] = [{'symbol': 'XLB', 'exit': '2020-01-10', 'reentry': '2020-01-22'}]
    bot._freeze_week(ctx, '2020-01-10', {'entry': '2020-01-13', 'exit': '2020-01-21'}, True)
    budgets = bot._allocate_buys(ctx, '2020-01-13')
    assert set(budgets) == {'XLE', 'XLF'}
    assert all(v[0] == D(133)/3 for v in budgets.values())
    assert bot._allocate_buys(ctx, '2020-01-21') == {}
    assert bot._allocate_buys(ctx, '2020-01-22') == {}


def test_small_rationed_budget_not_redistributed_and_stale_other_open_rejected():
    bot, ctx = simple_bot()
    bot.plan = {'entry': '2020-01-13', 'exit': '2020-01-21'}
    bot.targets, bot.pending = {'XLB': D('.5'), 'XLE': D(10)}, {'XLB', 'XLE'}
    ctx.cash = D('5.27')
    budgets = bot._allocate_buys(ctx, '2020-01-13')
    assert budgets['XLB'][0] == D('.25') and budgets['XLE'][0] == D(5)
    ctx.refs[2] = scenario_quote(2, datetime.fromisoformat('2020-01-10T16:00:00-05:00'), D(10), 10).as_snapshot()
    with pytest.raises(ValueError, match='fresh opens'):
        bot._allocate_buys(ctx, '2020-01-13')


def test_cycle_outside_partition_never_creates_a_target():
    bot, ctx = simple_bot()
    bot._freeze_week(ctx, '2020-01-10', {'entry': '2020-01-13', 'exit': None}, False)
    assert not bot.targets and bot.plan is None
    assert bot.skips[-1]['reason'] == 'cycle exit outside partition'


def test_profitable_top_one_sizes_to_the_actual_submitted_limit_cap():
    bot, ctx = simple_bot()
    bot.params['top_n'] = 1
    ctx.equity = ctx.cash = D(200)
    bot._freeze_week(ctx, '2020-01-10', {'entry': '2020-01-13', 'exit': '2020-01-21'}, True)
    assert bot.targets['XLB'] == 140
    event = scenario_quote(1, ctx.refs[1].time, D('9.991'), 10, phase='buy')
    ctx.refs[1] = event.as_snapshot()
    [order] = bot.on_event(ctx, event)
    assert order.limit_price == D('10.01')
    assert order.size * order.limit_price <= 140
    assert (order.size + D('.000000001')) * order.limit_price > 140
