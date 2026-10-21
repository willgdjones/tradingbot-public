from datetime import date
import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from tradingbot.data.alpaca_history import bars_page, capture_bars, monthly_cycles
from tradingbot.data.archive import Request


def test_symbol_first_pagination_is_exhausted_and_decimal_text_preserved(tmp_path):
    responses = [
        '{"bars":{"QQQ":[{"t":"2023-01-03T05:00:00Z","o":264.123456789}]},"next_page_token":"SPY-next"}',
        '{"bars":{"SPY":[{"t":"2023-01-03T05:00:00Z","o":380.01}]},"next_page_token":null}',
    ]
    seen=[]
    def get(request):
        seen.append(request)
        return responses[len(seen)-1]
    progress=capture_bars(get,tmp_path,'test',symbols=['SPY','QQQ'],timeframe='1Day',start='2023-01-03',end='2023-01-04')
    assert progress.complete and progress.pages_written==2 and progress.records_written==2
    assert seen[1].params['page_token']=='SPY-next'
    first=pq.read_table(progress.directory/'page-00000000.parquet').to_pylist()[0]
    assert first['response_json']==responses[0]
    again=capture_bars(get,tmp_path,'test',symbols=['QQQ','SPY'],timeframe='1Day',start='2023-01-03',end='2023-01-04')
    assert again.pages_written==0 and len(seen)==2


def test_repeated_bar_page_stops_capture(tmp_path):
    def get(request):
        return json.dumps({'bars':{'SPY':[{'t':'2023-01-03T05:00:00Z'}]},'next_page_token':'next' if 'page_token' not in request.params else 'another'})
    with pytest.raises(ValueError,match='repeated record page'):
        capture_bars(get,tmp_path,'test',symbols=['SPY'],timeframe='1Day',start='2023-01-03',end='2023-01-04')


def test_partial_capture_is_explicit(tmp_path):
    payload='{"bars":{"SPY":[{"t":"2023-01-03T05:00:00Z"}]},"next_page_token":"next"}'
    result=capture_bars(lambda _:payload,tmp_path,'test',symbols=['SPY'],timeframe='1Day',start='2023-01-03',end='2023-01-04',max_pages=1)
    assert not result.complete


def test_calendar_window_uses_trading_days_not_weekdays_and_excludes_unfinished():
    rows=[{'date':d} for d in ['2026-01-23','2026-01-26','2026-01-27','2026-01-28','2026-01-29','2026-01-30','2026-02-02','2026-02-03','2026-02-04']]
    assert monthly_cycles(rows,date(2026,2,3))==[]
    result=monthly_cycles(rows,date(2026,2,4))
    assert [(a['date'],b['date']) for a,b in result]==[('2026-01-27','2026-02-04')]


def test_missing_cursor_is_not_mistaken_for_complete():
    with pytest.raises(ValueError,match='malformed'):
        bars_page(Request('example',{}),{'bars':{}})


def test_letf_capture_restricts_years_and_skips_early_closes(tmp_path,monkeypatch):
    from dataclasses import dataclass
    import tradingbot.data.alpaca_history as module
    @dataclass
    class Progress:
        complete: bool = True
    calls=[]
    calendar=[{'date':'2023-07-03','close':'13:00'}, {'date':'2023-07-05','close':'16:00'}]
    monkeypatch.setattr(module,'capture_calendar',lambda *a,**k:(Progress(),calendar))
    monkeypatch.setattr(module,'capture_actions',lambda *a,**k:Progress())
    def capture(*a,**kwargs):
        calls.append(kwargs)
        return Progress()
    monkeypatch.setattr(module,'capture_bars',capture)
    with pytest.raises(ValueError,match='2023'):
        module.letf_capture(None,tmp_path,'test','2022-12-30','2023-07-05')
    module.letf_capture(None,tmp_path,'test','2023-01-01','2023-07-05')
    minute=[c for c in calls if c['timeframe']=='1Min']
    assert len(minute)==1
    assert minute[0]['start']=='2023-07-05T15:29:00-04:00'
    assert minute[0]['end']=='2023-07-05T15:59:59.999999-04:00'
    assert minute[0]['symbols']==['SPY','QQQ']
