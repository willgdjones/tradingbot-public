"""Import lossless public archives into the existing reference/tape schema.

One transaction per page; no new schema, credentials, trading, or risk writes.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal, localcontext
import hashlib
import json
from pathlib import Path

import pyarrow.parquet as pq
from sqlalchemy import Numeric, String, insert, or_, select, text
from sqlalchemy.orm import Session, load_only

from tradingbot.db.models import Instrument, Market, Quote, Trade, Venue
from .archive import SCHEMA, canonical
from .normalize import ImportDataError, Normalized, decimal_identity, digest, json_value, moment, normalize

# All instances of this importer serialize page writes (including dedup checks).
IMPORT_LOCK = 827406193251
MODELS = {"market": Market, "instrument": Instrument, "quote": Quote, "trade": Trade}


@dataclass(frozen=True)
class Page:
    path: Path
    manifest: dict
    row: dict
    complete: bool

    @property
    def source(self):
        return {"archive": str(self.path), "job": self.path.parent.name,
                "dataset": self.row["dataset"], "page": self.row["page"],
                "response_sha256": self.row["response_sha256"],
                "retrieved_at": self.row["retrieved_at"].isoformat(),
                "request": json.loads(self.row["request_json"]),
                "semantics": self.manifest["semantics"], "capture_complete": self.complete}

    def normalized(self):
        # Keep only page descriptors in memory, even for multi-year archives.
        if "response_json" in self.row:
            body = self.row["response_json"]
        else:
            table = pq.ParquetFile(self.path).read()
            if table.num_rows != 1 or not table.schema.equals(SCHEMA):
                raise ImportDataError(f"archive changed during import: {self.path}")
            current = table.to_pylist()[0]
            body = current.pop("response_json")
            if current != self.row:
                raise ImportDataError(f"archive changed during import: {self.path}")
        if hashlib.sha256(body.encode()).hexdigest() != self.row["response_sha256"]:
            raise ImportDataError(f"archive response checksum mismatch: {self.path}")
        return normalize(self.row["venue"], self.row["dataset"],
                         json.loads(body, parse_float=Decimal),
                         json.loads(self.row["request_json"]))


@dataclass
class Counts:
    pages: int = 0
    references_changed: int = 0
    documents_added: int = 0
    trades_inserted: int = 0
    quotes_inserted: int = 0
    points_skipped: int = 0
    identities_updated: int = 0

    def add(self, other):
        for key, value in asdict(other).items():
            setattr(self, key, getattr(self, key) + value)


def read_archives(root: Path) -> list[Page]:
    """Validate every page before any DB write; partial jobs are explicitly marked."""
    manifests = sorted(root.rglob("manifest.json"))
    if not manifests:
        raise ImportDataError("no archive manifests found")
    pages = []
    for path in manifests:
        manifest = json.loads(path.read_text())
        if manifest.get("format_version") != 1 or digest(manifest)[:24] != path.parent.name:
            raise ImportDataError(f"archive identity mismatch: {path}")
        if manifest.get("venue") not in {"kalshi", "polymarket_us", "polymarket_intl"}:
            raise ImportDataError(f"unsupported archive venue: {path}")
        request = canonical(manifest["request"])
        seen, job_rows = set(), []
        for index, file in enumerate(sorted(path.parent.glob("page-*.parquet"))):
            table = pq.ParquetFile(file).read()
            if file.name != f"page-{index:08d}.parquet" or table.num_rows != 1 or not table.schema.equals(SCHEMA):
                raise ImportDataError(f"invalid page sequence/schema: {file}")
            row = table.to_pylist()[0]
            if (row["format_version"] != 1 or row["venue"] != manifest["venue"]
                    or row["dataset"] != manifest["dataset"] or row["page"] != index
                    or row["request_json"] != request or request in seen
                    or row["record_count"] < 0 or moment(row["retrieved_at"].isoformat()) is None):
                raise ImportDataError(f"invalid page identity/request chain: {file}")
            if hashlib.sha256(row["response_json"].encode()).hexdigest() != row["response_sha256"]:
                raise ImportDataError(f"archive response checksum mismatch: {file}")
            seen.add(request)
            request = row["next_request_json"]
            if request is not None:
                request = canonical(json.loads(request))
                if request in seen:
                    raise ImportDataError(f"pagination cycle: {file}")
            del row["response_json"]
            job_rows.append((file, row))
        pages.extend(Page(file, manifest, row, request is None) for file, row in job_rows)
    if not pages:
        raise ImportDataError("archives contain no pages")
    # Catalogs (including nested event markets), then resolutions, then observations.
    def order(page):
        dataset = page.row["dataset"]
        phase = 2 if dataset in {"settlements", "resolutions"} else 3 if dataset.startswith("trades_") or dataset in {"display_prices", "price_history"} else 1
        return phase, page.row["retrieved_at"], str(page.path)
    return sorted(pages, key=order)


def checked_fields(model, fields):
    """Postgres NUMERIC must never silently round or overflow source values."""
    for name, value in fields.items():
        column = model.__table__.columns[name]
        if value is None:
            continue
        if isinstance(column.type, String) and column.type.length and len(value) > column.type.length:
            raise ImportDataError(f"{model.__tablename__}.{name} exceeds schema width")
        if isinstance(column.type, Numeric):
            if not isinstance(value, Decimal) or not value.is_finite():
                raise ImportDataError(f"{name} requires a finite Decimal")
            precision, scale = column.type.precision, column.type.scale
            if precision is None and scale is None:
                continue  # Unconstrained public-tape NUMERIC preserves the wire decimal.
            with localcontext() as ctx:
                ctx.prec = max(precision + scale + 2, len(value.as_tuple().digits) + scale + 2)
                if abs(value) >= Decimal(10) ** (precision - scale) or value != value.quantize(Decimal(1).scaleb(-scale)):
                    raise ImportDataError(f"{model.__tablename__}.{name} cannot represent source value exactly")
    return fields


def same_source_value(stored, incoming):
    """Compare aware timestamps by exact instant, including both DST folds.

    Python deliberately makes some cross-zone fold comparisons unequal, while
    same-zone equality ignores fold. PostgreSQL timestamptz preserves the
    instant but returns the session's timezone. Neither behavior may change
    deduplication of an immutable source execution.
    """
    if isinstance(stored, datetime) and isinstance(incoming, datetime):
        if stored.utcoffset() is None or incoming.utcoffset() is None:
            return stored == incoming
        return stored.astimezone(UTC) == incoming.astimezone(UTC)
    return stored == incoming


def reference_objects(session, venue, refs):
    """Lock each page's existing reference objects once, retaining new ones too."""
    wanted = {"market": set(), "instrument": set()}
    for ref in refs:
        wanted[ref.table].add(ref.external_id)
        if ref.table == "instrument":
            wanted["market"].add(ref.market_external_id)
    objects = {}
    for kind, names in wanted.items():
        if names:
            model = MODELS[kind]
            rows = session.scalars(select(model).where(model.venue_id == venue.id,
                model.external_id.in_(names)).order_by(model.id).with_for_update())
            objects.update(((kind, obj.external_id), obj) for obj in rows)
    return objects


