from datetime import timedelta
from decimal import Decimal as D

import pytest
from alpaca.common.enums import BaseURL
from sqlalchemy import func, select

from tradingbot.connectors.alpaca_live import (AlpacaLiveAPI, AlpacaLiveConnector, KillSwitchEngaged,
                                               LiveAPIError, NAME)
from tradingbot.connectors.alpaca_paper import OrderRejected, PaperAPIError
from tradingbot.connectors.cash import timestamp
from tradingbot.db.models import Fill, FxRate, Incident, Instrument, Market, Order, Strategy, Trial, Venue

from .conftest import FakeAPI, submit


class LiveFakeAPI(FakeAPI):
    def __init__(self, clock):
        super().__init__(clock)
        self.account_row.update(multiplier="1", shorting_enabled=False, account_number="123456789")

    def fill(self, request_id, qty="0.2", price="100", activity_id=None):
        # FakeAPI looks orders up under the paper prefix; alias the live order.
        self.orders.setdefault("tbp-" + request_id, self.orders["tbl-" + request_id])
        return super().fill(request_id, qty, price, activity_id)


@pytest.fixture
def live(session):
    clock = [timestamp("2026-09-30T14:00:00Z")]
    api = LiveFakeAPI(clock)
    venue = session.scalar(select(Venue).where(Venue.key == "alpaca"))
    strategy = Strategy(key="live-connector-test-" + api.asset_id, name="Live connector test",
                        venue_id=venue.id, status="live", allocation_usd=D(100))
    market = Market(venue_id=venue.id, external_id="LIVE-" + api.asset_id, market_type="equity")
    session.add_all([strategy, market])
    session.flush()
    instrument = Instrument(venue_id=venue.id, market_id=market.id, external_id=api.asset_id,
                            symbol="SPY", instrument_type="equity", currency="USD", contract_multiplier=D(1))
    trial = Trial(strategy_id=strategy.id, mode="live", params={"purpose": "live connector test"})
    session.add_all([instrument, trial])
    if session.scalar(select(FxRate.id).where(FxRate.ts == clock[0] - timedelta(days=1))) is None:
        # The paper fixture may already hold this rate when both books share a test.
        session.add(FxRate(base="USD", quote="GBP", rate=D("0.8"),
                           ts=clock[0] - timedelta(days=1), source="live-connector-test"))
    session.flush()
    connector = AlpacaLiveConnector(session, api, now=lambda: clock[0])
    return connector, api, clock, instrument, strategy, trial


@pytest.fixture
def live_ready(live):
    live[0].initialize_cash(D(100))
    return live


def test_transport_refuses_missing_or_paper_keys_and_pins_live_endpoint(tmp_path):
    env = tmp_path / ".env"
    env.write_text("ALPACA_LIVE_KEY=\nALPACA_LIVE_SECRET=\n")
    with pytest.raises(ValueError, match="ALPACA_LIVE_KEY and ALPACA_LIVE_SECRET"):
        AlpacaLiveAPI.from_env(env)
    env.write_text("ALPACA_LIVE_KEY=PKPAPERKEY\nALPACA_LIVE_SECRET=s\n")
    with pytest.raises(ValueError, match="paper key"):
        AlpacaLiveAPI.from_env(env)
    env.write_text("ALPACA_LIVE_KEY=AKLIVEKEY\nALPACA_LIVE_SECRET=s\n")
    api = AlpacaLiveAPI.from_env(env)  # construction performs no network request
    try:
        assert api._trading._base_url == BaseURL.TRADING_LIVE
        assert not any(hasattr(api, name) for name in ("transfer", "withdraw", "fund", "configure"))
    finally:
        api.close()


def test_live_round_trip_uses_live_mode_own_book_and_conservative_fees(live_ready):
    connector, api, clock, *_ = live_ready
    buy = submit(live_ready, "buy")
    assert buy.status == "open"
    assert api.submissions[0]["client_order_id"] == "tbl-buy"
    clock[0] += timedelta(seconds=1)
    api.fill("buy")
    assert connector.refresh(buy.order_id).status == "filled"
    sell = submit(live_ready, "sell", side="sell")
    clock[0] += timedelta(seconds=1)
    api.fill("sell")
    assert connector.refresh(sell.order_id).status == "filled"
    fills = list(connector.session.scalars(select(Fill).where(Fill.order_id.in_([buy.order_id, sell.order_id]))
                                          .order_by(Fill.id)))
    assert [f.mode for f in fills] == ["live", "live"]
    # Per-fill cent ceilings of the dated schedule: CAT on the buy; SEC, TAF and CAT on the sell.
    assert [f.fee for f in fills] == [D("0.01"), D("0.03")]
    assert all(f.metadata_["connector"] == NAME and "estimated" in f.metadata_["fee_source"] for f in fills)
    assert connector.session.scalar(select(Order.mode).where(Order.id == buy.order_id)) == "live"
    clock[0] = timestamp("2026-10-01T14:00:00Z")
    assert connector.cash().available == D("99.96")


