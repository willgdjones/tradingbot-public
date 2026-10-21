"""Archive checks plus transactional tests against the existing local schema."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import json
import os
from pathlib import Path
import uuid
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from tradingbot.data.archive import RawArchive, Request, SCHEMA, canonical
from tradingbot.data.loader import Page, checked_fields, import_page, local_engine, read_archives, same_source_value
from tradingbot.data.normalize import ImportDataError
from tradingbot.db.models import Instrument, Market, Quote, Trade, Venue


@pytest.fixture
def session():
    if os.environ.get('RUN_DB_TESTS') != '1':
        pytest.skip('set RUN_DB_TESTS=1 for rollback-only local DB integration checks')
    engine = local_engine()
    with engine.connect() as connection:
        transaction = connection.begin()
        with Session(connection, expire_on_commit=False) as session:
            yield session
        transaction.rollback()


def page(venue='kalshi', dataset='markets_historical', payload=None, params=None, time=None):
    from hashlib import sha256
    body = canonical(payload or {})
    return Page(Path('fixture/page-00000000.parquet'), {'semantics': 'test fixture'},
                {'venue': venue, 'dataset': dataset, 'retrieved_at': time or datetime(2026, 9, 30, tzinfo=UTC),
                 'page': 0, 'request_json': canonical({'params': params or {}}),
                 'response_json': body, 'response_sha256': sha256(body.encode()).hexdigest()}, True)


def kalshi_catalog(ticker, status='active', **updates):
    return page(payload={'markets': [{'ticker': ticker, 'event_ticker': ticker + '-event', 'status': status, **updates}]})


def trade_page(ticker, trade_id='one', **updates):
    return page(dataset='trades_historical', payload={'trades': [{
        'ticker': ticker, 'trade_id': trade_id, 'created_time': '2026-08-01T00:00:00Z',
        'yes_price_dollars': '.31', 'no_price_dollars': '.69', 'count_fp': '1.25',
        'taker_side': 'yes', **updates}]})


def test_archive_validation_rejects_corruption_before_loading(tmp_path):
    archive = RawArchive(tmp_path, 'kalshi', 'cutoff', 'test', Request('https://example.test', {}), semantics='fixture')
    archive.capture(lambda _: '{}', lambda *_: (1, None))
    assert read_archives(tmp_path)[0].complete
    file = next(archive.directory.glob('page-*.parquet'))
    row = pq.read_table(file).to_pylist()[0]
    row['response_json'] = '{"tampered":true}'
    pq.write_table(pa.Table.from_pylist([row], schema=SCHEMA), file)
    with pytest.raises(ImportDataError, match='checksum'):
        read_archives(tmp_path)


def test_partial_capture_is_explicit_and_chain_must_match(tmp_path):
    request = Request('https://example.test', {})
    archive = RawArchive(tmp_path, 'kalshi', 'cutoff', 'test', request, semantics='fixture')
    archive.capture(lambda _: '{}', lambda *_: (1, Request(request.url, {'cursor': 'next'})), max_pages=1)
    assert not read_archives(tmp_path)[0].complete
    file = next(archive.directory.glob('page-*.parquet'))
    row = pq.read_table(file).to_pylist()[0]
    row['request_json'] = Request(request.url, {'wrong': True}).to_json()
    pq.write_table(pa.Table.from_pylist([row], schema=SCHEMA), file)
    with pytest.raises(ImportDataError, match='chain'):
        read_archives(tmp_path)


@pytest.mark.parametrize('value', ['0.123456789', '10000000000'])
def test_numeric_precision_never_rounds(value):
    with pytest.raises(ImportDataError, match='exactly'):
        checked_fields(Quote, {'bid': Decimal(value)})
    checked_fields(Trade, {'price': Decimal('.997952381'), 'size': Decimal('1.12345678901234')})


def test_reruns_overlaps_and_outside_window_conflicts(session):
    ticker = 'LOAD-' + uuid.uuid4().hex[:10]
    cat = kalshi_catalog(ticker)
    assert import_page(session, cat).references_changed == 3
    assert import_page(session, cat).references_changed == 0
    trade = trade_page(ticker)
    first = import_page(session, trade)
    assert first.trades_inserted == 2
    overlap = replace(trade, path=Path('another-run/page-00000000.parquet'))
    again = import_page(session, overlap)
    assert again.trades_inserted == 0 and again.points_skipped == 2
    with pytest.raises(ImportDataError, match='conflicting'):
        import_page(session, trade_page(ticker, created_time='2026-08-02T00:00:00Z'))
    rows = list(session.scalars(select(Trade).join(Instrument, Trade.instrument_id == Instrument.id).where(Instrument.external_id.in_([ticker + ':yes', ticker + ':no']))))
    assert len(rows) == 2
    assert {t.price for t in rows} == {Decimal('.31'), Decimal('.69')}
    assert all(t.size == Decimal('1.25') for t in rows)


def test_timestamp_identity_uses_instant_across_dst_folds():
    first = datetime(2025, 11, 2, 1, 49, 33, tzinfo=ZoneInfo('America/Los_Angeles'), fold=0)
    second = first.replace(fold=1)
    assert first == second  # Python's same-zone wall-time comparison.
    assert second != second.astimezone(UTC)  # Python's cross-zone fold exception.
    assert not same_source_value(first, second)
    assert same_source_value(first, first.astimezone(UTC))
    assert same_source_value(second, second.astimezone(UTC))
    assert not same_source_value(second, second.astimezone(UTC) + timedelta(microseconds=1))
    assert not same_source_value(second, second.replace(tzinfo=None))


@pytest.mark.parametrize('stamp', ['2025-11-02T08:49:33Z','2025-11-02T09:49:33Z'])
def test_actual_postgres_dst_rerun_keeps_identity_and_rejects_changed_instant(session, stamp):
    session.execute(text("SET LOCAL TIME ZONE 'America/Los_Angeles'"))
    ticker = 'LOAD-' + uuid.uuid4().hex[:10]
    import_page(session, kalshi_catalog(ticker))
    source = trade_page(ticker, created_time=stamp)
    assert import_page(session, source).trades_inserted == 2
    session.expire_all()  # Force PostgreSQL's session-zone timestamp conversion.
    again = import_page(session, source)
    assert again.trades_inserted == 0 and again.points_skipped == 2
    other = '2025-11-02T09:49:33Z' if '08:49' in stamp else '2025-11-02T08:49:33Z'
    with pytest.raises(ImportDataError, match='conflicting'):
        import_page(session, trade_page(ticker, created_time=other))


def test_unknown_instrument_rolls_back_whole_page(session):
    ticker = 'LOAD-' + uuid.uuid4().hex[:10]
    source = kalshi_catalog(ticker)
    batch = source.normalized()
    batch.points.extend(trade_page('missing-' + ticker).normalized().points)
    with pytest.raises(ImportDataError, match='missing instrument'):
        with session.begin_nested():
            import_page(session, source, batch)
    assert not session.scalar(select(Instrument.id).where(Instrument.external_id == ticker + ':yes'))
    assert not session.scalar(select(Market.id).where(Market.external_id == ticker + '-event'))


def test_old_catalog_does_not_downgrade_state_or_erase_other_metadata(session):
    ticker = 'LOAD-' + uuid.uuid4().hex[:10]
    old = kalshi_catalog(ticker)
    new = kalshi_catalog(ticker, status='finalized', result='yes')
    new = replace(new, row={**new.row, 'retrieved_at': old.row['retrieved_at'] + timedelta(days=1)})
    import_page(session, new)
    inst = session.scalar(select(Instrument).where(Instrument.external_id == ticker + ':yes'))
    inst.metadata_ = {**inst.metadata_, 'other_app': {'keep': True}}
    import_page(session, old)
    assert inst.metadata_['other_app'] == {'keep': True}
    assert inst.metadata_['historical']['state']['payout'] == '1'
    market = session.get(Market, inst.market_id)
    assert market.status == 'settled'
    assert len(inst.metadata_['historical']['snapshots']) == 2


def test_repeated_page_references_keep_all_snapshots_and_latest_source_state(session):
    ticker = 'LOAD-' + uuid.uuid4().hex[:10]
    newer = {'ticker': ticker, 'event_ticker': ticker + '-event', 'status': 'finalized',
             'result': 'yes', 'updated_time': '2026-09-29T00:00:00Z'}
    older = {**newer, 'result': 'no', 'updated_time': '2026-09-28T00:00:00Z'}
    source = page(payload={'markets': [newer, older, newer]})
    # A page can repeat an entity; batching must preserve both evidence versions
    # without creating duplicate ORM objects or allowing input order to win.
    assert import_page(session, source).references_changed == 5
    inst = session.scalar(select(Instrument).where(Instrument.external_id == ticker + ':yes'))
    assert inst.metadata_['historical']['state']['payout'] == '1'
    assert len(inst.metadata_['historical']['snapshots']) == 2
    assert import_page(session, source).references_changed == 0
    assert len(list(session.scalars(select(Instrument).where(Instrument.market_id == inst.market_id)))) == 2


def test_venue_scoping_sampled_prices_and_settlement_precedence(session):
    slug = 'load-' + uuid.uuid4().hex[:10]
    raw = {'slug': slug, 'outcomes': ['Yes', 'No'], 'closed': False}
    us = page('polymarket_us', 'markets', {'markets': [raw]})
    import_page(session, us)
    intl = page('polymarket_intl', 'markets', {'markets': [{**raw, 'conditionId': slug, 'clobTokenIds': [slug + ':yes', slug + ':no']}]})
    import_page(session, intl)
    ids = list(session.scalars(select(Instrument.id).where(Instrument.external_id == slug + ':yes')))
    assert len(set(ids)) == 2
    sampled = page('polymarket_us', 'display_prices', {'history': [{'timestamp': 100, 'longPrice': '.4', 'shortPrice': '.61'}]}, {'symbol': slug})
    assert import_page(session, sampled).quotes_inserted == 2
    assert import_page(session, sampled).points_skipped == 2
    rows = list(session.scalars(select(Quote).where(Quote.instrument_id.in_(ids))))
    assert len(rows) == 1 and rows[0].bid is rows[0].ask is rows[0].last is None
    assert rows[0].metadata_['historical']['price'] == '0.4'
    assert not rows[0].metadata_['historical']['maker_fill_eligible']
    settled = page('polymarket_us', 'settlements', {'slug': slug, 'settlement': '.25'})
    import_page(session, settled)
    newer = replace(us, row={**us.row, 'retrieved_at': us.row['retrieved_at'] + timedelta(days=2)})
    import_page(session, newer)
    venue_id = session.scalar(select(Venue.id).where(Venue.key == 'polymarket_us'))
    market = session.scalar(select(Market).where(Market.external_id == slug, Market.venue_id == venue_id))
    inst = session.scalar(select(Instrument).where(Instrument.external_id == slug + ':yes', Instrument.venue_id == venue_id))
    assert market.status == 'settled'
    assert inst.metadata_['historical']['state']['payout'] == '0.25'


def test_legacy_decimal_fingerprint_is_upgraded_without_duplicate_rows(session):
    from tradingbot.data.normalize import digest
    slug = 'load-' + uuid.uuid4().hex[:10]
    catalog = page('polymarket_intl', 'markets', {'markets': [{
        'slug': slug, 'conditionId': slug, 'outcomes': ['Yes', 'No'],
        'clobTokenIds': [slug + ':yes', slug + ':no'], 'closed': False}]})
    import_page(session, catalog)
    raw = {'token_id': slug + ':yes', 'timestamp': 100, 'size': '5.0', 'price': '.20',
           'side': 'SELL', 'transaction_hash': 'tx', 'proxy_wallet': 'wallet',
           'condition_id': slug, 'outcome_index': 0}
    source = page('polymarket_intl', 'trades_recent', {'data': [raw]})
    batch = source.normalized()
    point = batch.points[0]
    canonical_key = point.key
    # Exact v1 key representation prior to scale-independent numeric identities.
    stable = {k: raw[k] for k in ('transaction_hash', 'proxy_wallet', 'condition_id', 'side', 'outcome_index')}
    stable.update(token_id=raw['token_id'], **{k: v for k, v in point.fields.items() if k != 'external_trade_id'})
    point.key = point.fields['external_trade_id'] = 'pm-intl:' + digest(stable)
    assert point.key != canonical_key
    assert import_page(session, source, batch).trades_inserted == 1
    result = import_page(session, source)
    assert result.identities_updated == 1 and result.trades_inserted == 0 and result.points_skipped == 1
    assert import_page(session, source).identities_updated == 0


def test_exact_taker_tape_survives_compression_and_rerun(session):
    slug = 'load-' + uuid.uuid4().hex[:10]
    catalog = page('polymarket_intl', 'markets', {'markets': [{
        'slug': slug, 'conditionId': slug, 'outcomes': ['Yes', 'No'],
        'clobTokenIds': [slug + ':yes', slug + ':no'], 'closed': False}]})
    import_page(session, catalog)
    raw = {'token_id': slug + ':yes', 'timestamp': 100,
           'size': '5.123456789012345678901', 'price': '0.9709999996000000001',
           'side': 'SELL', 'transaction_hash': 'tx', 'proxy_wallet': 'wallet',
           'condition_id': slug, 'outcome_index': 0}
    source = page('polymarket_intl', 'trades_taker_history', {'data': [raw]},
                  {'condition': slug, 'taker_only': True})
    request = json.loads(source.row['request_json'])
    request['url'] = 'https://data-api.polymarket.com/v2/trades'
    source = replace(source, row={**source.row, 'request_json': canonical(request)})
    assert import_page(session, source).trades_inserted == 1
    chunk = session.scalar(text("""SELECT format('%I.%I', chunk_schema, chunk_name)
        FROM timescaledb_information.chunks
        WHERE hypertable_name='trades' AND range_start <= to_timestamp(100)
          AND range_end > to_timestamp(100)"""))
    session.execute(text('SELECT compress_chunk(CAST(:chunk AS regclass))'), {'chunk': chunk})
    session.expire_all()
    row = session.scalar(select(Trade).join(Instrument, Trade.instrument_id == Instrument.id)
                         .where(Instrument.external_id == slug + ':yes'))
    assert row.price == Decimal(raw['price']) and row.size == Decimal(raw['size'])
    assert row.aggressor_side == 'sell'
    assert row.metadata_['historical']['maker_fill_eligible'] is True
    again = import_page(session, source)
    assert again.points_skipped == 1 and again.trades_inserted == again.identities_updated == 0


def test_terminal_resolution_is_not_backdated_to_catalog_close(session):
    slug = 'load-' + uuid.uuid4().hex[:10]
    catalog = page('polymarket_intl', 'markets', {'markets': [{
        'slug': slug, 'conditionId': slug, 'outcomes': ['Yes', 'No'],
        'clobTokenIds': [slug + ':yes', slug + ':no'], 'closed': True,
        'umaResolutionStatus': 'resolved', 'outcomePrices': ['1', '0'],
        'endDate': '2025-09-01T12:00:00Z'}]})
    import_page(session, catalog)
    resolved = page('polymarket_intl', 'resolutions', {'data': [{
        'condition_id': slug, 'status': 'resolved', 'price': '1000000000000000000',
        'transaction_hash': 'tx', 'log_index': '52', 'last_update_timestamp': '1756796247'}]})
    import_page(session, resolved)
    # A later catalog missing resolvedTime cannot erase the terminal event time.
    import_page(session, replace(catalog, row={**catalog.row, 'retrieved_at': catalog.row['retrieved_at'] + timedelta(days=1)}))
    venue = session.scalar(select(Venue).where(Venue.key == 'polymarket_intl'))
    market = session.scalar(select(Market).where(Market.venue_id == venue.id, Market.external_id == slug))
    assert market.resolve_ts == datetime.fromtimestamp(1756796247, UTC)
    assert market.resolve_ts > market.close_ts
    instrument = session.scalar(select(Instrument).where(Instrument.venue_id == venue.id, Instrument.external_id == slug + ':yes'))
    assert instrument.metadata_['historical']['state']['payout'] == '1'