def reference(session: Session, venue: Venue, ref, page: Page, objects) -> bool:
    model = MODELS[ref.table]
    obj = objects.get((ref.table, ref.external_id))
    creating = obj is None
    if creating:
        if ref.channel in {"settlement", "resolution_evidence", "resolution_time"}:
            raise ImportDataError(f"catalog required before {ref.channel}: {ref.external_id}")
        obj = model(venue_id=venue.id, external_id=ref.external_id)
        session.add(obj)
        objects[(ref.table, ref.external_id)] = obj
    if ref.table == "instrument":
        market = objects.get(("market", ref.market_external_id))
        if market is None:
            raise ImportDataError(f"missing market catalog: {ref.market_external_id}")
        if obj.market_id is not None and obj.market_id != market.id:
            raise ImportDataError(f"instrument changed market mapping: {ref.external_id}")
        obj.market_id = market.id
    source_time = next((ref.raw.get(k) for k in ("updated_time", "updatedAt", "updated_at") if ref.raw.get(k)), None)
    rank = (moment(source_time) or page.row["retrieved_at"]).isoformat()
    snapshot = json_value({"channel": ref.channel, "fields": ref.fields, "state": ref.state,
                           "raw": ref.raw, "rank": rank, "source": page.source})
    key = digest(snapshot)
    if key in (obj.metadata_ or {}).get("historical", {}).get("snapshots", {}):
        return False
    metadata = deepcopy(obj.metadata_ or {})
    historical = metadata.setdefault("historical", {})
    snapshots = historical.setdefault("snapshots", {})
    latest = historical.setdefault("latest", {})
    snapshots[key] = snapshot
    previous = snapshots.get(latest.get(ref.channel), {})
    # Rank ties are deterministic; an identical archive order is not required.
    if (rank, key) >= (previous.get("rank", ""), latest.get(ref.channel, "")):
        latest[ref.channel] = key
    effective, state = {}, {}
    # Settlement endpoint wins over catalog guesses. Preserve all older evidence.
    for channel in (ref.channel,) if ref.channel.startswith("contract:") else ("event", "catalog", "settlement", "resolution_time"):
        version = snapshots.get(latest.get(channel), {})
        effective.update(version.get("fields", {}))
        state.update(version.get("state", {}))
    for name, value in effective.items():
        column = model.__table__.columns[name]
        if isinstance(column.type, Numeric) and value is not None:
            value = Decimal(value)
        elif name.endswith("_ts") and value is not None:
            value = moment(value)
        checked_fields(model, {name: value})
        setattr(obj, name, value)
    if state:
        historical["state"] = state
    historical["version"] = 1
    obj.metadata_ = metadata
    session.flush()
    return True


