"""C02 monthly sector momentum; pure causal decisions for all execution modes.

Rank the nine Select Sector SPDRs at each month-end by a trailing economic
total-return momentum score, hold the top three equally inside the 95% total
weight (alphabetical ties), and rebalance monthly: at the first open of the next
month sell the names that left the top three and buy the names that entered or
remain under target, pro-rata across positive gaps. Names that stay in the top
three are held across the rebalance (no churn) — only their positive target gap
is topped up, never trimmed. Corporate-action blackouts (Amendment 21,
docs/research/21-corporate-action-blackout.md) are never held through: a
blacked-out name is excluded from selection and any held position is force-sold
at the blackout exit open and may re-enter only after the reentry open.

Decision uses the month-end economic total-return index (dividends reinvested,
true splits, economic in-kind value — never a cash credit or executable price);
execution uses the next session's raw open. The strategy is a pure reactor: all
state is derived from the observations it is shown (interface.py).
"""
from decimal import Decimal as D, ROUND_CEILING, ROUND_FLOOR
from zoneinfo import ZoneInfo

from .interface import PlaceOrder, Strategy

NY = ZoneInfo('America/New_York')
ZERO = D(0)
VARIANTS = ('ret12', 'ret6', 'mean5')
# Month-lookbacks whose trailing total return feeds each score; the longest sets
# the warm-up (need lookback+1 month-end samples before a score exists).
SCORE_LOOKBACKS = {'ret12': (12,), 'ret6': (6,), 'mean5': (1, 3, 6, 9, 12)}


def total_return_factor(previous, close, distribution=ZERO, split=D(1), in_kind=ZERO):
    """One session's economic total-return factor (identical to the C07 signal)."""
    values = (previous, close, distribution, split, in_kind)
    if any(not v.is_finite() for v in values) or min(previous, close, split) <= 0 or min(distribution, in_kind) < 0:
        raise ValueError('invalid economic total-return observation')
    return ((close + distribution) * split + in_kind) / previous


def momentum_score(index, variant):
    """Trailing total-return momentum from month-end index samples, or None while
    the warm-up (longest lookback + 1 samples) is incomplete."""
    lookbacks = SCORE_LOOKBACKS[variant]
    if len(index) <= max(lookbacks):
        return None
    returns = [index[-1] / index[-1 - lookback] - 1 for lookback in lookbacks]
    return sum(returns, ZERO) / len(returns)


def rank_momentum(month_end, symbols, variant, top_n):
    """Top-n by momentum score (pure rank), alphabetical ties; [] during warm-up."""
    if variant not in VARIANTS or top_n != 3:
        raise ValueError('outside preregistered C02 variant/slot choices')
    scores = {s: momentum_score(month_end[s], variant) for s in symbols}
    if any(score is None for score in scores.values()):
        return [], {}
    ordered = sorted(symbols, key=lambda s: (-scores[s], s))
    return ordered[:top_n], scores


