"""Lossless API-page Parquet archives with atomic, resumable checkpoints."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

import pyarrow as pa
import pyarrow.parquet as pq

SCHEMA = pa.schema([
    ("format_version", pa.int16()), ("venue", pa.string()),
    ("dataset", pa.string()), ("page", pa.int64()),
    ("retrieved_at", pa.timestamp("us", tz="UTC")),
    ("request_json", pa.string()), ("response_json", pa.large_string()),
    ("response_sha256", pa.string()), ("record_count", pa.int64()),
    ("next_request_json", pa.string()),
])


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


@dataclass(frozen=True)
class Request:
    url: str
    params: dict

    def to_json(self) -> str:
        return canonical({"url": self.url, "params": self.params})

    @classmethod
    def from_json(cls, value: str) -> Request:
        return cls(**json.loads(value))


@dataclass(frozen=True)
class Progress:
    directory: Path
    pages_written: int
    records_written: int
    complete: bool


class RawArchive:
    """One job is an immutable query snapshot; use a new run name to refresh it."""

    def __init__(self, root: Path, venue: str, dataset: str, run: str,
                 initial: Request, *, semantics: str, scope: dict | None = None):
        for component in (venue, dataset, run):
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", component):
                raise ValueError("archive names must be safe single path components")
        self.venue, self.dataset, self.initial = venue, dataset, initial
        self.identity = {"format_version": 1, "venue": venue, "dataset": dataset,
                         "request": json.loads(initial.to_json()), "semantics": semantics}
        if scope is not None:
            self.identity["scope"] = scope
        job = hashlib.sha256(canonical(self.identity).encode()).hexdigest()[:24]
        self.directory = root / "raw" / venue / dataset / run / job

    def _write(self, target: Path, write: Callable[[str], None]) -> None:
        fd, temporary = tempfile.mkstemp(prefix=".partial-", dir=self.directory)
        os.close(fd)
        try:
            write(temporary)
            with open(temporary, "rb") as file:
                os.fsync(file.fileno())
            os.replace(temporary, target)
            directory_fd = os.open(self.directory, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def capture(self, get: Callable[[Request], str],
                advance: Callable[[Request, object], tuple[int, Request | None]],
                *, max_pages: int | None = None,
                page_key: Callable[[object], str | None] | None = None,
                write_guard=None) -> Progress:
        if max_pages is not None and max_pages < 1:
            raise ValueError("max_pages must be positive")
        guard = write_guard or (lambda size: nullcontext())
        self.directory.mkdir(parents=True, exist_ok=True)
        # Lock the whole job, including recovery. No two writers share a cursor.
        with (self.directory / ".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            manifest = self.directory / "manifest.json"
            if manifest.exists():
                if json.loads(manifest.read_text()) != self.identity:
                    raise ValueError("archive identity mismatch")
            else:
                manifest_body = canonical(self.identity)
                with guard(max(64 * 1024, 3 * len(manifest_body.encode()))):
                    self._write(manifest, lambda p: Path(p).write_text(manifest_body))
            files = sorted(self.directory.glob("page-*.parquet"))
            request = self.initial
            seen: set[str] = set()
            seen_pages: set[str] = set()
            for index, file in enumerate(files):
                if file.name != f"page-{index:08d}.parquet":
                    raise ValueError("non-contiguous archive; repair before resuming")
                row = pq.ParquetFile(file).read().to_pylist()[0]
                if row["request_json"] != request.to_json():
                    raise ValueError("broken archive request chain")
                if hashlib.sha256(row["response_json"].encode()).hexdigest() != row["response_sha256"]:
                    raise ValueError("archive response checksum mismatch")
                seen.add(row["request_json"])
                if page_key is not None:
                    key = page_key(json.loads(row["response_json"]))
                    if key is not None:
                        if key in seen_pages:
                            raise ValueError("archive contains repeated record pages")
                        seen_pages.add(key)
                next_json = row["next_request_json"]
                if next_json is None:
                    if index != len(files) - 1:
                        raise ValueError("archive has pages after terminal response")
                    return Progress(self.directory, 0, 0, True)
                request = Request.from_json(next_json)
            pages = records = 0
            while max_pages is None or pages < max_pages:
                if request.to_json() in seen:
                    raise ValueError("pagination repeated a request; archive is incomplete")
                body = get(request)
                payload = json.loads(body)
                count, next_request = advance(request, payload)
                if page_key is not None:
                    key = page_key(payload)
                    if key is not None:
                        if key in seen_pages:
                            raise ValueError("API repeated record page; pagination did not advance")
                        seen_pages.add(key)
                if next_request is not None and (next_request.to_json() == request.to_json()
                                                or next_request.to_json() in seen):
                    raise ValueError("pagination cursor cycle; refusing incomplete page")
                row = {
                    "format_version": 1, "venue": self.venue, "dataset": self.dataset,
                    "page": len(files) + pages, "retrieved_at": datetime.now(UTC),
                    "request_json": request.to_json(), "response_json": body,
                    "response_sha256": hashlib.sha256(body.encode()).hexdigest(),
                    "record_count": count,
                    "next_request_json": next_request.to_json() if next_request else None,
                }
                target = self.directory / f"page-{len(files) + pages:08d}.parquet"
                table = pa.Table.from_pylist([row], schema=SCHEMA)
                with guard(max(64 * 1024, 3 * table.nbytes)):
                    self._write(target, lambda p: pq.write_table(table, p, compression="zstd"))
                seen.add(request.to_json())
                pages += 1
                records += count
                if next_request is None:
                    return Progress(self.directory, pages, records, True)
                request = next_request
            return Progress(self.directory, pages, records, False)


def records_in(payload: object, key: str | None) -> list[dict]:
    rows = payload.get(key) if key and isinstance(payload, dict) else payload
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError(f"expected an array of records at {key or 'response root'}")
    return rows


def cursor_pages(key: str):
    def advance(request: Request, payload: object) -> tuple[int, Request | None]:
        rows = records_in(payload, key)
        if not isinstance(payload, dict) or not isinstance(payload.get("cursor"), str):
            raise ValueError("missing or invalid pagination cursor")
        cursor = payload["cursor"]
        return len(rows), (Request(request.url, {**request.params, "cursor": cursor}) if cursor else None)
    return advance


def single_page(key: str | None):
    def advance(request: Request, payload: object) -> tuple[int, None]:
        return len(records_in(payload, key)), None
    return advance
