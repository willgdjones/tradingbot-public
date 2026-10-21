"""C04's frozen inverse-variance rule over completed, partition-local closes."""
from dataclasses import replace
from decimal import Decimal as D

from tradingbot.strategy.c05_commodity_trend import CommodityTrend, NY, ZERO

VARIANTS = ('0.0225', '0.01', '0.04')


def variance_weight(returns, c):
    """Sample variance of a complete calendar month, annualized by 252."""
    if str(c) not in VARIANTS:
        raise ValueError('outside frozen C04 variants')
    if len(returns) < 15 or any(not r.is_finite() for r in returns):
        return ZERO, None
    mean = sum(returns, ZERO) / len(returns)
    variance = 252 * sum(((r - mean) ** 2 for r in returns), ZERO) / (len(returns) - 1)
    if not variance.is_finite() or variance <= 0:
        return ZERO, variance
    return min(D('.95'), D(c) / variance), variance


class InverseVariance(CommodityTrend):
    """Reuse the tested frozen-target/settled-cash execution reactor."""
    key = 'sweep_c04_inverse_variance_readmission_v1'

    def on_start(self, ctx):
        super().on_start(ctx)
        if self.symbols != ('SPY',) or self.params['variant'] not in VARIANTS:
            raise ValueError('outside fixed C04 universe/variants')
        self.closes, self.daily_returns = {}, {}

    def on_event(self, ctx, event):
        if event.meta.get('phase') != 'close':
            return super().on_event(ctx, event)
        if event.instrument_id != self.ids['SPY']:
            return []
        day = event.time.astimezone(NY).date().isoformat()
        if day in self.closes:
            raise ValueError('duplicate completed close')
        close, distribution = event.mid, D(event.meta['distribution'])
        if close is None or not close.is_finite() or close <= 0 or not distribution.is_finite() or distribution < 0:
            raise ValueError('invalid raw close or distribution')
        previous_day = self.params['previous_session'].get(day)
        if previous_day in self.closes:
            self.daily_returns[day] = (close + distribution) / self.closes[previous_day] - 1
        self.closes[day] = close
        if day not in self.params['month_ends'] or day not in self.params['next_session']:
            return []
        required = self.params['month_return_sessions'][day[:7]]
        complete = all(d in self.daily_returns for d in required)
        weight, variance = variance_weight([self.daily_returns[d] for d in required], self.params['variant']) if complete else (ZERO, None)
        equity = ctx.marked_equity()
        if equity is None or not equity.is_finite() or equity <= 0:
            raise ValueError('positive decision equity required')
        self.reserve = D(self.params['cash_reserve_weight']) * equity
        self.targets['SPY'] = min(weight * equity, D(self.params['slot_usd']))
        self.pending.add('SPY')
        self.reasons['SPY'] = 'monthly inverse variance rebalance'
        self.decisions.append({'date': day, 'complete_calendar_month': complete,
            'observations': sum(d in self.daily_returns for d in required),
            'annualized_sample_variance': str(variance) if variance is not None else None,
            'weight': str(weight), 'equity': str(equity), 'reserve': str(self.reserve),
            'targets': {'SPY': str(self.targets['SPY'])}})
        return []

    def _order(self, snapshot, iid, size, side, day, reason):
        return [replace(order, tag=order.tag.replace('c05:', 'c04:', 1), reason='C04 ' + reason)
                for order in super()._order(snapshot, iid, size, side, day, reason)]