class SectorMomentum(Strategy):
    key = 'sweep_c02_sector_momentum_blackout_v1'

    def on_start(self, ctx):
        self.symbols = tuple(self.params['symbols'])
        self.ids = self.params['instrument_ids']
        self.by_id = {iid: s for s, iid in self.ids.items()}
        self.variant, self.top_n = self.params['variant'], self.params['top_n']
        self.tr = {s: ZERO for s in self.symbols}
        self.month_end = {s: [] for s in self.symbols}
        self.last_close, self.close_seen = {}, set()
        self.active_targets, self.active_window = {}, None
        self.decided, self.reserve = None, ZERO
        self.pending, self.forced_symbols = set(), set()
        self.causal_exits, self.attempted = set(), set()
        self.buy_day, self.buy_allocations = None, {}
        self.order_context, self.decisions, self.skips = {}, [], []

    # -- blackout -----------------------------------------------------------
    def holdable(self, symbol, day):
        return not any(p['symbol'] == symbol and p['exit'] <= day < p['reentry']
                       for p in self.params['blackouts'])

    # -- signal -------------------------------------------------------------
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
            self.tr[symbol] *= factor
        else:
            self.tr[symbol] = D(1)
        self.last_close[symbol] = close

    def _freeze_month(self, ctx, day, cycle, allowed):
        if not allowed:
            self.skips.append({'date': day, 'reason': 'rebalance entry outside partition', **cycle})
            return
        selected, scores = rank_momentum(self.month_end, self.symbols, self.variant, self.top_n)
        if not selected:
            self.skips.append({'date': day, 'reason': 'in-partition warm-up', **cycle})
            return
        equity = ctx.marked_equity()
        if equity is None or not equity.is_finite() or equity <= 0:
            raise ValueError('positive decision-close equity required')
        per_slot = min(D(self.params['target_weight']) * equity, D(self.params['slot_usd'])) / self.top_n
        self.decided = {'decision': day, 'entry': cycle['entry'], 'exit': cycle['exit'],
                        'selected': selected, 'targets': {s: per_slot for s in selected},
                        'reserve': D(self.params['cash_reserve_weight']) * equity}
        self.decisions.append({'decision': day, 'entry': cycle['entry'], 'exit': cycle['exit'],
            'equity': str(equity), 'reserve': str(self.decided['reserve']), 'selected': selected,
            'scores': {s: str(v) for s, v in scores.items()},
            'targets': {s: str(v) for s, v in self.decided['targets'].items()}})

    def _maybe_activate(self, day):
        """Install the prior month-end decision at its rebalance open (idempotent)."""
        if self.decided is not None and day == self.decided['entry']:
            self.active_targets = dict(self.decided['targets'])
            self.active_window = {k: self.decided[k] for k in ('decision', 'entry', 'exit', 'selected')}
            self.reserve = self.decided['reserve']
            self.pending = set(self.decided['selected'])
            self.forced_symbols = set()
            self.buy_day, self.buy_allocations = None, {}
            self.decided = None

    def _in_window(self, day):
        window = self.active_window
        return bool(window) and window['entry'] <= day and (window['exit'] is None or day < window['exit'])

    # -- reactor ------------------------------------------------------------
    def on_event(self, ctx, event):
        symbol = self.by_id.get(event.instrument_id)
        if symbol is None:
            return []
        day, phase = event.time.astimezone(NY).date().isoformat(), event.meta.get('phase')
        if phase == 'close':
            self._observe_close(symbol, day, event)
            if not self.holdable(symbol, day) and ctx.position(event.instrument_id):
                raise ValueError('held across corporate-action blackout after unfilled exit')
            if not event.meta.get('batch_last'):
                return []
            if any((s, day) not in self.close_seen for s in self.symbols):
                raise ValueError('incomplete simultaneous close batch')
            cycle = self.params['cycles'].get(day)
            if cycle:
                for s in self.symbols:
                    self.month_end[s].append(self.tr[s])
                self._freeze_month(ctx, day, cycle, event.meta['entry_admitted'])
            for plan in self.params['blackouts']:
                if day == plan['decision']:
                    self.causal_exits.add((plan['symbol'], plan['exit']))
            return []
        if phase not in ('reduce', 'buy'):
            return []
        iid, snapshot = event.instrument_id, ctx.snapshot(event.instrument_id)
        quantity = ctx.position(iid)
        if snapshot is None or snapshot.reference_price is None or snapshot.reference_price <= 0:
            raise ValueError('missing execution reference')
        self._maybe_activate(day)
        terminal, blocked = event.meta.get('terminal_open', False), not self.holdable(symbol, day)
        if phase == 'reduce':
            if not quantity:
                return []
            if blocked and (symbol, day) not in self.causal_exits:
                raise ValueError('missing prior-close action-exit decision')
            if terminal:
                return self._order(snapshot, iid, quantity, 'sell', day, 'terminal liquidation')
            if blocked:
                self.forced_symbols.add(symbol)
                if symbol in self.active_targets:
                    self.pending.add(symbol)
                return self._order(snapshot, iid, quantity, 'sell', day, 'forced blackout exit')
            if self._in_window(day) and day == self.active_window['entry'] and symbol not in self.active_targets:
                return self._order(snapshot, iid, quantity, 'sell', day, 'monthly rebalance exit')
            return []
        if terminal or blocked or not self._in_window(day) or symbol not in self.active_targets:
            return []
        if self.buy_day != day:
            self.buy_day = day
            self.buy_allocations = self._allocate_buys(ctx, day)
        allocation = self.buy_allocations.get(symbol)
        if allocation is None:
            return []
        dollars, complete = allocation
        if dollars < 1:
            self.skips.append({'date': day, 'symbol': symbol, 'rebalance_entry': self.active_window['entry'],
                'reason': 'pro-rata allocation under $1' if complete else 'cash delay or pro-rata allocation under $1'})
            if complete:
                self.pending.discard(symbol)
            return []
        size = (dollars / snapshot.ask).quantize(D(self.params['quantity_step']), rounding=ROUND_FLOOR)
        # The shared risk engine evaluates the submitted cent-rounded limit; respect
        # that exact per-position slot cap before submitting a top-up order.
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
        after_blackout = symbol in self.forced_symbols
        return self._order(snapshot, iid, size, 'buy', day,
            'blackout reentry' if after_blackout else 'monthly entry')

    def _allocate_buys(self, ctx, day):
        gaps = {}
        if not self._in_window(day):
            return gaps
        for symbol in sorted(self.pending):
            if not self.holdable(symbol, day):
                continue
            iid, snapshot = self.ids[symbol], ctx.snapshot(self.ids[symbol])
            if snapshot is None or snapshot.time.astimezone(NY).date().isoformat() != day or snapshot.ask is None:
                raise ValueError('all fresh opens required before pro-rata sizing')
            gap = max(ZERO, self.active_targets[symbol] - ctx.position(iid) * snapshot.reference_price)
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

    def _order(self, snapshot, iid, size, side, day, reason):
        if size <= 0:
            return []
        tag = f'c02:{day}:{iid}:{side}'
        if tag in self.attempted:
            raise ValueError('duplicate same-session order')
        self.attempted.add(tag)
        price = snapshot.ask if side == 'buy' else snapshot.bid
        if price is None or price <= 0:
            raise ValueError('execution price unavailable')
        if size * price < 1:
            self.skips.append({'date': day, 'instrument_id': iid, 'reason': 'order under $1'})
            return []
        window = self.active_window or {}
        self.order_context[tag] = {
            'rebalance_decision': window.get('decision') if side == 'buy' else None,
            'rebalance_entry': window.get('entry') if side == 'buy' else None,
            'rebalance_exit': window.get('exit') if side == 'buy' else None}
        return [PlaceOrder(instrument_id=iid, side=side, size=size,
            limit_price=price.quantize(D('.01'), rounding=ROUND_CEILING if side == 'buy' else ROUND_FLOOR),
            intended_liquidity='taker', tag=tag, reason='C02 ' + reason)]
