"""Render sealed study facts; no price access, strategy execution, or selection."""
from decimal import Decimal
import gzip
import io
import json
from pathlib import Path
import tarfile

from tradingbot.backtest.longshot_history import ROOT, AUDIT, PLAN, SPLIT, encoded, instant, sha

D=Decimal


def amount(x):
    return '—' if x is None else f'{D(str(x)):.4f}'


def pvalue(x):
    return 'undefined (n<2)' if x is None else f'{float(x):.5g}'


def percent(x):
    return '—' if x is None else f'{float(x):.1%}'


def main():
    training=json.loads((ROOT/'training.json').read_text())
    selection=json.loads((ROOT/'selection.json').read_text())
    finals=json.loads((ROOT/'final.json').read_text())
    audit=json.loads((ROOT/'execution-audit.json').read_text())
    source=json.loads(Path('docs/research/20-longshot-preparation.json').read_text())
    capture=json.loads(AUDIT.read_text())
    final_by={r['category']:r for r in finals}
    assert len(training)==30 and len({r['id'] for r in training})==30
    assert len(selection['choices'])==len(finals)==len(final_by)==5
    assert set(final_by)==set(selection['choices'])
    assert selection['training_sha256']==sha(ROOT/'training.json')
    assert not any(r['status']=='running' for r in training+finals)
    attempts=training+[r for r in finals if 'id' in r]
    assert {r['id'] for r in attempts}=={c['trial_id'] for c in audit['checks']}
    assert audit['all_complete_trials_verified']
    assert all(next(c for c in audit['checks'] if c['trial_id']==r['id'])['status']=='verified'
               for r in attempts if r['status']=='complete')
    for category,choice in selection['choices'].items():
        result=final_by[category]
        if choice is None:
            assert result['status']=='unconsumed_no_profitable_training_variant' and 'id' not in result
        else:
            assert result['strategy_version']==choice['strategy_version']
            assert result['final_holdout'] is True
    # The written interpretation below is specific to this sealed study.
    btc='polymarket_intl:pm-series:btc-up-or-down-daily'
    chosen=selection['choices'][btc]; evaluated=final_by[btc]
    assert chosen['id']==3935 and evaluated['id']==3969
    assert chosen['pnl_after_fees']=='121.781966' and evaluated['pnl_after_fees']=='15.638289'
    assert chosen['trade_count']==250 and evaluated['trade_count']==111
    assert D(chosen['metrics']['marked_drawdown'])==D('175.06646047')
    assert D(evaluated['metrics']['marked_drawdown'])==D('83.283383596')
    assert all(choice is None for category,choice in selection['choices'].items() if category!=btc)
    receipt_archive=Path('docs/research/20-longshot-executions.tar.gz')
    buffer=io.BytesIO()
    with tarfile.open(fileobj=buffer,mode='w',format=tarfile.USTAR_FORMAT) as archive:
        for r in sorted(attempts,key=lambda row:row['id']):
            if r['status']!='complete':
                continue
            path=Path(r['metrics']['execution_receipt'])
            assert path.resolve().parent==ROOT.resolve()
            assert path.name==f"trial-{r['id']}-executions.json"
            assert sha(path)==r['metrics']['execution_sha256']
            raw=path.read_bytes()
            info=tarfile.TarInfo(path.name)
            info.size=len(raw); info.mtime=0; info.mode=0o644
            archive.addfile(info,io.BytesIO(raw))
    receipt_archive.write_bytes(gzip.compress(buffer.getvalue(),mtime=0))
    overlap=[]
    for category in selection['choices']:
        for offset in ('0.01','0.02','0.05'):
            pair=[next(r for r in training if r['category']==category and r['offset']==offset and r['side_rule']==side)
                  for side in ('buy_favourite','sell_longshot')]
            if any(r['status']!='complete' for r in pair):
                continue
            fills=[]
            for r in pair:
                evidence=json.loads(Path(r['metrics']['execution_receipt']).read_text())
                fills.append({f['metadata']['source_execution_identity']:f for f in evidence['fills']
                              if not f['metadata'].get('settlement')})
            a,b=fills; shared=set(a)&set(b)
            complement=sum(a[k]['size']==b[k]['size'] and instant(a[k]['time'])==instant(b[k]['time'])
                           and D(a[k]['price'])+D(b[k]['price'])==1 and a[k]['instrument_id']!=b[k]['instrument_id']
                           for k in shared)
            overlap.append({'category':category,'offset':offset,'trial_ids':[r['id'] for r in pair],
                            'buy_entry_executions':len(a),'sell_entry_executions':len(b),
                            'shared_public_execution_identities':len(shared),
                            'equal_size_same_time_complementary_execution_prices':complement})
    decision=[]
    for category, chosen in selection['choices'].items():
        final=final_by[category]
        completed=[r for r in training if r['category']==category and r['status']=='complete']
        net=[D(r['pnl_after_fees']) for r in completed]
        killed=sum(any(h['kind']=='per_strategy_kill' for h in r['metrics']['halt_events']) for r in completed)
        delayed=sum(bool(r['metrics']['holding_breaches']) for r in completed)
        reasons=[]
        profit_gate = bool(chosen is not None and final['status']=='complete' and D(final['pnl_after_fees'])>0)
        if chosen is None:
            status='FAIL_TRAINING'; reasons.append('No completed positive-net training variant.')
        elif final['status']!='complete':
            status='FAIL_FINAL_EXECUTION'; reasons.append('Selected final did not complete; consumed attempts are never retried.')
        elif D(final['pnl_after_fees'])<=0:
            status='FAIL_HOLDOUT'; reasons.append('Selected final is not profitable after the stated fees.')
        else:
            status='COUNTERFACTUAL_PROFIT_BOTH_PARTITIONS'
        for label, result in [('training',chosen),('final',final if final.get('status')=='complete' else None)]:
            if result is None:
                continue
            metrics=result['metrics']
            if metrics['holding_breaches']:
                reasons.append(f'{label}: actual hold exceeded seven days; strategy mandate fails.')
                status='FAIL_SEVEN_DAY_MANDATE'
            if any(h['kind']=='per_strategy_kill' for h in metrics['halt_events']):
                reasons.append(f'{label}: permanent strategy kill fired; risk suitability fails.')
                status='FAIL_RISK'
            if D(metrics['marked_drawdown_fraction'])>=D('.4'):
                reasons.append(f'{label}: marked drawdown reached at least 40% of the virtual slot; a risk-review concern, not a change to the initial-allocation kill rule.')
        reasons.append('Native PM US execution/fee transfer and paper fidelity unproven; prediction venue verification remains deferred.')
        decision.append({'category':category,'historical_scenario_verdict':status,'profit_positive_in_both_partitions':profit_gate,
                         'pipeline_decision':'hold in research',
                         'live_allocation_requested':'0','training_trial':chosen['id'] if chosen else None,
                         'final_trial':final.get('id'),'reasons':reasons,
                         'training_evidence':{'completed_variants':len(completed),'profitable_variants':sum(x>0 for x in net),
                            'minimum_net':str(min(net)) if net else None,'maximum_net':str(max(net)) if net else None,
                            'killed_variants':killed,'holding_breach_variants':delayed}})
    result={'study':'tradingbot-yg2','implementation_commit':'73d02c5','source':source,'split':SPLIT.metadata(),
        'training':training,'selection':selection,'finals':finals,'decisions':decision,'execution_audit':audit,
        'paired_exposure_diagnostics':overlap,
        'artifacts':{str(path):sha(path) for path in (ROOT/'training.json',ROOT/'selection.json',ROOT/'final.json',ROOT/'execution-audit.json',receipt_archive,PLAN,AUDIT,Path(__file__))},
        'fee_basis':{'schedule_id':'pm-us-standard-applied-to-history','maker_coefficient':'-0.0125','taker_coefficient':'0.0695','maker_only':True,
                     'description':'Current PM US fee counterfactual on Kalshi and international PM trade history; no rewards.'},
        'funding':'Each category is an alternative $140 virtual deployment; category profits are not portfolio totals.',
        'statistics':'One-sided per-trip and UTC-exit-date aggregate zero-edge t-test p-values are descriptive, serially dependent and selected. Not probabilities a hypothesis is true; no additional p-value promotion gate.'}
    Path('docs/research/20-longshot-results.json').write_bytes(encoded(result))
    lines=['# Full-history favourite–longshot results','',
        'The fixed six-variant grid was evaluated separately in each of the five captured categories. '
        'The final partition was opened only for a positive-net training selection. '
        'All results below use the current PM US fee counterfactual on native public history; '
        'they do not establish executable returns on PM US. No paper/live promotion or real funding occurred.','',
        '[Preregistration](20-longshot-plan.md) · [Source admission](20-longshot-preparation.md) · '
        '[Frozen selection](20-longshot-selection.json) · [Full machine results](20-longshot-results.json) · '
        '[Final evidence](20-longshot-final.json) · [Execution audit](20-longshot-execution-audit.json) · '
        '[Exact execution receipts](20-longshot-executions.tar.gz)','',
        '## Interpretation','',
        'International BTC **sell-longshot at offset 0.05** is the only category/choice meeting the declared '
        'after-fee profit condition in both partitions: **+$121.781966 training / +$15.638289 final**. '
        'The selected version completed 250 training and 111 final trades. The other four categories have '
        'no profitable training choice and leave their finals unconsumed.','',
        'Retain this candidate in research. Its marked peak-to-trough drawdown is **$175.07 in training '
        'and $83.28 in the final**, equal to 125.05% and 59.49% of the initial virtual $140 slot. '
        'Training equity grew before retreating; the unchanged loss kill measures equity falling $56 '
        'below the initial $140, so these peak drawdowns did not trigger it. Those drawdowns do not '
        'demonstrate acceptable risk for this allocation. This review changes no loss limit or selection rule.','',
        'The final earns $47.64 in its June/Q2 portion, then **loses $32.00 in Q3**: July +$9.03, '
        'August −$16.12 and September −$24.91. Final gross profit is $9.80 plus $5.84 in modeled '
        'maker rebates. Its per-trip and date-aggregate one-sided p-values are both **0.43536**; '
        'training values are about 0.22. These selected and serially dependent observations provide '
        'weak statistical evidence and substantial regime/risk uncertainty. The stated profit condition '
        'has passed; native venue execution and promotion suitability remain unestablished.','',
        '## Decision by category','',
        '| Category | Training trial | Final trial | Historical scenario result | Pipeline decision |',
        '|---|---:|---:|---|---|']
    for row in decision:
        lines.append(f"| {row['category']} | {row['training_trial'] or 'none'} | {row['final_trial'] or 'unconsumed'} | {row['historical_scenario_verdict']} | hold in research |")
    lines+=['']
    for row in decision:
        e=row['training_evidence']
        lines.append(f"- **{row['category']}**: {e['completed_variants']}/6 training variants completed, "
            f"{e['profitable_variants']} profitable; net range ${amount(e['minimum_net'])} to ${amount(e['maximum_net'])}. "
            f"Permanent kills: {e['killed_variants']}; variants with a hold over seven days: {e['holding_breach_variants']}.")
    lines+=['','## Dataset and execution','',
        'The original cohort contains 37,384 contracts / 74,768 outcomes. The manifest excludes 53 contracts '
        '(30 off-session index contracts, 11 invalid weather windows, one uncertified payout pair and 11 split crossers), '
        'leaving 23,632 training and 13,699 final contracts. Zero-volume, empty-tape and catalog-gap observations '
        'are retained in the source audit, without fabricated executions.','',
        f'The elapsed UTC split is {SPLIT.data_start.isoformat()} to {SPLIT.data_end.isoformat()} (exclusive), with the fixed 70/30 cutoff at {SPLIT.holdout_start.isoformat()}.' ]
    lines+=['','Each category deploys an independent **virtual $140 alternative**. Summing these profits does not '
        'describe one funded portfolio. Every variant starts flat, reserves held and pending worst-case collateral, '
        'obeys the $25 binary-contract cap and unchanged risk veto, and holds until actual terminal settlement. '
        'Replay cash is released at the modeled terminal timestamp; native PM US cash availability is unverified. '
        'Strictly later through-price prints and observed volume are required for maker fills. '
        'Quiet-tape timers pull orders five minutes before scheduled close; later observations still mark positions.','',
        'The maker coefficient is −0.0125 and taker coefficient 0.0695; this study is maker-only, with fee-free settlement '
        'and a $1 value per binary payout unit, '
        'with no invented rewards. Negative fee totals are rebates. Native venue fee economics are not estimated. '
        'Source prices are exact Decimals, size rounds down to 10 decimal places, '
        'and cash/ledger residuals are explicitly checked against accounting-column precision.','',
        '## All training variants','',
        '| Category | Side | Offset | Trial | Status | Net $ | Gross $ | Fees $ | Trades | Maker fills | Marked DD $ | DD / $140 | Trip p | Date p (n dates) |',
        '|---|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in training:
        m=r.get('metrics') or {}
        trip_p=pvalue(r['luck_p_value']) if r['status']=='complete' else 'not estimated'
        date_p=pvalue(m.get('date_aggregate_p_value')) if r['status']=='complete' else 'not estimated'
        lines.append(f"| {r['category']} | {r['side_rule']} | {r['offset']} | {r['id']} | {r['status']} | {amount(r['pnl_after_fees'])} | {amount(r['pnl'])} | {amount(r['fees_total'])} | {r['trade_count']} | {m.get('maker_fills','—')} | {amount(m.get('marked_drawdown'))} | {percent(m.get('marked_drawdown_fraction'))} | {trip_p} | {date_p} ({m.get('unique_exit_dates','—')}) |")
    lines+=['','## Once-only selected finals','',
        '| Category | Trial | Net $ | Gross $ | Fees $ | Trades | Maker fills | Marked DD $ | DD / $140 | Trip p | Date p (n dates) |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in finals:
        if r['status']!='complete':
            lines.append(f"| {r['category']} | {r.get('id','unconsumed')} | {r['status']} | — | — | — | — | — | — | — | — |")
            continue
        m=r['metrics']
        lines.append(f"| {r['category']} | {r['id']} | {amount(r['pnl_after_fees'])} | {amount(r['pnl'])} | {amount(r['fees_total'])} | {r['trade_count']} | {m['maker_fills']} | {amount(m['marked_drawdown'])} | {float(m['marked_drawdown_fraction']):.1%} | {pvalue(r['luck_p_value'])} | {pvalue(m['date_aggregate_p_value'])} ({m['unique_exit_dates']}) |")
    lines+=['','## Regimes, dependence and risk events','',
        'The JSON includes month, quarter and fixed first-execution-price bands for **every variant**, '
        'with trade counts, gross/net P&L, fees and realized drawdown; zero-fill observed calendar months remain visible. '
        'Marked daily equity, monthly marked drawdowns, all simulated risk halts, rejection reasons, actual holds over '
        'seven days and maximum collateral are also retained. These are calendar buckets, not independently identified '
        'economic regimes. Marked drawdown uses observed public prints, not a continuous executable bid/ask series; '
        'quiet-period price moves can remain unobserved. First-entry bands use the price of the first execution, '
        'after the fixed quote offset.','',
        'The following quarterly matrix retains every variant. Cells show net dollars (completed trades). '
        'A zero after a permanent kill means no trading, not evidence of later regime stability.','']
    regimes=training+[r for r in finals if r.get('status')=='complete']
    quarters=sorted({q for r in regimes if r.get('status')=='complete' for q in r['metrics']['regimes']['quarter']})
    lines += ['| Category | Partition / trial | ' + ' | '.join(quarters) + ' |', '|---|---|'+'---:|'*len(quarters)]
    for r in regimes:
        if r.get('status')!='complete':
            continue
        buckets=r['metrics']['regimes']['quarter']
        cells=[f"{amount(buckets[q]['net_pnl'])} ({buckets[q]['trades']})" if q in buckets else '—' for q in quarters]
        part='final' if r['final_holdout'] else r['side_rule']+' '+r['offset']
        lines.append(f"| {r['category']} | {part} / {r['id']} | "+' | '.join(cells)+' |')
    lines+=['','The risk and effective sample counts below distinguish completed contracts from correlated events.','',
            '| Trial | Contracts | Events | Exit dates | Realized DD $ | Max collateral $ | Max hold days | Kill / daily halts | Rejected intents |',
            '|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in regimes:
        if r.get('status')!='complete':
            continue
        m=r['metrics']; h=m['halt_events']
        kills=sum(e['kind']=='per_strategy_kill' for e in h)
        daily=sum(e['kind']=='global_daily_halt' for e in h)
        lines.append(f"| {r['id']} | {m['unique_contracts']} | {m['unique_events']} | {m['unique_exit_dates']} | {amount(m['max_drawdown'])} | {amount(m['maximum_collateral'])} | {m['maximum_holding_seconds']/86400:.3f} | {kills} / {daily} | {m['orders_rejected']:,} |")
    lines+=['','Per-trip p-values and UTC-exit-date aggregate p-values test positive mean net outcomes against zero. '
        'They are descriptive after selection from six variants. Buy-favourite and sell-longshot variants can express '
        'the same economic exposure on complementary binary prints; they are not independent replications. '
        'Sibling strikes, complement projections, shared '
        'BTC/weather events and serially correlated dates do not supply independent observations. A p-value is not '
        'the probability that a hypothesis is true. Undefined values with fewer than two observations are reported '
        'as such. No p-value threshold was added to the owner\'s profit criterion.','',
        '## Ledger and execution verification','',
        f"The receipt audit checked {sum(c.get('fills_checked',0) for c in audit['checks']):,} simulated entry/terminal fills and {sum(c.get('round_trips_checked',0) for c in audit['checks']):,} completed round trips across {len(audit['checks'])} recorded attempts."]
    lines+=['It matched each maker fill to its exact cached public print and source identity, checked later timestamps, '
        'through prices, volume caps, blackout deadlines, per-contract fill limits, fees and terminal payouts, and '
        'reconciled terminal cash and flat inventory with the ledger. Per-trip arithmetic, date/event counts and '
        'all monthly/quarterly gross/net/fee/trade totals also reconcile. Independently reconstructed filled '
        'collateral stays within the fixed limits; canceled pending orders are covered by the frozen runner '
        'checks and reported maximum, not reconstructed from fill receipts. Savepoint order/fill/position rows do not persist; '
        'hashed execution receipts survive with the durable trial and in the deterministic receipt archive. '
        'Archive members preserve the exact bytes whose hashes the audit checked; price tapes remain in the '
        'frozen local capture. Failed or zero-fill variants are never dropped. '
        'The six earlier KXCPI trials remain unchanged under their full-row hash.','',
        '## Promotion checklist and account-risk review','',
        '- Rule and behavioural-edge hypothesis: explicit favourite/longshot quoting, size/offset/fill cap and terminal exit; same reactor as paper/live.',
        '- Profit, trade counts, drawdown and regimes: disclosed for every attempt above and in the JSON; category decisions explain failed gates.',
        '- Paper/live fidelity: unproven. Historical queue priority, native PM US liquidity and fee transfer are not established.',
        '- Risk constants: unchanged. Each trial used isolated virtual collateral; requested real allocation is $0.',
        '- Decision: hold in research. No account, key, venue, capital, public-post or live-state change.','',
        '**What could blow up this account? — Tail and gap risk.** Binary terminal losses can hit several sibling strikes at once. '
        'The $25 contract collateral limit does not make event-level exposures independent, and a gap can overshoot '
        'the $50 daily halt or $56 strategy kill before orders can be canceled. The contract cap bounds funded '
        'entry exposure; it does not cap the aggregate loss across correlated contracts.','',
        '**Adverse selection.** Through-price makers may be selected '
        'by faster or better-informed flow; the scheduled blackout and three-fill cap reduce exposure but do not '
        'prove queue fills. The fixed BTC, temperature and index cohort excludes sports and discretionary '
        'insider-sensitive event intake. A settlement delay can violate the seven-day mandate and tie up collateral.','',
        '**Counterparty and venue.** Counterparty rules, rebates and product availability may differ materially from this historical scenario. '
        'Accepted Mac/network downtime and absence of dead-man/startup reconciliation remain unchanged: resting live '
        'orders could survive a failure. No withdrawal-capable keys are introduced.','',
        '**Untrusted inputs.** External payloads remain data, never instructions. No model decides entries or '
        'interprets source payloads as commands.','',
        '**Reproducibility.** Frozen source hashes and deterministic strategy code '
        'support reproducibility, while already-consumed finals are reviewed through stored receipts only. '
        'Retrospective catalog state lacks a complete point-in-time revision record, so even positive numerical '
        'results do not establish a deployable PM US edge. '
        'The [receipt audit](20-longshot-audit.py) and [report builder](20-longshot-build-report.py) '
        'are review tools and do not invoke a strategy or reopen an unconsumed final.','',
        '**Correlation.** Shared venue, event and direction exposures can coincide '
        'with other strategies and concentrate the global daily-loss risk. These five alternative studies do '
        'not model a concurrent funded portfolio or establish its combined risk.','',
        'Decision recorded 2026-10-01 by OrangeCove: hold in research, $0 real allocation, '
        'with the trial IDs and individual reasons preserved above and in the machine results.','']
    Path('docs/research/20-longshot-results.md').write_text('\n'.join(lines))
    print(json.dumps({'decisions':decision,'recorded_training_variants':len(training),'final_attempts':sum('id'in r for r in finals)},indent=2))


if __name__=='__main__':
    main()
