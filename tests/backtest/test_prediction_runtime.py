from datetime import UTC, datetime, timedelta
from decimal import Decimal
import uuid

import pytest
from sqlalchemy import select

from tradingbot.backtest.engine import Settlement
from tradingbot.backtest.holdout import HoldoutSplit
from tradingbot.backtest.prediction_runtime import PredictionBacktester
from tradingbot.db.models import Fill, Instrument, Market, Order, RiskHalt, Strategy as StrategyRow, Venue
from tradingbot.strategy.interface import MarketEvent, PlaceOrder, Strategy

D = Decimal
T0 = datetime(2025, 2, 1, 12, tzinfo=UTC)
SPLIT = HoldoutSplit('test-prediction-runtime', T0, T0 + timedelta(days=10))


class Script(Strategy):
    key = 'synthetic_prediction_script'
    def on_event(self, ctx, event):
        return event.meta.get('intents', ())


def setup(session, cash='140', count=4, contracts=None):
    key = 'test-prediction-' + uuid.uuid4().hex
    venue = session.scalar(select(Venue).where(Venue.key == 'polymarket_us'))
    strategy = StrategyRow(key=key, name='Synthetic prediction book', status='backtest', allocation_usd=D(cash))
    session.add(strategy); session.flush()
    manifest = []
    for n in range(count):
        market = Market(venue_id=venue.id, external_id=key + str(n), market_type='binary')
        session.add(market); session.flush()
        inst = Instrument(venue_id=venue.id, market_id=market.id, external_id=key + str(n),
                          instrument_type='binary_yes', contract_multiplier=D(1))
        session.add(inst); session.flush()
        manifest.append({'instrument_id': inst.id, 'contract': (contracts or list(range(count)))[n],
                         'venue': 'polymarket_us', 'instrument_type': 'binary_yes', 'multiplier': '1',
                         'close_ts': (T0 + timedelta(days=6)).isoformat()})
    return strategy.id, manifest


def event(iid, seconds, price='.6', size='10', intents=(), timer=False):
    return MarketEvent.trade(iid, T0 + timedelta(seconds=seconds), price=D(price), size=D(size),
                            maker_fill_eligible=not timer, meta={'intents': intents, 'timer': timer})


def order(iid, *, side='buy', price='.5', size='10', tag='entry'):
    return PlaceOrder(iid, side, D(size), limit_price=D(price), tag=tag, intended_liquidity='maker')


def runtime(session, cash='140', count=4, contracts=None, params=None):
    sid, manifest = setup(session, cash, count, contracts)
    rt = PredictionBacktester(session, strategy=Script(params or {}), strategy_id=sid,
                              instruments=manifest, initial_cash=D(cash))
    return rt, [r['instrument_id'] for r in manifest]


@pytest.mark.parametrize('side,limit,first,through,payout,profit', [
    ('buy', '.5', '.6', '.4', '1', '5.03'),
    ('sell', '.4', '.3', '.5', '0', '4.03'),
])
def test_funded_long_and_short_reconcile_cash_ledger_and_terminal_book(
        session, side, limit, first, through, payout, profit):
    rt, (iid,) = runtime(session, count=1)
    result = rt.run([event(iid, 0, first, intents=[order(iid, side=side, price=limit)]),
                     event(iid, 1, through)], split=SPLIT,
                    settlements=[Settlement(iid, D(payout), T0 + timedelta(seconds=10))])
    assert result.fills == 1 and result.report['pnl_after_fees'] == D(profit)
    assert rt.cash == rt.equity() == D('140') + D(profit)
    assert rt.inventory_value == 0 and all(q == 0 for q in rt.quantities.values())
    assert rt.max_drawdown > 0 and rt.fees < 0
    assert rt.max_collateral <= 25


def test_short_sale_must_reserve_its_possible_loss(session):
    rt, (iid,) = runtime(session, count=1)
    result = rt.run([event(iid, 0, intents=[order(iid, side='sell', price='.2', size='40')])], split=SPLIT)
    assert result.orders_placed == 0 and result.orders_rejected == 1
    assert 'prediction cap' in next(iter(rt.rejection_reasons))


def test_sibling_pending_orders_share_the_binary_contract_cap(session):
    rt, (a, b) = runtime(session, count=2, contracts=['same-contract', 'same-contract'])
    result = rt.run([event(a, 0, intents=[order(a, size='30', tag='a')]),
                     event(b, 1, intents=[order(b, size='30', tag='b')])], split=SPLIT)
    assert result.orders_placed == result.orders_rejected == 1
    assert rt.max_collateral == 15