@pytest.mark.parametrize("field,value", [("multiplier", "4"), ("shorting_enabled", True),
                                         ("account_number", "PA1234567")])
def test_margin_or_paper_accounts_are_refused(live, field, value):
    connector, api, *_ = live
    api.account_row[field] = value
    with pytest.raises(OrderRejected):
        connector.initialize_cash(D(100))
    assert not api.submissions


def test_a_paper_trial_cannot_drive_live_orders(live_ready):
    connector, api, clock, instrument, strategy, trial = live_ready
    trial.mode = "paper"
    connector.session.commit()
    with pytest.raises(OrderRejected, match="running live trial"):
        submit(live_ready)
    assert not api.submissions


@pytest.mark.parametrize("veto", ["stale", "killed", "daily", "errors"])
def test_section6_risk_vetoes_apply_in_live_mode(live_ready, veto):
    connector, api, clock, instrument, strategy, trial = live_ready
    if veto == "stale":
        api.quote_age = timedelta(seconds=31)
    elif veto == "killed":
        strategy.status = "killed"
        connector.session.commit()
    elif veto == "daily":
        connector.risk.trigger_daily_halt("live", D(-50), clock[0])
        connector.session.commit()
    elif veto == "errors":
        for _ in range(5):
            connector.risk.record_api_error(clock[0])
        connector.session.commit()
    with pytest.raises(OrderRejected):
        submit(live_ready)
    assert not api.submissions


def test_kill_switch_cancels_blocks_persists_and_needs_a_note_to_clear(live_ready):
    connector, api, clock, instrument, strategy, trial = live_ready
    open_order = submit(live_ready, "open")
    result = connector.engage_kill_switch("owner test")
    assert result["cancel_requested"] == [open_order.order_id] and not result["cancel_failed"]
    assert api.cancellations and connector.session.get(Order, open_order.order_id).status == "canceled"
    with pytest.raises(KillSwitchEngaged):
        submit(live_ready, "after-kill")
    restarted = AlpacaLiveConnector(connector.session, api, now=lambda: clock[0])
    with pytest.raises(KillSwitchEngaged):
        submit((restarted, api, clock, instrument, strategy, trial), "after-restart")
    assert len(api.submissions) == 1
    with pytest.raises(ValueError, match="note"):
        connector.clear_kill_switch(" ")
    assert connector.clear_kill_switch("owner: test over")["active"] is False
    assert submit(live_ready, "after-clear").status == "open"
    kinds = list(connector.session.scalars(select(Incident.severity).where(
        Incident.mode == "live", Incident.category == "kill_switch").order_by(Incident.id)))
    assert kinds == ["critical", "info"]


def test_unknown_live_post_keeps_reservation_and_api_errors_are_sanitized(live_ready, monkeypatch):
    connector, api, *_ = live_ready
    api.timeout_submit = True
    first = submit(live_ready)
    assert first.submission_unknown and connector.cash().reserved == 20
    assert submit(live_ready).order_id == first.order_id and len(api.submissions) == 1
    assert connector.session.scalar(select(func.count()).select_from(Incident).where(
        Incident.mode == "live", Incident.severity == "critical", Incident.category == "connectivity")) == 1
    monkeypatch.setattr(api, "account", lambda: (_ for _ in ()).throw(RuntimeError("secret-bearing request")))
    with pytest.raises(LiveAPIError, match="Alpaca live API request failed") as error:
        submit(live_ready, "two")
    assert isinstance(error.value, PaperAPIError) and "secret" not in str(error.value)


def test_dry_run_matches_the_paper_payload_and_reserves_nothing(ready, live):
    paper_connector, paper_api, *_ = ready
    connector, api, clock, instrument, strategy, trial = live
    connector.initialize_cash(D(100))
    submit(ready, "same")
    dry = AlpacaLiveConnector(connector.session, api, now=lambda: clock[0], dry_run=True)
    result = submit((dry, api, clock, instrument, strategy, trial), "same")
    assert result.status == "dry_run" and result.order_id == 0
    assert not api.submissions
    expected = {**paper_api.submissions[0], "client_order_id": "tbl-same"}
    assert dry.last_dry_run == expected
    assert connector.cash().reserved == 0
    assert connector.session.scalar(select(func.count()).select_from(Order).where(Order.mode == "live")) == 0
    # The paper book is untouched by the live book and vice versa.
    assert paper_connector.cash().reserved == 20
