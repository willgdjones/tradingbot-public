"""Validated Alpaca bar/calendar archives and dated ECB reference FX."""
from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pyarrow.parquet as pq

from tradingbot.connectors.cash import MarketSession
from tradingbot.data.archive import SCHEMA, canonical
from tradingbot.data.normalize import number, required_time


@dataclass(frozen=True)
class Bar:
    symbol: str
    time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    @classmethod
    def from_raw(cls, symbol, row):
        values = [number(row[key], positive=True) for key in ('o', 'h', 'l', 'c')]
        volume = number(row['v'])
        if volume < 0 or values[1] < values[2]:
            raise ValueError('invalid bar range or volume')
        return cls(symbol, required_time(row['t']), *values, volume)


@dataclass
class EquityData:
    sessions: dict[date, MarketSession]
    bars: dict[str, dict[tuple[str, datetime], Bar]]
    source_hash: str
    source_pages: int
    source_records: int
    actions: list[dict]

    def daily(self, symbol, adjustment='raw') -> dict[date, Bar]:
        from tradingbot.data.alpaca_history import NY
        return {bar.time.astimezone(NY).date(): bar
                for (s, _), bar in self.bars.get('bars_1Day_' + adjustment, {}).items() if s == symbol}

    def minute(self, symbol, time: datetime) -> Bar:
        try:
            return self.bars['bars_1Min_raw'][(symbol, time.astimezone(UTC))]
        except KeyError:
            raise ValueError(f'missing execution bar: {symbol} {time.isoformat()}') from None


def load_equities(root: Path, run: str) -> EquityData:
    sessions, bars, hashes = {}, {}, []
    records = pages = 0
    actions = []
    manifests = sorted(root.glob('raw/alpaca/*/' + run + '/*/manifest.json'))
    if not manifests:
        raise ValueError('no matching equity archives')
    for path in manifests:
        manifest = json.loads(path.read_text())
        if hashlib.sha256(canonical(manifest).encode()).hexdigest()[:24] != path.parent.name:
            raise ValueError('archive identity mismatch')
        request = canonical(manifest['request'])
        files = sorted(path.parent.glob('page-*.parquet'))
        if not files:
            raise ValueError('empty/incomplete capture')
        seen = set()
        for index, file in enumerate(files):
            table = pq.read_table(file)
            if table.num_rows != 1 or not table.schema.equals(SCHEMA) or file.name != f'page-{index:08d}.parquet':
                raise ValueError('invalid archive sequence/schema')
            row = table.to_pylist()[0]
            if (row['format_version'] != 1 or row['venue'] != 'alpaca' or row['dataset'] != manifest['dataset']
                    or row['page'] != index or row['request_json'] != request or request in seen):
                raise ValueError('broken archive request chain')
            if hashlib.sha256(row['response_json'].encode()).hexdigest() != row['response_sha256']:
                raise ValueError('archive checksum mismatch')
            payload = json.loads(row['response_json'], parse_float=Decimal)
            if row['dataset'] == 'calendar':
                for raw in payload:
                    session = MarketSession.from_api(raw)
                    if session.trade_date in sessions and sessions[session.trade_date] != session:
                        raise ValueError('conflicting calendars')
                    sessions[session.trade_date] = session
                count = len(payload)
            elif row['dataset'] == 'corporate_actions':
                count = 0
                for kind, rows in payload['corporate_actions'].items():
                    actions.extend({'kind': kind, **raw} for raw in rows)
                    count += len(rows)
            else:
                target = bars.setdefault(row['dataset'], {})
                count = 0
                for symbol, rows in payload['bars'].items():
                    for raw in rows:
                        bar = Bar.from_raw(symbol, raw)
                        key = symbol, bar.time
                        if key in target and target[key] != bar:
                            raise ValueError('conflicting bar identity')
                        target[key] = bar
                        count += 1
            if count != row['record_count']:
                raise ValueError('archive record-count mismatch')
            seen.add(request)
            request = row['next_request_json']
            hashes.append(row['response_sha256'])
            records += count
            pages += 1
        if request is not None:
            raise ValueError('partial equity capture cannot be backtested')
    return EquityData(sessions, bars, hashlib.sha256(canonical(hashes).encode()).hexdigest(), pages, records, actions)


class ReferenceFX:
    """ECB GBP/EUR divided by USD/EUR; use a strictly previous reference day."""
    def __init__(self, path: Path):
        body = path.read_bytes()
        meta = json.loads(path.with_suffix('.json').read_text())
        if hashlib.sha256(body).hexdigest() != meta['sha256']:
            raise ValueError('FX source checksum mismatch')
        self.source_hash, self.source_url = meta['sha256'], meta['url']
        self.rates = {}
        for cube in ET.fromstring(body).iter():
            if 'time' not in cube.attrib:
                continue
            currencies = {child.attrib['currency']: Decimal(child.attrib['rate']) for child in cube}
            if 'USD' in currencies and 'GBP' in currencies:
                day = date.fromisoformat(cube.attrib['time'])
                rate = (currencies['GBP'] / currencies['USD']).quantize(Decimal('.00000001'))
                if not rate.is_finite() or rate <= 0 or day in self.rates:
                    raise ValueError('invalid FX history')
                self.rates[day] = rate
        self.days = sorted(self.rates)
        if not self.days:
            raise ValueError('empty FX history')

    def at(self, ts: datetime) -> tuple[Decimal, date]:
        day = ts.astimezone(UTC).date()
        index = bisect_left(self.days, day) - 1
        if index < 0 or day - self.days[index] > timedelta(days=7):
            raise ValueError('missing prior-day FX reference')
        reference = self.days[index]
        return self.rates[reference], reference
