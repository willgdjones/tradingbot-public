"""C05 bounded source/issuer watch and hash-bound, dated admission reviews.

Captures contain no strategy signal. An empty action response or a static HTML
placeholder cannot clear the issuer watch; every fund needs an explicit review.
"""
from __future__ import annotations

import argparse
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal as D
import json
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from sqlalchemy import select

from tradingbot.connectors.alpaca_paper import NAME as CONNECTOR
from tradingbot.connectors.cash import MarketSession, NEW_YORK, amount, timestamp
from tradingbot.data.alpaca_history import AlpacaHistoryAPI
from tradingbot.data.archive import Request
from tradingbot.data.disk_budget import CaptureDiskBudget
from tradingbot.data.free_history import USER_AGENT, YAHOO_CHART
from tradingbot.db.models import Instrument, Venue
from tradingbot.db.session import SessionLocal
from tradingbot.forward.c05_readiness import (
    ProbeBudget, ReadOnlyPaper, SYMBOLS, capture_actions, capture_http, capture_nontrade,
    capture_paper, close_window_evidence, digest, encoded,
)
from tradingbot.forward.c05_state import action_plans
from tradingbot.forward.paper_evidence import required_instrument_ids
from tradingbot.research.c08_source_audit import Links

ROOT = Path(__file__).resolve().parents[3]
ARCHIVE = ROOT / "data/forward/c05"
NAME = "c05_source_watch_v1"
WATCH_AGE = timedelta(hours=24)
REFERENCE_BOUND = D(".01")  # Same raw-price audit bound as C05 Amendment 21.
PUBLIC = {
    "GLD-product": "https://www.spdrgoldshares.com/usa/gld/",
    "SLV-product": "https://www.ishares.com/us/products/239855/ishares-silver-trust-fund",
    "USO-product": "https://www.uscfinvestments.com/uso",
    "UNG-product": "https://www.uscfinvestments.com/ung",
    "USCF-news": "https://www.uscfinvestments.com/news",
    "USCF-notices": "https://www.uscfinvestments.com/qualified-notices",
    "DBA-product": "https://www.invesco.com/us/en/financial-products/etfs/invesco-db-agriculture-fund.html",
}
ISSUER_KEYS = {"GLD": {"GLD-product"}, "SLV": {"SLV-product"}, "DBA": {"DBA-product"},
               "USO": {"USO-product", "USCF-news", "USCF-notices"},
               "UNG": {"UNG-product", "USCF-news", "USCF-notices"}}


def write_once(path, value, *, raw=False):
    path = Path(path).resolve()
    if not path.is_relative_to(ARCHIVE) or path == ARCHIVE:
        raise ValueError("C05 watch files must stay inside their archive")
    body = value if raw else encoded(value)
    with CaptureDiskBudget(ROOT / "data").reserve(3 * len(body) + 65536):
        with path.open("xb") as output:
            output.write(body)
    return {"path": str(path.relative_to(ROOT)), "sha256": digest(body)}


def read_receipt(ref):
    path = (ROOT / ref["path"]).resolve()
    if not path.is_relative_to(ROOT / "data/forward") or not path.is_file():
        raise ValueError("Receipt outside the forward archive")
    raw = path.read_bytes()
    if digest(raw) != ref["sha256"]:
        raise ValueError("Changed source receipt")
    return raw


def notice_links(raw, base):
    parser = Links()
    parser.feed(raw.decode("utf-8", errors="replace"))
    links = set()
    for href in parser.hrefs:
        url = urljoin(base, href).split("#")[0]
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc != urlparse(base).netloc:
            continue
        if any(word in parsed.path.lower() for word in ("notice", "split", "distribution", "press", "10-q", "10-k", "8-k", "annual")):
            links.add(url)
    if len(links) > 120:
        raise ValueError("Issuer notice inventory needs a bounded explicit review")
    return sorted(links)


def capture_public(directory, key, *, budget, reused=None):
    url = PUBLIC[key]
    if reused is not None:
        meta = json.loads(read_receipt(reused))
        raw = read_receipt(meta["raw_receipt"])
        if meta["url"] != url:
            raise ValueError("Reused issuer source URL differs")
        return {**meta, "reused_metadata_receipt": reused, "notice_links": notice_links(raw, url)}
    def fetch():
        with requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=(5, 25),
                          stream=True, allow_redirects=False) as response:
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > 8_000_000:
                    raise ValueError("Issuer source exceeds byte budget")
                chunks.append(chunk)
            return response.status_code, response.headers.get("content-type"), b"".join(chunks)
    status, content_type, raw = budget.call(fetch)
    if status != 200:
        budget.failure()
    meta = {"url": url, "status_code": status, "content_type": content_type,
            "observed_at": datetime.now(UTC).isoformat(),
            "raw_receipt": write_once(directory / (key + ".raw"), raw, raw=True),
            "notice_links": notice_links(raw, url)}
    write_once(directory / (key + ".json"), meta)
    return meta


