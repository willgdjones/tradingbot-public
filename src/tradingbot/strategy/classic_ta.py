"""Causal long/flat adaptations of je-suis-tm/quant-trading (Apache-2.0).

Upstream commit 611b73f2c3f577ac5b28aaa19ac8c43d3236c7a5; attribution,
original files and license: docs/research/classic-ta-sources/. Modified here:
streaming Decimal calculations, explicit warmup, long/flat projection, shared
strategy interface, settled-cash sizing and next-open execution.
"""
from decimal import Decimal as D, ROUND_FLOOR
from statistics import stdev

from .interface import PlaceOrder, Strategy

RULES = ('bollinger', 'rsi', 'sar', 'heikin_ashi', 'awesome')


class Signal:
    """Consume completed adjusted OHLC bars; return desired tranche count."""

    def __init__(self, rule):
        if rule not in RULES:
            raise ValueError('rule has no admitted upstream long default')
        self.rule, self.bars, self.units = rule, [], 0
        self.ha, self.bands = [], []

    def update(self, bar):
        b = {k: D(str(bar[k])) for k in ('open', 'high', 'low', 'close')}
        if (any(not v.is_finite() or v <= 0 for v in b.values())
                or b['low'] > min(b['open'], b['close'])
                or b['high'] < max(b['open'], b['close'])):
            raise ValueError('invalid completed OHLC')
        self.bars.append(b)
        i = len(self.bars)-1
        c = b['close']
        if self.rule == 'rsi' and i:
            change = c-self.bars[-2]['close']
            up, down = max(change, D(0)), max(-change, D(0))
            if i == 1:
                self.up, self.down = up, down
            else:
                self.up, self.down = (self.up*13+up)/14, (self.down*13+down)/14
            # A constant series yields no oversold signal; positive/zero loss = 100.
            self.units = int(i >= 14 and self.down > 0
                             and 100-100/(1+self.up/self.down) < 30)
        elif self.rule == 'awesome' and i >= 33:
            mids = [(r['high']+r['low'])/2 for r in self.bars[-34:]]
            diff = sum(mids[-5:])/5-sum(mids)/34
            # Both saucers are overwritten by the later nonzero MA comparison.
            if diff:
                self.units = int(diff > 0)
        elif self.rule == 'heikin_ashi':
            ho = b['open'] if not self.ha else (self.ha[-1][0]+self.ha[-1][1])/2
            hc = sum(b.values())/4
            hh, hl = max(ho, hc, b['high']), min(ho, hc, b['low'])
            if self.ha:
                po, pc = self.ha[-1]
                if ho > hc and ho == hh and abs(ho-hc) > abs(po-pc) and po > pc:
                    self.units = min(3, self.units+1)
                elif ho < hc and ho == hl and po < pc:
                    self.units = 0
            self.ha.append((ho, hc))
        elif self.rule == 'sar':
            if i == 1:
                self.trend = 1 if c > self.bars[0]['close'] else -1
                self.sar = self.bars[0]['high' if self.trend > 0 else 'low']
                self.ep = b['high' if self.trend > 0 else 'low']
                self.af, real = D('.02'), self.sar
                self.units = int(real < c)
            elif i >= 2:
                value = self.sar+self.af*(self.ep-self.sar)
                if self.trend < 0:
                    self.sar = max(value, self.bars[-2]['high'], self.bars[-3]['high'])
                    trend = 1 if self.sar < b['high'] else self.trend-1
                else:
                    self.sar = min(value, self.bars[-2]['low'], self.bars[-3]['low'])
                    trend = -1 if self.sar > b['low'] else self.trend+1
                ep = ((b['low'] if trend == -1 else min(b['low'], self.ep)) if trend < 0
                      else (b['high'] if trend == 1 else max(b['high'], self.ep)))
                if abs(trend) == 1:
                    real, self.af = self.ep, D('.02')
                else:
                    real = self.sar
                    if ep != self.ep:
                        self.af = min(D('.2'), self.af+D('.02'))
                self.trend, self.ep = trend, ep
                self.units = int(real < c)
        elif self.rule == 'bollinger':
            closes = [r['close'] for r in self.bars[-20:]]
            if i < 19:
                self.bands.append(None)
            else:
                mid, sd = sum(closes)/20, stdev(closes)
                self.bands.append((mid, mid+2*sd, mid-2*sd, sd))
                if i >= 75:
                    entered = False
                    if c > self.bands[i][1] and not self.units:
                        js = [j for j in range(i, i-75, -1) if self.bands[j]
                              and abs(self.bands[j][0]-self.bars[j]['close']) < D('.0001')
                              and abs(self.bands[j][0]-self.bands[i][1]) < D('.0001')]
                        if js:
                            j = js[0]
                            ks = [k for k in range(j, i-75, -1) if self.bands[k]
                                  and abs(self.bands[k][2]-self.bars[k]['close']) < D('.0001')]
                            if ks:
                                k = ks[0]
                                ls = [l for l in range(k, i-75, -1) if self.bands[l]
                                      and self.bands[l][0] < self.bars[l]['close']]
                                if ls:
                                    entered = any(self.bands[m] and
                                        0 < self.bars[m]['close']-self.bands[m][2] < D('.0001')
                                        and self.bars[m]['close'] < self.bars[k]['close']
                                        for m in range(i, j, -1))
                    if entered:
                        self.units = 1
                    elif self.units and sd < D('.0001'):
                        self.units = 0
        return self.units


