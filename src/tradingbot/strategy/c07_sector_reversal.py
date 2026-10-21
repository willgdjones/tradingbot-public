"""C07 weekly sector reversal; pure causal decisions for all execution modes."""
from decimal import Decimal as D, ROUND_CEILING, ROUND_FLOOR
from zoneinfo import ZoneInfo

from .interface import PlaceOrder, Strategy

NY = ZoneInfo('America/New_York')
ZERO = D(0)


def total_return_factor(previous, close, distribution=ZERO, split=D(1), in_kind=ZERO):
    values = (previous, close, distribution, split, in_kind)
    if any(not v.is_finite() for v in values) or min(previous, close, split) <= 0 or min(distribution, in_kind) < 0:
        raise ValueError('invalid economic total-return observation')
    return ((close + distribution) * split + in_kind) / previous


def rank_losers(history, symbols, lookback, top_n):
    """Return negative residuals only, retaining alphabetical tie order."""
    if lookback not in (5, 10) or top_n not in (1, 3):
        raise ValueError('outside preregistered lookback/slot choices')
    if any(len(history[s]) <= lookback for s in (*symbols, 'SPY')):
        return [], {}
    spy = history['SPY'][-1] / history['SPY'][-lookback-1] - 1
    scores = {s: history[s][-1] / history[s][-lookback-1] - 1 - spy for s in symbols}
    eligible = sorted((score, s) for s, score in scores.items() if score < 0)
    return [s for _, s in eligible[:top_n]], scores


