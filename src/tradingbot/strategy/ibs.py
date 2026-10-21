"""IBS (internal bar strength) mean reversion: the Wealth-Lab QQQ rule.

Source: wealth-lab.com/blog/build-a-profitable-mean-reversion-strategy-using-the-ibs-indicator
(tradingbot-kyn). IBS = (close - low) / (high - low) of the completed daily bar.
Go long at the next open after IBS crosses under 0.10; go flat at the next open
after it crosses over 0.90. Crossing compares with the previous completed bar,
as WealthLab's CrossesUnder/CrossesOver do. A zero-range bar has no IBS and
cannot cross. No stop, no time exit, no threshold tuning.
"""
from decimal import Decimal as D, ROUND_FLOOR

from .interface import PlaceOrder, Strategy

LOW, HIGH = D('.10'), D('.90')


class Signal:
    """Consume completed adjusted OHLC bars; return the desired position (0 or 1)."""

    def __init__(self):
        self.previous, self.units = None, 0

    def update(self, bar):
        b = {k: D(str(bar[k])) for k in ('open', 'high', 'low', 'close')}
        if (any(not v.is_finite() or v <= 0 for v in b.values())
                or b['low'] > min(b['open'], b['close'])
                or b['high'] < max(b['open'], b['close'])):
            raise ValueError('invalid completed OHLC')
        value = None if b['high'] == b['low'] else (b['close']-b['low'])/(b['high']-b['low'])
        prior, self.previous = self.previous, value
        if value is not None and prior is not None:
            if not self.units and prior >= LOW > value:
                self.units = 1
            elif self.units and prior <= HIGH < value:
                self.units = 0
        return self.units


class IBSReversion(Strategy):
    key = 'ibs_mean_reversion'

    def on_start(self, ctx):
        self.signal = Signal()
        self.units, self.pending = 0, None
        self.decisions, self.skips = [], []

    def on_event(self, ctx, event):
        iid = self.params['instrument_id']
        if event.instrument_id != iid:
            return []
        phase = event.meta.get('phase')
        if phase == 'close':
            wanted = self.signal.update(event.meta['ohlc'])
            if wanted != self.units:
                equity = ctx.marked_equity()
                self.pending = (min(D('.95')*equity, D(140))*wanted, D('.05')*equity)
                self.units = wanted
                self.decisions.append({'time': event.time.isoformat(), 'units': wanted,
                                       'ibs': str(self.signal.previous)})
            return []
        if phase != 'open':
            return []
        position, snap = ctx.position(iid), ctx.snapshot(iid)
        terminal = event.meta.get('terminal_open', False)
        if snap is None or snap.bid is None or snap.ask is None or min(snap.bid, snap.ask) <= 0:
            return []
        if position > 0 and (terminal or self.units == 0):
            return [PlaceOrder(instrument_id=iid, side='sell', size=position,
                limit_price=snap.bid, intended_liquidity='taker',
                tag='ibs:sell:'+event.time.isoformat(), reason='terminal liquidation' if terminal else 'IBS over 0.90')]
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
            intended_liquidity='taker', tag='ibs:buy:'+event.time.isoformat(), reason='IBS under 0.10')]
