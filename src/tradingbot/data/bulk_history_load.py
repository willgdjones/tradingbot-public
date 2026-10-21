"""Load and audit the fixed history cohort with page transactions and disk gates."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import time

import pyarrow.parquet as pq
from sqlalchemy import text
from sqlalchemy.orm import Session

from .bulk_history import START, END, btc_catalog_jobs, resolution_jobs, trade_jobs, write_json
from .disk_budget import CaptureDiskBudget, DiskBudget, WRITE_HEADROOM
from .loader import Counts, Page, import_page, local_engine, read_archives
from .normalize import ImportDataError, Normalized, normalize

COMPRESSION_TABLES = ("quotes", "trades")
LOAD_SCAN_PAGES = 128


class Cohort:
    def __init__(self, rows):
        self.rows = rows
        self.contracts = defaultdict(set)
        for row in rows:
            self.contracts[row["venue"]].add(row["contract"])

    def catalog_batch(self, page: Page) -> Normalized:
        """Filter raw catalogs before normalization, preserving original provenance."""
        row = pq.ParquetFile(page.path).read().to_pylist()[0]
        body = row["response_json"]
        if hashlib.sha256(body.encode()).hexdigest() != page.row["response_sha256"]:
            raise ImportDataError("catalog changed after verification")
        payload = json.loads(body, parse_float=Decimal)
        venue, dataset = page.row["venue"], page.row["dataset"]
        wanted = self.contracts[venue]
        if venue == "kalshi":
            payload["markets"] = [m for m in payload["markets"] if m["ticker"] in wanted]
        elif dataset == "events":
            events = []
            for event in payload["events"]:
                markets = [m for m in event.get("markets", []) if m.get("conditionId") in wanted]
                if markets:
                    events.append({**event, "markets": markets})
            payload["events"] = events
        else:
            raise ImportDataError("unsupported cohort catalog")
        return normalize(venue, dataset, payload, json.loads(page.row["request_json"]))

    def pages(self, root, *, allow_incomplete=False):
        catalog_dirs = sorted({Path(c["catalog_page"]).parent for c in self.rows})
        catalogs = []
        for directory in catalog_dirs:
            pages = read_archives(directory)
            if not all(p.complete for p in pages):
                raise ImportDataError("cohort was planned from an incomplete catalog")
            catalogs.extend(pages)
        resolutions, trades, missing = [], [], []
        for kind, jobs, target in (("resolutions", resolution_jobs(self.rows), resolutions),
                                   ("trades", trade_jobs(self.rows), trades)):
            for job in jobs:
                directory = job.archive(root).directory
                if not (directory / "manifest.json").exists() or not list(directory.glob("page-*.parquet")):
                    missing.append({"kind": kind, "job": asdict(job), "reason": "not captured"})
                    continue
                pages = read_archives(directory)
                if not all(p.complete for p in pages):
                    missing.append({"kind": kind, "job": asdict(job), "reason": "cursor remains"})
                    continue  # Load only complete jobs, even during an incremental pass.
                target.extend(pages)
        if missing and not allow_incomplete:
            raise ImportDataError(f"{len(missing)} missing/incomplete jobs; capture before loading")
        return catalogs, resolutions, trades, missing


def cohort_schedule(rows, *, start=START, end=END):
    """Count catalog dates separately from events, contracts and observed trades."""
    expected = {(start + timedelta(days=i)).date().isoformat() for i in range((end - start).days)}
    groups = defaultdict(lambda: defaultdict(set))
    for row in rows:
        close = datetime.fromisoformat(row["close"])
        if close.utcoffset() is None:
            raise ImportDataError("cohort close must have an explicit timezone")
        groups[(row["venue"], row["category"])][close.astimezone(UTC).date().isoformat()].add(row["event_id"])
    daily = {("kalshi", "KXHIGHNY"), ("kalshi", "KXBTC"),
             ("polymarket_intl", "pm-series:nyc-daily-weather"),
             ("polymarket_intl", "pm-series:btc-up-or-down-daily")}
    return [{"venue": venue, "category": category,
             "basis": "catalog scheduled close UTC date; not an observation-day or trade-coverage claim",
             "distinct_scheduled_close_dates": len(dates),
             "expected_calendar_dates": len(expected) if (venue, category) in daily else None,
             "dates_without_selected_close": sorted(expected - dates.keys()) if (venue, category) in daily else None,
             "dates_with_multiple_events": [{"date": day, "event_ids": sorted(events)}
                                             for day, events in sorted(dates.items()) if len(events) > 1]}
            for (venue, category), dates in sorted(groups.items())]


def capture_report(root, cohort, *, catalog_jobs=None):
    """Audit expected requests, including empty BTC dates absent from the cohort."""
    jobs = list(btc_catalog_jobs() if catalog_jobs is None else catalog_jobs)
    requests = [("catalog", j.venue, j.dataset, j.archive(root).directory) for j in jobs]
    known = {item[3] for item in requests}
    for directory in sorted({Path(c["catalog_page"]).parent for c in cohort.rows} - known):
        manifest = json.loads((directory / "manifest.json").read_text())
        requests.append(("catalog", manifest["venue"], manifest["dataset"], directory))
    for kind, jobs in (("resolutions", resolution_jobs(cohort.rows)), ("trades", trade_jobs(cohort.rows))):
        requests.extend((kind, j.venue, j.dataset, j.archive(root).directory) for j in jobs)
    totals, gaps = defaultdict(Counter), []
    for index, (kind, venue, dataset, directory) in enumerate(requests):
        counts = totals[(kind, venue, dataset)]
        counts["expected_jobs"] += 1
        if not (directory / "manifest.json").exists() or not list(directory.glob("page-*.parquet")):
            counts["missing_jobs"] += 1
            gaps.append({"kind": kind, "directory": str(directory), "reason": "not captured"})
            continue
        pages = read_archives(directory)
        complete = all(p.complete for p in pages)
        records = sum(p.row["record_count"] for p in pages)
        counts["complete_jobs" if complete else "partial_jobs"] += 1
        counts["empty_complete_jobs"] += complete and records == 0
        counts["source_records"] += records
        counts["pages"] += len(pages)
        counts["compressed_page_bytes"] += sum(p.path.stat().st_size for p in pages)
        if not complete:
            gaps.append({"kind": kind, "directory": str(directory), "reason": "cursor remains"})
        if (index + 1) % 1000 == 0:
            print(json.dumps({"verified_requests": index + 1, "expected_requests": len(requests)}), flush=True)
    selected = defaultdict(lambda: {"contracts": 0, "events": set(), "zero_volume_contracts_not_queried": 0})
    for row in cohort.rows:
        group = selected[(row["venue"], row["category"])]
        group["contracts"] += 1
        group["events"].add(row["event_id"])
        group["zero_volume_contracts_not_queried"] += (row["venue"] == "kalshi"
            and row["status"] in {"finalized", "settled"} and row["volume"] is not None
            and Decimal(row["volume"]) == 0)
    return {"captured_jobs_complete": not gaps, "missing_jobs": gaps,
            "request_groups": [{"kind": k[0], "venue": k[1], "dataset": k[2], **dict(v)}
                               for k, v in sorted(totals.items())],
            "selected": [{"venue": k[0], "category": k[1], **v, "events": len(v["events"])}
                         for k, v in sorted(selected.items())],
            "catalog_schedule": cohort_schedule(cohort.rows),
            "finished_at": datetime.now(UTC).isoformat(), **DiskBudget(root).check().as_dict()}


def load_cohort(root, cohort, *, allow_incomplete=False):
    budget = CaptureDiskBudget(root)
    budget.check()
    catalogs, resolutions, trades, missing = cohort.pages(root, allow_incomplete=allow_incomplete)
    print(json.dumps({"catalog_pages": len(catalogs), "resolution_pages": len(resolutions),
                      "trade_pages": len(trades), "missing_jobs": len(missing)}), flush=True)
    engine, counts = local_engine(), Counts()
    normalized_rows = Counter()
    snapshot, scanned_at = budget.check(), time.monotonic()
    for phase, pages in (("catalog", catalogs), ("resolutions", resolutions), ("trades", trades)):
        for index, page in enumerate(pages):
            if index % LOAD_SCAN_PAGES == 0 or time.monotonic() - scanned_at >= 30:
                snapshot, scanned_at = budget.check(), time.monotonic()
            # DB rows do not grow data/. Check its full tree each batch and
            # actual volume free space for every page transaction.
            budget.check_free(max(WRITE_HEADROOM, page.path.stat().st_size * 40))
            batch = cohort.catalog_batch(page) if phase == "catalog" else page.normalized()
            # One bad source/page rolls back; preceding pages stay resumable.
            with Session(engine) as session, session.begin():
                session.execute(text("SET LOCAL lock_timeout = '5s'"))
                added = import_page(session, page, batch)
            free_bytes = budget.check_free()
            counts.add(added)
            normalized_rows[page.row["venue"]] += len(batch.points)
            if phase == "catalog" or (index + 1) % 50 == 0 or index + 1 == len(pages):
                print(json.dumps({"phase": phase, "page": index + 1, "of": len(pages),
                                  **asdict(counts), "data_bytes_at_last_scan": snapshot.data_bytes,
                                  "free_bytes": free_bytes}), flush=True)
    return {**asdict(counts), "normalized_source_rows": dict(normalized_rows),
            "missing_jobs": missing, "captured_jobs_complete": not missing,
            "finished_at": datetime.now(UTC).isoformat(), **budget.check().as_dict()}


def compress_old_chunks(root):
    budget, engine = DiskBudget(root), local_engine()
    budget.check()
    with engine.connect() as connection:
        chunks = []
        for hypertable in COMPRESSION_TABLES:
            # is_compressed also includes chunks with newly inserted rowstore
            # data. Revisit all eligible chunks; compress_chunk is idempotent
            # and folds those late rows into the existing columnstore.
            chunks.extend(connection.execute(text("""
                SELECT format('%I.%I', c.chunk_schema, c.chunk_name) AS relation,
                       s.total_bytes AS bytes, c.is_compressed
                FROM timescaledb_information.chunks c
                JOIN chunks_detailed_size(CAST(:hypertable AS regclass)) s
                  USING (chunk_schema, chunk_name)
                WHERE c.range_end < now() - interval '7 days'
                ORDER BY c.range_start
            """), {"hypertable": hypertable}).mappings().all())
    for chunk in chunks:
        # Detailed size includes BOTH rowstore and existing compressed storage.
        # Cover two copies plus the owner's free-space floor during rewriting.
        budget.check(max(WRITE_HEADROOM, 2 * chunk["bytes"]))
        with engine.begin() as connection:
            connection.execute(text("SET LOCAL lock_timeout = '5s'"))
            connection.execute(text("SELECT compress_chunk(CAST(:relation AS regclass), if_not_compressed => true)"),
                               {"relation": chunk["relation"]})
        print(json.dumps({"compression_checked": chunk["relation"], "before_bytes": chunk["bytes"],
                          "previously_compressed": chunk["is_compressed"]}), flush=True)
    return {"chunks_compressed": sum(not c["is_compressed"] for c in chunks),
            "previously_compressed_chunks_rechecked": sum(c["is_compressed"] for c in chunks),
            "eligible_chunks_processed": len(chunks), **budget.check().as_dict()}


def database_report(cohort):
    engine = local_engine()
    expected = {}
    # Build a small temporary mapping; no permanent strategy/trading rows change.
    for row in cohort.rows:
        if row["venue"] == "kalshi":
            for side in ("yes", "no"):
                expected[(row["venue"], row["contract"] + ":" + side)] = row
        else:
            expected[(row["venue"], row["contract"])] = row  # PM joins by market.
    with engine.connect() as connection, connection.begin():
        connection.execute(text("""CREATE TEMP TABLE history_cohort_audit (
            instrument_id bigint PRIMARY KEY, venue text, category text, event_id text, contract text
        ) ON COMMIT DROP"""))
        refs = connection.execute(text("""SELECT i.id, i.external_id, m.external_id AS market_key,
            v.key AS venue, i.metadata->'historical'->'state'->>'payout' AS payout,
            m.resolve_ts FROM instruments i JOIN markets m ON m.id=i.market_id
            JOIN venues v ON v.id=i.venue_id WHERE v.key IN ('kalshi', 'polymarket_intl')""")).mappings()
        mappings, missing_payouts, missing_resolution = [], 0, 0
        contract_counts = Counter()
        for ref in refs:
            key = (ref["venue"], ref["external_id"] if ref["venue"] == "kalshi" else ref["market_key"])
            item = expected.get(key)
            if item is None:
                continue
            mappings.append({"instrument_id": ref["id"], "venue": ref["venue"], "category": item["category"],
                             "event_id": item["event_id"], "contract": item["contract"]})
            contract_counts[(item["venue"], item["contract"])] += 1
            missing_payouts += ref["payout"] is None
            missing_resolution += ref["resolve_ts"] is None
        if mappings:
            connection.execute(text("INSERT INTO history_cohort_audit VALUES (:instrument_id,:venue,:category,:event_id,:contract)"), mappings)
        categories = [dict(r) for r in connection.execute(text("""
            SELECT c.venue, c.category, count(*) AS trade_rows,
                   count(DISTINCT t.external_trade_id) AS unique_execution_identities,
                   count(DISTINCT c.event_id) AS trade_bearing_events,
                   count(DISTINCT c.contract) AS trade_bearing_contracts,
                   count(DISTINCT (t.time AT TIME ZONE 'UTC')::date) AS observed_utc_days,
                   min(t.time) AS first_trade, max(t.time) AS last_trade,
                   count(*) - count(DISTINCT (t.instrument_id,t.external_trade_id)) AS duplicate_identities
            FROM trades t JOIN history_cohort_audit c ON c.instrument_id=t.instrument_id
            WHERE t.metadata->'historical'->>'maker_fill_eligible'='true'
            GROUP BY c.venue,c.category ORDER BY c.venue,c.category
        """)).mappings()]
        months = [dict(r) for r in connection.execute(text("""
            SELECT c.venue,c.category,to_char(t.time AT TIME ZONE 'UTC','YYYY-MM') AS month,
                   count(*) AS trade_rows,count(DISTINCT c.event_id) AS events
            FROM trades t JOIN history_cohort_audit c ON c.instrument_id=t.instrument_id
            WHERE t.metadata->'historical'->>'maker_fill_eligible'='true'
            GROUP BY c.venue,c.category,month ORDER BY c.venue,c.category,month
        """)).mappings()]
        pm_windows = [dict(r) for r in connection.execute(text("""
            SELECT DISTINCT c.category,c.event_id,c.contract,m.open_ts,m.close_ts,m.resolve_ts
            FROM history_cohort_audit c JOIN instruments i ON i.id=c.instrument_id
            JOIN markets m ON m.id=i.market_id
            WHERE c.venue='polymarket_intl' AND
                (m.open_ts IS NULL OR m.close_ts IS NULL OR m.open_ts >= m.close_ts
                 OR m.resolve_ts < m.open_ts)
            ORDER BY c.category,c.event_id,c.contract
        """)).mappings()]
        storage = dict(connection.execute(text("""SELECT pg_database_size(current_database()) AS database_bytes,
            (SELECT count(*) FROM timescaledb_information.chunks WHERE is_compressed) AS compressed_chunks,
            (SELECT count(*) FROM timescaledb_information.chunks WHERE NOT is_compressed) AS rowstore_chunks
        """)).mappings().one())
    def safe(value):
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, dict):
            return {k: safe(v) for k, v in value.items()}
        if isinstance(value, list):
            return [safe(v) for v in value]
        return value
    absent = [{"venue": r["venue"], "contract": r["contract"],
               "instrument_count": contract_counts[(r["venue"], r["contract"]) ]}
              for r in cohort.rows if contract_counts[(r["venue"], r["contract"])] != 2]
    return safe({"expected_contracts": len(cohort.rows), "instrument_count": len(mappings),
                 "contracts_without_both_outcomes": absent, "instruments_missing_payout": missing_payouts,
                 "instruments_missing_resolution_time": missing_resolution,
                 "categories": categories, "by_month": months,
                 "polymarket_catalog_window_anomalies": pm_windows, **storage})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["load", "compress", "report", "capture-report"])
    parser.add_argument("--root", type=Path, default=Path("data"))
    parser.add_argument("--state", type=Path, default=Path("data/history/longshot-20260930"))
    parser.add_argument("--allow-incomplete", action="store_true")
    args = parser.parse_args()
    cohort_bytes = (args.state / "cohort.json").read_bytes()
    cohort = Cohort(json.loads(cohort_bytes))
    if args.action == "load":
        result = load_cohort(args.root, cohort, allow_incomplete=args.allow_incomplete)
    elif args.action == "compress":
        result = compress_old_chunks(args.root)
    elif args.action == "capture-report":
        result = capture_report(args.root, cohort)
    else:
        result = database_report(cohort)
    result["cohort_sha256"] = hashlib.sha256(cohort_bytes).hexdigest()
    write_json(args.state / (args.action + "-result.json"), result, DiskBudget(args.root))
    print(json.dumps({k: v for k, v in result.items() if k not in
                     {"by_month", "missing_jobs", "contracts_without_both_outcomes"}}), flush=True)


if __name__ == "__main__":
    main()
