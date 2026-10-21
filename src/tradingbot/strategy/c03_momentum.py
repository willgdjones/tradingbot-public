"""C03 monthly cross-asset momentum over completed total-return closes."""
from decimal import Decimal as D, ROUND_FLOOR

from .c05_commodity_trend import CommodityTrend, NY, ZERO
from .interface import PlaceOrder

SYMBOLS = ('SPY', 'IEF', 'GLD', 'EFA', 'VNQ')
VARIANTS = ('top-one', 'top-two', 'top-two-sma10')
LOOKBACKS = (1, 3, 6, 9, 12)


def allocation(history, variant):
    if variant not in VARIANTS or set(history) != set(SYMBOLS):
        raise ValueError('outside frozen C03 variants/universe')
    lengths = {len(values) for values in history.values()}
    if len(lengths) != 1:
        raise ValueError('incomplete month-end batch')
    if any(any(not p.is_finite() or p <= 0 for p in values) for values in history.values()):
        raise ValueError('invalid adjusted month-end close')
    if next(iter(lengths)) < 13:
        return {}, {}, []
    scores = {s: sum((values[-1]/values[-lag-1]-1 for lag in LOOKBACKS), ZERO)/len(LOOKBACKS)
              for s, values in history.items()}
    count = 1 if variant == 'top-one' else 2
    ranked = sorted(SYMBOLS, key=lambda s: (-scores[s], s))
    selected = ranked[:count]
    weights = {s: ZERO for s in SYMBOLS}
    for symbol in selected:
        passes = variant != 'top-two-sma10' or history[symbol][-1] > sum(history[symbol][-10:], ZERO)/10
        if passes:
            weights[symbol] = D('.95')/count
    return weights, scores, selected


class CrossAssetMomentum(CommodityTrend):
    key = 'sweep_c03_cross_asset_total_return_v1'

    def on_start(self, ctx):
        super().on_start(ctx)
        if (self.symbols != SYMBOLS or self.params['variant'] not in VARIANTS
                or tuple(self.params['lookbacks']) != LOOKBACKS or self.params['sma_months'] != 10):
            raise ValueError('outside frozen C03 signal specification')
        self.monthly = {s: [] for s in SYMBOLS}
        self.daily_closes = {}

    def on_event(self, ctx, event):
        if event.meta.get('phase') != 'close':
            return super().on_event(ctx, event)
        symbol = self.by_id.get(event.instrument_id)
        if symbol is None:
            return []
        day = event.time.astimezone(NY).date().isoformat()
        if (symbol, day) in self.close_seen:
            raise ValueError('duplicate completed close')
        price = event.mid
        if price is None or not price.is_finite() or price <= 0:
            raise ValueError('invalid adjusted close')
        self.close_seen.add((symbol, day))
        self.daily_closes[symbol] = price
        if not event.meta.get('batch_last'):
            return []
        if any((s, day) not in self.close_seen for s in self.symbols):
            raise ValueError('incomplete simultaneous close batch')
        if day not in self.params['month_ends']:
            return []
        for s in self.symbols:
            self.monthly[s].append(self.daily_closes[s])
        if day not in self.params['next_session'] or not event.meta.get('next_open_in_partition'):
            return []
        weights, scores, selected = allocation(self.monthly, self.params['variant'])
        if not weights:
            self.skips.append({'date': day, 'reason': '13 month-end warm-up observations inside partition required'})
            return []
        equity = ctx.marked_equity()
        if equity is None or not equity.is_finite() or equity <= 0:
            raise ValueError('positive completed-close equity required')
        scale = min(equity, D(self.params['slot_usd'])/D('.95'))
        self.reserve = D(self.params['cash_reserve_weight'])*equity
        self.targets = {s: weights[s]*scale for s in self.symbols}
        self.pending = set(self.symbols)
        self.reasons = {s: 'monthly relative momentum rebalance' for s in self.symbols}
        self.decisions.append({'date': day, 'execution': self.params['next_session'][day],
            'equity': str(equity), 'reserve': str(self.reserve), 'selected': selected,
            'scores': {s: str(v) for s, v in scores.items()},
            'weights': {s: str(v) for s, v in weights.items()},
            'targets': {s: str(v) for s, v in self.targets.items()}})
        return []

    def _allocate_buys(self, ctx, day):
        gaps = {}
        for symbol in sorted(self.pending):
            iid = self.ids[symbol]
            snapshot = ctx.snapshot(iid)
            if snapshot is None or snapshot.time.astimezone(NY).date().isoformat() != day or snapshot.ask is None:
                raise ValueError('all fresh opens required before pro-rata sizing')
            gap = max(ZERO, self.targets[symbol]-ctx.position(iid)*snapshot.reference_price)
            if gap:
                gaps[symbol] = gap
            else:
                self.pending.discard(symbol)
        if not gaps:
            return {}
        cash = ctx.available_cash(self.ids[self.symbols[0]])
        if cash is None or not cash.is_finite():
            raise ValueError('settled cash unavailable')
        spendable = max(ZERO, cash-self.reserve-D(self.params['buy_fee_reserve_usd'])*len(gaps))
        fraction = min(D(1), spendable/sum(gaps.values(), ZERO))
        allocations = {s: (gap*fraction, fraction == 1 or gap < 1) for s, gap in gaps.items()}
        result = {}
        for symbol, (dollars, complete) in allocations.items():
            iid = self.ids[symbol]
            ask = ctx.snapshot(iid).ask
            # The scenario is already rounded adversely in raw cents then
            # converted. Respect the exact price the risk engine receives.
            capacity = max(ZERO, D(self.params['slot_usd'])/ask-ctx.position(iid))
            capacity = capacity.quantize(D(self.params['quantity_step']), rounding=ROUND_FLOOR)*ask
            result[symbol] = min(dollars, capacity), complete or capacity < dollars
            if capacity < dollars:
                self.skips.append({'date': day, 'symbol': symbol, 'reason': 'buy clipped to unchanged full-position cap'})
        return result

    def _order(self, snapshot, iid, size, side, day, reason):
        if size <= 0:
            return []
        tag = f'c03:{day}:{iid}:{side}'
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
            intended_liquidity='taker', tag=tag, reason='C03 '+reason)]
