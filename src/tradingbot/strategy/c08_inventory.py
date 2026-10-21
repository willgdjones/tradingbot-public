"""C08 dated inventory reactor; pure decisions over already available evidence."""
from datetime import date, datetime, timedelta
from decimal import Decimal as D, ROUND_CEILING, ROUND_FLOOR
from zoneinfo import ZoneInfo

from .interface import PlaceOrder, Strategy

NY = ZoneInfo('America/New_York')


class InventoryScarcity(Strategy):
    key = 'sweep_c08_inventory_blackout_v1'

    def on_start(self, ctx):
        self.latest = None
        self.pending = None
        self.decisions, self.skips = [], []
        self.attempted = set()
        self.blackout_decisions = set()
        self.after_forced_exit = False

    def on_event(self, ctx, event):
        iid = self.params['uso_id']
        if event.instrument_id != iid:
            return []
        day = event.time.astimezone(NY).date()
        phase = event.meta.get('phase')
        quantity = ctx.position(iid)
        blocked = [p for p in self.params['blackouts']
                   if date.fromisoformat(p['exit']) <= day < date.fromisoformat(p['reentry'])]
        if phase == 'close':
            if blocked and quantity:
                raise ValueError('C08 forced exit failed; cannot hold across unresolved action')
            for plan in self.params['blackouts']:
                if str(day) == plan['decision']:
                    self.blackout_decisions.add(plan['exit'])
            return []
        if phase != 'open':
            return []
        snapshot = ctx.snapshot(iid)
        if snapshot is None:
            raise ValueError('C08 execution reference unavailable')
        for report in sorted(event.meta.get('releases', []), key=lambda r: (r['observation_date'], r['release_date'])):
            release = date.fromisoformat(report['release_date'])
            observation = date.fromisoformat(report['observation_date'])
            if (observation >= release or release >= day
                    or datetime.fromisoformat(report['available_at']) > event.time):
                raise ValueError('C08 report is not available before execution')
            current, year_ago = D(report['commercial_current']), D(report['commercial_year_ago'])
            if any(not n.is_finite() or n <= 0 for n in (current, year_ago)):
                raise ValueError('C08 invalid inventory level or denominator')
            if self.latest and observation <= date.fromisoformat(self.latest['observation_date']):
                self.skips.append({'date': str(day), 'reason': 'older or duplicate observation cannot replace latest publication',
                                   'release_key': report['key']})
                continue
            self.latest = {**report, 'scarcity': str(current / year_ago - 1)}
            self.decisions.append({'date': str(day), **self.latest,
                                   'qualified': D(self.latest['scarcity']) < D(self.params['threshold'])})
        terminal = event.meta.get('terminal_open', False)
        stale = self.latest is None or day > date.fromisoformat(self.latest['release_date']) + timedelta(days=14)
        wants_long = not stale and D(self.latest['scarcity']) < D(self.params['threshold'])
        forced = bool(blocked) and str(day) == blocked[0]['exit']
        if quantity and blocked and (not forced or str(day) not in self.blackout_decisions):
            raise ValueError('C08 held position without causal blackout exit decision')
        if terminal or blocked or not wants_long:
            self.pending = None
            if not blocked and not wants_long:
                self.after_forced_exit = False
            if quantity <= 0:
                return []
            reason = ('C08 terminal liquidation' if terminal else 'C08 forced blackout exit' if forced
                      else 'C08 stale inventory exit' if stale else 'C08 inventory cash signal')
            if forced:
                self.after_forced_exit = True
            return self._sell(snapshot, iid, quantity, day, reason)
        if quantity > 0:
            self.pending = None
            self.after_forced_exit = False
            return []  # Unchanged long state never resizes weekly.
        if self.pending is None:
            equity = ctx.marked_equity()
            if equity is None or not equity.is_finite() or equity <= 0:
                raise ValueError('C08 requires positive decision-time marked equity')
            weight = D(self.params['target_weight'])
            self.pending = {'target': min(weight * equity, D(self.params['slot_usd'])),
                            'reserve': (1 - weight) * equity, 'decision_equity': equity,
                            'decision_date': str(day), 'release_key': self.latest['key']}
        cash = ctx.available_cash(iid)
        if cash is None or not cash.is_finite():
            raise ValueError('C08 settled-cash evidence is unavailable')
        dollars = min(self.pending['target'], max(D(0), cash - self.pending['reserve'] - D(self.params['buy_fee_reserve_usd'])))
        if dollars < 1:
            self.skips.append({'date': str(day), 'reason': 'cash delay or under $1 after frozen reserve',
                               'frozen_target': str(self.pending['target'])})
            return []
        if snapshot.ask is None or snapshot.ask <= 0:
            raise ValueError('C08 buy price unavailable')
        limit = snapshot.ask.quantize(D('.01'), rounding=ROUND_CEILING)
        size = (dollars / limit).quantize(D(self.params['quantity_step']), rounding=ROUND_FLOOR)
        if size * snapshot.ask < 1:
            self.skips.append({'date': str(day), 'reason': 'floored order under $1'})
            return []
        tag = 'c08:' + str(day) + ':buy'
        if tag in self.attempted:
            return []
        self.attempted.add(tag)
        reason = 'C08 blackout reentry' if self.after_forced_exit else 'C08 inventory scarcity entry'
        return [PlaceOrder(instrument_id=iid, side='buy', size=size, limit_price=limit,
                           intended_liquidity='taker', tag=tag, reason=reason)]

    def _sell(self, snapshot, iid, quantity, day, reason):
        if snapshot.bid is None or snapshot.bid <= 0:
            raise ValueError('C08 sell price unavailable')
        tag = 'c08:' + str(day) + ':sell'
        if tag in self.attempted:
            return []
        self.attempted.add(tag)
        return [PlaceOrder(instrument_id=iid, side='sell', size=quantity,
                           limit_price=snapshot.bid.quantize(D('.01'), rounding=ROUND_FLOOR),
                           intended_liquidity='taker', tag=tag, reason=reason)]

    def on_finish(self, ctx):
        pass
