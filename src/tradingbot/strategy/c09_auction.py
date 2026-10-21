"""C09 dated auction recovery with fixed exits and settled-cash entry delays."""
from decimal import Decimal as D, ROUND_FLOOR
from zoneinfo import ZoneInfo

from .interface import PlaceOrder, Strategy

NY = ZoneInfo('America/New_York')


class AuctionRecovery(Strategy):
    key = 'sweep_c09_auction_total_return_v1'

    def on_start(self, ctx):
        self.windows = {}
        for window in self.params['windows']:
            self.windows.setdefault(window['decision'], []).append(window)
        self.pending, self.active_exit, self.active_id = None, None, None
        self.decisions, self.skips, self.attempted = [], [], set()

    def on_event(self, ctx, event):
        iid = self.params['instrument_id']
        if event.instrument_id != iid: return []
        day, phase = event.time.astimezone(NY).date().isoformat(), event.meta.get('phase')
        quantity = ctx.position(iid)
        if phase == 'close':
            for window in self.windows.get(day, []):
                key = window['id']+':decision'
                if key in self.attempted: continue
                self.attempted.add(key)
                if window['id'] not in event.meta.get('admitted_windows', []):
                    self.skips.append({'id':window['id'],'date':day,'reason':'round trip outside partition'})
                    continue
                if quantity or self.pending is not None:
                    self.skips.append({'id':window['id'],'date':day,'reason':'overlap while invested or pending'})
                    continue
                equity = ctx.marked_equity()
                if equity is None or not equity.is_finite() or equity <= 0:
                    raise ValueError('positive completed-close equity required')
                target, reserve = min(D('.95')*equity,D(self.params['slot_usd'])),D('.05')*equity
                self.pending = {'window':window,'target':target,'reserve':reserve}
                self.active_exit, self.active_id = window['exit'],window['id']
                self.decisions.append({**window,'decision_equity':str(equity),
                    'frozen_target_usd':str(target),'frozen_reserve_usd':str(reserve)})
            return []
        if phase != 'open': return []
        snapshot = ctx.snapshot(iid)
        if snapshot is None: return []
        terminal = event.meta.get('terminal_open',False)
        if quantity and (day == self.active_exit or terminal):
            self.pending = None
            return self._order(snapshot,iid,quantity,'sell',day,'terminal liquidation' if terminal else 'fixed auction exit')
        if self.pending is None: return []
        pending, window = self.pending,self.pending['window']
        if terminal or day >= window['exit']:
            self.skips.append({'id':window['id'],'date':day,'reason':'entry canceled at original exit or terminal'})
            self.pending = None
            return []
        if quantity or day < window['entry']: return []
        if snapshot.ask is None or snapshot.ask <= 0: raise ValueError('entry price unavailable')
        cash = ctx.available_cash(iid)
        if cash is None or not cash.is_finite(): raise ValueError('settled cash required')
        dollars = min(pending['target'],D(self.params['slot_usd']),max(D(0),cash-pending['reserve']-D('.01')))
        size = (dollars/snapshot.ask).quantize(D('.000000001'),rounding=ROUND_FLOOR)
        if size*snapshot.ask < 1:
            self.skips.append({'id':window['id'],'date':day,'reason':'cash delay: below $1 after reserve/fee'})
            return []
        if day != window['entry']:
            self.skips.append({'id':window['id'],'date':day,'reason':'late entry; original exit retained',
                               'planned_entry':window['entry'],'fixed_exit':window['exit']})
        self.pending = None
        return self._order(snapshot,iid,size,'buy',day,'frozen auction target')

    def _order(self,snapshot,iid,size,side,day,reason):
        tag=f'c09:{day}:{iid}:{side}'
        if tag in self.attempted: return []
        self.attempted.add(tag)
        price=snapshot.ask if side=='buy' else snapshot.bid
        if price is None or price<=0: raise ValueError('scenario execution price unavailable')
        return [PlaceOrder(instrument_id=iid,side=side,size=size,limit_price=price,
            intended_liquidity='taker',tag=tag,reason='C09 '+reason)]
