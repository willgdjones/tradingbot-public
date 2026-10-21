"""Gotobi-day USD/JPY research (tradingbot-z1t): frozen source, training, one final.

Research only; no venue. Frozen design: docs/research/51-gotobi-plan.md. The
source phase captures and cross-checks prices without splitting days by gotobi
status. Training reads only trades wholly inside the first 70%; the final claims
the family holdout through ``claim_final`` before any holdout trade is built.
"""
from __future__ import annotations

import argparse
import calendar
import csv
from datetime import UTC, date, datetime, time as clock, timedelta, timezone
from decimal import Decimal as D
import gzip
import io
import json
import math
import re
import subprocess
import time
import zipfile
from zoneinfo import ZoneInfo

import requests
from sqlalchemy import select

from tradingbot.backtest.holdout import HoldoutSplit, claim_final, json_value, register_split
from tradingbot.data.disk_budget import CaptureDiskBudget
from tradingbot.db.models import Strategy as StrategyRow, Trial
from tradingbot.db.session import session_scope
from tradingbot.ledger.stats import luck_probability, max_drawdown, student_t_sf
from tradingbot.research.c06_month_end import monthly_luck
from tradingbot.research.total_return_data import ROOT, sha

ARCHIVE = ROOT/'data/research/gotobi'
PLAN = ROOT/'docs/research/51-gotobi-plan.md'
PAIRS = ('USDJPY', 'EURJPY')
START, END = datetime(2016, 1, 1, tzinfo=UTC), datetime(2026, 10, 1, tzinfo=UTC)
JST = timezone(timedelta(hours=9))
NEW_YORK = ZoneInfo('America/New_York')
ANCHORS = ('03:00', '09:00', '09:55', '12:00')
WINDOWS = {
    'open_fix': {'direction': 1, 'entry': '09:00', 'exit': '09:55', 'weekdays': (0, 1, 2, 3, 4), 'condition': None},
    'early_fix': {'direction': 1, 'entry': '03:00', 'exit': '09:55', 'weekdays': (1, 2, 3, 4), 'condition': None},
    # Bessho et al. H2: fade only after a positive 03:00 -> 09:00 drift.
    'post_fix_fade': {'direction': -1, 'entry': '09:55', 'exit': '12:00', 'weekdays': (1, 2, 3, 4),
                      'condition': ('03:00', '09:00')},
}
COST_BP, SLOT, TOLERANCE_BP, ANCHOR_MINUTES = 3.0, 140, 5.0, 5
BANK_HOLIDAYS = {(12, 31), (1, 2), (1, 3)}
REGIMES = (('2016-2019', 2016, 2019), ('2020-2021', 2020, 2021), ('2022', 2022, 2022), ('2023-2026', 2023, 2026))
FXCM = 'https://candledata.fxcorporate.com/m1/{pair}/{year}/{week}.csv.gz'
HISTDATA = 'https://www.histdata.com/download-free-forex-historical-data/?/ascii/1-minute-bar-quotes/{pair}/{spec}'
CAO = 'https://www8.cao.go.jp/chosei/shukujitsu/syukujitsu.csv'
USER_AGENT = 'Mozilla/5.0 (research; read-only FX minute bars)'
CODE_VERSION = 'gotobi-v1'


# ---- calendar -------------------------------------------------------------

def jp_holidays(raw):
    rows = csv.reader(io.StringIO(raw.decode('shift_jis')))
    next(rows)
    return {datetime.strptime(r[0], '%Y/%m/%d').date() for r in rows if r}


def business_day(day, holidays):
    return day.weekday() < 5 and day not in holidays and (day.month, day.day) not in BANK_HOLIDAYS


