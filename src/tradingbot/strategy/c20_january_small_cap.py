"""C20 conditional January small-cap recovery: IWM after a weak December.

Pure reactor over the shared equity execution base. IWM is the only traded
leg; SPY is a reference used solely for the December qualifier. At December's
final regular-session close the December total returns of IWM and SPY (final
December close over the previous November final close, both inside the
partition) are compared. If IWM's December return is strictly negative and
strictly below SPY's, buy IWM at the next regular open (January's first
session) and exit at the original S+H session open (the sixth/eleventh January
session for H=5/10). At most one entry per year; the exit open is fixed at the
decision and is never restarted by a cash-delayed entry.
"""
from decimal import Decimal as D, ROUND_FLOOR

from .c05_commodity_trend import CommodityTrend, NY, ZERO
from .interface import PlaceOrder

SYMBOLS = ('IWM', 'SPY')   # IWM traded; SPY reference only, never held.
VARIANTS = ('5', '10')     # holding horizon H in session intervals.


class JanuarySmallCap(CommodityTrend):
    key = 'sweep_c20_january_small_cap_total_return_v1'

    def on_start(self, ctx):
        super().on_start(ctx)
        if self.symbols != SYMBOLS or self.params['variant'] not in VARIANTS:
            raise ValueError('outside frozen C20 universe/variants')
        # Month-end adjusted closes seen inside this partition, per symbol.
        self.month_end_close = {s: {} for s in SYMBOLS}
        self.entry_open = None       # scheduled IWM entry open (ISO date) or None
        self.exit_open = None        # scheduled IWM exit open (ISO date) or None
        self.active_year = None      # calendar year of the live position

    def on_event(self, ctx, event):
        symbol = self.by_id.get(event.instrument_id)
        if symbol is None:
            return []
        if event.meta.get('phase') != 'close':
            # The entry is a one-shot buy at open S; after that open it is held
            # untouched (no rebalance trim or top-up) until the fixed exit.
            if self.targets.get('IWM', ZERO) > 0 and event.time.astimezone(NY).date().isoformat() != self.entry_open:
                self.pending.discard('IWM')
            return super().on_event(ctx, event)
        day = event.time.astimezone(NY).date().isoformat()
        if (symbol, day) in self.close_seen:
            raise ValueError('duplicate completed close')
        price = event.mid
        if price is None or not price.is_finite() or price <= 0:
            raise ValueError('invalid adjusted close')
        self.close_seen.add((symbol, day))
        self.history[symbol].append(price)
        if day in self.params['month_ends']:
            self.month_end_close[symbol][day[:7]] = price
        if not event.meta.get('batch_last'):
            return []
        if any((s, day) not in self.close_seen for s in SYMBOLS):
            raise ValueError('incomplete simultaneous close batch')
        # Horizon exit: the session before the fixed S+H open schedules the sale.
        if self.exit_open is not None and self.params['next_session'].get(day) == self.exit_open:
            self.targets['IWM'] = ZERO
            self.pending = {'IWM'}
            self.reasons['IWM'] = 'January horizon exit'
            self.decisions.append({'date': day, 'kind': 'exit', 'execution': self.exit_open,
                                   'year': self.active_year})
            self.exit_open = None
        # December qualifier, executed at the next (January first) open.
        if (day in self.params['december_month_ends'] and day in self.params['next_session']
                and event.meta.get('next_open_in_partition')):
            self._december_decision(ctx, day)
        return []

    def _december_decision(self, ctx, day):
        year, month, nov = day[:4], day[:7], f'{day[:4]}-11'
        returns = {}
        for s in SYMBOLS:
            prev, last = self.month_end_close[s].get(nov), self.month_end_close[s].get(month)
            if prev is None or last is None:
                self.skips.append({'date': day, 'reason': 'November or December close outside partition'})
                return
            returns[s] = last / prev - 1
        iwm, spy = returns['IWM'], returns['SPY']
        qualifies = iwm < 0 and iwm < spy
        entry = self.params['next_session'][day]
        exit_open = self._session_offset(entry, int(self.params['variant']))
        record = {'date': day, 'kind': 'december_qualifier', 'year': year,
                  'iwm_december_return': str(iwm), 'spy_december_return': str(spy),
                  'qualifies': qualifies, 'entry_open': entry, 'exit_open': exit_open}
        if qualifies and exit_open is not None:
            equity = ctx.marked_equity()
            if equity is None or not equity.is_finite() or equity <= 0:
                raise ValueError('positive decision equity required')
            budget = min(D('.95') * equity, D(self.params['slot_usd']))
            self.reserve = D('.05') * equity
            self.targets = {s: ZERO for s in SYMBOLS}
            self.targets['IWM'] = budget
            self.pending = {'IWM'}
            self.reasons['IWM'] = 'January small-cap entry'
            self.entry_open, self.exit_open, self.active_year = entry, exit_open, year
            record.update(equity=str(equity), reserve=str(self.reserve), budget=str(budget))
        else:
            record['reason_no_entry'] = 'not qualified' if not qualifies else 'exit open outside session map'
        self.decisions.append(record)

    def _session_offset(self, start, steps):
        day = start
        for _ in range(steps):
            day = self.params['next_session'].get(day)
            if day is None:
                return None
        return day

    def _allocate_buys(self, ctx, day):
        # Clip full owned-plus-added notional at the adverse buy limit to the
        # frozen target and the $140 slot.
        result = {}
        for symbol, (dollars, complete) in super()._allocate_buys(ctx, day).items():
            iid = self.ids[symbol]
            ask = ctx.snapshot(iid).ask
            capacity = max(ZERO, min(self.targets[symbol], D(self.params['slot_usd'])) / ask - ctx.position(iid))
            capacity = capacity.quantize(D(self.params['quantity_step']), rounding=ROUND_FLOOR) * ask
            result[symbol] = min(dollars, capacity), complete or capacity < dollars
            if capacity < dollars:
                self.skips.append({'date': day, 'symbol': symbol,
                                   'reason': 'buy clipped at adverse-price full target/slot cap'})
        return result

    def _order(self, snapshot, iid, size, side, day, reason):
        if size <= 0:
            return []
        tag = f'c20:{day}:{iid}:{side}'
        if tag in self.attempted:
            raise ValueError('duplicate same-session order')
        self.attempted.add(tag)
        price = snapshot.ask if side == 'buy' else snapshot.bid
        if price is None or price <= 0:
            raise ValueError('execution price unavailable')
        if size * price < 1:
            self.skips.append({'date': day, 'instrument_id': iid, 'reason': 'order under $1'})
            return []
        return [PlaceOrder(instrument_id=iid, side=side, size=size, limit_price=price,
                           intended_liquidity='taker', tag=tag, reason='C20 ' + reason)]
