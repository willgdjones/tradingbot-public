"""Locked chronological splits and durable single-use holdout admission (PRD §4)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import hashlib
import inspect
import json
import re
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import Engine, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from tradingbot.db.models import (BacktestDataset, FamilyHoldoutSpend, HoldoutFamilyAlias,
                                  Incident, Strategy, Trial)


class HoldoutViolation(ValueError):
    pass


def utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise HoldoutViolation("dataset and replay times must be timezone-aware")
    return value.astimezone(UTC)


@dataclass(frozen=True)
class HoldoutSplit:
    """Full source coverage, with an exclusive end; never the selected run slice."""
    dataset_key: str
    data_start: datetime
    data_end: datetime

    def __post_init__(self):
        if not self.dataset_key or len(self.dataset_key) > 128:
            raise HoldoutViolation("dataset_key must contain 1..128 characters")
        object.__setattr__(self, "data_start", utc(self.data_start))
        object.__setattr__(self, "data_end", utc(self.data_end))
        if self.data_end - self.data_start < timedelta(microseconds=10):
            raise HoldoutViolation("dataset needs distinct training and holdout intervals")

    @property
    def holdout_start(self):
        micros = (self.data_end - self.data_start) // timedelta(microseconds=1)
        return self.data_start + timedelta(microseconds=micros * 7 // 10)

    def contains(self, ts, *, final_holdout=False):
        ts = utc(ts)
        lo, hi = ((self.holdout_start, self.data_end) if final_holdout else
                  (self.data_start, self.holdout_start))
        return lo <= ts < hi

    def require(self, ts, *, final_holdout=False):
        if not self.contains(ts, final_holdout=final_holdout):
            part = "final holdout" if final_holdout else "training (strictly before holdout_start)"
            raise HoldoutViolation(f"timestamp {ts.isoformat()} is outside {part}: {self.holdout_start.isoformat()}")

    def metadata(self):
        return {"dataset_key": self.dataset_key, "data_start": self.data_start.isoformat(),
                "data_end": self.data_end.isoformat(), "holdout_start": self.holdout_start.isoformat(),
                "split": "70/30 by elapsed UTC time; end exclusive"}


def json_value(value):
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise HoldoutViolation("nonfinite version parameter")
        # Decimal.normalize() uses the active precision and can merge distinct
        # high-precision parameter values. Canonicalize without arithmetic.
        if value == 0:
            return "0"
        rendered = format(value, "f")
        return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(v) for v in value]
    return value


def strategy_identity(strategy, runtime_type, version_params, execution_types=()):
    """Hash executable files and frozen decision/execution params, not run IDs.

    All configurable strategy decisions must be in Strategy.params. Source files
    are hashed directly, so uncommitted code cannot reuse a committed code hash.
    Shared fills, fees, ledger and risk code also affect the strategy version.
    """
    root = Path(__file__).resolve().parents[1]
    paths = {Path(inspect.getfile(type(strategy))).resolve(),
             Path(inspect.getfile(runtime_type)).resolve(), Path(__file__).resolve(),
             root / "backtest/engine.py", root / "backtest/fills.py",
             root / "strategy/interface.py", root / "connectors/cash.py"}
    paths.update(Path(inspect.getfile(kind)).resolve() for kind in execution_types)
    for directory in ("ledger", "risk", "fees"):
        paths.update((root / directory).glob("*.py"))
    code = {str(path.relative_to(root)) if path.is_relative_to(root) else str(path):
            hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(paths)}
    frozen = json_value({"strategy": type(strategy).__module__ + "." + type(strategy).__qualname__,
                         "key": strategy.key, "code": code, "params": strategy.params,
                         "execution_params": version_params})
    encoded = json.dumps(frozen, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest(), frozen


def register_split(session, split):
    values = {"key": split.dataset_key, "data_start": split.data_start,
              "data_end": split.data_end, "holdout_start": split.holdout_start}
    query = select(BacktestDataset.__table__).where(BacktestDataset.key == split.dataset_key)
    row = session.execute(query).mappings().one_or_none()
    if row is None:
        session.execute(insert(BacktestDataset).values(**values).on_conflict_do_nothing(index_elements=["key"]))
        row = session.execute(query).mappings().one()
    if any(row[key] != value for key, value in values.items()):
        raise HoldoutViolation("dataset bounds are locked; re-slicing an existing dataset is refused")


def engine_for(session):
    bind = session.get_bind()
    return bind if isinstance(bind, Engine) else bind.engine


# Admission is short and never loads data. One shared lock also serializes alias
# registration, so two renamed rows cannot race to assign a reactor to families.
FAMILY_ADMISSION_LOCK = int.from_bytes(hashlib.sha256(b"tradingbot-family-holdout-v1").digest()[:8], signed=True)

# Explicit owner instruction, 2026-10-01 (AGENTS d267cf7; lsr and ndl):
# re-evaluate C05/C08 using total-return equivalent accounting as new versions.
# This preserves old receipts and never represents the repeated period as unseen.
OWNER_APPROVED_RESEARCH_REVISIONS = {
    ("c05", "total_return_d267cf7"): "sweep_c05_commodity_trend_total_return_v1",
    ("c08", "total_return_d267cf7"): "sweep_c08_inventory_total_return_v1",
}


def known_family(value):
    """Candidate amendments and reactor versions retain their original family."""
    if not isinstance(value, str):
        return None
    match = re.match(r"^(?:sweep_)?(c[0-9]{2})(?:$|[-_])", value.lower())
    if match:
        return match[1]
    return {"turn_of_month": "turn_of_month", "tom_random_window_control": "turn_of_month",
            "longshot": "longshot", "letf_eod": "letf_eod", "rewards": "rewards"}.get(value)


def family_identity(strategy_row, params):
    """Family declarations are stable research provenance, never version params.

    New families declare config.research_family on the committed Strategy row.
    Existing candidate IDs/reactor names have explicit compatibility mappings.
    Renamed implementations must retain the same declaration. No automatic
    classifier can establish that two arbitrarily rewritten algorithms differ.
    """
    config = strategy_row.config or {}
    identity = (params.get("_holdout") or {}).get("identity") or params.get("_frozen") or {}
    reactor = identity.get("key")
    inferred = {key for value in (config.get("candidate"), reactor)
                if (key := known_family(value)) is not None}
    explicit = config.get("research_family")
    if explicit is not None:
        if not isinstance(explicit, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}", explicit):
            raise HoldoutViolation("research_family must be a stable 1..128 character identifier")
        inferred.add(known_family(explicit) or explicit.lower())
    if len(inferred) != 1:
        raise HoldoutViolation("declare one consistent research_family on the committed strategy before final admission")
    aliases = [f"strategy:{strategy_row.id}"]
    if reactor:
        if not isinstance(reactor, str) or len(reactor) > 248:
            raise HoldoutViolation("invalid reactor key for family registration")
        aliases.append("reactor:" + reactor)
    family = inferred.pop()
    revision = config.get("research_revision")
    if revision is not None:
        if (not isinstance(revision, str) or
                OWNER_APPROVED_RESEARCH_REVISIONS.get((family, revision)) != reactor):
            raise HoldoutViolation("research revision requires explicit owner-authorized model and reactor")
        family += ":revision:" + revision
    return family, aliases


def bind_family(audit, strategy_row, params):
    family, aliases = family_identity(strategy_row, params)
    for alias in aliases:
        previous = audit.get(HoldoutFamilyAlias, alias)
        if previous is not None and previous.family_key != family:
            raise HoldoutViolation(f"family binding is immutable: {alias} belongs to {previous.family_key}")
    for alias in aliases:
        audit.execute(insert(HoldoutFamilyAlias).values(alias=alias, family_key=family)
                      .on_conflict_do_nothing(index_elements=["alias"]))
    return family


def seen_training_trial(audit, family, split):
    """Reject a renamed/resliced holdout intersecting logged training coverage.

    Read only identity fields, never outcomes or bulky frozen calendars. Normal
    training remains caller-owned and must be committed before final admission.
    Trials without a locked split remain legacy evidence, never fresh OOS proof.
    """
    rows = audit.execute(select(
        Trial.id, Trial.strategy_id,
        Strategy.config["candidate"].astext.label("candidate"),
        Strategy.config["research_family"].astext.label("declared_family"),
        Strategy.config["research_revision"].astext.label("research_revision"),
        Trial.params["_holdout"]["identity"]["key"].astext.label("reactor"),
        Trial.params["_frozen"]["key"].astext.label("legacy_reactor"),
    ).join(Strategy, Strategy.id == Trial.strategy_id)
      .join(BacktestDataset, BacktestDataset.key == Trial.dataset_key)
      .where(Trial.mode == "backtest", ~Trial.final_holdout,
             BacktestDataset.data_start < split.data_end,
             BacktestDataset.holdout_start > split.holdout_start)
      .order_by(Trial.id)).mappings()
    for row in rows:
        reactor = row["reactor"] or row["legacy_reactor"]
        aliases = [f"strategy:{row['strategy_id']}"] + (["reactor:" + reactor] if reactor else [])
        for alias in aliases:
            binding = audit.get(HoldoutFamilyAlias, alias)
            if binding is not None and binding.family_key == family:
                return row["id"]
        identity = {"_frozen": {"key": reactor}}
        strategy = SimpleNamespace(id=row["strategy_id"], config={
            "candidate": row["candidate"], "research_family": row["declared_family"],
            "research_revision": row["research_revision"]})
        try:
            prior_family, _ = family_identity(strategy, identity)
        except HoldoutViolation:
            # Unmapped training cannot grant a final: its strategy must first
            # declare the family, after which this lookup will include it.
            continue
        if prior_family == family:
            return row["id"]
    return None


def claim_final(session, *, split, strategy_id, version, params, notes):
    """Commit family/window and version admission BEFORE consuming the feed.

    Whole previously consumed source coverage is seen: moving old training data
    into a differently named holdout cannot make it fresh. Date overlap is
    conservative across symbols and data vendors. Failed attempts stay spent.
    """
    trial_id = previous = family = None
    error = None
    with Session(engine_for(session)) as audit, audit.begin():
        audit.execute(text("SET LOCAL lock_timeout = '2s'"))
        audit.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": FAMILY_ADMISSION_LOCK})
        row = audit.get(Strategy, strategy_id)
        try:
            if row is None:
                raise HoldoutViolation("commit the research strategy and training run before a final holdout")
            family = bind_family(audit, row, params)
            register_split(audit, split)
            untracked = audit.scalar(select(Trial.id).outerjoin(
                FamilyHoldoutSpend, FamilyHoldoutSpend.trial_id == Trial.id
            ).where(Trial.final_holdout, FamilyHoldoutSpend.trial_id.is_(None)).order_by(Trial.id))
            if untracked is not None:
                raise HoldoutViolation(f"final trial {untracked} has no family receipt; audit legacy admission before proceeding")
            previous = audit.scalar(select(Trial.id).where(
                Trial.strategy_version == version, Trial.final_holdout).order_by(Trial.id))
            if previous is not None:
                kind = "holdout_reuse"
                error = f"final holdout already consumed by trial {previous}"
            else:
                previous = audit.scalar(select(FamilyHoldoutSpend.trial_id).where(
                    FamilyHoldoutSpend.family_key == family,
                    FamilyHoldoutSpend.data_start < split.data_end,
                    FamilyHoldoutSpend.data_end > split.holdout_start,
                ).order_by(FamilyHoldoutSpend.trial_id))
                if previous is not None:
                    kind = "holdout_family_reuse"
                    error = f"family {family} holdout already consumed/seen by trial {previous}"
                else:
                    previous = seen_training_trial(audit, family, split)
                    if previous is not None:
                        kind = "holdout_family_training_overlap"
                        error = f"family {family} holdout already seen in training trial {previous}"
        except HoldoutViolation as exc:
            kind, error = "holdout_admission_refused", str(exc)
        if error is None:
            trial_id = audit.scalar(insert(Trial).values(
                strategy_id=strategy_id, mode="backtest", status="running", params=params,
                dataset_key=split.dataset_key, holdout_start=split.holdout_start,
                strategy_version=version, final_holdout=True,
                data_start=split.holdout_start, data_end=split.data_end,
                notes=(notes or "") + "\nFinal holdout consumed before replay; interrupted attempts remain consumed.",
            ).on_conflict_do_nothing(index_elements=[Trial.strategy_version],
                                    index_where=Trial.final_holdout).returning(Trial.id))
            if trial_id is None:
                previous = audit.scalar(select(Trial.id).where(Trial.strategy_version == version, Trial.final_holdout))
                kind, error = "holdout_reuse", f"final holdout already consumed by trial {previous}"
            else:
                audit.add(FamilyHoldoutSpend(trial_id=trial_id, family_key=family,
                    dataset_key=split.dataset_key, data_start=split.data_start,
                    holdout_start=split.holdout_start, data_end=split.data_end))
        if error is not None:
            audit.add(Incident(severity="warning", category="other", mode="backtest",
                               message="Refused final holdout admission: " + error,
                               details={"kind": kind, "strategy_version": version,
                                        "family_key": family, "first_trial_id": previous,
                                        "requested_strategy_id": strategy_id, **split.metadata()}))
    # Raise only AFTER the refusal transaction has committed.
    if error is not None:
        raise HoldoutViolation(error + "; incident recorded")
    return trial_id
