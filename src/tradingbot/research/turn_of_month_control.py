"""Preregistered dividend-aware calendar-versus-drift diagnostic, not execution."""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal as D
import hashlib
import json
from pathlib import Path
import random
import statistics
import subprocess

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradingbot.backtest import Backtester
from tradingbot.connectors.cash import NEW_YORK
from tradingbot.data.disk_budget import DiskBudget
from tradingbot.data.loader import local_engine
from tradingbot.db.models import Strategy as StrategyRow, Trial
from tradingbot.strategy.interface import MarketEvent, Strategy
from .equity_data import load_equities
from .equity_runtime import equity_split
from .turn_of_month import cycles_for, instrument_for, jsonable


class RandomWindowControl(Strategy):
    key = 'tom_random_window_control'

    def on_start(self, ctx):
        self.closes = {}
        self.result = None

    def on_event(self, ctx, event):
        day = event.time.astimezone(NEW_YORK).date().isoformat()
        value = event.last
        if value is None or value <= 0 or not value.is_finite() or day in self.closes:
            raise ValueError('invalid or duplicate adjusted-close observation')
        self.closes[day] = value
        return []

    def on_finish(self, ctx):
        calendar = self.params['calendar']
        indices = {d: i for i, d in enumerate(calendar)}
        all_pairs = self.params['tom_pairs']
        pairs = [(a, b) for a, b in all_pairs if a in self.closes and b in self.closes]
        if not pairs:
            raise ValueError('no complete TOM comparison cycles in partition')
        months = defaultdict(list)
        for day in calendar:
            months[day[:7]].append(day)
        # Include the opening three and closing four sessions even when a
        # boundary-spanning TOM cycle lies partly outside observed prices.
        blocked = {d for days in months.values() for d in days[:3] + days[-4:]}
        actual = [self.closes[b] / self.closes[a] - 1 for a, b in pairs]
        if any(indices[b] - indices[a] != 6 for a, b in pairs):
            raise ValueError('TOM comparison must hold six session intervals')
        slip = D(str(self.params['slippage_bp_per_side'])) / 10000
        fee_rate = D(self.params['round_trip_fee']) / D(self.params['comparison_notional'])

        def net(value):
            return (1 + value) * (1 - slip) / (1 + slip) - 1 - fee_rate

        outputs = {}
        for duration in self.params['durations']:
            groups, candidates = [], []
            for a, b in pairs:
                choices = []
                for start in calendar:
                    if start[:7] != a[:7]:
                        continue
                    index = indices[start]
                    window = calendar[index:index+duration+1]
                    if (len(window) != duration+1 or any(d in blocked or d not in self.closes for d in window)):
                        continue
                    end = window[-1]
                    choices.append((start, end, self.closes[end] / self.closes[start] - 1))
                if not choices:
                    raise ValueError(f'no eligible {duration}-session control window for {a[:7]}')
                groups.append([float(net(r)) for _, _, r in choices])
                candidates.append({'month': a[:7], 'eligible_windows': len(choices),
                                   'first_entry': choices[0][0], 'last_entry': choices[-1][0],
                                   'mean_gross_return': sum(r for _, _, r in choices) / len(choices),
                                   'mean_net_scenario_return': sum(net(r) for _, _, r in choices) / len(choices)})
            rng = random.Random(self.params['seed'])
            draws = sorted(sum(rng.choice(values) for values in groups) / len(groups)
                           for _ in range(self.params['draws']))
            observed = float(sum(net(r) for r in actual) / len(actual))
            expected = statistics.mean(statistics.mean(group) for group in groups)
            years = {}
            for year in sorted({a[:4] for a, _ in pairs}):
                chosen = [i for i, (a, _) in enumerate(pairs) if a[:4] == year]
                years[year] = {'cycles': len(chosen),
                    'tom_mean_net_scenario_return': statistics.mean(float(net(actual[i])) for i in chosen),
                    'random_mean_net_scenario_return': statistics.mean(statistics.mean(groups[i]) for i in chosen)}
            outputs[str(duration)] = {'duration_session_intervals': duration, 'matched_cycles': len(pairs),
                'tom_mean_gross_return': sum(actual) / len(actual),
                'random_mean_gross_return': sum(c['mean_gross_return'] for c in candidates) / len(candidates),
                'tom_mean_net_scenario_return': observed, 'random_expected_mean_net_scenario_return': expected,
                'calendar_excess_mean_return': observed - expected,
                'random_mean_percentiles': {str(p): draws[round(p / 100 * (len(draws)-1))] for p in (5,50,95)},
                'random_at_least_tom_fraction': (1 + sum(value >= observed - 1e-12 for value in draws)) / (len(draws)+1),
                'draws': len(draws), 'candidates_by_month': candidates, 'by_entry_year': years}
        self.result = {'nonexecution_diagnostic': True, 'actual_ledger_trades': 0,
                       'first_observation': min(self.closes), 'last_observation': max(self.closes),
                       'adjusted_close_observations': len(self.closes), 'durations': outputs,
                       'limitations': 'Adjusted total-return proxy; independent comparison notionals, not portfolio P&L. Random-date exchangeability is an assumption; prior full-sample study was inspected.'}


