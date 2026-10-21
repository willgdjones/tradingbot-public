"""Ledger: the single source of truth for orders, fills, fees and P&L (PRD §7).

- :class:`Ledger` — records orders/fills, computes exact fees, snapshots the
  USD/GBP rate per fill (PRD §10), maintains the ``positions`` book, and reports
  per-strategy P&L after fees, trade count, and the luck p-value (PRD §4).
- :mod:`accounting` — pure Decimal average-cost position maths (no I/O).
- :mod:`stats` — the luck p-value (dependency-free Student's t-test).
"""

from __future__ import annotations

from .accounting import FillEvent, FillResult, PositionState, RoundTrip
from .ledger import Ledger
from .stats import luck_probability, t_test_pvalue

__all__ = [
    "Ledger",
    "PositionState",
    "FillResult",
    "FillEvent",
    "RoundTrip",
    "luck_probability",
    "t_test_pvalue",
]