def gotobi_days(first, last, holidays):
    """Map each gotobi business day in [first, last] to the targets rolled onto it."""
    days, year, month = {}, first.year, first.month
    while date(year, month, 1) <= last+timedelta(days=40):
        end = calendar.monthrange(year, month)[1]
        targets = {d: [] for d in (5, 10, 15, 20, 25, 30) if d <= end}
        targets.setdefault(end, []).append('month_end')
        for d, labels in targets.items():
            if d % 5 == 0:
                labels.append('five')
            day = date(year, month, d)
            while not business_day(day, holidays):
                day -= timedelta(days=1)
            if first <= day <= last:
                days.setdefault(day, set()).update(labels)
        year, month = (year+1, 1) if month == 12 else (year, month+1)
    return {d: sorted(v) for d, v in sorted(days.items())}


def anchor_utc(day, hhmm):
    return datetime.combine(day, clock.fromisoformat(hhmm), JST).astimezone(UTC)


def needed_minutes():
    """UTC (hour, minute) keys inside every [anchor, anchor + 5 min) window."""
    keys = set()
    for hhmm in ANCHORS:
        base = anchor_utc(date(2020, 1, 1), hhmm)
        keys.update(((base+timedelta(minutes=k)).hour, (base+timedelta(minutes=k)).minute)
                    for k in range(ANCHOR_MINUTES))
    return keys


def pick_anchor(bars, at):
    """Open of the first bar starting in [at, at + 5 min); non-positive first bar -> invalid.

    Amendment B: a crossed quote (ask < bid) stays valid and is flagged; its mid
    is used and the quoted-cost diagnostic fills it at mid.
    """
    for k in range(ANCHOR_MINUTES):
        stamp = at+timedelta(minutes=k)
        if stamp in bars:
            quote = bars[stamp]
            if not all(v > 0 for v in quote):
                return 'invalid'
            out = {'bar': stamp.isoformat(), 'quote': list(quote)}
            if len(quote) == 2 and quote[1] < quote[0]:
                out['crossed'] = True
            return out
    return None


def fill(anchor, side):
    """Quoted-cost fill price: the bid or ask, or the mid of a crossed quote."""
    bid, ask = anchor['quote']
    return (bid+ask)/2 if ask < bid else {'bid': bid, 'ask': ask}[side]


# ---- capture ---------------------------------------------------------------

def http():
    s = requests.Session()
    s.headers['User-Agent'] = USER_AGENT
    return s


def fetch(session, method, url, **kwargs):
    for wait in (5, 15, 45, None):
        response = session.request(method, url, timeout=120, **kwargs)
        if response.status_code in (200, 404):
            return response
        if wait is None:
            response.raise_for_status()
        time.sleep(wait)


def save(path, raw):
    with CaptureDiskBudget(ROOT/'data').reserve(3*len(raw)+65536):
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix+'.part')
        tmp.write_bytes(raw)
        tmp.replace(path)


def capture():
    s, missing = http(), []
    path = ARCHIVE/'cao-syukujitsu.csv'
    if not path.exists():
        save(path, fetch(s, 'GET', CAO).content)
    for pair in PAIRS:
        for year in range(START.year, END.year+1):
            for week in range(1, 54):
                path = ARCHIVE/'fxcm'/pair/f'{year}-{week:02d}.csv.gz'
                if path.exists():
                    continue
                response = fetch(s, 'GET', FXCM.format(pair=pair, year=year, week=week))
                if response.status_code == 404:
                    missing.append(f'{pair}/{year}/{week}')
                    continue
                gzip.decompress(response.content)  # Refuse a truncated archive.
                save(path, response.content)
                time.sleep(0.2)
        specs = [str(y) for y in range(START.year, END.year)]+[f'{END.year}/{m}' for m in range(1, END.month)]
        for spec in specs:
            path = ARCHIVE/'histdata'/pair/(spec.replace('/', '-')+'.zip')
            if path.exists():
                continue
            page = HISTDATA.format(pair=pair.lower(), spec=spec)
            html = fetch(s, 'GET', page).text
            form = html[html.index('id="file_down"'):]
            fields = dict(re.findall(r'name="([^"]+)" id="[^"]+" value="([^"]*)"', form[:form.index('</form>')]))
            raw = fetch(s, 'POST', 'https://www.histdata.com/get.php', data=fields, headers={'Referer': page}).content
            if not any(n.endswith('.csv') for n in zipfile.ZipFile(io.BytesIO(raw)).namelist()):
                raise ValueError('HistData archive without CSV: '+spec)
            save(path, raw)
            time.sleep(1)
    print(json.dumps({'fxcm_not_found': missing}), flush=True)
    return missing


