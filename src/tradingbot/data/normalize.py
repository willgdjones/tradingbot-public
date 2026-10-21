"""Pure normalization of archived public data into the existing DB vocabulary.

No database or network access. Decimal values remain exact until the existing
schema's explicit precision check in the loader. Source JSON stays in Parquet.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from .archive import canonical, records_in


class ImportDataError(ValueError):
    """Invalid or unsupported source data; the current page must roll back."""


def json_value(value):
    """JSONB-safe evidence: decimal numbers become exact strings, never floats."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(v) for v in value]
    return value


def digest(value) -> str:
    return hashlib.sha256(canonical(json_value(value)).encode()).hexdigest()


def number(value, *, probability=False, positive=False) -> Decimal:
    if value is None or isinstance(value, (bool, float)):
        raise ImportDataError("missing/invalid exact numeric value")
    try:
        result = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        raise ImportDataError("invalid numeric value") from None
    if not result.is_finite() or (probability and not 0 <= result <= 1) or (positive and result <= 0):
        raise ImportDataError("numeric value outside its valid range")
    return result


def decimal_identity(value: Decimal) -> str:
    """Scale-independent economic identity without Decimal context rounding."""
    if value == 0:
        return "0"
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def moment(value) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, Decimal)) and not isinstance(value, bool):
            # Timestamp units are seconds in these APIs; no magnitude guessing.
            return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=int(number(value) * 1_000_000))
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError
        return parsed.astimezone(UTC)
    except (ValueError, TypeError, OverflowError):
        raise ImportDataError("invalid or timezone-naive source timestamp") from None


def required_time(value) -> datetime:
    result = moment(value)
    if result is None:
        raise ImportDataError("missing observation timestamp")
    return result


def identifier(value) -> str:
    if not isinstance(value, (str, int)) or isinstance(value, bool) or not str(value):
        raise ImportDataError("missing source identifier")
    result = str(value)
    if len(result) > 255:
        raise ImportDataError("source identifier exceeds schema width")
    return result


def array(value) -> list:
    if isinstance(value, str):
        try:
            value = json.loads(value, parse_float=Decimal)
        except ValueError:
            raise ImportDataError("malformed embedded JSON array") from None
    if not isinstance(value, list):
        raise ImportDataError("expected an outcome/token array")
    return value


def source_price(raw, name) -> Decimal:
    if name + "_dollars" in raw:
        return number(raw[name + "_dollars"], probability=True)
    return number(number(raw.get(name)) / 100, probability=True)


@dataclass
class Reference:
    table: str
    external_id: str
    fields: dict
    channel: str
    raw: dict
    state: dict = field(default_factory=dict)
    market_external_id: str | None = None


@dataclass
class Point:
    table: str
    instrument_external_id: str
    fields: dict
    key: str
    evidence: dict
    raw: dict


@dataclass
class Normalized:
    references: list[Reference] = field(default_factory=list)
    points: list[Point] = field(default_factory=list)
    documents: list[tuple[str, dict]] = field(default_factory=list)


def kalshi_market(raw, out, series=None):
    ticker, event = identifier(raw.get("ticker")), identifier(raw.get("event_ticker"))
    if raw.get("market_type", "binary") != "binary":
        raise ImportDataError("unsupported Kalshi contract type")
    status = raw.get("status")
    status_map = {"active": "open", "open": "open", "initialized": "closed", "unopened": "closed",
                  "inactive": "closed", "closed": "closed", "determined": "closed",
                  "disputed": "closed", "amended": "closed", "finalized": "settled",
                  "settled": "settled", "canceled": "canceled", "cancelled": "canceled"}
    if status not in status_map:
        raise ImportDataError("unknown Kalshi market status")
    state = {"status": status_map[status], "ticker": ticker, "series_ticker": series,
             "open_ts": moment(raw.get("open_time")), "close_ts": moment(raw.get("close_time")),
             "resolve_ts": moment(raw.get("settlement_ts")), "result": raw.get("result")}
    payout = None
    if state["status"] == "settled":
        if raw.get("settlement_value_dollars") is not None:
            payout = number(raw["settlement_value_dollars"], probability=True)
        elif raw.get("result") in ("yes", "no"):
            payout = Decimal(raw["result"] == "yes")
    out.references.append(Reference("market", event, {"market_type": "binary"},
                                    "contract:" + ticker, {}, {"series_ticker": series}))
    for side in ("yes", "no"):
        side_state = {**state, "payout": payout if side == "yes" or payout is None else 1 - payout}
        fields = {"symbol": ticker[:120], "instrument_type": "binary_" + side,
                  "outcome": side, "currency": "USD", "price_min": Decimal(0),
                  "price_max": Decimal(1), "contract_multiplier": Decimal(1),
                  "expiry_ts": moment(raw.get("expected_expiration_time") or raw.get("expiration_time")),
                  "range_low": number(raw["floor_strike"]) if raw.get("floor_strike") is not None else None,
                  "range_high": number(raw["cap_strike"]) if raw.get("cap_strike") is not None else None}
        out.references.append(Reference("instrument", identifier(ticker + ":" + side), fields,
                                        "catalog", raw, side_state, event))


