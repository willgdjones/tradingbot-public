from datetime import datetime, time
import json

import pytest

from forward.test_c05_state import calendar
from tradingbot.connectors.cash import MarketSession, NEW_YORK
from tradingbot.forward import c05_sources as s
from tradingbot.forward.c05_readiness import SYMBOLS, digest, encoded


def fixture_watch(monkeypatch, tmp_path):
    monkeypatch.setattr(s, "ROOT", tmp_path)
    archive = tmp_path / "data/forward/c05"
    monkeypatch.setattr(s, "ARCHIVE", archive)
    folder = archive / "watch"
    folder.mkdir(parents=True)
    # Do not exercise the real disk budget in a temporary fixture.
    class Budget:
        def __init__(self, *a): pass
        def reserve(self, *a):
            from contextlib import nullcontext
            return nullcontext()
    monkeypatch.setattr(s, "CaptureDiskBudget", Budget)
    def save(name, value, raw=False):
        return s.write_once(folder / name, value, raw=raw)
    rows = calendar()
    sessions = [MarketSession.from_api(r) for r in rows]
    days = [m for m in sessions if str(m.trade_date) <= "2026-10-30"][-127:]
    prices = [100] * 126 + [101]
    public, sources, independent = {}, {}, {"bars": {}, "next_page_token": None}
    for key, url in s.PUBLIC.items():
        raw = b"<html><h1>Actual source content fixture</h1><a href='/notice'>notice</a></html>"
        ref = save(key + ".raw", raw, raw=True)
        public[key] = {"url": url, "status_code": 200, "content_type": "text/html", "raw_receipt": ref,
                       "observed_at": "2026-10-30T20:02:00Z", "notice_links": s.notice_links(raw, url)}
        save(key + ".json", public[key])
    for symbol in SYMBOLS:
        result = {"meta": {"symbol": symbol, "currency": "USD"}, "events": {},
                  "timestamp": [int(m.opens_at.timestamp()) for m in days],
                  "indicators": {"quote": [{"close": prices}], "adjclose": [{"adjclose": prices}]}}
        raw = encoded({"chart": {"result": [result]}})
        ref = save("closes-" + symbol + ".raw", raw, raw=True)
        meta = {"status_code": 200, "request_url": s.YAHOO_CHART.format(symbol=symbol),
                "raw_sha256": ref["sha256"], "observed_at": "2026-10-30T20:03:00Z"}
        save("closes-" + symbol + ".json", meta)
        vintage = s.price_vintage(raw, symbol, sessions, meta["observed_at"])
        bars = [{"t": m.opens_at.isoformat(), "c": price} for m, price in zip(days, prices)]
        independent["bars"][symbol] = bars
        sources[symbol] = {"raw_receipt": ref, "vintage": vintage,
                           "comparison": s.independent_comparison(vintage, bars)}
    ind = save("independent.raw", encoded(independent), raw=True)
    paper = {"account": {"audit": {"matches_existing_cash_book": True}}, "calendar": {"response": rows}}
    for key, value in paper.items(): save(key + ".json", value)
    save("quote-batch.json", {})
    raw_actions = json.dumps({"corporate_actions": {}, "next_page_token": None})
    action = save("actions-0.json", {"raw_response": raw_actions, "raw_response_sha256": digest(raw_actions.encode()),
                                   "response": json.loads(raw_actions)})
    nontrade = save("nontrade-0.json", {"response": []})
    report = {"schema": s.NAME, "started_at": "2026-10-30T20:01:00Z", "completed_at": "2026-10-30T20:04:00Z",
              "signals_computed": False, "calendar": rows, "account_matches_book": True, "paper": paper,
              "public": public, "sources": sources, "independent_receipt": ind, "errors": {},
              "actions": {"exhausted": True, "records": 0, "pages": [action]},
              "nontrade": {"exhausted": True, "records": 0, "pages": [nontrade]},
              "files": {p.name: digest(p.read_bytes()) for p in folder.iterdir()}}
    ref = save("watch.json", report)
    decision = {"reviewer": "test", "reason": "Synthetic fixture reviewed against every source without real execution.",
                "admitted": True, "reviewed_files": list(report["files"]),
                "issuer_reviews": {symbol: {"complete": True, "dynamic_content_resolved": True,
                    "income_and_actions_reconciled": True, "source_keys": sorted(s.ISSUER_KEYS[symbol]),
                    "reason": "Synthetic fixture has resolved document inventory and issuer events."} for symbol in SYMBOLS},
                "adjustment_continuity": dict.fromkeys(SYMBOLS, True), "actions": [],
                "notice_inventory": {k: v["notice_links"] for k, v in public.items()},
                "unresolved_actions": [], "unresolved_nontrade": []}
    return folder, ref, report, decision, sessions


def test_full_raw_bound_watch_review_and_today_vintage(monkeypatch, tmp_path):
    folder, ref, report, decision, sessions = fixture_watch(monkeypatch, tmp_path)
    assert s.verify_watch(ref) == report
    review = s.review_watch(ref, decision, folder.parent / "review.json", now="2026-10-30T20:05:00Z")
    result = s.admission(review, sessions, as_of="2026-10-30T20:06:00Z", close_day="2026-10-30")
    assert all(len(r["adjusted_closes"]) == 127 for r in result["vintage"].values())
    assert result["blackouts"] == []
    with pytest.raises(ValueError, match="today"):
        s.admission(review, sessions, as_of="2026-10-30T20:06:00Z", close_day="2026-10-29")


