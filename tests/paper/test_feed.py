"""Global live-feed ordering across bounded pages and committed cursors."""

from dataclasses import replace
from datetime import timedelta

import pytest
from sqlalchemy import event as sql_event

from tradingbot.paper.feed import FeedCursor, live_events


def key(event):
    return event.time, 0 if event.is_trade else 1, event.meta["row_id"]


@pytest.mark.parametrize("batch_size", [1, 3, 500])
@pytest.mark.parametrize("leading_channel", ["quote", "trade"])
def test_bounded_pages_preserve_global_order_and_both_cursors(setup, batch_size, leading_channel):
    s = setup
    start = s.clock[0]
    leading, trailing = ((s.quote, s.trade) if leading_channel == "quote" else (s.trade, s.quote))
    # One full channel page can omit an observation earlier than the other
    # channel's head. IDs within each channel retain recorder-time order.
    expected = [leading() for _ in range(batch_size + 2)]
    expected.extend([trailing(), leading(), trailing()])
    cursor, seen = FeedCursor(), []
    for _ in range(len(expected) + 1):
        page = live_events(s.session, [s.instrument.id], since=start, through=s.clock[0],
                           cursor=cursor, batch_size=batch_size)
        assert len(page) <= batch_size
        if not page:
            break
        for observation in page:
            seen.append(observation)
            cursor = replace(cursor, **{
                "trade_id" if observation.is_trade else "quote_id": observation.meta["row_id"],
            })
    assert list(map(key, seen)) == sorted(map(key, expected))
    assert cursor.quote_id == max(e.meta["row_id"] for e in expected if e.is_quote)
    assert cursor.trade_id == max(e.meta["row_id"] for e in expected if e.is_trade)


def test_equal_timestamp_pages_keep_trade_first_and_advance_no_unreturned_cursor(setup):
    s = setup
    start = s.clock[0]
    quotes = [s.quote(seconds=0) for _ in range(3)]
    trades = [s.trade(seconds=0) for _ in range(3)]
    expected = trades + quotes
    cursor = FeedCursor()
    for expected_event in expected:
        page = live_events(s.session, [s.instrument.id], since=start, through=start,
                           cursor=cursor, batch_size=1)
        assert [key(e) for e in page] == [key(expected_event)]
        cursor = replace(cursor, **{
            "trade_id" if page[0].is_trade else "quote_id": page[0].meta["row_id"],
        })
    assert live_events(s.session, [s.instrument.id], since=start, through=start,
                       cursor=cursor, batch_size=1) == []


def test_channels_and_payloads_share_one_read_statement(setup):
    s = setup
    start = s.clock[0]
    s.quote()
    s.trade()
    statements = []
    connection = s.session.connection()

    def record(conn, cursor, statement, params, context, executemany):
        statements.append(statement)

    sql_event.listen(connection, "before_cursor_execute", record)
    try:
        page = live_events(s.session, [s.instrument.id], since=start, through=s.clock[0],
                           cursor=FeedCursor())
    finally:
        sql_event.remove(connection, "before_cursor_execute", record)
    assert len(page) == 2
    assert len(statements) == 1  # commits cannot interleave two channel reads


def test_filters_apply_before_the_merged_limit(setup):
    s = setup
    start = s.clock[0]
    s.quote(source="history")
    s.trade(source="historical")
    expected = s.quote()
    s.trade()  # outside through
    page = live_events(s.session, [s.instrument.id], since=expected.time,
                       through=expected.time, cursor=FeedCursor(), batch_size=1)
    assert [key(e) for e in page] == [key(expected)]
    assert live_events(s.session, [], since=start, through=s.clock[0], cursor=FeedCursor()) == []
    assert live_events(s.session, [s.instrument.id], since=s.clock[0] + timedelta(seconds=1),
                       through=s.clock[0] + timedelta(seconds=2), cursor=FeedCursor()) == []


def test_invalid_batch_size_is_rejected(setup):
    s = setup
    with pytest.raises(ValueError, match="batch_size"):
        live_events(s.session, [s.instrument.id], since=s.clock[0], through=s.clock[0],
                    cursor=FeedCursor(), batch_size=0)
