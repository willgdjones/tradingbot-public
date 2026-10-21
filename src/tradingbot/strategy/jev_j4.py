"""J4 Jev Regime switcher over ETF rules.

Bead tradingbot-32i. At 09:45 and 12:30 ET the arm asks Jev one bounded Choice
to classify the regime from SPY, breadth and volatility features:

- ``trend``    -> hold the top-3 ETFs by 1-day momentum (ret_1d),
- ``chop``     -> hold the 2 most-oversold ETFs by RSI (rsi14),
- ``risk_off`` -> cash.

The model only picks the regime label; code owns which ETFs fill each basket
and every fraction. Each regime alternative carries its target longs plus
``fraction=0`` exits for currently-held symbols outside the new basket, so the
chosen regime reconciles the whole portfolio. The runtime flattens everything by
the session close. Twin: a uniform random regime (including cash); there is no
ungated twin.
"""
from __future__ import annotations

from decimal import Decimal as D

from tradingbot.data.iex_intraday import NY, SYMBOLS
from tradingbot.strategy.jev import DecisionSpec, JevStrategy, Plan, Target, View
from tradingbot.strategy.registry import register

ETF_SYMBOLS = tuple(SYMBOLS[:20])            # the 20 ETFs this arm rotates over
DECISION_TIMES = ("09:45", "12:30")          # ET 15-minute boundaries
TREND, CHOP, RISK_OFF, SKIP = "trend", "chop", "risk_off", "skip"
TREND_N, CHOP_N = 3, 2
TREND_FRACTION = D("0.3")                    # 3 x 0.3 = 0.9 of the slot
CHOP_FRACTION = D("0.45")                    # 2 x 0.45 = 0.9 of the slot
REGIMES = (TREND, CHOP, RISK_OFF)

_REGIME_INSTRUCTIONS = (
    "Classify the current intraday regime for a long-only ETF rotation, using SPY trend, market "
    "breadth and volatility in the observations. Choose 'trend' for a broad directional uptrend "
    "(ride momentum), 'chop' for range-bound two-sided action (fade oversold extremes), or "
    "'risk_off' for deteriorating/high-stress conditions (hold cash). Prefer 'risk_off' when the "
    "evidence is mixed or weak."
)
_CRITERIA = {
    TREND: "Broad directional uptrend; ride momentum.",
    CHOP: "Range-bound, two-sided; fade oversold extremes.",
    RISK_OFF: "Deteriorating or high-stress; hold cash.",
}


def _dec(features, key):
    value = features.get(key)
    return D(value) if value is not None else None


def _rank(view: View, feature, *, reverse):
    """ETFs with the feature present, sorted by it (reverse=True for momentum)."""
    scored = []
    for symbol in ETF_SYMBOLS:
        state = view.states.get(symbol)
        if state is None:
            continue
        value = _dec(state.get("features", {}), feature)
        if value is not None:
            scored.append((value, symbol))
    scored.sort(key=lambda pair: (pair[0], pair[1]), reverse=reverse)
    return [symbol for _, symbol in scored]


def _basket(longs, fraction, held):
    targets = [Target(symbol, fraction) for symbol in longs]
    exits = [Target(symbol, D(0)) for symbol in sorted(held) if symbol not in longs]
    return tuple(targets + exits)


@register
class J4Regime(JevStrategy):
    key = "jev_j4_regime"
    arm = "J4"
    ungated_twin = False

    def plan(self, view: View) -> Plan:
        if view.boundary.astimezone(NY).strftime("%H:%M") not in DECISION_TIMES:
            return Plan()
        held = frozenset(view.positions)
        momentum = _rank(view, "ret_1d", reverse=True)[:TREND_N]
        oversold = _rank(view, "rsi14", reverse=False)[:CHOP_N]
        alternatives = {
            TREND: _basket(momentum, TREND_FRACTION, held),
            CHOP: _basket(oversold, CHOP_FRACTION, held),
            RISK_OFF: tuple(Target(symbol, D(0)) for symbol in sorted(held)),
            SKIP: (),
        }
        spec = DecisionSpec(
            key=f"J4-{view.boundary.astimezone(NY).strftime('%H%M')}",
            questions={"regime": {"type": "choice", "instructions": _REGIME_INSTRUCTIONS, "criteria": dict(_CRITERIA)}},
            alternatives=alternatives,
            state={"decision_times_et": list(DECISION_TIMES), "trend_candidates": momentum,
                   "chop_candidates": oversold, "held": sorted(held),
                   "rule": "trend=top-3 by 1d momentum; chop=2 most oversold by RSI; risk_off=cash"},
            skip=SKIP, baseline=None, action_class="regime",
            random_mode="uniform", random_options=REGIMES,
        )
        return Plan(decisions=(spec,))

    def observation_symbols(self, spec: DecisionSpec) -> frozenset[str]:
        # The regime call reads breadth across the whole rotation universe.
        return frozenset(ETF_SYMBOLS) | super().observation_symbols(spec)

    def choose(self, spec: DecisionSpec, answers: dict) -> str:
        answer = answers.get("regime")
        choice = answer.get("choice") if isinstance(answer, dict) else None
        return choice if choice in spec.alternatives else SKIP
