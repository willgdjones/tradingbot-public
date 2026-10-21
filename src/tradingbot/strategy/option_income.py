"""Hold an option-income ETF, optionally only above its 200-day average (tradingbot-ae1).

Covered-call and put-write ETFs (XYLD, QYLD, JEPI, JEPQ, SPYI) sell index
options and pay the premium out monthly, a variance risk premium on top of
equity beta. `hold` is long from the first close of a partition to its last
open. `trend200` is long only while the completed adjusted (total-return)
close is strictly above the mean of the last 200 completed closes, and stays
in cash until 200 closes exist. Decisions are made on completed closes and
trade at the next open. No stop, no rebalancing, no tuning.
"""
from collections import deque
from decimal import Decimal as D, ROUND_FLOOR

from .interface import PlaceOrder, Strategy

VARIANTS = ('hold', 'trend200')
LENGTH = 200


class Trend:
    """Consume completed adjusted closes; return the desired position (0 or 1)."""

    def __init__(self, variant):
        if variant not in VARIANTS:
            raise ValueError('unknown option-income variant')
        self.variant, self.closes, self.average = variant, deque(maxlen=LENGTH), None

    def update(self, close):
        close = D(str(close))
        if not close.is_finite() or close <= 0:
            raise ValueError('invalid completed close')
        if self.variant == 'hold':
            return 1
        self.closes.append(close)
        if len(self.closes) < LENGTH:
            return 0
        self.average = sum(self.closes, D(0))/LENGTH
        return int(close > self.average)


class OptionIncomeHold(Strategy):
    key = 'option_income_hold'

    def on_start(self, ctx):
        self.signal = Trend(self.params.get('variant', 'hold'))
        self.units, self.pending = 0, None
        self.decisions, self.skips = [], []

    def on_event(self, ctx, event):
        iid = self.params['instrument_id']
        if event.instrument_id != iid:
            return []
        phase = event.meta.get('phase')
        if phase == 'close':
            wanted = self.signal.update(event.mid)
            if wanted != self.units:
                equity = ctx.marked_equity()
                self.pending = (min(D('.95')*equity, D(140))*wanted, D('.05')*equity)
                self.units = wanted
                self.decisions.append({'time': event.time.isoformat(), 'units': wanted,
                                       'average': str(self.signal.average)})
            return []
        if phase != 'open':
            return []
        position, snap = ctx.position(iid), ctx.snapshot(iid)
        terminal = event.meta.get('terminal_open', False)
        if snap is None or snap.bid is None or snap.ask is None or min(snap.bid, snap.ask) <= 0:
            return []
        if position > 0 and (terminal or self.units == 0):
            return [PlaceOrder(instrument_id=iid, side='sell', size=position,
                limit_price=snap.bid, intended_liquidity='taker', tag='income:sell:'+event.time.isoformat(),
                reason='terminal liquidation' if terminal else 'close not above 200-day average')]
        if terminal or not self.units or self.pending is None:
            return []
        target, reserve = self.pending
        cash = ctx.available_cash(iid)
        if cash is None:
            raise ValueError('settled cash required')
        budget = min(max(D(0), target-position*snap.ask), max(D(0), cash-reserve-D('.01')))
        size = (budget/snap.ask).quantize(D('.000000001'), rounding=ROUND_FLOOR)
        if size*snap.ask < 1:
            self.skips.append({'time': event.time.isoformat(), 'reason': 'cash/target below $1'})
            return []
        self.pending = None
        return [PlaceOrder(instrument_id=iid, side='buy', size=size, limit_price=snap.ask,
            intended_liquidity='taker', tag='income:buy:'+event.time.isoformat(),
            reason='hold' if self.signal.variant == 'hold' else 'close above 200-day average')]
