"""C06 causal month-end underweight reactor, with no I/O or venue decisions."""
from datetime import datetime
from decimal import Decimal as D, ROUND_CEILING, ROUND_FLOOR
from zoneinfo import ZoneInfo

from .interface import PlaceOrder, Strategy

NY = ZoneInfo('America/New_York')


class MonthEndUnderweight(Strategy):
    key = 'sweep_c06_month_end_underweight'

    def on_start(self, ctx):
        self._last_close = {}
        self._factors = {}
        self._history = {}
        self._targets = {}
        self._attempted = set()
        self._active_exit = None
        self.decisions, self.skips = [], []
        self._windows = {w['decision']: w for w in self.params['windows']}

    def on_event(self, ctx, event):
        spy, ief = self.params['spy_id'], self.params['ief_id']
        if event.instrument_id not in {spy, ief}:
            return []
        day = event.time.astimezone(NY).date().isoformat()
        phase = event.meta.get('phase')
        if phase == 'close':
            self._observe_close(event, day)
            if day in self._windows and day not in self._attempted:
                values = self._history.get(day, {})
                if spy in values and ief in values:
                    self._decision(ctx, event, day)
            return []
        if phase != 'open' or event.instrument_id != spy:
            return []
        snapshot = ctx.snapshot(spy)
        quantity = ctx.position(spy)
        if snapshot is None:
            return []
        terminal = event.meta.get('terminal_open', False)
        sell_key = day + ':sell'
        if quantity > 0 and (day == self._active_exit or terminal) and sell_key not in self._attempted:
            if snapshot.bid is None or snapshot.bid <= 0:
                return []
            self._attempted.add(sell_key)
            return [PlaceOrder(instrument_id=spy, side='sell', size=quantity,
                limit_price=snapshot.bid.quantize(D('.01'), rounding=ROUND_FLOOR),
                intended_liquidity='taker', tag='c06:' + sell_key,
                reason='C06 terminal liquidation' if terminal and day != self._active_exit else 'C06 first-session open exit')]
        buy_key = day + ':buy'
        target = self._targets.get(day)
        if target is None or terminal or quantity != 0 or buy_key in self._attempted:
            return []
        if snapshot.ask is None or snapshot.ask <= 0:
            return []
        cash = ctx.available_cash(spy)
        if cash is None or not cash.is_finite():
            self.skips.append({'date': day, 'reason': 'unavailable settled cash evidence'})
            return []
        dollars, reserve, exit_day = target
        fee_reserve = D(self.params['buy_fee_reserve_usd'])
        budget = min(dollars, max(D(0), cash - reserve - fee_reserve))
        self._attempted.add(buy_key)
        if budget < 1:
            self.skips.append({'date': day, 'reason': 'under $1 after settled-cash/reserve checks'})
            return []
        limit = snapshot.ask.quantize(D('.01'), rounding=ROUND_CEILING)
        size = (budget / limit).quantize(D(self.params['quantity_step']), rounding=ROUND_FLOOR)
        if size * snapshot.ask < 1:
            self.skips.append({'date': day, 'reason': 'floored order under $1'})
            return []
        self._active_exit = exit_day
        return [PlaceOrder(instrument_id=spy, side='buy', size=size, limit_price=limit,
            intended_liquidity='taker', tag='c06:' + buy_key,
            reason='C06 frozen penultimate-close underweight target')]

    def _observe_close(self, event, day):
        iid = event.instrument_id
        close = event.as_snapshot().reference_price
        dividend = D(event.meta['ex_date_distribution'])
        if close is None or not close.is_finite() or close <= 0 or not dividend.is_finite() or dividend < 0:
            raise ValueError('invalid completed close/distribution')
        if iid in self._history.get(day, {}):
            raise ValueError('duplicate completed close')
        factor = self._factors.get(iid, D(1))
        previous = self._last_close.get(iid)
        if previous is not None:
            factor *= (close + dividend) / previous
        self._last_close[iid], self._factors[iid] = close, factor
        self._history.setdefault(day, {})[iid] = factor

    def _decision(self, ctx, event, day):
        self._attempted.add(day)
        window = self._windows[day]
        spy, ief = self.params['spy_id'], self.params['ief_id']
        base = self._history.get(window['base'], {})
        if not event.meta.get('window_complete_in_partition', False) or spy not in base or ief not in base:
            self.skips.append({'date': day, 'reason': 'warm-up or complete round trip outside partition'})
            return
        a, b = self._history[day][spy] / base[spy], self._history[day][ief] / base[ief]
        weight = D('.6') * a / (D('.6') * a + D('.4') * b)
        threshold = D(self.params['threshold'])
        decision = {'month': window['month'], 'decision': day, 'base': window['base'],
                    'entry': window['entry'], 'exit': window['exit'],
                    'spy_total_factor': str(a), 'ief_total_factor': str(b),
                    'equity_weight': str(weight), 'qualified': weight < threshold}
        self.decisions.append(decision)
        if weight >= threshold:
            return
        equity = ctx.marked_equity()
        if equity is None or not equity.is_finite() or equity <= 0:
            raise ValueError('decision-time marked strategy equity is required')
        target = min(D(self.params['target_weight']) * equity, D(self.params['slot_usd']))
        reserve = (1 - D(self.params['target_weight'])) * equity
        self._targets[window['entry']] = (target, reserve, window['exit'])
        decision.update({'frozen_target_usd': str(target), 'frozen_reserve_usd': str(reserve),
                         'decision_equity_usd': str(equity)})
