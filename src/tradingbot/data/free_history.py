"""Free daily equity history (Yahoo Finance chart API) with archival integrity.

For the Alpaca strategy sweep (docs/research/07-candidate-shortlist.md). Read-only
HTTP GET of Yahoo's public chart endpoint — no key, no account, no premium feed.
Every capture archives the raw response bytes, the exact request URL, a UTC
retrieval timestamp and a sha256, so a backtest can prove what it consumed and a
re-load re-verifies the hash before any return is computed.

Adjustment rules (recorded, never assumed equivalent across sources):
  * Yahoo ``indicators.quote`` OHLC are **split-adjusted** but *not*
    dividend-adjusted; ``adjclose`` is split- *and* dividend-adjusted.
  * SPY has never split, so for SPY in-sample the quote OHLC equal actual traded
    prices. Execution uses raw quote prices; the monthly **signal** uses adjclose
    (a dimensionless trend comparison, not an executable price or a second
    dividend); cash dividends are credited separately on a payment-date proxy.
  * Stooq (the preregistered cross-check) is currently behind a JS/bot challenge
    and unreachable here; the independent cross-check instead uses the existing
    Alpaca IEX archive over its 2016+ overlap. No feed is silently switched to
    rescue a result.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path

import requests

YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
USER_AGENT = "Mozilla/5.0 (research; read-only daily bars)"
SOURCE = "yahoo_chart_v8"


class FreeHistoryError(RuntimeError):
    pass


@dataclass(frozen=True)
class DailyBar:
    """One regular session. ``dividend`` is the per-share cash dividend with this
    session as ex-date (0 if none); ``split_ratio`` is new/old shares (1 if none)."""
    date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    adj_close: Decimal
    dividend: Decimal
    split_ratio: Decimal


def _epoch(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp())


def fetch_yahoo_daily(symbol: str, start: date, end: date, *, session=None,
                      timeout: int = 60) -> tuple[str, str]:
    """GET daily bars + div/split events. Returns (request_url, raw_response_text)."""
    url = YAHOO_CHART.format(symbol=symbol)
    params = {"period1": _epoch(start), "period2": _epoch(end),
              "interval": "1d", "events": "div,split", "includeAdjustedClose": "true"}
    getter = session or requests
    r = getter.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    if r.status_code != 200:
        raise FreeHistoryError(f"yahoo {symbol}: HTTP {r.status_code}")
    return (r.url, r.text)


def _dec(x) -> Decimal:
    return Decimal(str(x))


def parse_yahoo(raw_text: str) -> tuple[dict, list[DailyBar]]:
    """Parse a Yahoo chart response into (meta, chronological bars). Rows with any
    null OHLC are dropped (rare provider gaps) and counted in meta['null_rows']."""
    from tradingbot.data.alpaca_history import NY
    doc = json.loads(raw_text)
    chart = doc.get("chart") or {}
    if chart.get("error"):
        raise FreeHistoryError(f"yahoo error: {chart['error']}")
    results = chart.get("result") or []
    if not results:
        raise FreeHistoryError("yahoo: empty result")
    res = results[0]
    meta = dict(res.get("meta") or {})
    stamps = res.get("timestamp") or []
    quote = (res.get("indicators", {}).get("quote") or [{}])[0]
    adj = (res.get("indicators", {}).get("adjclose") or [{}])
    adjclose = (adj[0].get("adjclose") if adj else None) or [None] * len(stamps)
    events = res.get("events") or {}
    # Map event ex-dates (NY date) -> amount / split ratio.
    divs: dict[date, Decimal] = {}
    for ev in (events.get("dividends") or {}).values():
        d = datetime.fromtimestamp(ev["date"], NY).date()
        divs[d] = divs.get(d, Decimal(0)) + _dec(ev["amount"])
    splits: dict[date, Decimal] = {}
    for ev in (events.get("splits") or {}).values():
        d = datetime.fromtimestamp(ev["date"], NY).date()
        num = _dec(ev.get("numerator", 1)); den = _dec(ev.get("denominator", 1))
        splits[d] = (num / den) if den else Decimal(1)
    bars: list[DailyBar] = []
    null_rows = 0
    o = quote.get("open") or []; h = quote.get("high") or []
    low = quote.get("low") or []; c = quote.get("close") or []
    v = quote.get("volume") or []
    for i, ts in enumerate(stamps):
        row = (o[i] if i < len(o) else None, h[i] if i < len(h) else None,
               low[i] if i < len(low) else None, c[i] if i < len(c) else None)
        ac = adjclose[i] if i < len(adjclose) else None
        if any(x is None for x in row) or ac is None:
            null_rows += 1
            continue
        d = datetime.fromtimestamp(ts, NY).date()
        bars.append(DailyBar(
            date=d, open=_dec(row[0]), high=_dec(row[1]), low=_dec(row[2]),
            close=_dec(row[3]), volume=int(v[i]) if i < len(v) and v[i] is not None else 0,
            adj_close=_dec(ac), dividend=divs.get(d, Decimal(0)),
            split_ratio=splits.get(d, Decimal(1))))
    bars.sort(key=lambda b: b.date)
    meta["null_rows"] = null_rows
    return meta, bars


# --- Archival ----------------------------------------------------------------
def archive_capture(symbol: str, start: date, end: date, out_dir: Path,
                    *, session=None) -> Path:
    """Fetch and durably archive one capture. Writes ``<out_dir>/<symbol>/`` with
    ``raw.json`` (verbatim response) and ``manifest.json`` (url, retrieval ts,
    sha256, params, adjustment notes). Returns the capture directory."""
    url, raw = fetch_yahoo_daily(symbol, start, end, session=session)
    retrieved = datetime.now(UTC).isoformat()
    sha = hashlib.sha256(raw.encode()).hexdigest()
    cap = out_dir / symbol
    cap.mkdir(parents=True, exist_ok=True)
    (cap / "raw.json").write_text(raw)
    manifest = {
        "source": SOURCE, "symbol": symbol, "request_url": url,
        "retrieved_utc": retrieved, "sha256": sha,
        "requested_start": start.isoformat(), "requested_end_exclusive": end.isoformat(),
        "adjustment_rules": {
            "quote_ohlc": "split-adjusted, not dividend-adjusted",
            "adj_close": "split- and dividend-adjusted",
            "execution_price_basis": "raw quote open/close",
            "signal_price_basis": "adj_close",
            "dividends": "per-share cash on ex-date; credited on a payment-date proxy",
        },
        "notes": "Stooq cross-check unavailable (JS/bot challenge); use Alpaca IEX 2016+ overlap.",
    }
    (cap / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return cap


def load_capture(capture_dir: Path) -> tuple[dict, list[DailyBar]]:
    """Re-verify sha256 against the manifest, then parse. Raises on any mismatch."""
    manifest = json.loads((capture_dir / "manifest.json").read_text())
    raw = (capture_dir / "raw.json").read_text()
    if hashlib.sha256(raw.encode()).hexdigest() != manifest["sha256"]:
        raise FreeHistoryError(f"archive checksum mismatch: {capture_dir}")
    _, bars = parse_yahoo(raw)
    return manifest, bars


# --- Validation --------------------------------------------------------------
def validate_coverage(bars: list[DailyBar], start: date, end: date,
                      *, max_gap_days: int = 6) -> dict:
    """Coverage/sanity checks computed WITHOUT inspecting any strategy return.
    ``max_gap_days`` flags calendar gaps between consecutive sessions longer than a
    normal weekend+holiday run (does not fail; reports for the manifest)."""
    if not bars:
        raise FreeHistoryError("no bars to validate")
    issues: list[str] = []
    prev: DailyBar | None = None
    gaps: list[tuple[str, str, int]] = []
    for b in bars:
        if b.open <= 0 or b.close <= 0 or b.high < b.low or b.adj_close <= 0:
            issues.append(f"bad prices at {b.date}")
        if prev is not None:
            if b.date <= prev.date:
                issues.append(f"non-increasing date at {b.date}")
            gap = (b.date - prev.date).days
            if gap > max_gap_days:
                gaps.append((prev.date.isoformat(), b.date.isoformat(), gap))
        prev = b
    span_years = max((bars[-1].date - bars[0].date).days / 365.25, 1e-9)
    return {
        "n_sessions": len(bars),
        "first": bars[0].date.isoformat(), "last": bars[-1].date.isoformat(),
        "requested_start": start.isoformat(), "requested_end_exclusive": end.isoformat(),
        "covers_start": bars[0].date <= (start + timedelta(days=7)),
        "covers_end": bars[-1].date >= (end - timedelta(days=7)),
        "sessions_per_year": round(len(bars) / span_years, 1),
        "large_calendar_gaps": gaps,
        "n_dividends": sum(1 for b in bars if b.dividend > 0),
        "n_splits": sum(1 for b in bars if b.split_ratio != 1),
        "issues": issues,
    }


def cross_check_closes(primary: list[DailyBar], other: dict[date, Decimal],
                       *, rel_tol: Decimal = Decimal("0.01")) -> dict:
    """Compare primary raw closes against another source's closes on overlapping
    dates (e.g. Alpaca IEX). Reports overlap and worst relative disagreement."""
    overlap = [(b.date, b.close, other[b.date]) for b in primary if b.date in other]
    worst = Decimal(0); mism = 0
    for _, a, c in overlap:
        if c <= 0:
            continue
        rel = abs(a - c) / c
        worst = max(worst, rel)
        if rel > rel_tol:
            mism += 1
    return {"n_overlap": len(overlap), "worst_rel_diff": str(worst),
            "n_mismatch_over_tol": mism, "rel_tol": str(rel_tol)}