def aggregate_kalshi(session, venue, market_keys):
    """Event summaries describe the known contracts; payouts remain per contract."""
    for key in market_keys:
        market = session.scalar(select(Market).where(Market.venue_id == venue.id, Market.external_id == key).with_for_update())
        states = [((i.metadata_ or {}).get("historical") or {}).get("state", {}) for i in session.scalars(select(Instrument).where(Instrument.market_id == market.id))]
        states = [state for state in states if state.get("status")]
        if not states:
            continue
        statuses = {s["status"] for s in states}
        market.status = "open" if "open" in statuses else "settled" if statuses == {"settled"} else "canceled" if statuses == {"canceled"} else "closed"
        for name, operation in (("open_ts", min), ("close_ts", max), ("resolve_ts", max)):
            values = [moment(s[name]) for s in states if s.get(name)]
            setattr(market, name, operation(values) if len(values) == len(states) and (name != "resolve_ts" or market.status == "settled") else None)
        metadata = deepcopy(market.metadata_ or {})
        metadata.setdefault("historical", {})["aggregation_scope"] = "observed contracts only; catalog may be incomplete"
        market.metadata_ = metadata


def observations(session, venue, points, page, counts):
    if not points:
        return
    names = {point.instrument_external_id for point in points}
    instruments = dict(session.execute(select(Instrument.external_id, Instrument.id).where(Instrument.venue_id == venue.id, Instrument.external_id.in_(names))).all())
    missing = names - instruments.keys()
    if missing:
        raise ImportDataError(f"missing instrument catalog: {sorted(missing)[:3]}")
    for table in ("trade", "quote"):
        selected = [p for p in points if p.table == table]
        if not selected:
            continue
        model = MODELS[table]
        times = [p.fields["time"] for p in selected]
        query = select(model).where(model.instrument_id.in_(instruments.values()))
        window = model.time.between(min(times), max(times))
        if table == "trade":
            # Native IDs must not reappear with a changed timestamp outside the window.
            window = or_(window, Trade.external_trade_id.in_([p.fields["external_trade_id"] for p in selected]))
        existing = {}
        for old in session.scalars(query.where(window)):
            evidence = (old.metadata_ or {}).get("historical", {})
            key = old.external_trade_id if table == "trade" else evidence.get("record_key")
            # Upgrade fingerprints written before scale-independent decimal keys.
            # Only our derived identities change; venue-native trade IDs never do.
            canonical_key = key
            canonical_evidence = dict(evidence)
            if table == "trade" and evidence.get("identity_basis") == "economic_fingerprint":
                source = evidence.get("source", {})
                dataset = source.get("dataset", "trades_recent")
                canonical_key = normalize(venue.key, dataset, {"data": [evidence["raw"]]}, source.get("request", {})).points[0].key
            elif table == "quote" and evidence.get("kind") in {"display_price", "sampled_price"}:
                canonical_evidence["price"] = decimal_identity(Decimal(evidence["price"]))
                economic = {k: canonical_evidence[k] for k in ("kind", "price", "resolution_seconds", "maker_fill_eligible")}
                name = next(name for name, inst in instruments.items() if inst == old.instrument_id)
                canonical_key = "price:" + digest([venue.key, evidence["source"]["dataset"], name, moment(old.time.isoformat()), economic])
            if canonical_key != key:
                metadata = deepcopy(old.metadata_)
                canonical_evidence["record_key"] = canonical_key
                metadata["historical"] = canonical_evidence
                old.metadata_ = metadata
                if table == "trade":
                    old.external_trade_id = canonical_key
                evidence, key = canonical_evidence, canonical_key
                counts.identities_updated += 1
            if key:
                natural = (old.instrument_id, key)
                if natural in existing:
                    raise ImportDataError("database already contains duplicate observation identities")
                existing[natural] = (old, evidence)
        pending = []
        for point in selected:
            fields = checked_fields(model, point.fields)
            inst = instruments[point.instrument_external_id]
            key = fields["external_trade_id"] if table == "trade" else point.key
            natural = (inst, key)
            if natural in existing:
                old, evidence = existing[natural]
                values = old if isinstance(old, dict) else {k: getattr(old, k) for k in fields}
                if any(not same_source_value(values.get(k), v) for k, v in fields.items()) or any(evidence.get(k) != json_value(v) for k, v in point.evidence.items()):
                    raise ImportDataError(f"conflicting observation identity: {point.key}")
                counts.points_skipped += 1
                continue
            evidence = {**json_value(point.evidence), "record_key": point.key, "version": 1,
                        "source": page.source, "raw": json_value(point.raw)}
            pending.append({**fields, "instrument_id": inst, "metadata": {"historical": evidence}})
            existing[natural] = (fields, evidence)
        if pending:
            session.execute(insert(model.__table__), pending)
        setattr(counts, table + "s_inserted", len(pending))