def price_vintage(raw, symbol, sessions, observed_at):
    summary = close_window_evidence(raw, symbol, sessions, observed_at)
    result = json.loads(raw)["chart"]["result"][0]
    expected = [s.trade_date for s in sessions if summary["first_session"] <= str(s.trade_date) <= summary["last_session"]]
    indexed = {datetime.fromtimestamp(t, NEW_YORK).date(): (c, a) for t, c, a in zip(
        result["timestamp"], result["indicators"]["quote"][0]["close"], result["indicators"]["adjclose"][0]["adjclose"])}
    return {"symbol": symbol, "days": list(map(str, expected)), "last_session": summary["last_session"],
            "raw_closes": [str(amount(str(indexed[d][0]), positive=True)) for d in expected],
            "adjusted_closes": [str(amount(str(indexed[d][1]), positive=True)) for d in expected],
            "events": result.get("events", {}), "observed_at": timestamp(observed_at).isoformat(),
            "raw_sha256": digest(raw)}


def independent_comparison(vintage, bars):
    """Compare raw actual-share closes; Yahoo's historical split basis is undone."""
    if (len(vintage["days"]) != 127 or vintage["days"] != sorted(set(vintage["days"]))
            or len(vintage["raw_closes"]) != 127):
        raise ValueError("Independent comparison requires 127 ordered unique source sessions")
    indexed = {str(timestamp(r["t"]).astimezone(NEW_YORK).date()): r for r in bars}
    if len(indexed) != len(bars):
        raise ValueError("Repeated independent close")
    splits = []
    for row in vintage["events"].get("splits", {}).values():
        splits.append((datetime.fromtimestamp(row["date"], NEW_YORK).date(),
                       amount(str(row["numerator"]), positive=True) / amount(str(row["denominator"]), positive=True)))
    comparisons, missing = [], []
    last = date.fromisoformat(vintage["last_session"])
    for day, raw_close in zip(vintage["days"], vintage["raw_closes"]):
        if day not in indexed:
            missing.append(day)
            continue
        value, day_date = D(raw_close), date.fromisoformat(day)
        for ex, ratio in splits:
            if day_date < ex <= last:
                value *= ratio
        reference = amount(str(indexed[day]["c"]), positive=True)
        relative = abs(value / reference - 1)
        comparisons.append({"date": day, "source_actual_share_close": str(value),
                            "independent_close": str(reference), "relative_difference": str(relative),
                            "within_bound": relative <= REFERENCE_BOUND})
    return {"bound": str(REFERENCE_BOUND), "missing": missing, "comparisons": comparisons,
            "complete_within_bound": not missing and len(comparisons) == 127
                                     and all(r["within_bound"] for r in comparisons)}