def run_control(session, data, *, run_id, commit, final_holdout=False):
    key = 'control_' + hashlib.sha256(run_id.encode()).hexdigest()[:28]
    if session.scalar(select(StrategyRow.id).where(StrategyRow.key == key)):
        raise ValueError('control run already attempted; never reset an existing trial')
    iid, venue_id = instrument_for(session, 'SPY')
    dates = sorted(data.daily('SPY'))
    pairs = cycles_for(data, dates[0], dates[-1])
    config = {'calendar': [str(d) for d in sorted(data.sessions)],
              'tom_pairs': [[str(a),str(b)] for a,b in pairs], 'durations': [5,6],
              'seed': 20261001, 'draws': 10000, 'slippage_bp_per_side': 2,
              'comparison_notional': '139.99', 'round_trip_fee': '.04'}
    row = StrategyRow(key=key, name='TOM random-window diagnostic ' + run_id,
                      venue_id=venue_id, status='backtest', allocation_usd=D(140),
                      config={'research_only': True, 'nonexecution_diagnostic': True, **config})
    session.add(row); session.commit()
    sid = row.id
    split = equity_split(data, ('SPY',))
    params = {'source_sha256': data.source_hash, 'source_pages': data.source_pages,
              'source_records': data.source_records, 'study_run_id': run_id, 'method': config,
              'prior_full_sample_inspection': True, 'nonexecution_diagnostic': True}
    try:
        raw, adjusted = data.daily('SPY'), data.daily('SPY','all')
        selected = [d for d in sorted(data.sessions)
                    if split.contains(data.sessions[d].closes_at, final_holdout=final_holdout)]
        if any(d not in raw or d not in adjusted for d in selected):
            raise ValueError('missing raw/adjusted daily session in diagnostic partition')
        events = (MarketEvent.quote(iid,data.sessions[d].closes_at,last=adjusted[d].close,
                                   meta={'adjusted_total_return_proxy': True, 'not_executable': True}) for d in selected)
        strategy = RandomWindowControl(config)
        runtime = Backtester(session,strategy=strategy,strategy_id=sid)
        dependency = Path(__file__).with_name('turn_of_month.py')
        result = runtime.run(events,params=params,split=split,final_holdout=final_holdout,
                             version_params={'calendar_helper_sha256':hashlib.sha256(dependency.read_bytes()).hexdigest()},
                             notes='Preregistered random-window diagnostic; no simulated orders or investable P&L.')
        trial = session.get(Trial,result.trial_id)
        trial.git_commit, trial.code_version = commit, 'tom-control-v1'
        trial.pnl_after_fees = None
        trial.metrics = jsonable({**strategy.result, 'holdout': result.report['holdout']})
        session.commit()
        return {'variant':'tom_random_window_control','trial_id':trial.id,'strategy_id':sid,
                'git_commit':commit,'params':params,'metrics':trial.metrics}
    except Exception as error:
        session.rollback()
        consumed = getattr(locals().get('runtime'),'last_trial_id',None) if final_holdout else None
        trial = session.get(Trial,consumed) if consumed is not None else None
        if trial is None:
            trial = Trial(strategy_id=sid,mode='backtest',params=jsonable(params),holdout_start=split.holdout_start)
        trial.status, trial.completed_ts = 'failed', datetime.now(UTC)
        trial.git_commit, trial.code_version = commit, 'tom-control-v1'
        trial.notes = f'{type(error).__name__}: {error}; audit retained, any final claim remains consumed'
        session.add(trial);session.commit()
        return {'variant':'tom_random_window_control','trial_id':trial.id,'status':'failed','error':str(error)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path('data/equities'))
    parser.add_argument('--data-run',default='tom-20260930')
    parser.add_argument('--run-id',required=True)
    parser.add_argument('--final-holdout',action='store_true')
    args = parser.parse_args()
    dirty = subprocess.check_output(['git','status','--porcelain','--','src/tradingbot/research',
        'src/tradingbot/strategy/interface.py','src/tradingbot/backtest','src/tradingbot/ledger',
        'src/tradingbot/risk','src/tradingbot/db','src/tradingbot/connectors/cash.py'],text=True)
    if dirty:
        raise ValueError('commit research code before evaluating returns')
    budget = DiskBudget(Path('data'));budget.check()
    data = load_equities(args.root,args.data_run)
    commit = subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
    with Session(local_engine(),expire_on_commit=False) as session:
        artifact = run_control(session,data,run_id=args.run_id,commit=commit,final_holdout=args.final_holdout)
    from tradingbot.data.bulk_history import write_json
    write_json(args.root/'results'/args.run_id/'tom_random_window_control.json',jsonable(artifact),budget)
    summary = {k:v for k,v in artifact.items() if k != 'params'}
    if 'metrics' in summary:
        summary['metrics'] = {**summary['metrics'], 'durations': {k:{a:b for a,b in v.items() if a!='candidates_by_month'}
            for k,v in summary['metrics']['durations'].items()}}
    print(json.dumps(summary,default=str),flush=True)


if __name__ == '__main__':
    main()