def weekly_open(day):
    """The FX week opens on Sunday at 17:00 New York time; returned as naive UTC."""
    return datetime.combine(day, clock(17), NEW_YORK).astimezone(UTC).replace(tzinfo=None)


def fxcm_bars(pair, keys):
    """FXCM bid/ask opens at anchor minutes, plus a check of each week's UTC open."""
    bars, opens = {}, {'weeks': 0, 'late_or_early': []}
    for path in sorted((ARCHIVE/'fxcm'/pair).glob('*.csv.gz')):
        rows = csv.reader(io.StringIO(gzip.decompress(path.read_bytes()).decode()))
        next(rows)
        for i, r in enumerate(rows):
            if i == 0:
                first = datetime.strptime(r[0][:16], '%m/%d/%Y %H:%M')
                opens['weeks'] += 1
                if not timedelta(0) <= first-weekly_open(first.date()) <= timedelta(minutes=15):
                    opens['late_or_early'].append(f'{path.name}: {first.isoformat()}')
            if (int(r[0][11:13]), int(r[0][14:16])) in keys:
                bars[datetime.strptime(r[0][:16], '%m/%d/%Y %H:%M').replace(tzinfo=UTC)] = (float(r[1]), float(r[5]))
    return bars, opens


def histdata_bars(pair, keys):
    """HistData bid opens at anchor minutes, re-timed to UTC week by week.

    Amendment A2: the documented fixed EST is wrong. The stamps follow New York
    DST until 2018 and EU DST dates from 2019, so each week's UTC offset (4 or 5
    hours) is read from its first bar against the Sunday 17:00 New York open. A
    week whose first bar does not fit falls back to New York local time (counted).
    """
    bars, offsets, previous, offset = {}, {}, None, None
    for path in sorted((ARCHIVE/'histdata'/pair).glob('*.zip')):
        z = zipfile.ZipFile(path)
        for line in z.read(next(n for n in z.namelist() if n.endswith('.csv'))).decode().splitlines():
            local = datetime(int(line[:4]), int(line[4:6]), int(line[6:8]), int(line[9:11]), int(line[11:13]))
            # A week opens on a Sunday bar after a gap; mid-week outages keep the offset.
            if previous is None or (local-previous > timedelta(hours=24) and local.weekday() == 6):
                hours = (weekly_open(local.date())-local)/timedelta(hours=1)
                offset = round(hours) if round(hours) in (4, 5) and abs(hours-round(hours)) <= .25 else None
                offsets[str(offset)] = offsets.get(str(offset), 0)+1
            previous = local
            stamp = ((local+timedelta(hours=offset)).replace(tzinfo=UTC) if offset is not None
                     else local.replace(tzinfo=NEW_YORK).astimezone(UTC))
            if (stamp.hour, stamp.minute) in keys:
                bars[stamp] = (float(line.split(';')[1]),)
    return bars, offsets


def log_bp(a, b):
    return math.log(b/a)*1e4


def quantile(values, q):
    values = sorted(values)
    return values[min(len(values)-1, int(q*len(values)))] if values else None