def capture_watch(directory, *, through, reused=None):
    directory = Path(directory).resolve()
    if not directory.is_relative_to(ARCHIVE) or directory == ARCHIVE:
        raise ValueError("Use a new C05 source-watch directory")
    directory.mkdir(parents=True, exist_ok=False)
    began, errors, budget = datetime.now(UTC), {}, ProbeBudget()
    with SessionLocal() as session:
        venue = session.scalar(select(Venue).where(Venue.key == "alpaca"))
        expected = venue.metadata_[CONNECTOR]["account"]
        exposures = [session.get(Instrument, iid) for iid in required_instrument_ids(session)]
        if any(i.venue_id != venue.id or i.instrument_type != "equity" for i in exposures):
            raise ValueError("Portfolio includes an unsupported source venue or instrument")
        price_symbols = sorted(set(SYMBOLS) | {i.symbol for i in exposures})
    start = began.astimezone(NEW_YORK).date() - timedelta(days=400)
    end = through + timedelta(days=45)
    api = ReadOnlyPaper.from_env()
    try:
        paper, quotes, _ = capture_paper(api, directory, start, end, expected_account=expected, budget=budget)
        if paper.get("account", {}).get("audit", {}).get("matches_existing_cash_book") is not True:
            raise ValueError("Source watch requires the existing paper account")
        sessions = [MarketSession.from_api(r) for r in paper["calendar"]["response"]]
        try:
            nontrade = capture_nontrade(api, directory, began - timedelta(days=30), datetime.now(UTC), budget=budget)
        except Exception as exc:
            errors["nontrade"] = type(exc).__name__
            nontrade = {"exhausted": False}
    finally:
        api.close()
    api = AlpacaHistoryAPI()
    try:
        try:
            actions = capture_actions(api, directory, start, end, budget=budget)
        except Exception as exc:
            errors["actions"] = type(exc).__name__
            actions = {"exhausted": False}
        params = {"symbols": ",".join(price_symbols), "timeframe": "1Day", "adjustment": "raw", "feed": "iex",
                  "start": str(start) + "T00:00:00Z", "end": began.isoformat(), "limit": 10000, "sort": "asc", "asof": "-"}
        try:
            raw = budget.call(lambda: api(Request("https://data.alpaca.markets/v2/stocks/bars", params)))
            independent = json.loads(raw)
            independent_ref = write_once(directory / "independent.raw", raw.encode(), raw=True)
            if independent.get("next_page_token") is not None:
                raise ValueError("Independent price page is incomplete")
        except Exception as exc:
            errors["independent"] = type(exc).__name__
            independent, independent_ref = {}, None
    finally:
        api.close()
    # Includes today's daily bar only if already completed when parsed. All
    # forward sources retain actual observation times; no signal is computed.
    boundary = datetime.combine(began.astimezone(NEW_YORK).date() + timedelta(days=1), time.min, NEW_YORK)
    params = {"period1": int(datetime.combine(start, time.min, NEW_YORK).timestamp()),
              "period2": int(boundary.timestamp()), "interval": "1d", "events": "div,split", "includeAdjustedClose": "true"}
    sources = {}
    for symbol in SYMBOLS:
        try:
            meta, raw, _ = capture_http(directory, "closes-" + symbol, YAHOO_CHART.format(symbol=symbol), params=params, budget=budget)
            if meta["status_code"] != 200:
                raise ValueError("Close source HTTP error")
            curve = price_vintage(raw, symbol, sessions, meta["observed_at"])
            comparison = independent_comparison(curve, independent["bars"][symbol])
            sources[symbol] = {"vintage": curve, "comparison": comparison,
                               "raw_receipt": {"path": str((directory / ("closes-" + symbol + ".raw")).relative_to(ROOT)),
                                               "sha256": digest(raw)}}
        except Exception as exc:
            errors["closes-" + symbol] = type(exc).__name__
            sources[symbol] = {"error": type(exc).__name__}
    public = {}
    for key in PUBLIC:
        try:
            public[key] = capture_public(directory, key, budget=budget, reused=(reused or {}).get(key))
            if public[key]["status_code"] != 200:
                errors[key] = "HTTP source unavailable"
        except Exception as exc:
            errors[key] = type(exc).__name__
    files = {str(p.relative_to(directory)): digest(p.read_bytes()) for p in sorted(directory.iterdir()) if p.is_file()}
    report = {"schema": NAME, "started_at": began.isoformat(), "completed_at": datetime.now(UTC).isoformat(),
              "account_matches_book": True, "calendar": paper["calendar"]["response"], "public": public,
              "paper": paper, "quote_batch": quotes, "actions": actions, "nontrade": nontrade,
              "sources": sources, "independent_receipt": independent_ref, "files": files,
              "errors": errors, "source_admitted": False, "signals_computed": False,
              "issuer_watch_symbols": list(SYMBOLS), "empty_actions_are_clearance": False,
              "api_budget": {"attempts": budget.attempts, "halted": budget.halted}}
    return write_once(directory / "watch.json", report)


