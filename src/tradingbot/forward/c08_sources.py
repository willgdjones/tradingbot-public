"""Immutable C08 publication/watch receipts and explicit, dated source review.

An empty vendor page never clears an issuer watch. This adapter only consumes a
review of the exact captured bytes; changed documents require another review.
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from sqlalchemy import select

from tradingbot.connectors.alpaca_paper import AlpacaPaperConnector, NAME as CONNECTOR
from tradingbot.connectors.cash import MarketSession, timestamp
from tradingbot.data.alpaca_history import AlpacaHistoryAPI
from tradingbot.data.disk_budget import CaptureDiskBudget
from tradingbot.data.free_history import USER_AGENT
from tradingbot.db.models import Venue
from tradingbot.db.session import SessionLocal
from tradingbot.forward.c05_readiness import ProbeBudget, ReadOnlyPaper, capture_nontrade
from tradingbot.forward.c08_readiness import capture_actions, capture_eia, digest, encoded
from tradingbot.forward.c08_state import action_plans
from tradingbot.research.c08_source_audit import Links

ROOT = Path(__file__).resolve().parents[3]
ARCHIVE = ROOT / "data/forward/c08-integration"
NAME = "c08_source_watch_v1"
PUBLIC = {
    "issuer-product": "https://www.uscfinvestments.com/uso",
    "issuer-news": "https://www.uscfinvestments.com/news",
    "issuer-qualified-notices": "https://www.uscfinvestments.com/qualified-notices",
    "eia-method": "https://www.eia.gov/petroleum/supply/weekly/pdf/appendixb.pdf",
    "eia-errata": "https://www.eia.gov/petroleum/supply/weekly/pdf/appendix_e.pdf",
}
MAX_WATCH_AGE = timedelta(hours=24)


def write_once(path, value, *, raw=False):
    path = Path(path).resolve()
    if not path.is_relative_to(ARCHIVE) or path == ARCHIVE:
        raise ValueError("C08 receipts must stay inside the integration archive")
    body = value if raw else encoded(value)
    with CaptureDiskBudget(ROOT / "data").reserve(3 * len(body) + 65536):
        with path.open("xb") as output:
            output.write(body)
    return {"path": str(path.relative_to(ROOT)), "sha256": digest(body)}


def read_receipt(ref):
    path = (ROOT / ref["path"]).resolve()
    if not path.is_relative_to(ARCHIVE) or not path.is_file():
        raise ValueError("Source receipt outside C08 integration archive")
    raw = path.read_bytes()
    if digest(raw) != ref["sha256"]:
        raise ValueError("Source receipt bytes changed")
    return raw


def fetch_public(directory, key, url):
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc not in {"www.eia.gov", "www.uscfinvestments.com"}:
        raise ValueError("Source watch is restricted to primary public hosts")
    with requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=(5, 25),
                      stream=True, allow_redirects=False) as response:
        chunks, count = [], 0
        for chunk in response.iter_content(65536):
            count += len(chunk)
            if count > 8_000_000:
                raise ValueError("Source watch response exceeds byte limit")
            chunks.append(chunk)
        body = b"".join(chunks)
        raw = write_once(directory / f"{key}.raw", body, raw=True)
        meta = {"url": url, "status_code": response.status_code, "observed_at": datetime.now(UTC).isoformat(),
                "content_type": response.headers.get("content-type"), "raw_receipt": raw}
        write_once(directory / f"{key}.json", meta)
    return meta, body


def notice_links(raw, base):
    links = Links()
    links.feed(raw.decode("utf-8", errors="replace"))
    result = set()
    for href in links.hrefs:
        url = urljoin(base, href)
        parsed = urlparse(url)
        if parsed.netloc != urlparse(base).netloc or parsed.scheme != "https":
            continue
        if any(word in parsed.path.lower() for word in ("notice", "split", "distribution", "press-release", "wpsr_notice")):
            result.add(url.split("#")[0])
    if len(result) > 40:
        raise ValueError("Notice link inventory exceeds bounded review")
    return sorted(result)


def capture_watch(directory, *, through, paper_api, history_api, expected_account):
    directory = Path(directory).resolve()
    if not directory.is_relative_to(ARCHIVE) or directory == ARCHIVE:
        raise ValueError("Use a new C08 integration directory")
    directory.mkdir(parents=True, exist_ok=False)
    began, errors, budget = datetime.now(UTC), {}, ProbeBudget()
    account = budget.call(paper_api.account)
    AlpacaPaperConnector._account_ok(account)
    if AlpacaPaperConnector._fingerprint(account) != expected_account:
        raise ValueError("Paper watch account differs from existing cash book")
    rows = budget.call(lambda: paper_api.calendar_range(began.date() - timedelta(days=10), through + timedelta(days=10)))
    sessions = [MarketSession.from_api(row) for row in rows]
    write_once(directory / "calendar.json", {"observed_at": datetime.now(UTC), "response": rows})
    public, inventory = {}, {}
    for key, url in PUBLIC.items():
        try:
            meta, body = budget.call(lambda: fetch_public(directory, key, url))
            public[key] = meta
            if meta["status_code"] != 200:
                errors[key] = "HTTP source unavailable"
                budget.failure()
            if "text/html" in (meta["content_type"] or ""):
                inventory[key] = notice_links(body, url)
        except Exception as exc:
            errors[key] = type(exc).__name__
    try:
        eia = budget.call(lambda: capture_eia(directory, sessions))
        page = (directory / "eia-page/raw").read_bytes()
        inventory["eia-page"] = notice_links(page, eia["source_url"])
    except Exception as exc:
        eia = {"error": type(exc).__name__}
        errors["eia"] = type(exc).__name__
    try:
        actions = budget.call(lambda: capture_actions(history_api, directory, began.date() - timedelta(days=30), through + timedelta(days=45)))
    except Exception as exc:
        actions = {"exhausted": False}
        errors["actions"] = type(exc).__name__
    try:
        nontrade = capture_nontrade(paper_api, directory, began - timedelta(days=30), datetime.now(UTC), budget=budget)
    except Exception as exc:
        nontrade = {"exhausted": False}
        errors["nontrade"] = type(exc).__name__
    files = {str(p.relative_to(directory)): digest(p.read_bytes())
             for p in sorted(directory.rglob("*")) if p.is_file()}
    report = {"schema": NAME, "started_at": began.isoformat(), "completed_at": datetime.now(UTC).isoformat(),
              "account_matches_book": True, "calendar": rows, "public": public,
              "notice_links": inventory, "eia": eia, "actions": actions, "nontrade": nontrade,
              "errors": errors, "files": files, "source_admitted": False,
              "scope": {"symbol": "USO", "action_lookback_days": 30,
                        "action_through": str(through + timedelta(days=45)), "nontrade_lookback_days": 30},
              "issuer_dynamic_content_review_required": True, "empty_broker_is_clearance": False}
    report["capture_code_sha256"] = digest(Path(__file__).read_bytes())
    return write_once(directory / "watch.json", report)


def verify_watch(ref):
    report = json.loads(read_receipt(ref))
    if report["schema"] != NAME:
        raise ValueError("Unknown C08 source schema")
    parent = (ROOT / ref["path"]).resolve().parent
    for rel, expected in report["files"].items():
        path = (parent / rel).resolve()
        if not path.is_relative_to(parent) or not path.is_file() or digest(path.read_bytes()) != expected:
            raise ValueError("Captured watch file changed or is missing")
    return report


def review_watch(watch_ref, decision, output, *, now=None):
    """Append a signed-by-name assessment; never reuse another capture's review."""
    now = timestamp(now or datetime.now(UTC))
    report = verify_watch(watch_ref)
    if timestamp(report["completed_at"]) > now:
        raise ValueError("Cannot review future capture")
    if not decision.get("reviewer") or len(decision.get("reason", "")) < 20:
        raise ValueError("A named, substantive source review is required")
    if set(decision.get("reviewed_files", [])) != set(report["files"]):
        raise ValueError("Review must bind every captured file")
    result = {**decision, "schema": NAME + ":review", "watch": watch_ref,
              "reviewed_at": now.isoformat(), "valid_until": (timestamp(report["started_at"]) + MAX_WATCH_AGE).isoformat()}
    # Preserve negative decisions as receipts too. Admission validates all gates.
    ref = write_once(output, result)
    return ref