class SectorReversal(Strategy):
    key = 'sweep_c07_sector_reversal_blackout_v1'

    def on_start(self, ctx):
        self.symbols = tuple(self.params['symbols'])
        self.ids = self.params['instrument_ids']
        self.by_id = {iid: s for s, iid in self.ids.items()}
        self.by_id[self.params['spy_reference_id']] = 'SPY'
        self.history = {s: [] for s in (*self.symbols, 'SPY')}
        self.last_close, self.targets, self.expiries = {}, {}, {}
        self.pending, self.close_seen, self.causal_exits, self.attempted = set(), set(), set(), set()
        self.plan, self.reserve, self.buy_day = None, ZERO, None
        self.buy_allocations, self.order_context = {}, {}
        self.decisions, self.skips, self.forced_symbols = [], [], set()

    def holdable(self, symbol, day):
        return not any(p['symbol'] == symbol and p['exit'] <= day < p['reentry'] for p in self.params['blackouts'])

    def _observe_close(self, symbol, day, event):
        if (symbol, day) in self.close_seen:
            raise ValueError('duplicate completed observation')
        self.close_seen.add((symbol, day))
        close = event.as_snapshot().reference_price
        if close is None or not close.is_finite() or close <= 0:
            raise ValueError('invalid completed close')
        if symbol in self.last_close:
            factor = total_return_factor(self.last_close[symbol], close,
                D(event.meta.get('distribution', '0')), D(event.meta.get('split_ratio', '1')),
                D(event.meta.get('in_kind_signal_value', '0')))
            self.history[symbol].append(self.history[symbol][-1] * factor)
        else:
            self.history[symbol].append(D(1))
        self.last_close[symbol] = close

    def _freeze_week(self, ctx, day, cycle, allowed):
        if not allowed:
            self.skips.append({'date': day, 'reason': 'cycle exit outside partition', **cycle})
            return
        lookback, slots = self.params['lookback_sessions'], self.params['top_n']
        selected, residuals = rank_losers(self.history, self.symbols, lookback, slots)
        if not residuals:
            self.skips.append({'date': day, 'reason': 'in-partition warm-up', **cycle})
            return
        equity = ctx.marked_equity()
        if equity is None or not equity.is_finite() or equity <= 0:
            raise ValueError('positive decision-close equity required')
        per_slot = min(D(self.params['target_weight']) * equity, D(self.params['slot_usd'])) / slots
        self.reserve = D(self.params['cash_reserve_weight']) * equity
        self.plan = {'decision': day, **cycle}
        self.targets = {s: per_slot for s in selected}
        self.pending = set(selected)
        self.forced_symbols.clear()
        self.decisions.append({**self.plan, 'equity': str(equity), 'reserve': str(self.reserve),
            'selected': selected, 'residuals': {s: str(v) for s, v in residuals.items()},
            'targets': {s: str(v) for s, v in self.targets.items()}})

    def on_event(self, ctx, event):
        symbol = self.by_id.get(event.instrument_id)
        if symbol is None:
            return []
        day, phase = event.time.astimezone(NY).date().isoformat(), event.meta.get('phase')
        if phase == 'close':
            self._observe_close(symbol, day, event)
            if symbol != 'SPY' and not self.holdable(symbol, day) and ctx.position(event.instrument_id):
                raise ValueError('held across corporate-action blackout after unfilled exit')
            if not event.meta.get('batch_last'):
                return []
            if any((s, day) not in self.close_seen for s in (*self.symbols, 'SPY')):
                raise ValueError('incomplete simultaneous close batch')
            cycle = self.params['cycles'].get(day)
            if cycle:
                self._freeze_week(ctx, day, cycle, event.meta['cycle_exit_admitted'])
            for plan in self.params['blackouts']:
                if day == plan['decision']:
                    self.causal_exits.add((plan['symbol'], plan['exit']))
            return []
        if symbol == 'SPY' or phase not in ('reduce', 'buy'):
            return []
        iid, snapshot = event.instrument_id, ctx.snapshot(event.instrument_id)
        quantity = ctx.position(iid)
        if snapshot is None or snapshot.reference_price is None or snapshot.reference_price <= 0:
            raise ValueError('missing execution reference')
        terminal, blocked = event.meta.get('terminal_open', False), not self.holdable(symbol, day)
        expiry = self.expiries.get(symbol)
        if quantity and expiry is None:
            raise ValueError('owned position has no original weekly exit')
        if phase == 'reduce':
            if not quantity:
                return []
            if blocked and (symbol, day) not in self.causal_exits:
                raise ValueError('missing prior-close action-exit decision')
            if terminal or blocked or day >= expiry:
                reason = 'terminal liquidation' if terminal else ('forced blackout exit' if blocked else 'scheduled weekly exit')
                if blocked:
                    self.forced_symbols.add(symbol)
                    if self.plan and day < self.plan['exit'] and symbol in self.targets:
                        self.pending.add(symbol)
                return self._order(snapshot, iid, quantity, 'sell', day, reason, expiry)
            return []
        if terminal or blocked or self.plan is None or not self.plan['entry'] <= day < self.plan['exit']:
            return []
        if self.buy_day != day:
            self.buy_day = day
            self.buy_allocations = self._allocate_buys(ctx, day)
        allocation = self.buy_allocations.get(symbol)
        if allocation is None:
            return []
        dollars, complete = allocation
        if dollars < 1:
            self.skips.append({'date': day, 'symbol': symbol, 'scheduled_exit': self.plan['exit'],
                'reason': 'pro-rata allocation under $1' if complete else 'cash delay or pro-rata allocation under $1'})
            if complete:
                self.pending.discard(symbol)
            return []
        size = (dollars / snapshot.ask).quantize(D(self.params['quantity_step']), rounding=ROUND_FLOOR)
        # The shared risk engine evaluates the submitted cent-rounded limit.
        # Respect that exact cap before submitting a slot-sized top-one order.
        risk_price = snapshot.ask.quantize(D('.01'), rounding=ROUND_CEILING)
        cap_size = max(ZERO, D(self.params['slot_usd']) / risk_price - quantity).quantize(
            D(self.params['quantity_step']), rounding=ROUND_FLOOR)
        size = min(size, cap_size)
        if size * snapshot.ask < 1:
            self.skips.append({'date': day, 'symbol': symbol, 'reason': 'floored buy under $1'})
            if complete:
                self.pending.discard(symbol)
            return []
        if complete:
            self.pending.discard(symbol)
        self.expiries[symbol] = self.plan['exit']
        after_blackout = symbol in self.forced_symbols or any(
            p['symbol'] == symbol and self.plan['entry'] < p['reentry'] <= day < self.plan['exit']
            for p in self.params['blackouts'])
        return self._order(snapshot, iid, size, 'buy', day,
            'blackout reentry' if after_blackout else 'weekly entry', self.plan['exit'])

    def _allocate_buys(self, ctx, day):
        gaps = {}
        if self.plan is None or not self.plan['entry'] <= day < self.plan['exit']:
            return gaps
        for symbol in sorted(self.pending):
            if not self.holdable(symbol, day):
                continue
            iid, snapshot = self.ids[symbol], ctx.snapshot(self.ids[symbol])
            if snapshot is None or snapshot.time.astimezone(NY).date().isoformat() != day or snapshot.ask is None:
                raise ValueError('all fresh opens required before pro-rata sizing')
            owned = ctx.position(iid)
            if owned and self.expiries.get(symbol) != self.plan['exit']:
                self.skips.append({'date': day, 'symbol': symbol, 'reason': 'old weekly position failed to exit'})
                continue
            gap = max(ZERO, self.targets[symbol] - owned * snapshot.reference_price)
            if not gap:
                self.pending.discard(symbol)
            else:
                gaps[symbol] = gap
        if not gaps:
            return {}
        cash = ctx.available_cash(self.ids[self.symbols[0]])
        if cash is None or not cash.is_finite():
            raise ValueError('settled cash unavailable')
        spendable = max(ZERO, cash - self.reserve - D(self.params['buy_fee_reserve_usd']) * len(gaps))
        fraction = min(D(1), spendable / sum(gaps.values(), ZERO))
        return {s: (gap * fraction, fraction == 1 or gap < 1) for s, gap in gaps.items()}

    def _order(self, snapshot, iid, size, side, day, reason, expiry):
        if size <= 0:
            return []
        tag = f'c07:{day}:{iid}:{side}'
        if tag in self.attempted:
            raise ValueError('duplicate same-session order')
        self.attempted.add(tag)
        price = snapshot.ask if side == 'buy' else snapshot.bid
        if price is None or price <= 0:
            raise ValueError('execution price unavailable')
        if size * price < 1:
            self.skips.append({'date': day, 'instrument_id': iid, 'reason': 'order under $1'})
            return []
        self.order_context[tag] = {'original_scheduled_exit': expiry,
            'entry_decision': self.plan['decision'] if side == 'buy' else None,
            'initial_entry_session': self.plan['entry'] if side == 'buy' else None}
        return [PlaceOrder(instrument_id=iid, side=side, size=size,
            limit_price=price.quantize(D('.01'), rounding=ROUND_CEILING if side == 'buy' else ROUND_FLOOR),
            intended_liquidity='taker', tag=tag, reason='C07 ' + reason)]