@pytest.mark.parametrize("case", ["issuer_empty", "issuer_wrong_fund", "unresolved_cash", "changed_inventory", "adjustment", "denied"])
def test_empty_broker_and_complete_calendar_cannot_override_source_holds(monkeypatch, tmp_path, case):
    folder, ref, _, decision, sessions = fixture_watch(monkeypatch, tmp_path)
    if case == "issuer_empty": decision["issuer_reviews"]["USO"]["dynamic_content_resolved"] = False
    if case == "issuer_wrong_fund": decision["issuer_reviews"]["SLV"]["source_keys"] = ["USO-product"]
    if case == "unresolved_cash": decision["unresolved_nontrade"] = ["unknown cash activity"]
    if case == "changed_inventory": decision["notice_inventory"] = {}
    if case == "adjustment": decision["adjustment_continuity"]["GLD"] = False
    if case == "denied": decision["admitted"] = False
    review = s.review_watch(ref, decision, folder.parent / "review.json", now="2026-10-30T20:05:00Z")
    with pytest.raises(ValueError):
        s.admission(review, sessions, as_of="2026-10-30T20:06:00Z")


def test_inline_calendar_or_price_first_seen_cannot_be_rewritten(monkeypatch, tmp_path):
    folder, ref, report, _, _ = fixture_watch(monkeypatch, tmp_path)
    report["sources"]["GLD"]["vintage"]["observed_at"] = "2026-10-30T20:01:00Z"
    changed = s.write_once(folder.parent / "bad-watch.json", report)
    # Keep same captured directory while replacing only the watch reference.
    bad = folder / "bad-watch.json"
    bad.write_bytes((folder.parent / "bad-watch.json").read_bytes())
    with pytest.raises(ValueError, match="Inline prices"):
        s.verify_watch({"path": str(bad.relative_to(s.ROOT)), "sha256": changed["sha256"]})
    (folder / "GLD-product.raw").write_bytes(b"changed issuer page")
    with pytest.raises(ValueError, match="inventory changed"):
        s.verify_watch(ref)


def test_independent_source_split_basis_uses_actual_shares_and_bound():
    days = [r["date"] for r in calendar() if r["date"] <= "2026-10-02"][-127:]
    vintage = {"days": days, "raw_closes": ["400"] * 126 + ["400"], "last_session": "2026-10-02",
        "events": {"splits": {"x": {"date": int(datetime.combine(datetime(2026, 10, 2).date(), time(9, 30), NEW_YORK).timestamp()),
                                     "numerator": 1, "denominator": 4}}}}
    bars = [{"t": day + "T13:30:00Z", "c": "100" if day < "2026-10-02" else "400"} for day in days]
    result = s.independent_comparison(vintage, bars)
    assert result["complete_within_bound"]
    bars[0]["c"] = "95"
    assert not s.independent_comparison(vintage, bars)["complete_within_bound"]


def test_first_action_review_survives_later_daily_review_and_binds_original_bytes(monkeypatch, tmp_path):
    folder, ref, report, decision, sessions = fixture_watch(monkeypatch, tmp_path)
    # The first review is outside the immutable watch inventory.
    meta_path = folder / "GLD-product.json"
    metadata_ref = {"path": str(meta_path.relative_to(s.ROOT)), "sha256": digest(meta_path.read_bytes())}
    action = {"identity": "gld-fixture-distribution", "symbol": "GLD", "kind": "ordinary_cash", "currency": "USD",
              "announced_at": "2026-10-30T19:00:00Z", "ex_date": "2026-11-02",
              "payable_date": "2026-11-03", "amount_per_share": "0.5"}
    reviewed = s.review_action(action, metadata_ref, folder.parent / "action.json",
        reviewer="test", reason="Synthetic original issuer announcement and causal receipt reviewed.",
        now="2026-10-30T20:04:00Z")
    decision["actions"] = [reviewed]
    review = s.review_watch(ref, decision, folder.parent / "review.json", now="2026-10-30T20:05:00Z")
    result = s.admission(review, sessions, as_of="2026-10-30T20:06:00Z")
    assert result["actions"][0]["reviewed_at"] == "2026-10-30T20:04:00+00:00"
    decision["actions"][0]["amount_per_share"] = "0.6"
    changed = s.review_watch(ref, decision, folder.parent / "changed.json", now="2026-10-30T20:07:00Z")
    with pytest.raises(ValueError, match="first review"):
        s.admission(changed, sessions, as_of="2026-10-30T20:08:00Z")


def test_first_action_review_cannot_precede_observed_primary_evidence(monkeypatch, tmp_path):
    folder, ref, report, decision, sessions = fixture_watch(monkeypatch, tmp_path)
    meta_path = folder / "GLD-product.json"
    metadata_ref = {"path": str(meta_path.relative_to(s.ROOT)), "sha256": digest(meta_path.read_bytes())}
    with pytest.raises(ValueError, match="Primary observed"):
        s.review_action({"announced_at": "2026-10-30T19:00:00Z"}, metadata_ref,
            folder.parent / "early.json", reviewer="test", reason="Synthetic substantive source review cannot be backdated.",
            now="2026-10-30T20:01:00Z")