def cross_check(days, primary, second):
    """Window bid-to-bid returns from both sources; prices only, no gotobi split.

    Amendment C: coverage is measured over the days the primary source can supply
    (complete FXCM anchors), the only days the study can use.
    """
    out = {}
    for name, w in WINDOWS.items():
        eligible = [d for d in days if d.weekday() in w['weekdays']]
        usable = [d for d in eligible if all(isinstance(primary[d].get(w[k]), dict) for k in ('entry', 'exit'))]
        diffs = []
        for d in usable:
            legs = [(primary[d].get(w[k]), second[d].get(w[k])) for k in ('entry', 'exit')]
            if any(not isinstance(x, dict) for leg in legs for x in leg):
                continue
            (p0, s0), (p1, s1) = legs
            diffs.append(log_bp(p0['quote'][0], p1['quote'][0])-log_bp(s0['quote'][0], s1['quote'][0]))
        within = sum(abs(x) <= TOLERANCE_BP for x in diffs)
        out[name] = {'business_days': len(eligible), 'fxcm_usable_days': len(usable), 'common_days': len(diffs),
            'coverage': len(diffs)/len(usable) if usable else 0.0,
            'within_5bp': within, 'agreement': within/len(diffs) if diffs else 0.0,
            'median_abs_bp': quantile([abs(x) for x in diffs], .5), 'p99_abs_bp': quantile([abs(x) for x in diffs], .99),
            'mean_signed_bp': sum(diffs)/len(diffs) if diffs else None,
            'passed': bool(diffs) and len(diffs) >= .95*len(usable) and within >= .99*len(diffs)}
    return out


def write_once(name, value):
    raw = (json.dumps(json_value(value), sort_keys=True, indent=2)+'\n').encode()
    path = ARCHIVE/name
    if path.exists() and path.read_bytes() != raw:
        raise ValueError('refuse replacement of gotobi artifact: '+name)
    if not path.exists():
        save(path, raw)
    return sha(raw)


def freeze_source():
    missing = capture()
    holidays = jp_holidays((ARCHIVE/'cao-syukujitsu.csv').read_bytes())
    first, last = START.date(), (END-timedelta(days=1)).date()
    days = [first+timedelta(days=i) for i in range((last-first).days+1)]
    days = [d for d in days if business_day(d, holidays)]
    keys = needed_minutes()
    pairs = {}
    for pair in PAIRS:
        (fx, week_opens), (hd, hd_offsets) = fxcm_bars(pair, keys), histdata_bars(pair, keys)
        sources = {'fxcm': fx, 'histdata': hd}
        anchors = {name: {d: {a: pick_anchor(bars, anchor_utc(d, a)) for a in ANCHORS} for d in days}
                   for name, bars in sources.items()}
        counts = {name: {a: {'missing': sum(v[a] is None for v in table.values()),
                             'invalid': sum(v[a] == 'invalid' for v in table.values()),
                             'crossed': sum(isinstance(v[a], dict) and v[a].get('crossed', False)
                                            for v in table.values())} for a in ANCHORS}
                  for name, table in anchors.items()}
        check = cross_check(days, anchors['fxcm'], anchors['histdata'])
        pairs[pair] = {'passed': all(c['passed'] for c in check.values()), 'cross_check': check,
            'anchor_counts': counts, 'fxcm_week_opens': week_opens, 'histdata_week_offsets': hd_offsets,
            'fxcm': {d.isoformat(): v for d, v in anchors['fxcm'].items()}}
        print(json.dumps({'pair': pair, 'passed': pairs[pair]['passed'],
            'agreement': {k: round(c['agreement'], 5) for k, c in check.items()},
            'coverage': {k: round(c['coverage'], 5) for k, c in check.items()}}), flush=True)
    # Raw captures only; the phase artifacts in ARCHIVE itself are outputs.
    raw = [p for p in sorted(ARCHIVE.rglob('*')) if p.is_file() and not p.name.endswith('.part')
           and (p.parent != ARCHIVE or p.name == 'cao-syukujitsu.csv')]
    inputs = {str(p.relative_to(ROOT)): sha(p.read_bytes()) for p in raw}
    source = {'interval': [START, END], 'pairs': pairs, 'inputs': inputs, 'fxcm_not_found': missing,
        'calendar': {'business_days': [d.isoformat() for d in days],
                     'gotobi': {d.isoformat(): v for d, v in gotobi_days(first, last, holidays).items()}},
        'anchor_rule': 'open of first bar in [T, T+5min); non-positive first bar = missing; crossed kept (amendment B)',
        'histdata_time': 'per-week UTC offset from the Sunday 17:00 New York open (amendment A2)'}
    print(json.dumps({'source_sha256': write_once('source.json', source)}), flush=True)


