import json

import pytest

from tradingbot.connectors.cash import MarketSession, timestamp
from tradingbot.forward import c08_sources as source
from tradingbot.forward.c08_readiness import digest
from .test_c08_state import eia, rows


@pytest.fixture
def reviewed(tmp_path, monkeypatch):
    monkeypatch.setattr(source, "ROOT", tmp_path)
    root = tmp_path / "data/forward/c08-integration"
    monkeypatch.setattr(source, "ARCHIVE", root)
    root.mkdir(parents=True)
    folder = root / "capture"
    folder.mkdir()
    raw = b"Synthetic issuer content reviewed explicitly; not actual evidence."
    (folder / "issuer.raw").write_bytes(raw)
    report = {"schema": source.NAME, "started_at": "2026-10-01T20:00:00Z",
              "completed_at": "2026-10-01T20:01:00Z", "account_matches_book": True,
              "calendar": rows(), "errors": {}, "files": {"issuer.raw": digest(raw)},
              "notice_links": {"issuer-product": ["https://www.uscfinvestments.com/qualified-notices"]},
              "actions": {"pages": [], "exhausted": True}, "nontrade": {"exhausted": True}, "eia": eia()}
    watch = source.write_once(folder / "watch.json", report)
    decision = {"reviewer": "synthetic fixture", "reason": "Synthetic complete source review only for isolated tests.",
                "admitted": True, "reviewed_files": ["issuer.raw"], "actions": [],
                "unresolved_notices": [], "unmatched_activities": [], "reviewed_broker_rows": [],
                "reviewed_notice_links": report["notice_links"]["issuer-product"]}
    for name in ("issuer_coverage", "eia_methodology", "broker_actions", "nontrade_activity"):
        decision[name] = {"clear": True, "reason": "Synthetic fixture sources inspected and reconciled."}
    review = source.review_watch(watch, decision, folder / "review.json", now=timestamp("2026-10-01T20:02:00Z"))
    return folder, watch, decision, review


def admitted(ref):
    return source.admission(ref, [MarketSession.from_api(r) for r in rows()], as_of="2026-10-02T13:30:00Z")


def test_dated_review_can_admit_current_eia_without_fake_first_vintage(reviewed):
    _, _, _, ref = reviewed
    result = admitted(ref)
    assert result["eia"]["first_release_vintage_verified"] is False
    assert result["blackouts"] == []


def test_changed_raw_file_invalidates_review(reviewed):
    folder, _, _, ref = reviewed
    (folder / "issuer.raw").write_bytes(b"new unknown corporate action")
    with pytest.raises(ValueError, match="changed"):
        admitted(ref)


@pytest.mark.parametrize("field,value", [
    ("admitted", False), ("unresolved_notices", ["unparsed dynamic news"]),
    ("unmatched_activities", ["unexpected credit"]), ("reviewed_notice_links", []),
    ("reviewed_broker_rows", ["unknown"]),
    ("issuer_coverage", {"clear": False, "reason": "Dynamic issuer content has not been retrieved."}),
])
def test_empty_broker_never_substitutes_for_notice_review(reviewed, field, value):
    folder, watch, decision, _ = reviewed
    decision[field] = value
    ref = source.review_watch(watch, decision, folder / "changed-review.json", now=timestamp("2026-10-01T20:03:00Z"))
    with pytest.raises(ValueError):
        admitted(ref)


def test_review_expiry_cannot_be_extended_or_backdated(reviewed):
    folder, watch, decision, ref = reviewed
    with pytest.raises(ValueError, match="future capture"):
        source.review_watch(watch, decision, folder / "early-review.json", now=timestamp("2026-10-01T19:00:00Z"))
    with pytest.raises(ValueError, match="expired"):
        source.admission(ref, [], as_of="2026-10-02T20:00:00Z")
    review = json.loads(source.read_receipt(ref))
    review["valid_until"] = "2026-10-03T20:00:00Z"
    fake = source.write_once(folder / "extended.json", review)
    with pytest.raises(ValueError, match="extended"):
        admitted(fake)


def test_file_inventory_is_complete_and_paths_cannot_escape(reviewed):
    folder, watch, decision, _ = reviewed
    decision["reviewed_files"] = []
    with pytest.raises(ValueError, match="every captured"):
        source.review_watch(watch, decision, folder / "incomplete.json", now=timestamp("2026-10-01T20:03:00Z"))
    with pytest.raises(ValueError, match="outside"):
        source.read_receipt({"path": "elsewhere", "sha256": "0" * 64})
