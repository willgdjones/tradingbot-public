from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import json

import pytest

from tradingbot.data.alpaca_history import capture_bars
from tradingbot.research.equity_data import ReferenceFX, load_equities


def test_archive_requires_complete_capture_and_preserves_prices(tmp_path):
    row = {'t': '2026-09-29T04:00:00Z', 'o': 660.12, 'h': 661.1,
           'l': 659.2, 'c': 660.19, 'v': 100}
    payload = json.dumps({'bars': {'SPY': [row]}, 'next_page_token': None})
    capture_bars(lambda _: payload, tmp_path, 'ok', symbols=['SPY'],
                 timeframe='1Day', start='2026-09-29', end='2026-09-30')
    data = load_equities(tmp_path, 'ok')
    assert list(data.daily('SPY').values())[0].close == Decimal('660.19')
    partial = payload.replace('null', '"next"')
    capture_bars(lambda _: partial, tmp_path, 'partial', symbols=['SPY'],
                 timeframe='1Day', start='2026-09-29', end='2026-09-30', max_pages=1)
    with pytest.raises(ValueError, match='partial'):
        load_equities(tmp_path, 'partial')


def test_fx_uses_strictly_prior_reference_date_and_checks_hash(tmp_path):
    path = tmp_path / 'fx.xml'
    body = b'<root><Cube time="2026-09-28"><Cube currency="USD" rate="1.2"/><Cube currency="GBP" rate="0.9"/></Cube><Cube time="2026-09-29"><Cube currency="USD" rate="1.1"/><Cube currency="GBP" rate="0.8"/></Cube></root>'
    path.write_bytes(body)
    path.with_suffix('.json').write_text(json.dumps({'sha256': hashlib.sha256(body).hexdigest(), 'url': 'fixture'}))
    fx = ReferenceFX(path)
    rate, day = fx.at(datetime(2026, 9, 29, 20, tzinfo=UTC))
    assert rate == Decimal('.75') and day.isoformat() == '2026-09-28'
    with pytest.raises(ValueError, match='missing prior'):
        fx.at(datetime(2026, 10, 9, tzinfo=UTC))
    path.write_bytes(body + b' ')
    with pytest.raises(ValueError, match='checksum'):
        ReferenceFX(path)
