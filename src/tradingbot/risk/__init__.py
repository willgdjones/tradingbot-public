"""Risk engine with the PRD §6 hard limits and absolute veto power.

- :class:`RiskEngine` — pre-trade veto (:meth:`~RiskEngine.evaluate_order`) plus
  periodic P&L re-evaluation (:meth:`~RiskEngine.refresh_halts`) that trips the
  daily halt and per-strategy kills, persisting them and logging incidents.
- :mod:`limits` — the hard-coded §6 constants. **Never change without owner
  approval** (AGENTS.md).
"""

from __future__ import annotations

from . import limits
from .engine import RiskDecision, RiskEngine

__all__ = ["RiskEngine", "RiskDecision", "limits"]
