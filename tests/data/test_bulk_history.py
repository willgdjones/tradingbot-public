import json
from pathlib import Path

from tradingbot.data.archive import RawArchive, Request, cursor_pages
from tradingbot.data.bulk_history import (BASE, CATALOG_RUN, DATA, START, END, Job,
                                        btc_catalog_jobs, build_cohort, capture_jobs, trade_jobs)


def test_daily_cohort_dates_and_nonzero_or_unknown_volume():
    jobs = list(btc_catalog_jobs())
    assert len(jobs) == (END - START).days * 2
    assert jobs[0].params['event_ticker'] == 'KXBTC-25SEP0117'
    assert jobs[-1].params['event_ticker'] == 'KXBTC-26SEP3017'
    base = {'venue': 'kalshi', 'contract': 'X', 'close': START.isoformat(),
            'status': 'finalized', 'volume': '0'}
    assert list(trade_jobs([base])) == []
    for volume in [None, '0.01', '100']:
        pair = list(trade_jobs([{**base, 'volume': volume}]))
        assert len(pair) == 2
        assert pair[0].params['min_ts'] < START.timestamp() - 7 * 86400
        assert pair[0].params['max_ts'] > START.timestamp()
    assert len(list(trade_jobs([{**base, 'status': 'active'}]))) == 2


def test_pm_job_requests_only_actual_takers_and_no_fake_date_bounds():
    job, = trade_jobs([{'venue': 'polymarket_intl', 'contract': 'condition'}])
    assert job.url == DATA + '/v2/trades'
    assert job.params == {'condition': 'condition', 'taker_only': True, 'limit': 1000}


def test_cohort_keeps_winners_losers_zero_volume_and_missing_settlement(tmp_path):
    rows = []
    for i, result in enumerate(['yes', 'no', '']):
        rows.append({'ticker': f'KXHIGHNY-X-{i}', 'event_ticker': 'KXHIGHNY-X',
                     'close_time': START.isoformat(), 'result': result, 'status': 'finalized',
                     'volume_fp': '0'})
    rows.append({**rows[0], 'ticker': 'outside', 'close_time': END.isoformat()})
    archive = RawArchive(tmp_path, 'kalshi', 'markets_historical', CATALOG_RUN,
                         Request(BASE + '/historical/markets', {'series_ticker': 'KXHIGHNY'}), semantics='test')
    archive.capture(lambda _: json.dumps({'markets': rows, 'cursor': ''}), cursor_pages('markets'))
    cohort = build_cohort(tmp_path)
    assert {c['contract'] for c in cohort} == {'KXHIGHNY-X-0', 'KXHIGHNY-X-1', 'KXHIGHNY-X-2'}
    assert all(c['volume'] == '0' for c in cohort)


def test_capture_resumes_partial_then_caches_complete(monkeypatch, tmp_path):
    calls = []
    class API:
        def __call__(self, request):
            calls.append(request)
            return json.dumps({'trades': [], 'cursor': '' if request.params.get('cursor') else 'next'})
        def close(self):
            pass
    monkeypatch.setattr('tradingbot.data.bulk_history.KalshiPublic', API)
    job = Job('kalshi', 'trades_historical', 'test', BASE + '/historical/trades',
              {'ticker': 'test'}, 'test')
    state_path = tmp_path / 'capture.json'
    state = capture_jobs(tmp_path, [job], state_path=state_path, workers=1, max_pages=1)
    assert state[job.key]['complete'] is False
    state = capture_jobs(tmp_path, [job], state_path=state_path, workers=1, max_pages=1)
    assert state[job.key]['complete'] is True
    capture_jobs(tmp_path, [job], state_path=state_path, workers=1, max_pages=1)
    assert len(calls) == 2
    assert calls[1].params['cursor'] == 'next'


def test_worker_reuses_connection_across_batches_and_closes_on_error(monkeypatch, tmp_path):
    import pytest
    from tradingbot.data.transport import FetchError
    clients = []
    class API:
        def __init__(self):
            self.calls, self.closed = 0, False
            clients.append(self)
        def __call__(self, request):
            assert not self.closed
            self.calls += 1
            if request.params['ticker'] == 'bad':
                raise FetchError(400)
            return '{"trades": [], "cursor": ""}'
        def close(self):
            self.closed = True
    monkeypatch.setattr('tradingbot.data.bulk_history.KalshiPublic', API)
    monkeypatch.setattr('tradingbot.data.bulk_history.Pace.wrap', lambda self, get: get)
    def job(ticker):
        return Job('kalshi', 'trades_historical', 'test', BASE + '/historical/trades',
                   {'ticker': ticker}, 'test')
    jobs = [job(str(i)) for i in range(34)]
    state = capture_jobs(tmp_path, jobs, state_path=tmp_path/'state.json', workers=1)
    assert len(state) == 34 and len(clients) == 1
    assert clients[0].calls == 34 and clients[0].closed
    with pytest.raises(FetchError):
        capture_jobs(tmp_path, [job('bad')], state_path=tmp_path/'bad.json', workers=1)
    assert len(clients) == 2 and all(c.closed for c in clients)