def pm_market(raw, out, venue, *, parent_event=None):
    us = venue == "polymarket_us"
    key = identifier(raw.get("slug") if us else raw.get("conditionId"))
    labels = array(raw.get("outcomes"))
    if not labels or len(labels) != len(set(labels)) or not all(isinstance(x, str) and len(x) <= 120 for x in labels):
        raise ImportDataError("invalid or ambiguous outcome labels")
    if us:
        if len(labels) != 2:
            raise ImportDataError("US market must have two outcome sides")
        sides = raw.get("marketSides", [])
        if sides:
            mapping = {side.get("long"): side.get("description") for side in sides if isinstance(side.get("long"), bool)}
            if set(mapping) != {True, False} or set(mapping.values()) != set(labels):
                raise ImportDataError("ambiguous US long/short outcome mapping")
            labels = [mapping[True], mapping[False]]
        elif [x.lower() for x in labels] != ["yes", "no"]:
            raise ImportDataError("US named outcomes need explicit long/short mapping")
        tokens = [key + ":yes", key + ":no"]
    else:
        tokens = array(raw.get("clobTokenIds"))
        if len(tokens) != len(labels) or len(tokens) != len(set(tokens)):
            raise ImportDataError("outcome/token mapping is missing or ambiguous")
    status = "closed" if raw.get("closed") else "open"
    resolved = raw.get("status") == "MARKET_STATUS_RESOLVED" if us else raw.get("umaResolutionStatus") == "resolved"
    canceled = raw.get("status") in {"MARKET_STATUS_CANCELED", "MARKET_STATUS_CANCELLED"}
    if canceled:
        status = "canceled"
    prices = None
    if resolved:
        candidates = array(raw.get("outcomePrices"))
        if len(candidates) != len(labels):
            raise ImportDataError("resolution/outcome mapping mismatch")
        candidates = [number(x, probability=True) for x in candidates]
        # Align to explicit US long/short order; the source arrays keep source label order.
        by_label = dict(zip(array(raw["outcomes"]), candidates, strict=True))
        if sum(candidates) == 1:
            prices = [by_label[label] for label in labels]
            status = "settled"
    # Gamma commonly omits category. Its explicit recurring-series relationship
    # is a source-grounded grouping, unlike classifying question text with an LLM.
    events = [parent_event] if parent_event else raw.get("events", [])
    series = {s["slug"] for event in events for s in event.get("series", []) if s.get("slug")}
    category = raw.get("category")
    if not us and category is None and len(series) == 1:
        category = "pm-series:" + next(iter(series))
    fields = {"title": raw.get("question"), "category": category,
              "market_type": "binary" if len(labels) == 2 else "categorical",
              "status": status, "open_ts": moment(raw.get("startDate")),
              "close_ts": moment(raw.get("endDate")),
              "resolve_ts": moment(raw.get("resolvedTime")) if status == "settled" else None,
              "resolution": next((label for label, price in zip(labels, prices or []) if price == 1), None)}
    out.references.append(Reference("market", key, fields, "catalog", raw))
    for index, (token, label) in enumerate(zip(tokens, labels, strict=True)):
        if us:
            side = "yes" if index == 0 else "no"
        else:
            side = label.lower() if label.lower() in {"yes", "no"} else ("no" if len(labels) == 2 and index == 1 else "yes")
        fields = {"symbol": raw.get("slug", key)[:120], "instrument_type": "binary_" + side,
                  "outcome": label, "currency": "USD" if us else "USDC",
                  "price_min": Decimal(0), "price_max": Decimal(1), "contract_multiplier": Decimal(1),
                  "tick_size": number(raw["orderPriceMinTickSize"], positive=True) if raw.get("orderPriceMinTickSize") else None,
                  "expiry_ts": moment(raw.get("endDate"))}
        state = {"status": status, "payout": prices[index] if prices is not None else None,
                 "outcome_index": index, "market_slug": raw.get("slug")}
        evidence = {k: raw.get(k) for k in ("id", "slug", "conditionId", "updatedAt")}
        evidence.update(token_id=token, label=label)
        out.references.append(Reference("instrument", identifier(token), fields, "catalog", evidence, state, key))


