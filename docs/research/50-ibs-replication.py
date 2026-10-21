"""Independent replication of IBS QQQ v1 (`tradingbot-3xw`).

Written from the pre-registration (50-ibs-mean-reversion-plan.md) and the frozen
source only; it does not import strategy/ibs.py, the backtester, the ledger or
the risk engine. Read-only: no database, no trial, no new holdout decision.

    uv run python docs/research/50-ibs-replication.py replay [QQQ|SPY]
        Re-run the rule and compare trades/P&L with the stored train/final artifacts.
    uv run python docs/research/50-ibs-replication.py sources [QQQ|SPY]
        Compare IBS crossings from the frozen Yahoo OHLC with Alpaca SIP and IEX
        daily bars (paper key from .env; read-only market data).
"""
from datetime import datetime, timezone
from decimal import Decimal as D, ROUND_CEILING, ROUND_FLOOR
import hashlib
import json
from pathlib import Path
import sys
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
ART = ROOT/'data/research/ibs-mean-reversion'
SPLIT = datetime(2020, 7, 10, 14, 24, tzinfo=timezone.utc)
CENT, NANO, SLOT, BP = D('.01'), D('.000000001'), D(140), D(10)/10000


def ibs(high, low, close):
    return None if high == low else (close-low)/(high-low)


def quote_ibs(q):
    return ibs(D(q['high']), D(q['low']), D(q['close']))


def crosses(series):
    """{day: 'under'|'over'} for WealthLab CrossesUnder(0.10)/CrossesOver(0.90)."""
    events, prev = {}, None
    for day, value in series:
        if value is not None and prev is not None:
            if prev >= D('.10') and value < D('.10'):
                events[day] = 'under'
            elif prev <= D('.90') and value > D('.90'):
                events[day] = 'over'
        if value is not None:
            prev = value
    return events


def fill_price(q, side):
    raw = D(q['raw_open'])
    if side == 'buy':
        px = (raw*(1+BP)).quantize(CENT, rounding=ROUND_CEILING)
    else:
        px = (raw*(1-BP)).quantize(CENT, rounding=ROUND_FLOOR)
    return px*D(q['factor'])  # total-return-equivalent units


class Fees:
    """Alpaca 2026-09-17 schedule: each kind rounded up to the cent per day."""
    def __init__(self): self.totals = {}

    def charge(self, day, side, price, size, factor):
        shares = size*factor  # raw-share equivalent
        raw = {'cat': shares*D('.000003'), 'sec': D(0), 'taf': D(0)}
        if side == 'sell':
            raw['sec'] = price*size*D('.0000206')
            raw['taf'] = min(shares*D('.000195'), D('9.79'))
        fee = D(0)
        for kind, amount in raw.items():
            before = self.totals.get((day, kind), D(0))
            self.totals[(day, kind)] = before+amount
            fee += (before+amount).quantize(CENT, rounding=ROUND_CEILING)-before.quantize(CENT, rounding=ROUND_CEILING)
        return fee


def replay(rows, holdout):
    def inside(stamp):
        t = datetime.fromisoformat(stamp)
        return t >= SPLIT if holdout else t < SPLIT
    opens = [r for r in rows if inside(r['opens_at'])]
    terminal = opens[-1]['opens_at']
    cash, unsettled, size = SLOT, [], D(0)  # unsettled: [(release_iso, amount)]
    prev, want, pending = None, False, None
    fees, trades, skips, entry = Fees(), [], [], None
    for r in rows:
        q, day = r['quote'], r['date']
        if inside(r['opens_at']):
            now = datetime.fromisoformat(r['opens_at'])
            cash += sum((a for t, a in unsettled if datetime.fromisoformat(t) <= now), D(0))
            unsettled = [(t, a) for t, a in unsettled if datetime.fromisoformat(t) > now]
            last = r['opens_at'] == terminal
            if size and (not want or last):
                px = fill_price(q, 'sell')
                fee = fees.charge(day, 'sell', px, size, D(q['factor']))
                proceeds = px*size-fee
                unsettled.append((r['conservative_cash_release'], proceeds))
                entry.update(exit=now, net=proceeds-entry['cost'], gross=(px-entry['entry_px'])*size)
                trades.append(entry)
                size, entry = D(0), None
            elif want and not size and pending and not last:
                target, reserve = pending
                ask = fill_price(q, 'buy')
                budget = min(target, max(D(0), cash-reserve-CENT))
                qty = (budget/ask).quantize(NANO, rounding=ROUND_FLOOR)
                if qty*ask < 1:
                    skips.append(day)
                else:
                    fee = fees.charge(day, 'buy', ask, qty, D(q['factor']))
                    cash -= ask*qty+fee
                    size, pending = qty, None
                    entry = {'entry': now, 'entry_px': ask, 'size': qty, 'cost': ask*qty+fee}
        if inside(r['closes_at']):
            cur = quote_ibs(q)
            if cur is not None and prev is not None:
                if not want and prev >= D('.10') and cur < D('.10'):
                    equity = cash+sum((a for _, a in unsettled), D(0))+size*D(q['close'])
                    want, pending = True, (min(D('.95')*equity, SLOT), D('.05')*equity)
                elif want and prev <= D('.90') and cur > D('.90'):
                    want, pending = False, None
            if cur is not None:
                prev = cur
    end = cash+sum((a for _, a in unsettled), D(0))
    return trades, skips, end-SLOT


