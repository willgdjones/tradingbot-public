from datetime import date, datetime, time, timedelta
from decimal import Decimal as D
from types import SimpleNamespace
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tradingbot.connectors.cash import MarketSession, NEW_YORK
from tradingbot.data.loader import local_engine
from tradingbot.db.models import Fill, Trial
from tradingbot.research.equity_data import Bar, EquityData
from tradingbot.research.eod_letf import run_variant, study_days, validate_data


def fixtures():
    days=[date(2023,1,3),date(2023,1,4),date(2023,1,5),date(2023,1,10)]
    sessions={d:MarketSession(d,d+timedelta(days=2),datetime.combine(d,time(9,30),NEW_YORK),datetime.combine(d,time(16),NEW_YORK)) for d in days}
    raw,adj,minutes={},{},{}
    for symbol in ['SPY','QQQ']:
        for day in days:
            ts=datetime.combine(day,time(0),NEW_YORK)
            bar=Bar(symbol,ts,D(500),D(600),D(400),D(500),D(10000))
            raw[symbol,ts]=adj[symbol,ts]=bar
            for minute in range(30,60):
                ts=datetime.combine(day,time(15,minute),NEW_YORK)
                p=D('505.5') if minute==59 else D(505)
                minutes[symbol,ts]=Bar(symbol,ts,p,D(900),D(300),D(400),D(100))
    data=EquityData(sessions,{'bars_1Day_raw':raw,'bars_1Day_all':adj,'bars_1Min_raw':minutes},'fixture-'+uuid.uuid4().hex,1,1,[])
    fx=SimpleNamespace(at=lambda ts:(D('.75'),ts.date()-timedelta(days=1)),source_hash='fixture',source_url='fixture')
    return data,fx


def test_missing_minute_is_rejected_instead_of_forward_filled():
    data,_=fixtures()
    days=study_days(data,date(2023,1,1),date(2023,1,5))
    assert validate_data(data,days)['required_minute_bars']==180
    data.bars['bars_1Min_raw'].pop(next(iter(data.bars['bars_1Min_raw'])))
    with pytest.raises(ValueError,match='missing execution bar'):
        validate_data(data,days)
    with pytest.raises(ValueError,match='restricted'):
        study_days(data,date(2022,12,30),date(2023,1,5))


def test_two_etfs_share_daily_fee_rounding_and_alternate_cash_halves():
    data,fx=fixtures()
    with local_engine().connect() as connection:
        transaction=connection.begin()
        with Session(connection,expire_on_commit=False,join_transaction_mode='create_savepoint') as session:
            result=run_variant(session,data,fx,'fixture-'+uuid.uuid4().hex[:12],('letf_1pct_2bp','.01',2,False),
                               'fixture-commit',date(2023,1,1),date(2023,1,5))
            assert 'error' not in result,result
            m=result['metrics']
            assert m['trades']==4 and m['rejected_orders']==0 and m['fees_usd']==D('.06')
            assert m['open_positions']=={} and m['signal_counts']=={'long':4}
            fills=list(session.scalars(select(Fill).where(Fill.trial_id==result['trial_id'])))
            assert all(f.metadata_['research']['cash_bucket']==(1 if f.fill_ts.date()==date(2023,1,4) else 0) for f in fills)
            assert session.get(Trial,result['trial_id']).status=='complete'
            assert max(f.fill_ts for f in fills)<session.get(Trial,result['trial_id']).holdout_start
        transaction.rollback()