def verify_watch(ref):
    report = json.loads(read_receipt(ref))
    if report["schema"] != NAME or report["signals_computed"] is not False:
        raise ValueError("Unknown C05 source watch")
    parent = (ROOT / ref["path"]).resolve().parent
    listed = set()
    for rel, expected in report["files"].items():
        path = (parent / rel).resolve()
        if not path.is_relative_to(parent) or not path.is_file() or digest(path.read_bytes()) != expected:
            raise ValueError("Source inventory changed")
        listed.add(path.name)
    # Reviews are separate append-only receipts, not mutable children of capture.
    if not {"account.json", "calendar.json", "quote-batch.json"} <= listed:
        raise ValueError("Source watch account/calendar inventory incomplete")
    def child(name):
        if name not in listed:
            raise ValueError("Required watch child missing")
        return json.loads((parent / name).read_bytes())
    if child("calendar.json")["response"] != report["calendar"]:
        raise ValueError("Calendar differs from captured response")
    for key, value in report["paper"].items():
        if child(key + ".json") != value:
            raise ValueError("Paper source summary differs from captured response")
    if (report["account_matches_book"] is not True
            or report["paper"]["account"].get("audit", {}).get("matches_existing_cash_book") is not True):
        raise ValueError("Missing account binding")
    for key, value in report["public"].items():
        read_receipt(value["raw_receipt"])
        if value.get("reused_metadata_receipt"):
            original = json.loads(read_receipt(value["reused_metadata_receipt"]))
            if any(original[k] != value[k] for k in ("url", "status_code", "observed_at", "raw_receipt")):
                raise ValueError("Reused source observation changed")
        elif child(key + ".json") != value:
            raise ValueError("Issuer source differs from its observed receipt")
        if value["url"] != PUBLIC[key] or value["notice_links"] != notice_links(read_receipt(value["raw_receipt"]), value["url"]):
            raise ValueError("Issuer source URL or notice inventory differs")
    for label, section in (("actions", "actions"), ("nontrade", "nontrade")):
        summary = report[section]
        if not summary.get("exhausted"):
            continue
        pages = []
        for number, page_ref in enumerate(summary["pages"]):
            path = (ROOT / page_ref["path"]).resolve()
            if path.parent != parent or path.name != f"{label}-{number}.json" or path.name not in listed:
                raise ValueError("Page inventory differs from captured watch")
            pages.append(json.loads(read_receipt(page_ref)))
        if not pages:
            raise ValueError("Exhausted page evidence is missing")
        if label == "actions":
            for page in pages:
                if (digest(page["raw_response"].encode()) != page["raw_response_sha256"]
                        or json.loads(page["raw_response"]) != page["response"]):
                    raise ValueError("Action raw response differs")
            count = sum(len(v) for p in pages for v in p["response"]["corporate_actions"].values())
            if pages[-1]["response"]["next_page_token"] is not None:
                raise ValueError("Action pages are not exhausted")
        else:
            count = sum(len(p["response"]) for p in pages)
            if len(pages[-1]["response"]) >= 100:
                raise ValueError("Nontrade pages are not exhausted")
        if count != summary["records"]:
            raise ValueError("Page counts differ from summary")
    if report["independent_receipt"]:
        independent = json.loads(read_receipt(report["independent_receipt"]))
        sessions = [MarketSession.from_api(r) for r in report["calendar"]]
        for symbol, row in report["sources"].items():
            if "error" in row:
                continue
            meta = child("closes-" + symbol + ".json")
            if (meta["status_code"] != 200 or meta["request_url"] != YAHOO_CHART.format(symbol=symbol)
                    or meta["raw_sha256"] != row["raw_receipt"]["sha256"]):
                raise ValueError("Close source metadata differs")
            curve = price_vintage(read_receipt(row["raw_receipt"]), symbol, sessions, meta["observed_at"])
            if curve != row["vintage"] or independent_comparison(curve, independent["bars"][symbol]) != row["comparison"]:
                raise ValueError("Inline prices differ from immutable source bytes")
    return report


def review_watch(watch_ref, decision, output, *, now=None):
    now = timestamp(now or datetime.now(UTC))
    report = verify_watch(watch_ref)
    if (not timestamp(report["completed_at"]) <= now or not decision.get("reviewer")
            or len(decision.get("reason", "")) < 30 or set(decision.get("reviewed_files", [])) != set(report["files"])):
        raise ValueError("Named review must bind every captured source file")
    return write_once(output, {**decision, "schema": NAME + ":review", "watch": watch_ref,
        "reviewed_at": now.isoformat(), "valid_until": (timestamp(report["started_at"]) + WATCH_AGE).isoformat()})


def review_action(action, metadata_ref, output, *, reviewer, reason, now=None):
    """Persist the first causal review, retained across later daily watches."""
    now = timestamp(now or datetime.now(UTC))
    meta = json.loads(read_receipt(metadata_ref))
    read_receipt(meta["raw_receipt"])
    if (meta["status_code"] != 200 or not reviewer or len(reason) < 30
            or not timestamp(action["announced_at"]) <= timestamp(meta["observed_at"]) <= now):
        raise ValueError("Primary observed action evidence and substantive review required")
    row = {**action, "observed_at": meta["observed_at"], "reviewed_at": now.isoformat(),
           "source_receipt": meta["raw_receipt"], "source_metadata_receipt": metadata_ref}
    ref = write_once(output, {"schema": NAME + ":action", "action": row,
                              "reviewer": reviewer, "reason": reason})
    return {**row, "first_review_receipt": ref}