def normalize(venue: str, dataset: str, payload: dict, request: dict) -> Normalized:
    out = Normalized()
    params = request.get("params", {})
    if venue == "kalshi":
        if dataset.startswith("markets_"):
            for raw in records_in(payload, "markets"):
                series = params.get("series_ticker")
                if not series and params.get("event_ticker") and params["event_ticker"] == raw.get("event_ticker"):
                    # Kalshi event tickers are prefixed with their series ticker.
                    series = str(params["event_ticker"]).split("-", 1)[0]
                kalshi_market(raw, out, series)
        elif dataset.startswith("trades_"):
            for raw in records_in(payload, "trades"):
                ticker, trade_id = identifier(raw.get("ticker")), identifier(raw.get("trade_id"))
                time = required_time(raw.get("created_time"))
                size = number(raw.get("count_fp", raw.get("count")), positive=True)
                taker = raw.get("taker_outcome_side", raw.get("taker_side"))
                for side in ("yes", "no"):
                    price = source_price(raw, side + "_price")
                    fields = {"time": time, "price": price, "size": size, "external_trade_id": trade_id,
                              "aggressor_side": ("buy" if side == taker else "sell") if taker in {"yes", "no"} else None}
                    evidence = {"kind": "public_trade", "source_trade_id": trade_id, "outcome_side": side,
                                "maker_fill_eligible": not raw.get("is_block_trade", False),
                                "projection": "same matched trade represented on each outcome"}
                    out.points.append(Point("trade", identifier(ticker + ":" + side), fields,
                                            "kalshi:" + trade_id + ":" + side, evidence, raw))
        elif dataset == "events":
            for raw in records_in(payload, "events"):
                event = identifier(raw.get("event_ticker"))
                out.references.append(Reference("market", event, {"market_type": "binary", "title": raw.get("title"),
                                                                  "category": raw.get("category")}, "event", raw,
                                                {"series_ticker": raw.get("series_ticker")}))
                for market in raw.get("markets", []):
                    kalshi_market(market, out, raw.get("series_ticker"))
        elif dataset in {"cutoff", "series", "series-fees", "event-fees"}:
            key = {"series": "series", "series-fees": "series_fee_change_arr", "event-fees": "event_fee_changes"}.get(dataset)
            for raw in records_in(payload, key) if key else [payload]:
                out.documents.append((dataset, raw))
        else:
            raise ImportDataError("unsupported Kalshi dataset")
    elif venue in {"polymarket_us", "polymarket_intl"}:
        if dataset == "markets":
            for raw in records_in(payload, "markets"):
                pm_market(raw, out, venue)
        elif dataset == "events" and venue == "polymarket_intl":
            for event in records_in(payload, "events"):
                out.documents.append(("events", {k: v for k, v in event.items() if k != "markets"}))
                for raw in event.get("markets", []):
                    pm_market(raw, out, venue, parent_event=event)
        elif dataset in {"display_prices", "price_history"}:
            us = venue == "polymarket_us"
            if us != (dataset == "display_prices"):
                raise ImportDataError("venue/price dataset mismatch")
            for raw in records_in(payload, "history" if us else "data"):
                time = required_time(raw.get("timestamp"))
                if us:
                    slug = identifier(params.get("symbol"))
                    observations = [(slug + ":yes", number(raw.get("longPrice"), probability=True)),
                                    (slug + ":no", number(raw.get("shortPrice"), probability=True))]
                else:
                    observations = [(identifier(params.get("token_id")), number(raw.get("price"), probability=True))]
                for instrument, price in observations:
                    evidence = {"kind": "display_price" if us else "sampled_price", "price": decimal_identity(price),
                                "resolution_seconds": raw.get("resolution_seconds"), "maker_fill_eligible": False}
                    key = "price:" + digest([venue, dataset, instrument, time, evidence])
                    # These prices have no guaranteed BBO/last-trade semantics.
                    out.points.append(Point("quote", identifier(instrument), {"time": time}, key, evidence, raw))
        elif dataset in {"trades_recent", "trades_taker_history"} and venue == "polymarket_intl":
            taker_history = dataset == "trades_taker_history"
            if taker_history and (request.get("url") != "https://data-api.polymarket.com/v2/trades"
                                  or params.get("taker_only") is not True or not params.get("condition")):
                raise ImportDataError("taker history requires the verified condition-scoped taker-only endpoint")
            for raw in records_in(payload, "data"):
                if taker_history and (raw.get("side") not in {"BUY", "SELL"}
                                      or raw.get("condition_id") not in str(params["condition"]).split(",")):
                    raise ImportDataError("taker history has invalid direction or unexpected condition")
                token = identifier(raw.get("token_id", raw.get("asset")))
                fields = {"time": required_time(raw.get("timestamp")),
                          "price": number(raw.get("price"), probability=True),
                          "size": number(raw.get("size"), positive=True),
                          "aggressor_side": raw["side"].lower() if taker_history else None}
                # Mixed maker/taker activity remains ineligible. Only an explicit
                # taker_only=true archive has documented aggressor semantics.
                stable = {k: raw.get(k) for k in ("transaction_hash", "proxy_wallet", "condition_id", "side", "outcome_index")}
                stable.update(token_id=token, **{k: decimal_identity(v) if isinstance(v, Decimal) else v
                                                 for k, v in fields.items()})
                natural = raw.get("trade_id")
                log_index = raw.get("log_index")
                basis = [raw.get("transaction_hash"), log_index, token] if log_index is not None else stable
                prefix = "pm-intl-taker:" if taker_history else "pm-intl:"
                key = prefix + (str(natural) if natural else digest(basis))
                fields["external_trade_id"] = identifier(key)
                evidence = {"kind": "public_taker_trade" if taker_history else "recent_public_activity", "identity_basis": "venue_id" if natural else "log_index" if log_index is not None else "economic_fingerprint",
                            "maker_fill_eligible": taker_history, "wallet_side": raw.get("side")}
                out.points.append(Point("trade", token, fields, key, evidence, raw))
        elif dataset == "settlements" and venue == "polymarket_us":
            key, payout = identifier(payload.get("slug")), number(payload.get("settlement"), probability=True)
            out.references.append(Reference("market", key, {"market_type": "binary", "status": "settled", "resolution": "yes" if payout == 1 else "no" if payout == 0 else "split"}, "settlement", payload))
            for side in ("yes", "no"):
                state = {"payout": payout if side == "yes" else 1 - payout, "status": "settled"}
                out.references.append(Reference("instrument", identifier(key + ":" + side), {}, "settlement", payload, state, key))
        elif dataset == "resolutions" and venue == "polymarket_intl":
            for raw in records_in(payload, "data"):
                # Preserve lifecycle evidence. Sentinel prices (e.g. posed=69)
                # and proposed outcomes are never promoted to settlement payouts.
                key = identifier(raw.get("condition_id"))
                out.references.append(Reference("market", key, {}, "resolution_evidence", raw))
                if raw.get("status") == "resolved":
                    timestamp = raw.get("resolved_at")
                    basis = "resolved_at"
                    if not timestamp and raw.get("transaction_hash") and str(raw.get("log_index", "")).isdigit():
                        timestamp = raw.get("last_update_timestamp")
                        basis = "resolved_lifecycle_event"
                        if isinstance(timestamp, str) and timestamp.isdigit():
                            timestamp = Decimal(timestamp) if Decimal(timestamp) > 0 else None
                    resolved_at = moment(timestamp)
                    if resolved_at is not None:
                        # Only an observed terminal state establishes availability.
                        # Do not scale oracle proposal prices or manufacture payouts;
                        # catalog outcome mappings still supply separately checked labels.
                        out.references.append(Reference("market", key, {"resolve_ts": resolved_at},
                                                        "resolution_time", raw, {"resolution_time_basis": basis}))
        else:
            raise ImportDataError("unsupported Polymarket dataset")
    else:
        raise ImportDataError("unsupported archive venue")
    return out
