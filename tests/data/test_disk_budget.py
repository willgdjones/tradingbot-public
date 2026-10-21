from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

import pytest

from tradingbot.data import disk_budget as d


def space(monkeypatch, *, used=0, free=d.FREE_MIN_BYTES + d.WRITE_HEADROOM):
    monkeypatch.setattr(d, "tree_bytes", lambda _: used)
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(d.shutil, "disk_usage", lambda _: usage(100, 0, free))


def test_exact_bounds_and_headroom(monkeypatch, tmp_path):
    budget = d.DiskBudget(tmp_path)
    space(monkeypatch)
    assert budget.check().free_bytes == d.FREE_MIN_BYTES + d.WRITE_HEADROOM
    space(monkeypatch, free=d.FREE_MIN_BYTES + d.WRITE_HEADROOM - 1)
    with pytest.raises(d.DiskBudgetExceeded, match="below 30"):
        budget.check()
    space(monkeypatch, used=d.DATA_MAX_BYTES - d.WRITE_HEADROOM)
    with pytest.raises(d.DiskBudgetExceeded, match="20 GB"):
        budget.check()


def test_low_disk_aborts_before_network(monkeypatch, tmp_path):
    space(monkeypatch, free=d.FREE_MIN_BYTES - 1)
    called = []
    get = d.DiskBudget(tmp_path).getter(lambda r: called.append(r))
    with pytest.raises(d.DiskBudgetExceeded):
        get("request")
    assert not called


def test_external_write_during_fetch_aborts_before_archive(monkeypatch, tmp_path):
    space(monkeypatch)
    def fetch(_):
        space(monkeypatch, free=d.FREE_MIN_BYTES - 1)
        return "response"
    with pytest.raises(d.DiskBudgetExceeded):
        d.DiskBudget(tmp_path).getter(fetch)("request")


def test_allocated_files_and_symlinks(tmp_path):
    file = tmp_path / "small"
    file.write_text("x")
    assert d.tree_bytes(tmp_path) >= max(1, file.stat().st_blocks * 512)
    (tmp_path / "hidden").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(d.DiskBudgetExceeded, match="symlink"):
        d.tree_bytes(tmp_path)


def test_missing_data_root_checks_existing_parent(monkeypatch, tmp_path):
    space(monkeypatch)
    assert d.DiskBudget(tmp_path / "missing").check().data_bytes == 0


def test_two_capture_workers_share_one_conservative_reservation(monkeypatch, tmp_path):
    space(monkeypatch, used=d.DATA_MAX_BYTES-d.WRITE_HEADROOM-100_000,
          free=d.FREE_MIN_BYTES+3*d.WRITE_HEADROOM)
    first, second = d.CaptureDiskBudget(tmp_path), d.CaptureDiskBudget(tmp_path)
    first.check()
    def attempt(budget):
        try:
            with budget.reserve(10):
                return "written"
        except d.DiskBudgetExceeded:
            return "blocked"
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, (first, second)))
    assert sorted(outcomes) == ["blocked", "written"]


def test_failed_write_cannot_lose_its_reservation(monkeypatch, tmp_path):
    space(monkeypatch, used=d.DATA_MAX_BYTES-d.WRITE_HEADROOM-100_000,
          free=d.FREE_MIN_BYTES+3*d.WRITE_HEADROOM)
    budget = d.CaptureDiskBudget(tmp_path)
    budget.check()
    with pytest.raises(OSError, match="interrupted"):
        with budget.reserve(10):
            raise OSError("interrupted atomic write")
    with pytest.raises(d.DiskBudgetExceeded):
        with d.CaptureDiskBudget(tmp_path).reserve(10):
            pytest.fail("failed writer's reservation was lost")
    budget.check()  # A full physical rescan safely recovers unused reservations.
    with budget.reserve(10):
        pass


def test_capture_fast_path_still_checks_free_space_after_fetch(monkeypatch, tmp_path):
    space(monkeypatch, free=d.FREE_MIN_BYTES+3*d.WRITE_HEADROOM)
    def fetch(_):
        space(monkeypatch, free=d.FREE_MIN_BYTES-1)
        return "response"
    with pytest.raises(d.DiskBudgetExceeded, match="below 30"):
        d.CaptureDiskBudget(tmp_path).getter(fetch)("request")


def test_batch_boundary_ignores_cached_estimate_and_rescans_external_growth(monkeypatch, tmp_path):
    space(monkeypatch, free=d.FREE_MIN_BYTES+3*d.WRITE_HEADROOM)
    budget = d.CaptureDiskBudget(tmp_path)
    budget.check()
    space(monkeypatch, used=d.DATA_MAX_BYTES, free=d.FREE_MIN_BYTES+3*d.WRITE_HEADROOM)
    with pytest.raises(d.DiskBudgetExceeded, match="20 GB"):
        budget.check()


def test_archive_pages_use_guard_and_do_not_write_on_denial(monkeypatch, tmp_path):
    from contextlib import contextmanager
    from tradingbot.data.archive import RawArchive, Request, cursor_pages
    calls = []
    @contextmanager
    def guard(size):
        calls.append(size)
        if len(calls) == 2:
            raise d.DiskBudgetExceeded("page denied")
        yield
    archive = RawArchive(tmp_path, "kalshi", "trades_historical", "test",
                         Request("https://example.test", {}), semantics="test")
    with pytest.raises(d.DiskBudgetExceeded, match="page denied"):
        archive.capture(lambda _: json.dumps({"trades": [], "cursor": ""}), cursor_pages("trades"),
                        write_guard=guard)
    assert (archive.directory / "manifest.json").exists()
    assert not list(archive.directory.glob("page-*.parquet"))
    assert len(calls) == 2 and min(calls) >= 64 * 1024