def load_source():
    raw = (ARCHIVE/'source.json').read_bytes()
    digest = sha(raw)
    if digest not in PLAN.read_text():
        raise ValueError('commit source hash in plan before outcomes')
    source = json.loads(raw)
    for name, expected in source['inputs'].items():
        if sha((ROOT/name).read_bytes()) != expected:
            raise ValueError('frozen input changed: '+name)
    return {**source, 'sha256': digest}


def split_for(source):
    return HoldoutSplit('gotobi:'+source['sha256'], START, END)


# ---- trades and statistics -------------------------------------------------

def mid(anchor):
    return sum(anchor['quote'])/2


def trades(source, pair, window, split, final):
    """Gotobi and control trades whose entry and exit both lie in one partition."""
    w, table = WINDOWS[window], source['pairs'][pair]['fxcm']
    gotobi = source['calendar']['gotobi']
    out, counts = [], {'straddle': 0, 'missing_anchor': 0, 'condition_false': 0}
    for iso in source['calendar']['business_days']:
        day = date.fromisoformat(iso)
        if day.weekday() not in w['weekdays']:
            continue
        inside = [split.contains(anchor_utc(day, w[k]), final_holdout=final) for k in ('entry', 'exit')]
        if not any(inside):
            continue
        if not all(inside):
            counts['straddle'] += 1
            continue
        needed = (w['entry'], w['exit'])+(w['condition'] or ())
        quotes = {a: table[iso][a] for a in needed}
        if any(not isinstance(q, dict) for q in quotes.values()):
            counts['missing_anchor'] += 1
            continue
        if w['condition'] and not mid(quotes[w['condition'][1]]) > mid(quotes[w['condition'][0]]):
            counts['condition_false'] += 1
            continue
        entry, exit_ = quotes[w['entry']], quotes[w['exit']]
        gross = w['direction']*log_bp(mid(entry), mid(exit_))
        # Long buys the ask and sells the bid; short sells the bid and buys the ask.
        quoted = (log_bp(fill(entry, 'ask'), fill(exit_, 'bid')) if w['direction'] > 0
                  else log_bp(fill(exit_, 'ask'), fill(entry, 'bid')))
        out.append({'day': iso, 'entry_bar': entry['bar'], 'exit_bar': exit_['bar'], 'gotobi': iso in gotobi,
            'labels': gotobi.get(iso, []), 'gross_bp': gross, 'quoted_bp': quoted, 'net_bp': gross-COST_BP,
            'net_usd': SLOT*(gross-COST_BP)/1e4})
    return out, counts


def welch(a, b):
    if len(a) < 2 or len(b) < 2:
        return {'difference_bp': None, 'p_value': None}
    ma, mb = sum(a)/len(a), sum(b)/len(b)
    va, vb = (sum((x-ma)**2 for x in a)/(len(a)-1)/len(a), sum((x-mb)**2 for x in b)/(len(b)-1)/len(b))
    if va+vb == 0:
        return {'difference_bp': ma-mb, 't': None, 'p_value': None}
    t = (ma-mb)/math.sqrt(va+vb)
    df = (va+vb)**2/(va**2/(len(a)-1)+vb**2/(len(b)-1))
    return {'difference_bp': ma-mb, 't': t, 'df': df, 'p_value': student_t_sf(t, df)}


def months_between(split, final):
    lo, hi = (split.holdout_start, split.data_end) if final else (split.data_start, split.holdout_start)
    out, cursor = [], date(lo.year, lo.month, 1)
    while cursor < hi.date():
        out.append(cursor.strftime('%Y-%m'))
        cursor = date(cursor.year+(cursor.month == 12), cursor.month % 12+1, 1)
    return out


