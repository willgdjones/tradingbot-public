"""AI-1 daily cross-sectional momentum signals and probability gate."""
from decimal import Decimal as D

from tradingbot.strategy.jev import DecisionSpec, JevStrategy, Plan, Target
from tradingbot.strategy.registry import register

COUNT = 8
FRACTION = D("0.90") / COUNT
THRESHOLD = D("0.55")


@register
class DailyGate(JevStrategy):
    key = "ai1-daily-gate-v1"
    arm = "AI1"
    include_news = True

    def plan(self, view):
        eligible = []
        for symbol, state in view.states.items():
            features, quality = state.get("features", {}), state.get("quality", {})
            if (state.get("events", {}).get("collection_halted")
                    or quality.get("complete_suffix_intervals", 0) < 4
                    or features.get("ret_session") is None):
                continue
            ret = D(features["ret_session"])
            if ret.is_finite():
                eligible.append((ret, symbol))
        # The strongest eight include negative returns on broadly down days.
        # Missing coverage produces fewer signals; no data is imputed.
        symbols = [s for _, s in sorted(eligible, key=lambda x: (-x[0], x[1]))[:COUNT]]
        decisions = []
        for symbol in symbols:
            if symbol in view.positions or symbol in view.entered_today:
                continue
            decisions.append(DecisionSpec(key=symbol, questions={"profit": {"type": "noul",
                "instructions": f"Probability that the code-owned {symbol} long, entered now and closed "
                "five minutes before today's regular-session close, makes positive net P&L after the "
                "per-ticket spread, regulatory fees and model allowance in execution_by_option. "
                "Predict the ungated base trade outcome, even if you would reject it. "
                "The base selects the eight strongest complete first-hour session returns; "
                "unknown inputs remain unknown."}},
                alternatives={"skip": (), "enter": (Target(symbol, FRACTION),)},
                baseline="enter", state={"symbol": symbol, "base_rank": symbols.index(symbol)+1}))
        return Plan(tuple(decisions), {"candidate_count": len(decisions), "eligible_count": len(eligible)})

    def choose(self, spec, answers):
        answer = answers.get("profit", {})
        value = answer.get("noul")
        if answer.get("type") != "noul" or type(value) not in (int, float):
            return "skip"
        p = D(str(value))
        return "enter" if p.is_finite() and THRESHOLD <= p <= 1 else "skip"
