"""C17 fixed credit-relative-return signal; only SPY is tradable."""
from decimal import Decimal as D, ROUND_FLOOR

from .c05_commodity_trend import CommodityTrend, NY, ZERO
from .interface import PlaceOrder

SYMBOLS = ('SPY', 'HYG', 'IEF')
VARIANTS = ('63', '126')


def credit_score(history, variant):
    if variant not in VARIANTS or set(history) != {'HYG', 'IEF'}:
        raise ValueError('outside C17 signal specification')
    if len({len(values) for values in history.values()}) != 1:
        raise ValueError('unequal reference history')
    if any(not p.is_finite() or p <= 0 for values in history.values() for p in values):
        raise ValueError('invalid adjusted reference close')
    lag = int(variant)
    if len(history['HYG']) <= lag:
        return None
    return history['HYG'][-1]/history['HYG'][-lag-1] - history['IEF'][-1]/history['IEF'][-lag-1]


class CreditSignal(CommodityTrend):
    key = 'sweep_c17_credit_total_return_v1'

    def on_start(self, ctx):
        super().on_start(ctx)
        if self.symbols != SYMBOLS or self.params['variant'] not in VARIANTS:
            raise ValueError('outside frozen C17 universe/variants')

    def on_event(self, ctx, event):
        symbol = self.by_id.get(event.instrument_id)
        if symbol is None:
            return []
        if event.meta.get('phase') != 'close':
            return super().on_event(ctx, event) if symbol == 'SPY' else []
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
        score = credit_score({s: self.history[s] for s in ('HYG', 'IEF')}, self.params['variant'])
        if score is None:
            self.skips.append({'date': day, 'reason': 'L+1 complete closes inside partition required'})
            return []
        equity = ctx.marked_equity()
        if equity is None or not equity.is_finite() or equity <= 0:
            raise ValueError('positive decision equity required')
        budget = min(D('.95')*equity, D(self.params['slot_usd']))
        self.reserve = D('.05')*equity
        self.targets = {'SPY': budget if score > 0 else ZERO}
        self.pending = {'SPY'}
        self.reasons = {'SPY': 'monthly credit signal rebalance'}
        self.decisions.append({'date': day, 'execution': self.params['next_session'][day],
            'equity': str(equity), 'reserve': str(self.reserve), 'score': str(score),
            'risk_on': score > 0, 'targets': {'SPY': str(self.targets['SPY'])}})
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
        if iid != self.ids['SPY']:
            raise ValueError('reference ETFs are not tradable')
        if size <= 0:
            return []
        tag = f'c17:{day}:{iid}:{side}'
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
            intended_liquidity='taker', tag=tag, reason='C17 '+reason)]
