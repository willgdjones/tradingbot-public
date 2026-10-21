"""Disk-bounded, resumable capture of the fixed strategy-1 research cohort.

See docs/research/08-history-plan.md. No orders, credentials or trading state.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import threading
import time

import pyarrow.parquet as pq

from .archive import RawArchive, Request, canonical, cursor_pages, single_page
from .disk_budget import CaptureDiskBudget, DiskBudget
from .kalshi import BASE, KalshiPublic
from .normalize import moment
from .polymarket import DATA, GAMMA, InternationalPublic, data_pages, gamma_pages
from .transport import RetryingGetter

START = datetime(2025, 9, 1, tzinfo=UTC)
END = datetime(2026, 10, 1, tzinfo=UTC)
CATALOG_RUN = "longshot-catalog-20260930"
TARGET_RUN = "longshot-daily-20260930"
TAPE_RUN = "longshot-tape-20260930"
CAPTURE_BATCH_JOBS = 128


@dataclass(frozen=True)
class Job:
    venue: str
    dataset: str
    run: str
    url: str
    params: dict
    semantics: str

    def archive(self, root):
        return RawArchive(root, self.venue, self.dataset, self.run,
                          Request(self.url, self.params), semantics=self.semantics)

    @property
    def key(self):
        return hashlib.sha256(canonical(asdict(self)).encode()).hexdigest()


def btc_catalog_jobs():
    day = START
    while day < END:
        # The venue's daily 17:00 New York event naming was verified on 2025-09-01.
        event = "KXBTC-" + day.strftime("%y%b%d").upper() + "17"
        for tier, path in (("recent", "/markets"), ("historical", "/historical/markets")):
            yield Job("kalshi", "markets_" + tier, TARGET_RUN, BASE + path,
                      {"limit": 1000, "event_ticker": event},
                      "fixed daily 17:00 New York cohort catalog; all strikes; current metadata is not point-in-time")
        day += timedelta(days=1)


class Pace:
    """Shared request start spacing across workers and retries (at most 4/s)."""
    def __init__(self):
        self.lock = threading.Lock()
        self.next = 0.0

    def wrap(self, fetch):
        def paced(request):
            with self.lock:
                time.sleep(max(0, self.next - time.monotonic()))
                self.next = time.monotonic() + 0.25
            return fetch(request)
        return paced


def write_json(path, value, budget):
    body = json.dumps(value, indent=2, sort_keys=True) + "\n"
    with budget.reserve(max(64 * 1024, 2 * len(body.encode()))):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".partial")
        temporary.write_text(body)
        os.replace(temporary, path)


def capture_jobs(root, jobs, *, state_path, workers=4, max_pages=200, max_jobs=None):
    """Each job is independently resumable; failures cannot imply completeness."""
    if not 1 <= workers <= 4 or max_pages < 1:
        raise ValueError("workers must be 1..4 and max_pages positive")
    budget, pace = CaptureDiskBudget(root), Pace()
    budget.check()
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    jobs = list(jobs)
    # Completion cache only saves unnecessary re-fetching. The loader and final
    # audit still validate every Parquet page/checksum before any claim of proof.
    pending = [j for j in jobs if not state.get(j.key, {}).get("complete")]
    if max_jobs is not None:
        pending = pending[:max_jobs]
    local, clients, clients_lock = threading.local(), [], threading.Lock()

    def one(job):
        # Reuse each worker's own connection pool across jobs and batches.
        # Sharing one SDK instance across threads is deliberately avoided.
        if not hasattr(local, "clients"):
            local.clients = {}
        if job.venue not in local.clients:
            client = KalshiPublic() if job.venue == "kalshi" else InternationalPublic()
            local.clients[job.venue] = client
            with clients_lock:
                clients.append(client)
        get = budget.getter(RetryingGetter(pace.wrap(local.clients[job.venue]), interval=0))
        advance = (cursor_pages("markets" if job.dataset.startswith("markets_") else "trades")
                   if job.venue == "kalshi" else
                   gamma_pages(job.dataset) if job.dataset in {"markets", "events"} else
                   single_page("data") if job.dataset == "resolutions" else data_pages)
        progress = job.archive(root).capture(get, advance, max_pages=max_pages, write_guard=budget.reserve)
        return {**asdict(progress), "directory": str(progress.directory), "job": asdict(job)}

    completed = 0
    # A bounded group is a storage batch. Recheck the entire data tree before
    # each group and every network/page write inside it.
    try:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            for offset in range(0, len(pending), CAPTURE_BATCH_JOBS):
                print(json.dumps({"batch": offset // CAPTURE_BATCH_JOBS, "pending": len(pending) - offset,
                                  **budget.check().as_dict()}), flush=True)
                futures = {executor.submit(one, j): j for j in pending[offset:offset + CAPTURE_BATCH_JOBS]}
                try:
                    for future in as_completed(futures):
                        job = futures[future]
                        state[job.key] = future.result()
                        completed += 1
                except BaseException:
                    for future in futures:
                        future.cancel()
                    # Atomic archive pages survive even if the progress cache
                    # cannot be written; retry resumes those exact pages.
                    raise
                write_json(state_path, state, budget)
                print(json.dumps({"completed_this_run": completed,
                                  "complete_jobs": sum(x.get("complete", False) for x in state.values()),
                                  "total_jobs": len(jobs)}), flush=True)
    finally:
        for client in clients:
            client.close()
    return state


def catalog_rows(root):
    """Yield raw catalogs and exact source references, never execution prices."""
    patterns = ["raw/kalshi/markets_*/longshot-catalog-20260930/*/page-*.parquet",
                "raw/kalshi/markets_*/longshot-daily-20260930/*/page-*.parquet",
                "raw/polymarket_intl/events/longshot-catalog-20260930/*/page-*.parquet"]
    for pattern in patterns:
        for path in sorted(root.glob(pattern)):
            page = pq.ParquetFile(path).read().to_pylist()[0]
            request = json.loads(page["request_json"])
            payload = json.loads(page["response_json"], parse_float=Decimal)
            if page["venue"] == "kalshi":
                series = request["params"].get("series_ticker")
                event_filter = request["params"].get("event_ticker")
                if series not in {"KXHIGHNY", "KXINX"} and not event_filter:
                    continue  # Exclude the deliberately stopped broad BTC scan.
                for raw in payload["markets"]:
                    series_key = series or str(event_filter).split("-", 1)[0]
                    yield page, path, raw, series_key, raw["event_ticker"]
            else:
                expected = {10005: "nyc-daily-weather", 41: "btc-up-or-down-daily"}
                series_id = request["params"].get("series_id")
                if series_id not in expected:
                    continue
                for event in payload["events"]:
                    if not any(str(s.get("id")) == str(series_id) and s.get("slug") == expected[series_id]
                               for s in event.get("series", [])):
                        raise ValueError("Gamma event returned outside the requested recurring series")
                    for raw in event.get("markets", []):
                        yield page, path, raw, "pm-series:" + expected[series_id], str(event["id"])


def build_cohort(root):
    chosen = {}
    for page, path, raw, category, event_id in catalog_rows(root):
        kalshi = page["venue"] == "kalshi"
        close = moment(raw.get("close_time" if kalshi else "endDate"))
        if close is None or not START <= close < END:
            continue
        if kalshi and category == "KXBTC":
            if not event_id.endswith("17"):
                raise ValueError("Bitcoin cohort must be the 17:00 daily event")
        external = raw["ticker"] if kalshi else raw.get("conditionId")
        if not external:
            raise ValueError("cohort catalog missing trade identifier")
        rank = (moment(raw.get("updated_time" if kalshi else "updatedAt")) or page["retrieved_at"],
                page["retrieved_at"], str(path))
        key = (page["venue"], external)
        item = {"venue": page["venue"], "category": category, "event_id": event_id,
                "contract": external, "close": close.isoformat(),
                "status": raw.get("status" if kalshi else "umaResolutionStatus"),
                "catalog_page": str(path), "volume": str(raw.get("volume_fp" if kalshi else "volume"))
                if raw.get("volume_fp" if kalshi else "volume") is not None else None}
        if key not in chosen or rank > chosen[key][0]:
            chosen[key] = rank, item
    return sorted((x[1] for x in chosen.values()), key=lambda x: (x["close"], x["venue"], x["contract"]))


def trade_jobs(cohort):
    pm_conditions = []
    for item in cohort:
        if item["venue"] == "kalshi":
            # Keep zero-volume contracts in the cohort audit, not in a phantom
            # "complete API tape" count. Unknown volume must still be queried.
            if item["status"] in {"finalized", "settled"} and item["volume"] is not None and Decimal(item["volume"]) == 0:
                continue
            end = int(moment(item["close"]).timestamp()) + 1
            for tier, path in (("recent", "/markets/trades"), ("historical", "/historical/trades")):
                yield Job("kalshi", "trades_" + tier, TAPE_RUN, BASE + path,
                          {"ticker": item["contract"], "min_ts": end - 7 * 86400 - 2,
                           "max_ts": end, "limit": 1000},
                          "fixed thirteen-month cohort; public matched trades in final seven days; both tiers; exact IDs; not account fills")
        else:
            pm_conditions.append(item["contract"])
    # Official v2 supports up to twenty conditions per query. This avoids
    # thousands of mostly empty first pages without dropping any cohort market.
    for offset in range(0, len(pm_conditions), 20):
        yield Job("polymarket_intl", "trades_taker_history", TAPE_RUN, DATA + "/v2/trades",
                  {"condition": ",".join(pm_conditions[offset:offset + 20]), "taker_only": True, "limit": 1000},
                  "condition-scoped three-year public feed; taker_only=true; economic-fingerprint identity; block-time ordering; no account fee evidence")


def resolution_jobs(cohort):
    for job in trade_jobs([c for c in cohort if c["venue"] == "polymarket_intl"]):
        yield Job("polymarket_intl", "resolutions", "longshot-resolution-20260930", DATA + "/v2/resolutions",
                  {"condition": job.params["condition"]},
                  "terminal resolution state and lifecycle timestamp; unresolved estimates are not settlement times")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["catalog-btc", "plan", "trades", "resolutions"])
    parser.add_argument("--root", type=Path, default=Path("data"))
    parser.add_argument("--state", type=Path, default=Path("data/history/longshot-20260930"))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--max-pages", type=int, default=200)
    parser.add_argument("--max-jobs", type=int)
    parser.add_argument("--venue", choices=["kalshi", "polymarket_intl"])
    args = parser.parse_args()
    budget = DiskBudget(args.root)
    budget.check()
    if args.action == "plan":
        cohort = build_cohort(args.root)
        write_json(args.state / "cohort.json", cohort, budget)
        print(json.dumps({"contracts": len(cohort), "events": len({(c["venue"], c["event_id"]) for c in cohort}),
                          "trade_jobs": len(list(trade_jobs(cohort))), **budget.check().as_dict()}))
        return
    jobs = (btc_catalog_jobs() if args.action == "catalog-btc" else
            (resolution_jobs if args.action == "resolutions" else trade_jobs)(
                json.loads((args.state / "cohort.json").read_text())))
    if args.venue:
        jobs = (j for j in jobs if j.venue == args.venue)
    capture_jobs(args.root, jobs, state_path=args.state / (args.action + ".json"),
                 workers=args.workers, max_pages=args.max_pages, max_jobs=args.max_jobs)


if __name__ == "__main__":
    main()
