"""Conservative per-batch disk gates for the owner's historical data budget."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import shutil
import stat
import time

# Storage limits, not PRD section 6 trading limits. GB uses decimal bytes.
DATA_MAX_BYTES = 20_000_000_000
FREE_MIN_BYTES = 30_000_000_000
WRITE_HEADROOM = 64 * 1024 * 1024


class DiskBudgetExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class DiskSnapshot:
    data_bytes: int
    free_bytes: int

    def as_dict(self):
        return asdict(self)


def tree_bytes(root: Path) -> int:
    """Count at least both logical and allocated size; refuse hidden symlink trees."""
    total = 0
    if root.is_symlink():
        raise DiskBudgetExceeded("data root must not be a symlink")
    if not root.exists():
        return total
    pending = [root]
    while pending:
        with os.scandir(pending.pop()) as entries:
            for entry in entries:
                try:
                    info = entry.stat(follow_symlinks=False)
                except FileNotFoundError:
                    # Concurrent atomic rename/removal; the next gate rescans.
                    continue
                if stat.S_ISLNK(info.st_mode):
                    raise DiskBudgetExceeded("data tree contains a symlink; cannot certify its budget")
                total += max(info.st_size, getattr(info, "st_blocks", 0) * 512)
                if stat.S_ISDIR(info.st_mode):
                    pending.append(entry.path)
    return total


class DiskBudget:
    def __init__(self, root: Path):
        self.root = root

    def check_free(self, reserve_bytes: int = WRITE_HEADROOM) -> int:
        """Check actual free space for DB writes between full batch scans."""
        if reserve_bytes < 0:
            raise ValueError("negative disk reservation")
        ancestor = self.root
        while not ancestor.exists():
            ancestor = ancestor.parent
        free = shutil.disk_usage(ancestor).free
        if free - reserve_bytes < FREE_MIN_BYTES:
            raise DiskBudgetExceeded(f"free disk would fall below 30 GB: {free}")
        return free

    def check(self, reserve_bytes: int = WRITE_HEADROOM) -> DiskSnapshot:
        if reserve_bytes < 0:
            raise ValueError("negative disk reservation")
        ancestor = self.root
        while not ancestor.exists():
            ancestor = ancestor.parent
        snapshot = DiskSnapshot(tree_bytes(self.root), shutil.disk_usage(ancestor).free)
        # Strictly less than 20 GB. Keep enough free space for the impending
        # write too, rather than only noticing a breach after it has happened.
        if snapshot.data_bytes + reserve_bytes >= DATA_MAX_BYTES:
            raise DiskBudgetExceeded(f"data budget would reach 20 GB: {snapshot.as_dict()}")
        if snapshot.free_bytes - reserve_bytes < FREE_MIN_BYTES:
            raise DiskBudgetExceeded(f"free disk would fall below 30 GB: {snapshot.as_dict()}")
        return snapshot

    def getter(self, get):
        """Wrap a public GET; check before fetch and before its Parquet write."""
        def guarded(request):
            self.check()
            body = get(request)
            # Cover compression framing, request/manifest metadata, and the
            # atomic temporary file. No API response is saved on a failed gate.
            self.check(max(WRITE_HEADROOM, 3 * len(body.encode("utf-8"))))
            return body
        return guarded

    @contextmanager
    def reserve(self, estimated_bytes):
        self.check(max(WRITE_HEADROOM, estimated_bytes))
        yield


class CaptureDiskBudget(DiskBudget):
    """Coordinated write reservations between full batch-boundary disk scans.

    A file lock serializes archive writes across workers AND capture processes.
    Persist the conservative byte reservation before writing; a crash can only
    overcount until the next full scan. Full checks also run at most 30 seconds
    apart or after 128 writes. Free space is checked before every GET and write.
    """
    MAX_SCAN_AGE = 30
    MAX_WRITES = 128

    @contextmanager
    def _lock(self):
        if self.root.is_symlink():
            raise DiskBudgetExceeded("data root must not be a symlink")
        self._free(WRITE_HEADROOM)
        if not (self.root / ".history-budget.lock").exists():
            super().check()  # Account for initial coordination files too.
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / ".history-budget.lock"
        if path.is_symlink() or self._journal.is_symlink():
            raise DiskBudgetExceeded("budget state must not be a symlink")
        with path.open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    @property
    def _journal(self):
        return self.root / ".history-budget.json"

    def _save(self, state):
        # In-place, fsynced BEFORE any data write. An interrupted JSON update is
        # repaired by a full scan while no cooperating archive writer can run.
        new_file = not self._journal.exists()
        with self._journal.open("w") as file:
            json.dump(state, file, sort_keys=True)
            file.flush()
            os.fsync(file.fileno())
        if new_file:
            fd = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)

    def _scan(self, reserve_bytes=WRITE_HEADROOM):
        snapshot = super().check(reserve_bytes)
        state = {"estimated_bytes": snapshot.data_bytes, "scanned_at": time.monotonic(), "writes": 0}
        self._save(state)
        return state, snapshot

    def check(self, reserve_bytes=WRITE_HEADROOM):
        """A full scan at every explicit batch boundary, under the write lock."""
        with self._lock():
            return self._scan(reserve_bytes)[1]

    def _free(self, reserve_bytes):
        return self.check_free(reserve_bytes)

    @contextmanager
    def reserve(self, estimated_bytes):
        if estimated_bytes < 0:
            raise ValueError("negative write reservation")
        # Also cover new archive directories, Parquet framing and budget state.
        allocation = max(64 * 1024, estimated_bytes)
        with self._lock():
            try:
                state = json.loads(self._journal.read_text())
                age = time.monotonic() - state["scanned_at"]
                if (not 0 <= age <= self.MAX_SCAN_AGE or not 0 <= state["writes"] < self.MAX_WRITES
                        or not 0 <= state["estimated_bytes"] < DATA_MAX_BYTES):
                    raise ValueError("stale budget snapshot")
            except (FileNotFoundError, KeyError, TypeError, ValueError):
                state, _ = self._scan()
            projected = state["estimated_bytes"] + allocation
            if projected + WRITE_HEADROOM >= DATA_MAX_BYTES:
                raise DiskBudgetExceeded(f"reserved data budget would reach 20 GB: {projected}")
            self._free(allocation + WRITE_HEADROOM)
            state["estimated_bytes"] = projected
            state["writes"] += 1
            self._save(state)
            yield  # The archive's atomic write is inside the cross-process lock.
            self._free(WRITE_HEADROOM)

    def getter(self, get):
        def guarded(request):
            self._free(WRITE_HEADROOM)
            body = get(request)
            self._free(WRITE_HEADROOM + max(64 * 1024, 3 * len(body.encode("utf-8"))))
            return body
        return guarded
