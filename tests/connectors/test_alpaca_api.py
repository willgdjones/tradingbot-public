from datetime import date

from tradingbot.connectors.alpaca_api import AlpacaPaperAPI


def test_paper_endpoint_no_retries_and_exact_wire_payload(monkeypatch, tmp_path):
    path = tmp_path / ".env"
    path.write_text("ALPACA_PAPER_KEY=test\nALPACA_PAPER_SECRET=test\nAPCA_API_BASE_URL=https://api.alpaca.markets\n")
    monkeypatch.setenv("APCA_API_BASE_URL", "https://api.alpaca.markets")
    api = AlpacaPaperAPI.from_env(path)
    assert api._trading._base_url == "https://paper-api.alpaca.markets"
    assert api._trading._retry == 0
    payload = {"qty": "0.012345678", "limit_price": "600.01"}
    calls = []
    monkeypatch.setattr(api._trading, "post", lambda path, data: calls.append((path, data)) or data)
    assert api.submit(payload) is payload
    assert calls == [("/orders", payload)]
    monkeypatch.setattr(api._trading, "get", lambda path, data: (path, data))
    assert api.calendar(date(2026, 9, 30)) == (
        "/calendar", {"start": "2026-09-30", "end": "2026-09-30"})
    api.close()