def admission(review_ref, sessions, *, as_of):
    now = timestamp(as_of)
    review = json.loads(read_receipt(review_ref))
    report = verify_watch(review["watch"])
    reviewed = timestamp(review["reviewed_at"])
    if not timestamp(report["completed_at"]) <= reviewed <= now < timestamp(review["valid_until"]):
        raise ValueError("Source watch review is future-dated or expired")
    if timestamp(review["valid_until"]) > timestamp(report["started_at"]) + MAX_WATCH_AGE:
        raise ValueError("Source watch lifetime was extended")
    if (review.get("admitted") is not True or report["errors"] or not report["account_matches_book"]
            or not report["actions"].get("exhausted") or not report["nontrade"].get("exhausted")):
        raise ValueError("Source/account watch is not admitted")
    if set(review.get("reviewed_files", [])) != set(report["files"]):
        raise ValueError("Review does not cover the captured source bytes")
    for key in ("issuer_coverage", "eia_methodology", "broker_actions", "nontrade_activity"):
        item = review.get(key, {})
        if item.get("clear") is not True or len(item.get("reason", "")) < 20:
            raise ValueError("Missing explicit issuer/methodology/action/activity review")
    if review.get("unresolved_notices") != [] or review.get("unmatched_activities") != []:
        raise ValueError("Unknown or conflicting notice/activity requires resolution")
    if report["nontrade"].get("records", 0):
        # No guessed credit, split or cash-in-lieu posting. A future nontrade
        # receipt needs an explicit account reconciliation adapter/admission.
        raise ValueError("Observed nontrade activity requires account reconciliation before C08 admission")
    reviewed_links = set(review.get("reviewed_notice_links", []))
    all_links = {url for links in report["notice_links"].values() for url in links}
    if reviewed_links != all_links:
        raise ValueError("New or missing notice link requires review")
    actions = review.get("actions", [])
    broker_rows = []
    for page in report["actions"]["pages"]:
        body = json.loads(read_receipt(page))
        broker_rows += [r for group in body["response"]["corporate_actions"].values() for r in group]
    if set(review.get("reviewed_broker_rows", [])) != {digest(encoded(row)) for row in broker_rows}:
        raise ValueError("Corporate-action row inventory differs from review")
    for row in actions:
        if row["issuer_source"] not in report["files"]:
            raise ValueError("Action lacks captured issuer evidence")
        if timestamp(row["reviewed_at"]) > reviewed:
            raise ValueError("Action review postdates source assessment")
        sources = [meta for meta in report["public"].values()
                   if Path(meta["raw_receipt"]["path"]).name == row["issuer_source"]]
        if len(sources) != 1 or timestamp(row["observed_at"]) < timestamp(sources[0]["observed_at"]):
            raise ValueError("Action first-seen time precedes its captured issuer source")
    mappings = [key for action in actions for key in action.get("broker_rows", [])]
    if len(mappings) != len(set(mappings)) or set(mappings) != {digest(encoded(row)) for row in broker_rows}:
        raise ValueError("Every broker action must map to one reviewed issuer action")
    prepared = {s.trade_date: s for s in sessions}
    for row in report["calendar"]:
        observed = MarketSession.from_api(row)
        if observed.trade_date in prepared and observed != prepared[observed.trade_date]:
            raise ValueError("Observed official calendar differs from prepared C08 calendar")
    plans = action_plans(actions, sessions, as_of=now)
    return {"review": review, "watch": report, "blackouts": plans,
            "review_ref": review_ref, "eia": report["eia"], "actions": actions}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    capture = sub.add_parser("capture")
    capture.add_argument("--directory", required=True, type=Path)
    capture.add_argument("--through", required=True)
    review = sub.add_parser("review")
    review.add_argument("--watch", required=True, type=Path)
    review.add_argument("--decision", required=True, type=Path)
    review.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "capture":
        from datetime import date
        with SessionLocal() as session:
            venue = session.scalar(select(Venue).where(Venue.key == "alpaca"))
            expected = venue.metadata_[CONNECTOR]["account"]
        paper, history = ReadOnlyPaper.from_env(), AlpacaHistoryAPI()
        try:
            ref = capture_watch(args.directory, through=date.fromisoformat(args.through),
                                paper_api=paper, history_api=history, expected_account=expected)
        finally:
            paper.close()
            history.close()
    else:
        path = args.watch.resolve()
        ref = review_watch({"path": str(path.relative_to(ROOT)), "sha256": digest(path.read_bytes())},
                           json.loads(args.decision.read_text()), args.output)
    print(json.dumps(ref))


if __name__ == "__main__":
    main()
