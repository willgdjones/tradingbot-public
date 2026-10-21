"""Calendar-known expiration-week reactor, using completed-close targets."""
from decimal import Decimal as D, ROUND_FLOOR
from zoneinfo import ZoneInfo

from .interface import PlaceOrder, Strategy

NY = ZoneInfo('America/New_York')


class ExpirationWeek(Strategy):
    key = 'sweep_c11_expiration_week'

    def on_start(self, ctx):
        self.windows = {w['decision']: w for w in self.params['windows']}
        self.targets, self.attempted = {}, set()
        self.active_exit = None
        self.decisions, self.skips = [], []

    def on_event(self, ctx, event):
        iid = self.params['instrument_id']
        if event.instrument_id != iid:
            return []
        day = event.time.astimezone(NY).date().isoformat()
        phase = event.meta.get('phase')
        key = day + ':' + str(phase)
        if phase == 'close' and day in self.windows and key not in self.attempted:
            self.attempted.add(key)
            if event.meta.get('window_complete_in_partition'):
                equity = ctx.marked_equity()
                if equity is None or not equity.is_finite() or equity <= 0:
                    raise ValueError('completed-close equity required')
                window = self.windows[day]
                target = min(D('.95') * equity, D(self.params['slot_usd']))
                reserve = D('.05') * equity
                self.targets[window['entry']] = target, reserve, window
                self.decisions.append({**window, 'decision_equity': str(equity),
                                       'target_usd': str(target), 'reserve_usd': str(reserve)})
            else:
                self.skips.append({'date': day, 'reason': 'round trip outside partition'})
        if phase not in ('open', 'close'):
            return []
        position, snapshot = ctx.position(iid), ctx.snapshot(iid)
        if snapshot is None:
            return []
        terminal = phase == 'open' and event.meta.get('terminal_open', False)
        sell_key = key + ':sell'
        if position > 0 and (self.active_exit == (day, phase) or terminal) and sell_key not in self.attempted:
            self.attempted.add(sell_key)
            if snapshot.bid is None or snapshot.bid <= 0:
                raise ValueError('exit requires scenario bid')
            return [PlaceOrder(instrument_id=iid, side='sell', size=position,
                limit_price=snapshot.bid, intended_liquidity='taker', tag='c11:' + sell_key,
                reason='C11 terminal liquidation' if terminal else 'C11 scheduled expiration exit')]
        buy_key = key + ':buy'
        target = self.targets.get(day)
        if phase != 'open' or terminal or position != 0 or target is None or buy_key in self.attempted:
            return []
        if snapshot.ask is None or snapshot.ask <= 0:
            raise ValueError('entry requires scenario ask')
        self.attempted.add(buy_key)
        dollars, reserve, window = target
        cash = ctx.available_cash(iid)
        if cash is None or not cash.is_finite():
            raise ValueError('settled cash is required')
        budget = min(dollars, D(self.params['slot_usd']), max(D(0), cash-reserve-D('.01')))
        size = (budget/snapshot.ask).quantize(D('.000000001'), rounding=ROUND_FLOOR)
        if size * snapshot.ask < 1:
            self.skips.append({'date': day, 'reason': 'settled cash below $1 after reserves'})
            return []
        self.active_exit = window['exit'], window['exit_phase']
        return [PlaceOrder(instrument_id=iid, side='buy', size=size, limit_price=snapshot.ask,
            intended_liquidity='taker', tag='c11:' + buy_key, reason='C11 frozen prior-week close target')]
