from datetime import datetime
from decimal import Decimal as D

import pytest

from tradingbot.research.turn_of_month import scenario_quote
from tradingbot.strategy.c02_sector_momentum import (
    SectorMomentum, momentum_score, rank_momentum, total_return_factor)

SYMBOLS = ('XLB', 'XLE', 'XLF', 'XLI', 'XLK', 'XLP', 'XLU', 'XLV', 'XLY')
IDS = dict(zip(SYMBOLS, range(1, 10)))


class Context:
    def __init__(self, day='2021-02-01', price=D(10)):
        self.quantities = {i: D(0) for i in range(1, 10)}
        self.cash, self.equity = D(140), D(140)
        self.refs = {}
        self.set_day(day, price)

    def set_day(self, day, price=D(10)):
        ts = datetime.fromisoformat(day + 'T09:30:00-05:00')
        self.refs = {i: scenario_quote(i, ts, price, 10).as_snapshot() for i in range(1, 10)}

    def position(self, iid): return self.quantities[iid]
    def snapshot(self, iid): return self.refs.get(iid)
    def available_cash(self, _): return self.cash
    def marked_equity(self): return self.equity


def make_bot(variant='ret6'):
    params = {'symbols': list(SYMBOLS), 'instrument_ids': dict(IDS), 'spy_reference_id': 99,
        'variant': variant, 'top_n': 3, 'target_weight': '.95', 'cash_reserve_weight': '.05',
        'slot_usd': '140', 'buy_fee_reserve_usd': '.01', 'quantity_step': '.000000001',
        'blackouts': [], 'cycles': {}}
    bot = SectorMomentum(params)
    bot.on_start(Context())
    return bot


# -- pure signal ---------------------------------------------------------------
def test_total_return_factor_matches_economic_identity():
    assert total_return_factor(D(10), D(5), split=D(2)) == 1
    assert total_return_factor(D(10), D('9.9'), distribution=D('.1')) == 1
    assert total_return_factor(D(30), D('25.5'), in_kind=D('4.5')) == 1
    with pytest.raises(ValueError):
        total_return_factor(D(0), D(1))


def test_momentum_score_warmup_and_lookbacks():
    assert momentum_score([D(1)] * 7, 'ret12') is None     # needs 13
    assert momentum_score([D(1)] * 13, 'ret12') == 0
    assert momentum_score([D(1)] * 6, 'ret6') is None       # needs 7
    idx = [D(1)] * 12 + [D('1.5')]
    assert momentum_score(idx, 'ret6') == D('1.5') / idx[-7] - 1
    # mean of 1/3/6/9/12-month returns, needs 13 samples
    assert momentum_score([D(1)] * 12, 'mean5') is None
    ramp = [D(1) + D(i) / 100 for i in range(13)]
    expected = sum((ramp[-1] / ramp[-1 - l] - 1 for l in (1, 3, 6, 9, 12)), D(0)) / 5
    assert momentum_score(ramp, 'mean5') == expected


def test_rank_momentum_pure_top3_and_alphabetical_ties():
    month_end = {s: [D(1)] * 7 for s in SYMBOLS}
    assert rank_momentum({s: h[:6] for s, h in month_end.items()}, SYMBOLS, 'ret6', 3) == ([], {})
    month_end['XLK'][-1] = D('1.3')
    month_end['XLE'][-1] = D('1.2')
    # three-way tie at 1.1 among XLF, XLV, XLY -> alphabetical fills remaining slot
    for s in ('XLF', 'XLV', 'XLY'):
        month_end[s][-1] = D('1.1')
    selected, scores = rank_momentum(month_end, SYMBOLS, 'ret6', 3)
    assert selected == ['XLK', 'XLE', 'XLF']
    assert scores['XLK'] == D('.3') and scores['XLB'] == 0
    with pytest.raises(ValueError):
        rank_momentum(month_end, SYMBOLS, 'ret6', 2)


# -- decision freeze -----------------------------------------------------------
def frozen_bot(variant='ret6', equity=D(140)):
    bot, ctx = make_bot(variant), Context()
    ctx.equity = equity
    bot.month_end = {s: [D(1)] * 7 for s in SYMBOLS}
    bot.month_end['XLK'][-1] = D('1.3')
    bot.month_end['XLE'][-1] = D('1.2')
    bot.month_end['XLF'][-1] = D('1.1')
    bot._freeze_month(ctx, '2021-01-29', {'entry': '2021-02-01', 'exit': '2021-03-01'}, True)
    return bot, ctx


def test_freeze_sets_equal_targets_and_reserve():
    bot, _ = frozen_bot()
    target = D(133) / 3
    assert bot.decided['targets'] == dict.fromkeys(['XLK', 'XLE', 'XLF'], target)
    assert bot.decided['reserve'] == 7 and bot.decided['entry'] == '2021-02-01'
    assert bot.active_targets == {}  # not active until the rebalance open


def test_warmup_and_outside_partition_freeze_nothing():
    bot, ctx = make_bot(), Context()
    bot.month_end = {s: [D(1)] * 3 for s in SYMBOLS}
    bot._freeze_month(ctx, '2021-01-29', {'entry': '2021-02-01', 'exit': '2021-03-01'}, True)
    assert bot.decided is None and bot.skips[-1]['reason'] == 'in-partition warm-up'
    bot.month_end = {s: [D(1)] * 7 for s in SYMBOLS}
    bot._freeze_month(ctx, '2021-01-29', {'entry': '2021-02-01', 'exit': None}, False)
    assert bot.decided is None and bot.skips[-1]['reason'] == 'rebalance entry outside partition'


