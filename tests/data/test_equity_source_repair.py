from datetime import UTC, datetime
from decimal import Decimal

import pytest

from tradingbot.data.equity_source_repair import primary_closing_price, primary_opening_price

CLOSE = datetime(2025, 4, 9, 20, tzinfo=UTC)


def trade(price='548.62', *, exchange='P', conditions=(' ', '6'), time='2025-04-09T20:00:00.275268096Z'):
    return {'p': price, 'x': exchange, 'c': list(conditions), 't': time}


def test_primary_auction_is_not_last_trade_or_other_venue_close():
    rows = [trade('542.955', exchange='V', conditions=('@',)),
            trade('543.54', exchange='T', conditions=(' ', 'M')),
            trade('544.30', conditions=(' ', 'T')), trade(),
            trade(conditions=(' ', 'M')), trade()]
    assert primary_closing_price(rows, CLOSE, 'P') == Decimal('548.62')


@pytest.mark.parametrize('rows', [[], [trade(conditions=('@',))],
    [trade(exchange='T')], [trade(conditions=('6','T'))],
    [trade(time='2025-04-09T19:59:59Z')],
    [trade(time='2025-04-09T20:00:10Z')],
    [trade(), trade('548.63', conditions=('M',))], [trade('NaN')]])
def test_missing_ambiguous_or_invalid_evidence_cannot_pass(rows):
    with pytest.raises(ValueError):
        primary_closing_price(rows, CLOSE, 'P')


def test_opening_auction_uses_primary_trade_and_rejects_official_conflict():
    opened = datetime(2016,11,7,14,30,tzinfo=UTC)
    primary = trade('211.47',conditions=(' ', 'O'),time='2016-11-07T14:30:00.243Z')
    other = trade('211.45',exchange='T',conditions=(' ', 'O','X'),time='2016-11-07T14:30:00.05Z')
    assert primary_opening_price([other,primary,primary],opened,'P') == Decimal('211.47')
    with pytest.raises(ValueError,match='conflicting'):
        primary_opening_price([primary,{**primary,'c':['Q'],'p':'211.48'}],opened,'P')
    with pytest.raises(ValueError,match='missing'):
        primary_opening_price([other],opened,'P')
