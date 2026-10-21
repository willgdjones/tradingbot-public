"""C05 monthly five-sleeve commodity trend, pure decisions over available events."""
from decimal import Decimal as D, ROUND_CEILING, ROUND_FLOOR
from zoneinfo import ZoneInfo

from .interface import PlaceOrder, Strategy

NY = ZoneInfo('America/New_York')
ZERO = D(0)


def positive_signal(history, variant):
    if variant in ('total_return_252_positive', 'total_return_126_positive'):
        lag = 252 if variant == 'total_return_252_positive' else 126
        return len(history) > lag and history[-1] > history[-lag-1]
    if variant == 'above_sma_200':
        return len(history) >= 200 and history[-1] > sum(history[-200:], ZERO) / 200
    raise ValueError('unknown C05 signal')


class CommodityTrend(Strategy):
    key = 'sweep_c05_commodity_trend_blackout_v1'

    def on_start(self, ctx):
        self.symbols = tuple(self.params['symbols'])
        self.ids = self.params['instrument_ids']
        self.by_id = {iid: symbol for symbol, iid in self.ids.items()}
        self.history = {s: [] for s in self.symbols}
        self.signals = {s: False for s in self.symbols}
        self.targets, self.pending, self.reasons = {}, set(), {}
        self.reserve = ZERO
        self.decisions, self.skips = [], []
        self.attempted, self.close_seen, self.causal_exits = set(), set(), set()
        self.buy_day, self.buy_allocations = None, {}

    def holdable(self, symbol, day):
        return not any(p['symbol'] == symbol and p['exit'] <= day < p['reentry']
                       for p in self.params['blackouts'])

    def _target(self, equity):
        # All five active sleeves sum to min(95% equity, the virtual slot).
        return min(D(self.params['sleeve_weight']) * equity, D(self.params['slot_usd']) / len(self.symbols))

    def _freeze(self, ctx, symbols, day, reason):
        equity = ctx.marked_equity()
        if equity is None or not equity.is_finite() or equity <= 0:
            raise ValueError('positive completed-close equity required')
        self.reserve = D(self.params['cash_reserve_weight']) * equity
        next_day = self.params['next_session'][day]
        for symbol in symbols:
            target = self._target(equity) if self.signals[symbol] and self.holdable(symbol, next_day) else ZERO
            self.targets[symbol] = target
            self.pending.add(symbol)
            self.reasons[symbol] = reason
        self.decisions.append({'date': day, 'kind': reason, 'equity': str(equity),
            'reserve': str(self.reserve), 'signals': {s: self.signals[s] for s in symbols},
            'targets': {s: str(self.targets[s]) for s in symbols}})

    def on_event(self, ctx, event):
        symbol = self.by_id.get(event.instrument_id)
        if symbol is None:
            return []
        day = event.time.astimezone(NY).date().isoformat()
        phase = event.meta.get('phase')
        if phase == 'close':
            if (symbol, day) in self.close_seen:
                raise ValueError('duplicate completed observation')
            self.close_seen.add((symbol, day))
            price = D(event.meta['adjusted_close'])
            if not price.is_finite() or price <= 0:
                raise ValueError('invalid adjusted close')
            self.history[symbol].append(price)
            if not self.holdable(symbol, day) and ctx.position(event.instrument_id):
                raise ValueError('held across corporate-action blackout')
            if not event.meta.get('batch_last'):
                return []
            if any((s, day) not in self.close_seen for s in self.symbols):
                raise ValueError('incomplete simultaneous close batch')
            if day in self.params['month_ends'] and day in self.params['next_session']:
                self.signals = {s: positive_signal(self.history[s], self.params['variant']) for s in self.symbols}
                self._freeze(ctx, self.symbols, day, 'monthly rebalance')
            reentries = [p['symbol'] for p in self.params['blackouts']
                         if self.params['next_session'].get(day) == p['reentry']]
            if reentries:
                self._freeze(ctx, reentries, day, 'blackout reentry')
            for plan in self.params['blackouts']:
                if day == plan['decision']:
                    s = plan['symbol']
                    self.causal_exits.add((s, plan['exit']))
                    self.targets[s] = ZERO
                    self.pending.add(s)
                    self.reasons[s] = 'forced blackout exit'
            return []
        if phase not in ('reduce', 'buy'):
            return []
        iid, snapshot = event.instrument_id, ctx.snapshot(event.instrument_id)
        quantity = ctx.position(iid)
        if snapshot is None or snapshot.reference_price is None or snapshot.reference_price <= 0:
            raise ValueError('missing execution reference')
        terminal = event.meta.get('terminal_open', False)
        blocked = not self.holdable(symbol, day)
        if blocked and quantity and (symbol, day) not in self.causal_exits:
            raise ValueError('missing causal forced exit')
        if phase == 'reduce':
            if terminal or blocked:
                self.targets[symbol] = ZERO
                self.pending.discard(symbol)
                reason = 'terminal liquidation' if terminal else 'forced blackout exit'
                return self._order(snapshot, iid, quantity, 'sell', day, reason) if quantity else []
            if symbol not in self.pending:
                return []
            target = self.targets[symbol]
            excess = quantity * snapshot.reference_price - target
            if excess <= 0:
                return []
            size = quantity if not target else (excess / snapshot.reference_price).quantize(
                D(self.params['quantity_step']), rounding=ROUND_FLOOR)
            if target and size * snapshot.bid < 1:
                self.skips.append({'date': day, 'symbol': symbol, 'reason': 'reduction under $1'})
                self.pending.discard(symbol)
                return []
            self.pending.discard(symbol)
            return self._order(snapshot, iid, size, 'sell', day, self.reasons[symbol])
        if terminal or blocked:
            return []
        if self.buy_day != day:
            self.buy_day = day
            self.buy_allocations = self._allocate_buys(ctx, day)
        allocation = self.buy_allocations.get(symbol)
        if allocation is None:
            return []
        dollars, complete = allocation
        if dollars < 1:
            self.skips.append({'date': day, 'symbol': symbol,
                'reason': 'pro-rata allocation under $1' if complete else 'cash delay or pro-rata allocation under $1'})
            if complete:
                self.pending.discard(symbol)
            return []
        size = (dollars / snapshot.ask).quantize(D(self.params['quantity_step']), rounding=ROUND_FLOOR)
        if size * snapshot.ask < 1:
            self.skips.append({'date': day, 'symbol': symbol, 'reason': 'floored buy under $1'})
            if complete:
                self.pending.discard(symbol)
            return []
        if complete:
            self.pending.discard(symbol)
        return self._order(snapshot, iid, size, 'buy', day, self.reasons[symbol])

    def _allocate_buys(self, ctx, day):
        gaps = {}
        for symbol in tuple(self.pending):
            if not self.holdable(symbol, day):
                continue
            iid = self.ids[symbol]
            snapshot = ctx.snapshot(iid)
            if snapshot is None or snapshot.time.astimezone(NY).date().isoformat() != day or snapshot.ask is None:
                raise ValueError('all fresh opens required before pro-rata sizing')
            gap = max(ZERO, self.targets[symbol] - ctx.position(iid) * snapshot.reference_price)
            if not gap:
                self.pending.discard(symbol)
            else:
                gaps[symbol] = gap
        if not gaps:
            return {}
        cash = ctx.available_cash(self.ids[self.symbols[0]])
        if cash is None or not cash.is_finite():
            raise ValueError('settled cash unavailable')
        total = sum(gaps.values(), ZERO)
        spendable = max(ZERO, cash - self.reserve - D(self.params['buy_fee_reserve_usd']) * len(gaps))
        fraction = min(D(1), spendable / total)
        return {s: (gap * fraction, fraction == 1 or gap < 1) for s, gap in gaps.items()}

    def _order(self, snapshot, iid, size, side, day, reason):
        if size <= 0:
            return []
        tag = f'c05:{day}:{iid}:{side}'
        if tag in self.attempted:
            raise ValueError('duplicate same-session order')
        self.attempted.add(tag)
        price = snapshot.ask if side == 'buy' else snapshot.bid
        if price is None or price <= 0:
            raise ValueError('execution price unavailable')
        if size * price < 1:
            self.skips.append({'date': day, 'instrument_id': iid, 'reason': 'order under $1'})
            return []
        return [PlaceOrder(instrument_id=iid, side=side, size=size,
            limit_price=price.quantize(D('.01'), rounding=ROUND_CEILING if side == 'buy' else ROUND_FLOOR),
            intended_liquidity='taker', tag=tag, reason='C05 ' + reason)]
