"""PRD #6: fixed SPY calendar rule, shared by research/paper/live runtimes."""
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from zoneinfo import ZoneInfo

from .interface import PlaceOrder, Strategy
from .registry import register

NY = ZoneInfo('America/New_York')


@register
class TurnOfMonth(Strategy):
    key = 'turn_of_month'

    def on_start(self, ctx):
        self._attempted = set()

    def on_event(self, ctx, event):
        iid = self.params['instrument_id']
        if event.instrument_id != iid:
            return []
        day = ctx.now.astimezone(NY).date().isoformat()
        action = self.params['schedule'].get(day)
        if action is None or day in self._attempted:
            return []
        close = datetime.fromisoformat(day + 'T' + self.params['session_closes'][day]).replace(tzinfo=NY)
        offset = int(self.params.get('seconds_before_close', 60))
        start = close - timedelta(seconds=offset)
        end = close if offset else close + timedelta(seconds=1)
        if not start <= ctx.now < end:
            return []
        snap = ctx.snapshot(iid)
        position = ctx.position(iid)
        if snap is None or (action == 'buy' and position != 0) or (action == 'sell' and position <= 0):
            return []
        # Real runtimes supply a touch. A daily-close benchmark explicitly opts
        # into reference-price execution in its research adapter only.
        touch = snap.ask if action == 'buy' else snap.bid
        if touch is None or touch <= 0:
            return []
        limit = touch.quantize(Decimal('.01'), rounding=ROUND_CEILING if action == 'buy' else ROUND_FLOOR)
        if action == 'buy':
            budget = Decimal(self.params.get('entry_notional', '24.90'))
            if self.params.get('use_available_cash', False):
                cash = ctx.available_cash(iid)
                reserve = Decimal(self.params.get('entry_fee_reserve', '.01'))
                if cash is None or not cash.is_finite() or reserve < 0 or not reserve.is_finite():
                    return []
                budget = min(budget, cash) - reserve
            if not budget.is_finite() or budget < 1:
                return []
            size = (budget / limit).quantize(Decimal('.000000001'), rounding=ROUND_FLOOR)
        else:
            size = position
        if size <= 0:
            return []
        self._attempted.add(day)
        return [PlaceOrder(instrument_id=iid, side=action, size=size,
                           limit_price=limit, intended_liquidity='taker',
                           tag=f'tom:{day}:{action}', reason='PRD #6 fixed calendar')]
