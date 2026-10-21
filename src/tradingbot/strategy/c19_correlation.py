"""C19 monthly correlation-conditioned SPY and defensive-fund allocation."""
from decimal import Decimal as D, ROUND_FLOOR

from .c05_commodity_trend import CommodityTrend, NY, ZERO
from .interface import PlaceOrder

SYMBOLS = ('SPY', 'IEF', 'GLD')
VARIANTS = ('63', '126')


def pearson_returns(x, y):
    if len(x) != len(y) or len(x) < 2:
        raise ValueError('aligned return observations required')
    if any(not value.is_finite() for value in (*x, *y)):
        raise ValueError('finite returns required')
    ax, ay = sum(x, ZERO)/len(x), sum(y, ZERO)/len(y)
    dx, dy = [v-ax for v in x], [v-ay for v in y]
    vx, vy = sum((v*v for v in dx), ZERO), sum((v*v for v in dy), ZERO)
    if not vx or not vy:
        return None
    covariance = sum((a*b for a,b in zip(dx, dy)), ZERO)
    return covariance/(vx*vy).sqrt()


def correlation(history, variant):
    if variant not in VARIANTS or set(history) != {'SPY', 'IEF'}:
        raise ValueError('outside C19 signal specification')
    if len({len(values) for values in history.values()}) != 1:
        raise ValueError('unequal reference history')
    if any(not p.is_finite() or p <= 0 for values in history.values() for p in values):
        raise ValueError('invalid adjusted close')
    lag = int(variant)
    if len(history['SPY']) <= lag:
        return None, 'L+1 complete closes inside partition required'
    returns = {s:[b/a-1 for a,b in zip(values[-lag-1:-1], values[-lag:])]
               for s,values in history.items()}
    rho = pearson_returns(returns['SPY'], returns['IEF'])
    return rho, 'undefined zero-variance correlation' if rho is None else None


def defensive_fund(rho):
    return None if rho is None else 'GLD' if rho > 0 else 'IEF'


class CorrelationHedge(CommodityTrend):
    key = 'sweep_c19_correlation_total_return_v1'

    def on_start(self, ctx):
        super().on_start(ctx)
        if self.symbols != SYMBOLS or self.params['variant'] not in VARIANTS:
            raise ValueError('outside frozen C19 universe/variants')

    def on_event(self, ctx, event):
        symbol = self.by_id.get(event.instrument_id)
        if symbol is None:
            return []
        if event.meta.get('phase') != 'close':
            return super().on_event(ctx, event)
        day = event.time.astimezone(NY).date().isoformat()
        if (symbol, day) in self.close_seen:
            raise ValueError('duplicate completed close')
        if event.mid is None or not event.mid.is_finite() or event.mid <= 0:
            raise ValueError('invalid adjusted close')
        self.close_seen.add((symbol, day))
        self.history[symbol].append(event.mid)
        if not event.meta.get('batch_last'):
            return []
        if any((s, day) not in self.close_seen for s in SYMBOLS):
            raise ValueError('incomplete simultaneous close batch')
        if day not in self.params['month_ends']:
            return []
        # A new monthly decision expires any previous delayed target.
        self.pending.clear()
        if day not in self.params['next_session'] or not event.meta.get('next_open_in_partition'):
            return []
        rho, reason = correlation({s:self.history[s] for s in ('SPY','IEF')}, self.params['variant'])
        hedge = defensive_fund(rho)
        if reason:
            self.skips.append({'date':day,'reason':reason})
        equity = ctx.marked_equity()
        if equity is None or not equity.is_finite() or equity <= 0:
            raise ValueError('positive decision equity required')
        budget = min(D('.95')*equity, D(self.params['slot_usd']))
        self.reserve = D('.05')*equity
        self.targets = {s:ZERO for s in SYMBOLS}
        if hedge:
            self.targets['SPY'] = self.targets[hedge] = budget/2
        self.pending = set(SYMBOLS)
        self.reasons = {s:'monthly correlation rebalance' for s in SYMBOLS}
        self.decisions.append({'date':day,'execution':self.params['next_session'][day],
            'equity':str(equity),'reserve':str(self.reserve),'correlation':str(rho) if rho is not None else None,
            'hedge':hedge,'reason':reason,'targets':{s:str(v) for s,v in self.targets.items()}})
        return []

    def _allocate_buys(self, ctx, day):
        allocations = super()._allocate_buys(ctx, day)
        result = {}
        for symbol, (dollars, complete) in allocations.items():
            iid = self.ids[symbol]
            ask = ctx.snapshot(iid).ask
            capacity = max(ZERO, min(self.targets[symbol], D(self.params['slot_usd']))/ask - ctx.position(iid))
            capacity = capacity.quantize(D(self.params['quantity_step']), rounding=ROUND_FLOOR)*ask
            result[symbol] = min(dollars, capacity), complete or capacity < dollars
            if capacity < dollars:
                self.skips.append({'date': day, 'symbol': symbol, 'reason': 'buy clipped at adverse-price full target/slot cap'})
        return result

    def _order(self, snapshot, iid, size, side, day, reason):
        if size <= 0:
            return []
        tag = f'c19:{day}:{iid}:{side}'
        if tag in self.attempted:
            raise ValueError('duplicate same-session order')
        self.attempted.add(tag)
        price = snapshot.ask if side == 'buy' else snapshot.bid
        if price is None or price <= 0:
            raise ValueError('execution price unavailable')
        if size*price < 1:
            self.skips.append({'date': day, 'instrument_id': iid, 'reason': 'order under $1'})
            return []
        return [PlaceOrder(instrument_id=iid, side=side, size=size, limit_price=price,
            intended_liquidity='taker', tag=tag, reason='C19 '+reason)]