def import_page(session: Session, page: Page, batch: Normalized | None = None) -> Counts:
    """Caller owns transaction; any error must roll it back before continuing."""
    batch = batch if batch is not None else page.normalized()
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": IMPORT_LOCK})
    venue_query = select(Venue).where(Venue.key == page.row["venue"])
    if not batch.documents:
        # A venue can hold large archived event documents. Tape/reference pages
        # need only its identity, not the entire JSON evidence on every read.
        venue_query = venue_query.options(load_only(Venue.id, Venue.key))
    # The import advisory lock serializes reference/tape deduplication. Only
    # auxiliary documents mutate venue metadata; catalog pages must not block
    # unrelated venue seed/settings transactions for their whole import.
    venue = session.scalar(venue_query.with_for_update() if batch.documents else venue_query)
    if venue is None:
        raise ImportDataError("venue not seeded; importer never creates/enables venues")
    counts = Counts(pages=1)
    objects = reference_objects(session, venue, batch.references)
    for ref in batch.references:
        counts.references_changed += reference(session, venue, ref, page, objects)
    if venue.key == "kalshi":
        aggregate_kalshi(session, venue, {r.external_id for r in batch.references if r.table == "market"})
    if batch.documents:
        metadata = deepcopy(venue.metadata_ or {})
        documents = metadata.setdefault("historical", {}).setdefault("documents", {})
        for kind, raw in batch.documents:
            value = {"kind": kind, "raw": json_value(raw), "source": page.source}
            key = digest(value)
            if key not in documents:
                documents[key] = value
                counts.documents_added += 1
        venue.metadata_ = metadata
    observations(session, venue, batch.points, page, counts)
    session.flush()
    return counts


def local_engine():
    from dotenv import load_dotenv
    from tradingbot.db.session import get_engine
    load_dotenv(".env", override=False)
    engine = get_engine()
    if engine.url.host not in {"localhost", "127.0.0.1", "::1"} or engine.url.port != 5433 or engine.url.database != "tradingbot":
        raise ImportDataError("loader requires local tradingbot database on port 5433")
    return engine


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=Path("data/raw"))
    parser.add_argument("--validate-only", action="store_true", help="validate and normalize without accessing Postgres")
    args = parser.parse_args()
    try:
        pages = read_archives(args.root)
        # Fail unsupported/malformed source records before committing any page.
        for page in pages:
            page.normalized()
        jobs = {str(p.path.parent): p.complete for p in pages}
        result = {"archive_pages": len(pages), "jobs": len(jobs), "incomplete_jobs": sum(not complete for complete in jobs.values())}
        if not args.validate_only:
            counts = Counts()
            engine = local_engine()
            for page in pages:
                with Session(engine) as session, session.begin():
                    added = import_page(session, page)
                counts.add(added)
            result.update(asdict(counts))
        print(json.dumps(result, sort_keys=True))
    except ImportDataError as error:
        parser.exit(1, f"Import stopped: {error}\n")


if __name__ == "__main__":
    main()