# -- rebalance: hold stayers, sell leavers, buy entrants -----------------------
def test_rebalance_keeps_stayers_sells_leavers_and_buys_entrants():
    bot, ctx = frozen_bot()
    # Already hold XLK (stays in top-3) and XLI (drops out of top-3).
    ctx.quantities[IDS['XLK']] = D('4')    # ~ $40 held, under the ~$44.3 target
    ctx.quantities[IDS['XLI']] = D('3')
    ctx.set_day('2021-02-01')
    # Reduce phase: XLI leaves -> sold; XLK stays -> not sold.
    [sell] = bot.on_event(ctx, scenario_quote(IDS['XLI'], ctx.refs[IDS['XLI']].time, D(10), 10, phase='reduce'))
    assert sell.side == 'sell' and sell.size == 3 and sell.reason == 'C02 monthly rebalance exit'
    assert bot.on_event(ctx, scenario_quote(IDS['XLK'], ctx.refs[IDS['XLK']].time, D(10), 10, phase='reduce')) == []
    # Buy phase: entrants XLE, XLF bought to target; XLK topped up toward target.
    buys = {}
    for s in ('XLE', 'XLF', 'XLK'):
        orders = bot.on_event(ctx, scenario_quote(IDS[s], ctx.refs[IDS[s]].time, D(10), 10, phase='buy'))
        if orders:
            buys[s] = orders[0]
    assert set(buys) == {'XLE', 'XLF', 'XLK'}
    assert buys['XLK'].side == 'buy'  # topped up, held across rebalance
    # XLK top-up is only the positive gap (~$4.3), far less than a fresh ~$44 slot.
    assert buys['XLK'].size * buys['XLK'].limit_price < buys['XLE'].size * buys['XLE'].limit_price


def test_overweight_stayer_is_not_trimmed():
    bot, ctx = frozen_bot()
    ctx.quantities[IDS['XLK']] = D('6')    # ~$60 > ~$44 target: no sell-down
    ctx.set_day('2021-02-01')
    assert bot.on_event(ctx, scenario_quote(IDS['XLK'], ctx.refs[IDS['XLK']].time, D(10), 10, phase='reduce')) == []
    bot._maybe_activate('2021-02-01')
    assert 'XLK' not in bot._allocate_buys(ctx, '2021-02-01')  # zero positive gap


# -- pro-rata rationing and sub-$1 skip ----------------------------------------
def test_pro_rata_rations_to_settled_cash_without_redistribution():
    bot, ctx = frozen_bot()
    bot._maybe_activate('2021-02-01')
    ctx.cash = D(200)
    full = bot._allocate_buys(ctx, '2021-02-01')
    assert all(v[0] == D(133) / 3 for v in full.values())  # reserve 7 + 3 slots fit in 200
    bot.buy_day = None
    ctx.cash = D('10')     # tight: reserve 7 + fee reserve .03 leaves ~2.97 across 3 gaps
    rationed = bot._allocate_buys(ctx, '2021-02-01')
    assert all(v[0] < D(133) / 3 and v[0] > 0 for v in rationed.values())
    assert all(not v[1] for v in rationed.values())  # fraction < 1 -> incomplete


# -- blackout ------------------------------------------------------------------
def test_blackout_excludes_selection_target_and_forces_exit_then_reentry():
    bot, ctx = make_bot(), Context()
    bot.params['blackouts'] = [{'symbol': 'XLF', 'decision': '2021-01-29',
        'exit': '2021-02-03', 'reentry': '2021-02-08'}]
    ctx.equity = D(140)
    bot.month_end = {s: [D(1)] * 7 for s in SYMBOLS}
    bot.month_end['XLK'][-1] = D('1.3')
    bot.month_end['XLE'][-1] = D('1.2')
    bot.month_end['XLF'][-1] = D('1.1')
    bot._freeze_month(ctx, '2021-01-29', {'entry': '2021-02-01', 'exit': '2021-03-01'}, True)
    bot.causal_exits.add(('XLF', '2021-02-03'))
    bot._maybe_activate('2021-02-01')
    # XLF is blacked out on 02-03..02-07: excluded from pro-rata allocation there.
    ctx.set_day('2021-02-03')
    assert 'XLF' not in bot._allocate_buys(ctx, '2021-02-03')
    # A held XLF is force-sold at the blackout exit open.
    ctx.quantities[IDS['XLF']] = D('4')
    [sell] = bot.on_event(ctx, scenario_quote(IDS['XLF'], ctx.refs[IDS['XLF']].time, D(10), 10, phase='reduce'))
    assert sell.reason == 'C02 forced blackout exit' and 'XLF' in bot.forced_symbols
    assert 'XLF' in bot.pending  # re-queued for reentry
    # After reentry it buys back, tagged as a blackout reentry.
    ctx.quantities[IDS['XLF']] = D(0)
    ctx.set_day('2021-02-08')
    [buy] = bot.on_event(ctx, scenario_quote(IDS['XLF'], ctx.refs[IDS['XLF']].time, D(10), 10, phase='buy'))
    assert buy.reason == 'C02 blackout reentry'


def test_blackout_without_prior_close_decision_fails_closed():
    bot, ctx = make_bot(), Context()
    bot.params['blackouts'] = [{'symbol': 'XLF', 'decision': '2021-01-29',
        'exit': '2021-02-03', 'reentry': '2021-02-08'}]
    ctx.quantities[IDS['XLF']] = D('4')
    ctx.set_day('2021-02-03')
    with pytest.raises(ValueError, match='missing prior-close action-exit decision'):
        bot.on_event(ctx, scenario_quote(IDS['XLF'], ctx.refs[IDS['XLF']].time, D(10), 10, phase='reduce'))