def test_partial_fill_transfers_pending_reservation_without_freeing_its_cost(session):
    rt, (a, b, c) = runtime(session, cash='20', count=3)
    result = rt.run([event(a, 0, intents=[order(a, size='30', tag='a')]),
                     event(b, 1, intents=[order(b, size='20', tag='b')]),
                     event(a, 2, price='.4', size='10'),
                     event(c, 3, intents=[order(c, size='10', tag='c')])], split=SPLIT)
    assert result.orders_placed == 2 and result.orders_rejected == 1 and result.fills == 1
    assert rt.collateral[a] == 5 and rt.max_collateral == 20
    assert rt.cash == D('15.03')


def test_filled_short_proceeds_do_not_fund_new_risk(session):
    rt, (a, b) = runtime(session, cash='10', count=2)
    result = rt.run([event(a, 0, price='.3', intents=[order(a, side='sell', price='.4')]),
                     event(a, 1, price='.5'),
                     event(b, 2, intents=[order(b, price='.5')])], split=SPLIT)
    assert rt.cash > 10  # Sale proceeds exist, with a larger terminal liability.
    assert result.orders_rejected == 1 and result.orders_placed == 1


def test_blackout_cancels_on_quiet_feed_before_later_trade(session):
    rt, (iid,) = runtime(session, count=1, params={'entry_blackout_seconds': 300})
    rt.instruments[iid]['close_ts'] = (T0 + timedelta(seconds=400)).isoformat()
    result = rt.run([event(iid, 0, intents=[order(iid)]),
                     event(iid, 101, price='.4', intents=[order(iid, tag='late')])], split=SPLIT)
    assert result.fills == 0 and result.orders_rejected == 1
    placed = session.scalar(select(Order).where(Order.trial_id == result.trial_id, Order.metadata_['tag'].astext == 'entry'))
    assert placed.status == 'canceled'


def test_future_database_print_cannot_make_timer_data_fresh(session, add_trade):
    rt, (iid,) = runtime(session, count=1)
    add_trade(iid, T0 + timedelta(days=1), price=D('.9'), size=D(10))
    result = rt.run([event(iid, 0, timer=True, intents=[order(iid)])], split=SPLIT)
    assert result.orders_placed == 0 and result.orders_rejected == 1
    assert 'stale market data' in next(iter(rt.rejection_reasons))


def test_permanent_kill_retains_open_losses_and_survives_next_day(session):
    rt, (iid,) = runtime(session, cash='20', count=1)
    result = rt.run([event(iid, 0, price='.9', intents=[order(iid, price='.8', size='20')]),
                     event(iid, 1, price='.7', size='20'),
                     event(iid, 86400, price='.01'),
                     event(iid, 172800, price='.9', intents=[order(iid, price='.8', size='1', tag='after-kill')])],
                    split=SPLIT)
    assert rt.killed and result.orders_rejected == 1
    assert rt.quantities[iid] == 20 and rt.max_drawdown > 15
    assert session.get(StrategyRow, rt.strategy_id).status == 'backtest'
    assert session.scalar(select(RiskHalt.id).where(RiskHalt.strategy_id == rt.strategy_id)) is None


def test_utc_overnight_loss_trips_daily_halt_then_resets_without_resetting_kill(session):
    rt, ids = runtime(session)
    events = []
    for n, iid in enumerate(ids[:3]):
        events += [event(iid, n * 2, price='.95', intents=[order(iid, price='.9', size='20', tag=str(n))]),
                   event(iid, n * 2 + 1, price='.89', size='20')]
    events += [event(ids[3], 10, intents=[order(ids[3], size='5', tag='pending')])]
    for n, iid in enumerate(ids[:3]):
        events.append(event(iid, 86400 + n, price='.01'))
    events += [event(ids[3], 86404, price='.4'),
               event(ids[3], 172800, price='.6', intents=[order(ids[3], size='1', tag='new-day')])]
    result = rt.run(events, split=SPLIT)
    assert any(h['kind'] == 'global_daily_halt' for h in rt.halt_events)
    assert not rt.killed and not rt.daily_halted
    assert result.fills == 3 and result.orders_placed == 5
    canceled = session.scalar(select(Order).where(Order.trial_id == result.trial_id, Order.metadata_['tag'].astext == 'pending'))
    assert canceled.status == 'canceled'


def test_fractional_trade_volume_is_never_rounded_up(session):
    rt, (iid,) = runtime(session, count=1)
    result = rt.run([event(iid, 0, intents=[order(iid)]),
                     event(iid, 1, price='.4', size='.1234567890999')], split=SPLIT)
    size = session.scalar(select(Fill.size).where(Fill.trial_id == result.trial_id))
    assert size == D('.1234567890') < D('.1234567890999')


def test_repeated_identical_rejections_keep_one_order_and_full_attempt_count(session):
    rt, (iid,) = runtime(session, count=1)
    result = rt.run([event(iid, n, intents=[order(iid, size='100')]) for n in range(3)], split=SPLIT)
    rejected = session.scalars(select(Order).where(Order.trial_id == result.trial_id)).all()
    assert result.orders_rejected == 3 and len(rejected) == 1
    assert rejected[0].metadata_['attempt_count'] == 3
