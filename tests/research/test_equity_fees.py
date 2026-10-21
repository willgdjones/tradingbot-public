from datetime import date
from decimal import Decimal as D

from tradingbot.research.equity_fees import EquityFeeBook


def test_daily_fee_type_aggregation_for_fractional_round_trip():
    fees=EquityFeeBook();day=date(2026,9,30)
    buy,_=fees.charge(day=day,side='buy',price=D('500'),size=D('.05'))
    sell,_=fees.charge(day=day,side='sell',price=D('501'),size=D('.05'))
    assert buy==D('.01') and sell==D('.02')
    again,_=fees.charge(day=day,side='sell',price=D('501'),size=D('.05'))
    assert again==0  # same account/day does not pay three more minimum pennies
    tomorrow,_=fees.charge(day=date(2026,10,1),side='sell',price=D('501'),size=D('.05'))
    assert tomorrow==D('.03')


def test_fee_preview_does_not_spend_or_advance_rounding_and_cap_applies():
    fees=EquityFeeBook();args=dict(day=date(2026,9,30),side='sell',price=D('1'),size=D('100000'))
    preview,evidence=fees.charge(**args,commit=False)
    assert not fees.totals and evidence['raw']['taf']=='9.79'
    charged,_=fees.charge(**args)
    assert charged==preview
