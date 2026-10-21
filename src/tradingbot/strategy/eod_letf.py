"""PRD #5 cash-account subset: buy large positive daily moves at 15:30 ET."""
from datetime import datetime, time, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from zoneinfo import ZoneInfo

from .interface import PlaceOrder, Strategy
from .registry import register

NY = ZoneInfo('America/New_York')


@register
class EodLetf(Strategy):
    key = 'letf_eod'

    def on_start(self, ctx):
        self.previous_close = {}
        self.attempted = set()
        self.decisions = []

    def on_event(self, ctx, event):
        iid = event.instrument_id
        if iid not in self.params['instrument_ids']:
            return []
        day = ctx.now.astimezone(NY).date()
        day_key = day.isoformat()
        close_string = self.params['session_closes'].get(day_key)
        if close_string is None:
            return []
        close = datetime.combine(day, time.fromisoformat(close_string), NY)
        enter = datetime.combine(day, time(15, 30), NY)
        snapshot = ctx.snapshot(iid)
        if snapshot is None:
            return []
        reference = snapshot.reference_price
        if ctx.now == close and reference is not None:
            self.previous_close[iid] = (day_key, reference)
        if close <= enter:
            return []
        exit_time = close - timedelta(seconds=int(self.params.get('seconds_before_close', 60)))
        action = None
        if enter <= ctx.now < enter + timedelta(seconds=30) and (iid, day, 'buy') not in self.attempted:
            self.attempted.add((iid, day, 'buy'))
            previous = self.previous_close.get(iid)
            if previous is None or previous[0] != self.params['previous_session'].get(day_key):
                return []
            if reference is None or reference <= 0 or previous[1] <= 0:
                return []
            move = reference / previous[1] - 1
            threshold = Decimal(self.params.get('threshold', '.01'))
            signal = 'long' if move >= threshold else 'short_unavailable' if move <= -threshold else 'none'
            self.decisions.append({'date': day_key, 'instrument_id': iid, 'price_return': str(move), 'signal': signal})
            if signal == 'long' and ctx.position(iid) == 0:
                action = 'buy'
        elif exit_time <= ctx.now <= close and (iid, day, 'sell') not in self.attempted:
            if ctx.position(iid) > 0:
                action = 'sell'
        if action is None:
            return []
        touch = snapshot.ask if action == 'buy' else snapshot.bid
        if touch is None or touch <= 0:
            return []
        limit = touch.quantize(Decimal('.01'), rounding=ROUND_CEILING if action == 'buy' else ROUND_FLOOR)
        size = ((Decimal(self.params.get('entry_notional', '24.90')) / limit).quantize(Decimal('.000000001'), rounding=ROUND_FLOOR)
                if action == 'buy' else ctx.position(iid))
        if size <= 0:
            return []
        self.attempted.add((iid, day, action))
        return [PlaceOrder(instrument_id=iid, side=action, size=size, limit_price=limit,
                           intended_liquidity='taker', tag=f'letf:{iid}:{day}:{action}',
                           reason='PRD #5 positive daily move; cash-only subset')]
