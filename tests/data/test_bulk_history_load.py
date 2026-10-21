from pathlib import Path

import pytest

from tradingbot.data.archive import RawArchive, Request, canonical, cursor_pages
from tradingbot.data.bulk_history import BASE, Job, trade_jobs
from tradingbot.data.bulk_history_load import Cohort, capture_report, cohort_schedule
from tradingbot.data.loader import read_archives
from tradingbot.data.normalize import ImportDataError


def fixture(tmp_path, *, partial=False):
    selected = {'ticker': 'KXHIGHNY-X', 'event_ticker': 'KXHIGHNY-E', 'status': 'finalized',
                'result': 'yes', 'close_time': '2025-09-01T00:00:00Z'}
    unrelated = {'ticker': 'sports-or-unsupported', 'market_type': 'unsupported'}
    archive = RawArchive(tmp_path, 'kalshi', 'markets_historical', 'test',
                         Request('https://example.test', {'series_ticker': 'KXHIGHNY'}), semantics='test')
    archive.capture(lambda _: canonical({'markets': [selected, unrelated], 'cursor': 'more' if partial else ''}),
                    cursor_pages('markets'), max_pages=1)
    file = next(archive.directory.glob('*.parquet'))
    rows = [{'venue': 'kalshi', 'contract': 'KXHIGHNY-X', 'catalog_page': str(file),
             'category': 'KXHIGHNY', 'event_id': 'KXHIGHNY-E',
             'close': '2025-09-01T00:00:00Z', 'volume': '1', 'status': 'finalized'}]
    return Cohort(rows), file


def test_loader_filters_out_of_cohort_before_normalizing(tmp_path):
    cohort, file = fixture(tmp_path)
    page = read_archives(file.parent)[0]
    batch = cohort.catalog_batch(page)
    assert len(batch.references) == 3
    assert {r.external_id for r in batch.references} == {'KXHIGHNY-E', 'KXHIGHNY-X:yes', 'KXHIGHNY-X:no'}


def test_missing_capture_fails_closed_or_is_explicit_incremental(tmp_path):
    cohort, file = fixture(tmp_path)
    with pytest.raises(ImportDataError, match='missing/incomplete'):
        cohort.pages(tmp_path)
    catalogs, resolutions, trades, missing = cohort.pages(tmp_path, allow_incomplete=True)
    assert len(catalogs) == 1 and not resolutions and not trades and len(missing) == 2


def test_partial_catalog_cannot_define_complete_cohort(tmp_path):
    cohort, file = fixture(tmp_path, partial=True)
    with pytest.raises(ImportDataError, match='incomplete catalog'):
        cohort.pages(tmp_path, allow_incomplete=True)


def test_capture_audit_distinguishes_empty_partial_missing_and_omitted_dates(tmp_path):
    cohort, file = fixture(tmp_path)
    recent, historical = trade_jobs(cohort.rows)
    recent.archive(tmp_path).capture(lambda _: canonical({'trades': [], 'cursor': ''}), cursor_pages('trades'))
    historical.archive(tmp_path).capture(lambda _: canonical({'trades': [], 'cursor': 'more'}),
                                        cursor_pages('trades'), max_pages=1)
    absent_date = Job('kalshi', 'markets_historical', 'audit', BASE + '/historical/markets',
                      {'event_ticker': 'date-with-no-selected-contracts'}, 'test')
    report = capture_report(tmp_path, cohort, catalog_jobs=[absent_date])
    assert report['captured_jobs_complete'] is False
    assert sorted(g['reason'] for g in report['missing_jobs']) == ['cursor remains', 'not captured']
    groups = {r['dataset']: r for r in report['request_groups'] if r['kind'] == 'trades'}
    assert groups['trades_recent']['empty_complete_jobs'] == 1
    assert groups['trades_historical']['partial_jobs'] == 1
    assert groups['trades_historical']['empty_complete_jobs'] == 0
    # A genuinely empty expected catalog is complete, even with no cohort row.
    absent_date.archive(tmp_path).capture(lambda _: canonical({'markets': [], 'cursor': ''}), cursor_pages('markets'))
    historical.archive(tmp_path).capture(lambda _: canonical({'trades': [], 'cursor': ''}), cursor_pages('trades'))
    assert capture_report(tmp_path, cohort, catalog_jobs=[absent_date])['captured_jobs_complete'] is True


def test_capture_audit_zero_volume_is_not_an_exhaustively_queried_tape(tmp_path):
    cohort, file = fixture(tmp_path)
    cohort.rows[0]['volume'] = '0'
    report = capture_report(tmp_path, cohort, catalog_jobs=[])
    assert report['captured_jobs_complete'] is True
    assert report['selected'][0]['zero_volume_contracts_not_queried'] == 1
    assert {r['kind'] for r in report['request_groups']} == {'catalog'}


