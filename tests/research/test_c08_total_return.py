"""Total-return C08 holds continuous units across actions without bypassing risk."""
from copy import deepcopy
from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from test_c08_inventory import db, database_setup, synthetic_source
from tradingbot.research import c08_inventory as prior
from tradingbot.research import c08_total_return as replay


def adjusted_fixture():
    source, split = synthetic_source()
    original = deepcopy(source)
    bars = [SimpleNamespace(date=date.fromisoformat(r['date']), open=D(r['open']),
            close=D(r['close']), adj_close=D(r['uso_split_continuous_close']))
            for r in source['prices']]
    replay.adjusted_source(source, bars)
    return source, split, original, bars


def test_conversion_preserves_reports_calendar_and_all_sessions():
    source, _, original, _ = adjusted_fixture()
    assert source['releases'] == original['releases']
    assert source['exposure_regimes'] == original['exposure_regimes']
    assert source['blackouts'] == []
    assert len(source['prices']) == len(original['prices'])
    for row, old in zip(source['prices'], original['prices']):
        assert D(row['open']) == D(row['close']) == D(old['uso_split_continuous_close'])
        for key in ('opens_at', 'closes_at', 'scheduled_t1', 'conservative_cash_release'):
            assert row[key] == old[key]


def test_missing_and_duplicate_primary_sessions_fail():
    source, _, _, bars = adjusted_fixture()
    for bad in (bars[:-1], bars + bars[:1]):
        with pytest.raises(ValueError, match='sessions'):
            replay.adjusted_source(deepcopy(source), bad)


def runtime_fixture(db, monkeypatch):
    source, split, _, _ = adjusted_fixture()
    sid, ids, fx = database_setup(db)
    monkeypatch.setattr(prior, 'split_for', lambda _: split)
    bot = replay.TotalReturnInventory(prior.strategy_params(source, *ids, '0'))
    runtime = replay.TotalReturnBacktester(db, strategy=bot, strategy_id=sid, source=source, fx=fx)
    return source, split, bot, runtime


def test_continuous_units_cross_split_without_blackout_or_double_return(db, monkeypatch):
    source, split, bot, runtime = runtime_fixture(db, monkeypatch)
    observed = []
    result = runtime.run(replay.events(source, bot.params, 10, False, observed), split=split)
    metrics, trips, fills = prior.finish_metrics(db, result, runtime, expected_trips=1)
    assert result.fills == 2 and result.orders_rejected == 0
    assert fills[0].size == fills[1].size and fills[0].price == D('80.08')
    assert fills[1].price == D('92.907') and D(0) < metrics['net_usd'] < D(23)
    assert all(f.metadata_['research']['units'] == 'virtual_total_return_equivalent' for f in fills)
    details = prior.diagnostics(bot, source, observed, trips, fills, runtime, False)
    assert details['blackout']['count'] == 0
    assert details['terminal_liquidation_fills'] == 1
    assert observed[0].meta['research_revision'] == replay.REVISION


def test_permanent_kill_still_vetoes_exit_and_reports_open_marked_loss(db, monkeypatch):
    source, split, bot, runtime = runtime_fixture(db, monkeypatch)
    for row in source['prices'][2:]:
        row['open'] = row['close'] = '1'
    result = runtime.run(replay.events(source, bot.params, 10, False, []), split=split)
    metrics, _, _ = prior.finish_metrics(db, result, runtime, allow_rejections=True, require_flat=False)
    assert runtime.killed and result.orders_rejected > 0
    assert metrics['open_positions'] and metrics['unrealized_pnl_usd'] < -D(130)
    assert metrics['ending_marked_equity_usd'] < 10
    assert runtime.now.date() == date(2020, 5, 4)