def load(symbol):
    raw = (ART/'source.json').read_bytes()
    rows = json.loads(raw)['panels'][symbol]['prices']
    zero = sum(1 for r in rows if quote_ibs(r['quote']) is None)
    print(f'{symbol}: source sha256 {hashlib.sha256(raw).hexdigest()[:16]}, {len(rows)} sessions, {zero} zero-range bars')
    return rows


def compare_replay(symbol):
    rows = load(symbol)
    for name, holdout in (('train', False), ('final', True)):
        stored = json.loads((ART/f'{name}-{symbol}.json').read_text())
        if 'trades' not in stored:
            print(f'  {name}: no stored outcome ({stored.get("status")})')
            continue
        trades, skips, net = replay(rows, holdout)
        ours = [(t['entry'], t['exit']) for t in trades]
        theirs = [(datetime.fromisoformat(t['entry']), datetime.fromisoformat(t['exit'])) for t in stored['trades']]
        diffs = [abs(a['net']-D(b['net_usd'])) for a, b in zip(trades, stored['trades'])]
        stored_skips = [s['time'][:10] if isinstance(s, dict) else s for s in stored['metrics']['skips']]
        print(f'  {name}: ours {len(trades)} trades, net {net:.4f}, win {sum(t["net"] > 0 for t in trades)/len(trades):.1%},'
              f' skips {skips} | stored {len(theirs)} trades, net {D(stored["metrics"]["net_usd"]):.4f}, skips {stored_skips}')
        print(f'    identical entry/exit times: {ours == theirs}; only ours {len(set(ours)-set(theirs))},'
              f' only stored {len(set(theirs)-set(ours))}; max per-trade net diff {max(diffs):.4f}')


def alpaca_daily(symbol, feed, start, end='2026-10-01'):
    from dotenv import dotenv_values
    env = dotenv_values(ROOT/'.env')
    headers = {'APCA-API-KEY-ID': env['ALPACA_PAPER_KEY'], 'APCA-API-SECRET-KEY': env['ALPACA_PAPER_SECRET']}
    out, token = {}, None
    while True:
        params = {'symbols': symbol, 'timeframe': '1Day', 'start': start, 'end': end, 'feed': feed,
                  'adjustment': 'raw', 'limit': 10000} | ({'page_token': token} if token else {})
        url = 'https://data.alpaca.markets/v2/stocks/bars?'+urllib.parse.urlencode(params)
        page = json.load(urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60))
        for b in page['bars'].get(symbol, []):
            out[b['t'][:10]] = ibs(D(str(b['h'])), D(str(b['l'])), D(str(b['c'])))
        token = page.get('next_page_token')
        if not token:
            return out


def compare_sources(symbol):
    rows = load(symbol)
    # IEX history on Alpaca starts in August 2020; SIP from 2016.
    for feed, start in (('sip', '2016-01-01'), ('sip', '2022-01-01'), ('iex', '2020-09-01')):
        ref = [(r['date'], quote_ibs(r['quote'])) for r in rows if r['date'] >= start]
        other = alpaca_daily(symbol, feed, start)
        alt = [(day, other.get(day)) for day, _ in ref]
        big = sum(1 for (_, x), (_, y) in zip(ref, alt) if x is not None and y is not None and abs(x-y) > D('.02'))
        e_ref, e_alt = crosses(ref), crosses(alt)
        same = sum(1 for day, kind in e_ref.items() if e_alt.get(day) == kind)
        u_ref = {d for d, k in e_ref.items() if k == 'under'}
        u_alt = {d for d, k in e_alt.items() if k == 'under'}
        print(f'  {feed} from {start}: {len(ref)} sessions, missing {sum(v is None for _, v in alt)},'
              f' IBS |diff|>0.02 on {big}; crosses {len(e_ref)} vs {len(e_alt)}, identical {same};'
              f' entry crosses {len(u_ref)} vs {len(u_alt)}, shared {len(u_ref & u_alt)}')


if __name__ == '__main__':
    mode, symbol = (sys.argv[1:] + ['replay', 'QQQ'][len(sys.argv)-1:])[:2]
    {'replay': compare_replay, 'sources': compare_sources}[mode](symbol)