class ClassicTA(Strategy):
    key = 'classic_ta'

    def __init__(self, params):
        super().__init__(params)
        # Each preregistered rule is its own family; tickers share that family.
        # The durable guard binds the reactor key immutably to one family.
        self.key = 'classic_ta_'+params['rule']

    def on_start(self, ctx):
        self.signal = Signal(self.params['rule'])
        self.units, self.pending = 0, None
        self.decisions, self.skips = [], []

    def on_event(self, ctx, event):
        iid = self.params['instrument_id']
        if event.instrument_id != iid:
            return []
        phase = event.meta.get('phase')
        if phase == 'close':
            wanted = self.signal.update(event.meta['ohlc'])
            if wanted != self.units:
                equity = ctx.marked_equity()
                self.pending = (min(D('.95')*equity, D(140)) * wanted /
                                (3 if self.params['rule'] == 'heikin_ashi' else 1), D('.05')*equity)
                self.units = wanted
                self.decisions.append({'time': event.time.isoformat(), 'units': wanted})
            return []
        if phase != 'open':
            return []
        position, snap = ctx.position(iid), ctx.snapshot(iid)
        terminal = event.meta.get('terminal_open', False)
        if snap is None or snap.bid is None or snap.ask is None or min(snap.bid, snap.ask) <= 0:
            return []
        if position > 0 and (terminal or self.units == 0):
            return [PlaceOrder(instrument_id=iid, side='sell', size=position,
                limit_price=snap.bid, intended_liquidity='taker',
                tag='classic:sell:'+event.time.isoformat(), reason='terminal liquidation' if terminal else 'TA exit')]
        if terminal or not self.units or self.pending is None:
            return []
        target, reserve = self.pending
        cash = ctx.available_cash(iid)
        if cash is None:
            raise ValueError('settled cash required')
        budget = min(max(D(0), target-position*snap.ask), max(D(0), cash-reserve-D('.01')))
        size = (budget/snap.ask).quantize(D('.000000001'), rounding=ROUND_FLOOR)
        if size*snap.ask < 1:
            self.skips.append({'time': event.time.isoformat(), 'reason': 'cash/target below $1'})
            return []
        self.pending = None
        return [PlaceOrder(instrument_id=iid, side='buy', size=size, limit_price=snap.ask,
            intended_liquidity='taker', tag='classic:buy:'+event.time.isoformat(), reason='prior close TA target')]
