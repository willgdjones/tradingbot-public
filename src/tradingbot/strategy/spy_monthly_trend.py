"""C01 — SPY monthly trend (Faber-style long/cash SMA rule). Pure decision logic.

At each month-end, hold ``target_weight`` (95%) if that month's adjusted close
exceeds the arithmetic mean of the last L month-end adjusted closes *including*
the current one; hold cash if it is below; an exact tie retains the previous
state. Before L month-ends of in-partition history exist, the rule stays in cash.

The rule is deliberately a tiny pure function of completed month-end observations
so the same decision runs identically in backtest, paper and live, and so the
holdout version hash covers exactly the decision logic. All configuration lives in
``params`` (so ``Strategy.params`` / ``ctx.params`` fully determine behaviour).
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal


@dataclass
class SpyMonthlyTrend:
    key: str
    params: dict  # {"lookback_months": int, "target_weight": str, "symbol": str}

    @property
    def lookback_months(self) -> int:
        return int(self.params["lookback_months"])

    @property
    def target(self) -> Decimal:
        return Decimal(str(self.params.get("target_weight", "0.95")))

    def decide(self, month_end_adj_closes: Sequence[Decimal],
               prev_weight: Decimal) -> Decimal:
        """Target weight for the *next* month given month-end adjusted closes
        (chronological, up to and including the deciding month) and the current
        held weight. Uses only completed observations."""
        L = self.lookback_months
        if len(month_end_adj_closes) < L:
            return Decimal(0)  # warm-up: cash until L month-ends exist in-partition
        window = month_end_adj_closes[-L:]
        mean = sum(window) / L
        current = month_end_adj_closes[-1]
        if current > mean:
            return self.target
        if current < mean:
            return Decimal(0)
        return prev_weight  # exact equality retains the previous state