def describe(rows):
    gross, net = [r['gross_bp'] for r in rows], [r['net_bp'] for r in rows]
    n = len(rows)
    sd = (math.sqrt(sum((x-sum(net)/n)**2 for x in net)/(n-1)) if n > 1 else None)
    p = luck_probability(net)
    return {'trades': n, 'mean_gross_bp': sum(gross)/n if n else None,
        'median_gross_bp': sorted(gross)[n//2] if n else None,
        'mean_quoted_bp': sum(r['quoted_bp'] for r in rows)/n if n else None,
        'mean_net_bp': sum(net)/n if n else None, 'sd_net_bp': sd,
        't_net': (sum(net)/n)/(sd/math.sqrt(n)) if sd else None, 'p_net': p,
        'win_rate_net': sum(x > 0 for x in net)/n if n else None,
        'sum_net_bp': sum(net), 'net_usd': SLOT*sum(net)/1e4}


def summarize(rows, counts, split, final):
    picked = [r for r in rows if r['gotobi']]
    control = [r for r in rows if not r['gotobi']]
    stats = describe(picked)
    usd = [D(str(round(r['net_usd'], 6))) for r in picked]
    dd_usd = max_drawdown(usd)
    peak = cumulative = worst_bp = D(0)
    for r in picked:
        cumulative += D(str(r['net_bp']))
        peak = max(peak, cumulative)
        worst_bp = max(worst_bp, peak-cumulative)
    monthly = {m: 0.0 for m in months_between(split, final)}
    for r in picked:
        monthly[r['day'][:7]] += r['net_usd']
    by_year, regimes = {}, {}
    for r in picked:
        by_year.setdefault(r['day'][:4], []).append(r)
    for name, lo, hi in REGIMES:
        rows_in = [r for r in picked if lo <= int(r['day'][:4]) <= hi]
        regimes[name] = {k: v for k, v in describe(rows_in).items()
                         if k in ('trades', 'mean_gross_bp', 'mean_net_bp', 'win_rate_net', 'net_usd')} if rows_in else None
    month_end_only = [r for r in picked if r['labels'] == ['month_end']]
    five = [r for r in picked if 'five' in r['labels']]
    monday = [r for r in rows if date.fromisoformat(r['day']).weekday() == 0]
    return {**stats, 'counts': counts, 'control': describe(control),
        'gotobi_minus_control': welch([r['gross_bp'] for r in picked], [r['gross_bp'] for r in control]),
        'break_even_cost_bp': stats['mean_gross_bp'],
        'max_drawdown': {'usd': str(dd_usd), 'pct_of_slot': float(dd_usd/SLOT*100), 'bp': float(worst_bp)},
        'monthly_marked_net_usd': {m: round(v, 6) for m, v in monthly.items()},
        'luck': monthly_luck(monthly, len(picked)),
        'by_year': {y: {k: v for k, v in describe(rs).items() if k in ('trades', 'mean_gross_bp', 'mean_net_bp', 'net_usd')}
                    for y, rs in sorted(by_year.items())},
        'regimes': regimes,
        'diagnostics': {'month_end_only': describe(month_end_only), 'five_multiple': describe(five),
                        'monday_gotobi': describe([r for r in monday if r['gotobi']]),
                        'monday_control': describe([r for r in monday if not r['gotobi']])}}


def admitted(metrics):
    diff = metrics['gotobi_minus_control']
    return bool(metrics['trades'] and metrics['mean_net_bp'] > 0 and metrics['p_net'] is not None
                and metrics['p_net'] < .05 and diff['difference_bp'] is not None and diff['difference_bp'] > 0
                and diff['p_value'] is not None and diff['p_value'] < .05)


def passed_final(metrics):
    diff = metrics['gotobi_minus_control']
    return bool(metrics['trades'] and metrics['mean_net_bp'] > 0 and metrics['p_net'] is not None
                and metrics['p_net'] < .05 and diff['difference_bp'] is not None and diff['difference_bp'] > 0)


# ---- ledger ----------------------------------------------------------------

def require_committed():
    paths = ['src/tradingbot/research/gotobi.py', str(PLAN.relative_to(ROOT))]
    if subprocess.check_output(['git', 'status', '--porcelain', '--', *paths], cwd=ROOT).strip():
        raise ValueError('commit code and plan before outcomes')
    return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()


def version(source, window, pair):
    params = {'window': window, 'spec': WINDOWS[window], 'pair': pair, 'cost_bp': COST_BP, 'slot_usd': SLOT,
              'anchor_minutes': ANCHOR_MINUTES, 'source_sha256': source['sha256'],
              'code_sha256': sha((ROOT/'src/tradingbot/research/gotobi.py').read_bytes())}
    raw = json.dumps(json_value(params), sort_keys=True, separators=(',', ':'))
    return sha(raw.encode()), params


def record(session, trial, metrics):
    trial.status, trial.completed_ts, trial.metrics = 'complete', datetime.now(UTC), json_value(metrics)
    trial.trade_count = metrics['trades']
    if metrics['trades']:
        trial.pnl_after_fees = D(str(round(metrics['net_usd'], 6)))
        trial.fees_total = D(str(round(SLOT*COST_BP/1e4*metrics['trades'], 6)))
        trial.pnl = trial.pnl_after_fees+trial.fees_total
        trial.win_rate = D(str(round(metrics['win_rate_net'], 4)))
        trial.max_drawdown = D(metrics['max_drawdown']['usd'])
        if metrics['t_net'] is not None:
            trial.sharpe = D(str(round(metrics['t_net']/math.sqrt(metrics['trades']), 4)))
        if metrics['p_net'] is not None:
            trial.luck_p_value = D(str(round(metrics['p_net'], 6)))
    session.commit()


def train():
    source, commit = load_source(), require_committed()
    split, results = split_for(source), {}
    for pair in PAIRS:
        for window in WINDOWS:
            key = f'gotobi-{window}-{pair}-train-v1'
            ver, params = version(source, window, pair)
            with session_scope() as session:
                if session.scalar(select(StrategyRow.id).where(StrategyRow.key == key)):
                    raise ValueError('configuration already attempted; inspect durable trials')
                register_split(session, split)
                row = StrategyRow(key=key, name=f'Gotobi {window} {pair}', status='backtest', allocation_usd=D(0),
                    config={'research_only': True, 'research_family': 'gotobi', 'params': json_value(params)})
                session.add(row); session.flush()
                trial = Trial(strategy_id=row.id, mode='backtest', final_holdout=False, dataset_key=split.dataset_key,
                    holdout_start=split.holdout_start, data_start=START, data_end=split.holdout_start,
                    strategy_version=ver, git_commit=commit, code_version=CODE_VERSION, params=json_value(params),
                    notes='Gotobi training; research only, no venue. Plan 51-gotobi-plan.md.')
                session.add(trial); session.commit()
                if not source['pairs'][pair]['passed']:
                    trial.status, trial.completed_ts = 'failed', datetime.now(UTC)
                    trial.metrics = {'disposition': 'DATA_FAIL', 'promotion_eligible': False,
                                     'reason': 'FXCM/HistData window returns failed the frozen cross-check'}
                    session.commit()
                    results[f'{window}:{pair}'] = {'status': 'DATA_FAIL', 'trial_id': trial.id}
                    continue
                rows, counts = trades(source, pair, window, split, final=False)
                metrics = summarize(rows, counts, split, final=False)
                metrics['admitted'] = pair == 'USDJPY' and admitted(metrics)
                record(session, trial, metrics)
                write_once(f'train-{window}-{pair}.json', {'metrics': metrics, 'trades': rows, 'trial_id': trial.id})
                results[f'{window}:{pair}'] = {'status': 'complete', 'trial_id': trial.id, 'strategy_version': ver,
                    'metrics': {k: v for k, v in metrics.items() if k not in ('monthly_marked_net_usd', 'by_year')}}
                print(json.dumps({'window': window, 'pair': pair, 'trial_id': trial.id, 'trades': metrics['trades'],
                    'mean_gross_bp': metrics['mean_gross_bp'], 'mean_net_bp': metrics['mean_net_bp'],
                    'p_net': metrics['p_net'], 'diff': metrics['gotobi_minus_control'], 'admitted': metrics['admitted']}),
                    flush=True)
    eligible = [(w, r) for w in WINDOWS if (r := results.get(f'{w}:USDJPY')) and r['status'] == 'complete'
                and r['metrics']['admitted']]
    selected = max(eligible, key=lambda x: x[1]['metrics']['t_net'])[0] if eligible else None
    choice = {'source_sha256': source['sha256'], 'split': split.metadata(), 'git_commit': commit,
              'code_sha256': sha((ROOT/'src/tradingbot/research/gotobi.py').read_bytes()),
              'training': results, 'selected': selected}
    print(json.dumps({'selection_sha256': write_once('selection.json', choice), 'selected': selected}), flush=True)


def final():
    source, commit = load_source(), require_committed()
    raw = (ARCHIVE/'selection.json').read_bytes()
    committed = subprocess.check_output(['git', 'show', commit+':'+str(PLAN.relative_to(ROOT))], cwd=ROOT)
    if sha(raw) not in committed.decode() or committed != PLAN.read_bytes():
        raise ValueError('commit selection hash before final')
    choice = json.loads(raw)
    if choice['source_sha256'] != source['sha256'] or choice['code_sha256'] != sha((ROOT/'src/tradingbot/research/gotobi.py').read_bytes()):
        raise ValueError('frozen selection identity changed')
    window = choice['selected']
    if window is None:
        raise ValueError('no window admitted in training; the holdout stays unspent')
    split, (ver, params) = split_for(source), version(source, window, 'USDJPY')
    if ver != choice['training'][f'{window}:USDJPY']['strategy_version']:
        raise ValueError('final differs from frozen training version')
    with session_scope() as session:
        key = f'gotobi-{window}-USDJPY-final-v1'
        if session.scalar(select(StrategyRow.id).where(StrategyRow.key == key)):
            raise ValueError('final already attempted; inspect durable trials')
        row = StrategyRow(key=key, name=f'Gotobi {window} USDJPY final', status='backtest', allocation_usd=D(0),
            config={'research_only': True, 'research_family': 'gotobi', 'params': json_value(params)})
        session.add(row); session.commit()
        trial_id = claim_final(session, split=split, strategy_id=row.id, version=ver,
            params=json_value({**params, '_holdout': split.metadata()}),
            notes='Gotobi final: USD/JPY verdict, EUR/JPY same-window replication diagnostic. Research only.')
        trial = session.get(Trial, trial_id)
        trial.git_commit, trial.code_version = commit, CODE_VERSION
        session.commit()
        try:
            out = {}
            for pair in PAIRS:
                if not source['pairs'][pair]['passed']:
                    out[pair] = {'disposition': 'DATA_FAIL'}
                    continue
                rows, counts = trades(source, pair, window, split, final=True)
                out[pair] = {'metrics': summarize(rows, counts, split, final=True), 'trades': rows}
            metrics = {**out['USDJPY']['metrics'], 'window': window,
                       'verdict': 'PASS' if passed_final(out['USDJPY']['metrics']) else 'FAIL',
                       'eurjpy_replication': out['EURJPY'].get('metrics', out['EURJPY'])}
            trial = session.get(Trial, trial_id)
            record(session, trial, metrics)
        except BaseException as error:
            session.rollback()
            trial = session.get(Trial, trial_id)
            trial.status, trial.completed_ts = 'failed', datetime.now(UTC)
            trial.notes = (trial.notes or '')+f'\nFinal failed after admission: {type(error).__name__}: {error}'
            session.commit()
            raise
    digest = write_once(f'final-{window}.json', {'trial_id': trial_id, 'metrics': metrics,
        'trades': {p: o.get('trades') for p, o in out.items()}})
    print(json.dumps({'window': window, 'trial_id': trial_id, 'verdict': metrics['verdict'],
        'mean_net_bp': metrics['mean_net_bp'], 'p_net': metrics['p_net'], 'sha256': digest}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('source', 'train', 'final'))
    args = parser.parse_args()
    {'source': freeze_source, 'train': train, 'final': final}[args.phase]()


if __name__ == '__main__':
    main()