def test_catalog_schedule_does_not_count_sibling_strikes_or_duplicate_events_as_days():
    from datetime import UTC, datetime
    rows = [dict(venue='polymarket_intl', category='pm-series:nyc-daily-weather',
                 event_id=e, contract=c, close=close) for e, c, close in (
                     ('event-a', 'strike-1', '2025-09-01T12:00:00Z'),
                     ('event-a', 'strike-2', '2025-09-01T12:00:00Z'),
                     ('event-b', 'strike-3', '2025-09-01T13:00:00Z'),
                     ('event-c', 'strike-4', '2025-09-02T12:00:00Z'))]
    rows.append(dict(venue='kalshi', category='KXINX', event_id='index-a',
                     contract='index-strike', close='2025-09-02T20:00:00Z'))
    result = cohort_schedule(rows, start=datetime(2025, 9, 1, tzinfo=UTC), end=datetime(2025, 9, 4, tzinfo=UTC))
    index, weather = result
    assert index['expected_calendar_dates'] is None and index['dates_without_selected_close'] is None
    assert weather['distinct_scheduled_close_dates'] == 2
    assert weather['expected_calendar_dates'] == 3
    assert weather['dates_without_selected_close'] == ['2025-09-03']
    assert weather['dates_with_multiple_events'] == [{'date': '2025-09-01', 'event_ids': ['event-a', 'event-b']}]
    rows[0]['close'] = '2025-09-01T12:00:00'
    with pytest.raises(ImportDataError, match='timezone'):
        cohort_schedule(rows)


def test_compression_pass_folds_late_rows_and_preserves_data(tmp_path, monkeypatch):
    """Real Timescale storage regression, isolated in a rolled-back test table."""
    from contextlib import contextmanager, nullcontext
    import uuid
    from sqlalchemy import text
    from tradingbot.data import bulk_history_load as module
    from tradingbot.data.loader import local_engine

    name = 'compression_audit_' + uuid.uuid4().hex
    # A private engine: in a whole-suite run the forward-paper fixture points the
    # cached engine's search_path at its own schema, hiding TimescaleDB's functions.
    from sqlalchemy import create_engine
    engine = create_engine(local_engine().url)
    with engine.connect() as connection:
        tx = connection.begin()
        try:
            connection.execute(text(f'CREATE TABLE {name} (time timestamptz NOT NULL, value bigint NOT NULL)'))
            connection.execute(text("SELECT create_hypertable(CAST(:name AS regclass), 'time', chunk_time_interval => interval '1 day')"), {'name': name})
            connection.execute(text(f"ALTER TABLE {name} SET (timescaledb.compress, timescaledb.compress_orderby = 'time')"))
            connection.execute(text(f"INSERT INTO {name} SELECT '2020-01-01 UTC'::timestamptz + n * interval '1 second', n FROM generate_series(1,1000) n"))
            relation = connection.execute(text("SELECT show_chunks(CAST(:name AS regclass))::text"), {'name': name}).scalar_one()
            connection.execute(text("SELECT compress_chunk(CAST(:chunk AS regclass))"), {'chunk': relation})
            def storage_state():
                return connection.execute(text("SELECT status FROM _timescaledb_catalog.chunk WHERE relid = CAST(:chunk AS regclass)"), {'chunk': relation}).scalar_one()

            fully_compressed_state = storage_state()
            connection.execute(text(f"INSERT INTO {name} SELECT '2020-01-01 UTC'::timestamptz + n * interval '1 second', n FROM generate_series(1001,1100) n"))
            assert storage_state() != fully_compressed_state

            class BoundEngine:
                def connect(self):
                    return nullcontext(connection)

                @contextmanager
                def begin(self):
                    with connection.begin_nested():
                        yield connection

            monkeypatch.setattr(module, 'COMPRESSION_TABLES', (name,))
            monkeypatch.setattr(module, 'local_engine', BoundEngine)
            result = module.compress_old_chunks(tmp_path)
            assert result['previously_compressed_chunks_rechecked'] == result['eligible_chunks_processed'] == 1
            assert result['chunks_compressed'] == 0
            # Heap pages can stay allocated until VACUUM, so size alone cannot
            # prove that late rows were folded into compressed storage.
            assert storage_state() == fully_compressed_state
            assert connection.execute(text(f'SELECT count(*),sum(value) FROM {name}')).one() == (1100, 605550)
            # The same pass can be safely repeated without duplicating/removing data.
            assert module.compress_old_chunks(tmp_path)['eligible_chunks_processed'] == 1
            assert connection.execute(text(f'SELECT count(*),sum(value) FROM {name}')).one() == (1100, 605550)
        finally:
            tx.rollback()
    engine.dispose()
