"""Real Postgres integration, enclosed in a rolled-back outer transaction."""

from copy import deepcopy
from datetime import timedelta
from decimal import Decimal as D
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from tradingbot.connectors.alpaca_paper import AlpacaPaperConnector
from tradingbot.connectors.cash import timestamp
from tradingbot.db.models import FxRate, Instrument, Market, Strategy, Trial, Venue
from tradingbot.db.seed import seed
from tradingbot.db.session import get_engine


class FakeAPI:
    def __init__(self, clock):
        self.clock = clock
        self.asset_id = str(uuid4())
        self.account_row = {"id": str(uuid4()), "status": "ACTIVE", "cash": "100",
                            "buying_power": "400", "multiplier": "4", "trading_blocked": False,
                            "account_blocked": False, "trade_suspended_by_user": False}
        self.asset_row = {"id": self.asset_id, "symbol": "SPY", "class": "us_equity",
                          "status": "active", "tradable": True, "fractionable": True}
        self.orders, self.fills = {}, []
        self.submissions, self.cancellations = [], []
        self.quote_age = timedelta(0)
        self.timeout_submit = False
        self.cancel_ack_only = False

    def account(self):
        return deepcopy(self.account_row)

    def asset(self, symbol):
        return deepcopy(self.asset_row)

    def calendar(self, day):
        settlements = {"2026-09-30": "2026-10-01", "2026-10-01": "2026-10-02",
                       "2026-10-02": "2026-10-05", "2026-10-09": "2026-10-13",
                       "2026-10-12": "2026-10-13", "2026-10-13": "2026-10-14"}
        if day.isoformat() not in settlements:
            return []
        return [{"date": day.isoformat(), "open": "09:30", "close": "16:00",
                 "settlement_date": settlements[day.isoformat()]}]

    def quote(self, symbol):
        return {"bp": 100.0, "ap": 100.0, "t": (self.clock[0] - self.quote_age).isoformat()}

    def submit(self, payload):
        self.submissions.append(deepcopy(payload))
        row = {**payload, "id": str(uuid4()), "status": "new", "filled_qty": "0",
               "submitted_at": self.clock[0].isoformat()}
        self.orders[payload["client_order_id"]] = row
        if self.timeout_submit:
            raise TimeoutError("must not expose SDK request or credentials")
        return deepcopy(row)

    def order(self, client_id):
        return deepcopy(self.orders[client_id])

    def cancel(self, venue_order_id):
        self.cancellations.append(venue_order_id)
        if not self.cancel_ack_only:
            for row in self.orders.values():
                if row["id"] == venue_order_id:
                    row["status"] = "canceled"

    def activities(self, after, page_token=None):
        rows = [deepcopy(row) for row in self.fills if timestamp(row["transaction_time"]) > after]
        if page_token:
            rows = rows[next(i for i, row in enumerate(rows) if row["id"] == page_token) + 1:]
        return rows[:100]

    def fill(self, request_id, qty="0.2", price="100", activity_id=None):
        order = self.orders["tbp-" + request_id]
        cumulative = D(order["filled_qty"]) + D(qty)
        order["filled_qty"] = str(cumulative)
        order["status"] = "filled" if cumulative == D(order["qty"]) else "partially_filled"
        row = {"activity_type": "FILL", "type": "fill", "id": activity_id or str(uuid4()),
               "qty": qty, "price": price, "cum_qty": str(cumulative), "symbol": order["symbol"],
               "side": order["side"], "order_id": order["id"], "transaction_time": self.clock[0].isoformat()}
        self.fills.append(row)
        return row


@pytest.fixture(scope="session", autouse=True)
def connector_seed(paper_test_database):
    seed()


@pytest.fixture
def session():
    connection = get_engine().connect()
    outer = connection.begin()
    sess = Session(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
    try:
        isolate_alpaca_venue(sess)
        yield sess
    finally:
        sess.close()
        assert outer.is_active, "Connector tests must never escape the rollback transaction"
        outer.rollback()
        connection.close()


def isolate_alpaca_venue(session):
    """Rollback-only venue so tests never inherit the running paper cash book.

    The suite uses a disposable schema, so this can never lock a production
    venue. Other fixture connections retain ordinary PostgreSQL MVCC behavior.
    """
    existing = session.scalar(select(Venue).where(Venue.key == "alpaca"))
    existing.key = "alpaca-test-hidden-" + uuid4().hex[:20]
    session.flush()
    session.add(Venue(key="alpaca", name="Isolated Alpaca test", kind=existing.kind,
                      is_live_enabled=False))
    # Real dated reference rates must not supersede synthetic fixture rates.
    # This deletion is visible only inside the rolled-back test transaction.
    session.execute(delete(FxRate))
    session.flush()


@pytest.fixture
def setup(session):
    clock = [timestamp("2026-09-30T14:00:00Z")]
    api = FakeAPI(clock)
    venue = session.scalar(select(Venue).where(Venue.key == "alpaca"))
    strategy = Strategy(key="connector-test-" + uuid4().hex, name="Connector test",
                        venue_id=venue.id, status="paper", allocation_usd=D(100))
    market = Market(venue_id=venue.id, external_id="TEST-" + uuid4().hex, market_type="equity")
    session.add_all([strategy, market])
    session.flush()
    instrument = Instrument(venue_id=venue.id, market_id=market.id, external_id=api.asset_id,
                            symbol="SPY", instrument_type="equity", currency="USD", contract_multiplier=D(1))
    trial = Trial(strategy_id=strategy.id, mode="paper", params={"purpose": "connector integration test"})
    session.add_all([instrument, trial, FxRate(base="USD", quote="GBP", rate=D("0.8"),
                                              ts=clock[0] - timedelta(days=1), source="connector-test")])
    session.flush()
    connector = AlpacaPaperConnector(session, api, now=lambda: clock[0])
    return connector, api, clock, instrument, strategy, trial


@pytest.fixture
def ready(setup):
    setup[0].initialize_cash(D(100))
    return setup


def submit(setup, request_id="one", side="buy", quantity="0.2", limit_price="100"):
    connector, api, clock, instrument, strategy, trial = setup
    return connector.submit_limit(request_id=request_id, instrument_id=instrument.id,
                                  strategy_id=strategy.id, trial_id=trial.id, side=side,
                                  quantity=D(quantity), limit_price=D(limit_price))