def admission(review_ref, sessions, *, as_of, close_day=None):
    now = timestamp(as_of)
    review = json.loads(read_receipt(review_ref))
    report = verify_watch(review["watch"])
    if (review["schema"] != NAME + ":review" or review.get("admitted") is not True
            or report["errors"] or not report["account_matches_book"]
            or set(report["sources"]) != set(SYMBOLS) or set(report["public"]) != set(PUBLIC)
            or not report["actions"].get("exhausted") or not report["nontrade"].get("exhausted")):
        raise ValueError("C05 source/action/account admission remains held")
    reviewed = timestamp(review["reviewed_at"])
    if not timestamp(report["completed_at"]) <= reviewed <= now < timestamp(review["valid_until"]):
        raise ValueError("C05 watch review is future or expired")
    if timestamp(review["valid_until"]) > timestamp(report["started_at"]) + WATCH_AGE:
        raise ValueError("Watch lifetime cannot be extended")
    if set(review.get("reviewed_files", [])) != set(report["files"]):
        raise ValueError("Incomplete reviewed source inventory")
    if set(review.get("issuer_reviews", {})) != set(SYMBOLS):
        raise ValueError("All five issuers need an explicit current watch review")
    for symbol in SYMBOLS:
        issuer = review["issuer_reviews"][symbol]
        if (issuer.get("complete") is not True or issuer.get("dynamic_content_resolved") is not True
                or issuer.get("income_and_actions_reconciled") is not True or not issuer.get("source_keys")
                or not set(issuer["source_keys"]) <= set(report["public"])
                or not ISSUER_KEYS[symbol] <= set(issuer["source_keys"])
                or len(issuer.get("reason", "")) < 30):
            raise ValueError("Issuer HTML/empty vendor response is not action clearance")
        for key in issuer["source_keys"]:
            public = report["public"][key]
            if public["status_code"] != 200 or not 0 <= (now - timestamp(public["observed_at"])).total_seconds() < WATCH_AGE.total_seconds():
                raise ValueError("Issuer evidence is unavailable, future or stale")
        if (not report["sources"][symbol]["comparison"]["complete_within_bound"]
                or review.get("adjustment_continuity", {}).get(symbol) is not True):
            raise ValueError("Independent prices or single-vintage adjustment continuity not admitted")
    if len({tuple(report["sources"][symbol]["vintage"]["days"]) for symbol in SYMBOLS}) != 1:
        raise ValueError("Five source windows must share identical completed sessions")
    if review.get("notice_inventory") != {k: v["notice_links"] for k, v in report["public"].items()}:
        raise ValueError("Review does not cover the captured issuer notice inventory")
    if review.get("unresolved_nontrade") or review.get("unresolved_actions"):
        raise ValueError("Unresolved share/cash/action evidence requires review")
    actions = review.get("actions", [])
    for action in actions:
        read_receipt(action["source_receipt"])
        first = json.loads(read_receipt(action["first_review_receipt"]))
        if (first["schema"] != NAME + ":action"
                or first["action"] != {k: v for k, v in action.items() if k != "first_review_receipt"}
                or timestamp(action["reviewed_at"]) > reviewed):
            raise ValueError("Causal action facts differ from their first review")
        meta = json.loads(read_receipt(action["source_metadata_receipt"]))
        if (meta["status_code"] != 200 or meta["observed_at"] != action["observed_at"]
                or meta["raw_receipt"] != action["source_receipt"]):
            raise ValueError("Action first-seen facts differ from captured source")
    plans = action_plans(actions, sessions, as_of=now)
    vintage = {s: report["sources"][s]["vintage"] for s in SYMBOLS}
    if close_day is not None and any(r["last_session"] != str(close_day) for r in vintage.values()):
        raise ValueError("All five coherent vintages must include today's completed close")
    return {"review": review, "watch": report, "vintage": vintage, "blackouts": plans,
            "actions": actions, "reviewed_at": reviewed.isoformat()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--through", type=date.fromisoformat, required=True)
    parser.add_argument("--reuse-public", type=Path)
    args = parser.parse_args()
    try:
        reused = json.loads(args.reuse_public.read_text()) if args.reuse_public else None
        ref = capture_watch(args.output, through=args.through, reused=reused)
        print(json.dumps({"receipt": ref, "orders": 0, "signals_computed": False}))
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__, "orders": 0}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
