"""hwm Race 1: the connector settles a small quote clock-lead instead of refusing it.

Pure unit tests of connectors.alpaca_paper.SettledQuotes (no DB). The host clock
can lag the IEX feed by tens of ms (sntp -32 ms), so the freshest quote is stamped a
few ms "ahead"; SettledQuotes waits that lead out (<= QUOTE_CLOCK_TOLERANCE) so the
downstream `when > now` / `0 <= now - t` checks pass. A larger lead is passed through
and still refused downstream.
"""
from datetime import datetime, timedelta, UTC

from tradingbot.connectors.alpaca_paper import QUOTE_CLOCK_TOLERANCE, SettledQuotes


class FakeAPI:
    def __init__(self, row):
        self.row = row
        self.calls = 0

    def quote(self, symbol):
        self.calls += 1
        return self.row

    def quotes(self, symbols):
        self.calls += 1
        return {s: self.row for s in symbols}

    def submit_order(self, *a, **k):  # non-quote attribute: must delegate unchanged
        return "order-ok"


def _at(now, offset_s):
    return {"t": (now + timedelta(seconds=offset_s)).isoformat(), "bp": "10.00", "ap": "10.01"}


def test_small_lead_is_waited_out():
    now = datetime(2026, 10, 7, 13, 30, 0, tzinfo=UTC)
    slept = []
    api = FakeAPI(_at(now, 0.3))  # quote stamped 0.3 s ahead of host clock
    wrapped = SettledQuotes(api, lambda: now, sleep=slept.append)
    row = wrapped.quote("SPY")
    assert api.calls == 1 and row["bp"] == "10.00"
    assert slept and abs(slept[0] - 0.3) < 1e-6  # waited the lead out, once


def test_lead_beyond_tolerance_is_not_waited():
    now = datetime(2026, 10, 7, 13, 30, 0, tzinfo=UTC)
    slept = []
    ahead = QUOTE_CLOCK_TOLERANCE.total_seconds() + 4
    wrapped = SettledQuotes(FakeAPI(_at(now, ahead)), lambda: now, sleep=slept.append)
    wrapped.quote("SPY")
    assert slept == []  # genuinely future quote passes through, refused downstream as before


def test_past_quote_does_not_wait():
    now = datetime(2026, 10, 7, 13, 30, 0, tzinfo=UTC)
    slept = []
    wrapped = SettledQuotes(FakeAPI(_at(now, -30)), lambda: now, sleep=slept.append)
    wrapped.quote("SPY")
    assert slept == []


def test_quotes_dict_settles_on_max_lead():
    now = datetime(2026, 10, 7, 13, 30, 0, tzinfo=UTC)
    slept = []
    wrapped = SettledQuotes(FakeAPI(_at(now, 0.5)), lambda: now, sleep=slept.append)
    wrapped.quotes(["SPY", "QQQ"])
    assert slept and abs(slept[0] - 0.5) < 1e-6


def test_non_quote_attributes_delegate_unchanged():
    now = datetime(2026, 10, 7, 13, 30, 0, tzinfo=UTC)
    slept = []
    wrapped = SettledQuotes(FakeAPI(_at(now, 0.3)), lambda: now, sleep=slept.append)
    assert wrapped.submit_order() == "order-ok"
    assert slept == []  # only quote/quotes settle


def test_double_wrap_is_idempotent():
    clock = [datetime(2026, 10, 7, 13, 30, 0, tzinfo=UTC)]
    slept = []

    def sleep(seconds):  # advance the clock like real time.sleep
        slept.append(seconds)
        clock[0] = clock[0] + timedelta(seconds=seconds)

    row = {"t": (clock[0] + timedelta(seconds=0.4)).isoformat(), "bp": "10.00", "ap": "10.01"}
    # jev Runner wraps before building the connector, which now wraps again.
    inner = SettledQuotes(FakeAPI(row), lambda: clock[0], sleep=sleep)
    outer = SettledQuotes(inner, lambda: clock[0], sleep=sleep)
    outer.quote("SPY")
    # inner settles the 0.4 s lead; the outer settle then sees a non-positive lead.
    assert len([s for s in slept if s > 0]) == 1
