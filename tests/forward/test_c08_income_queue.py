from copy import deepcopy
import json

import pytest

from tradingbot.connectors.cash import timestamp
from tradingbot.forward import c08_runner as c08, paper_evidence as pe
from .test_c08_runner import setup


def announcement(setup, monkeypatch, tmp_path):
    runner, api, now, admitted = setup
    monkeypatch.setattr(c08, "ROOT", tmp_path)
    # Dependency hashes are tested by the parent suite; ROOT here is only a
    # synthetic issuer archive, not a checkout.
    monkeypatch.setattr(c08, "verify_binding", lambda trial: None)
    monkeypatch.setattr(pe, "ROOT", tmp_path)
    folder = tmp_path / "data/forward/watch"
    folder.mkdir(parents=True)
    (folder / "issuer.raw").write_bytes(b"Synthetic USD ordinary distribution")
    admitted["review"]["watch"] = {"path": "data/forward/watch/watch.json"}
    admitted["actions"] = [{"symbol": "USO", "kind": "ordinary_cash", "currency": "USD",
        "ex_date": "2026-10-05", "payable_date": "2026-10-06", "amount_per_share": "0.5",
        "observed_at": "2026-10-01T19:00:00Z", "reviewed_at": "2026-10-01T20:00:00Z",
        "issuer_source": "issuer.raw"}]
    return runner, api, now, admitted


def test_binding_review_queues_future_entitlement_for_all_consumers(setup, monkeypatch, tmp_path):
    runner, api, now, admitted = announcement(setup, monkeypatch, tmp_path)
    prior = deepcopy(runner.connector._book(runner.connector._venue()))
    c08.bind_review(runner.session, runner.trial_id, admitted["review_ref"], now=now[0])
    venue = runner.connector._venue()
    queued = venue.metadata_[pe.NAME]["scheduled_income"]
    assert len(queued) == 1
    assert queued[0]["event_id"] == "USO:2026-10-05:ordinary_cash"
    assert timestamp(queued[0]["recognized_at"]) == timestamp("2026-10-05T13:30:00Z")
    assert timestamp(queued[0]["modeled_release_at"]) == timestamp("2026-10-07T13:30:00Z")
    assert runner.connector._book(venue) == prior
    assert api.submissions == []
    # Rebinding after ex-date may preserve already queued facts, never invent them.
    c08.bind_review(runner.session, runner.trial_id, admitted["review_ref"], now=timestamp("2026-10-05T13:31:00Z"))
    assert len(runner.connector._venue().metadata_[pe.NAME]["scheduled_income"]) == 1


def test_late_new_income_review_rolls_back_the_entire_binding(setup, monkeypatch, tmp_path):
    runner, api, now, admitted = announcement(setup, monkeypatch, tmp_path)
    before = runner.state()
    admitted["actions"][0]["ex_date"] = "2026-10-02"
    with pytest.raises(ValueError, match="before ex-open"):
        c08.bind_review(runner.session, runner.trial_id, {"path": "new-review"}, now=now[0])
    assert runner.state() == before
    assert not runner.connector._venue().metadata_.get(pe.NAME, {}).get("scheduled_income")
    assert api.submissions == []


def test_activation_queues_income_before_account_baseline(setup, monkeypatch, tmp_path):
    runner, api, now, admitted = announcement(setup, monkeypatch, tmp_path)
    now[0] = timestamp("2026-10-01T21:00:00Z")
    state = runner.state()
    state["enabled"] = False
    runner.save(state)
    decision = {"trial_id": runner.trial_id, "decision": "activate_paper",
        "promotion_checklist_complete": True, "account_integration_verified": True,
        "what_could_blow_up_this_account": "Synthetic test only. " * 10,
        "reviewed_at": now[0].isoformat()}
    monkeypatch.setattr(c08, "read_receipt", lambda ref: json.dumps(decision).encode())
    c08.activate(runner.session, api, runner.trial_id, decision_ref={"path": "fixture"}, now=now[0])
    assert runner.state()["enabled"]
    assert len(runner.connector._venue().metadata_[pe.NAME]["scheduled_income"]) == 1
    assert api.submissions == []
