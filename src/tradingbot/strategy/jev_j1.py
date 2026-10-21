"""J1 Jev Gate: a 15-minute breakout base rule gated by a finite Jev Choice.

Bead tradingbot-1tc. Base rule (code-owned): the latest completed 15-minute
close is above the prior one-hour high on above-average volume. For each firing
symbol the arm asks Jev a bounded Choice on five independent dimensions; code
blocks the entry on any ``block`` answer, or a ``conflict`` answer at confidence
>= 0.55. The entry is one code-owned long slot with a -1.5*ATR stop; the runtime
enforces the stop and the session-close exit, so this arm emits no exit
decisions. Twins: an ungated twin that always takes the base breakout
(``baseline="enter"``) and a random twin at the matched pass rate.

A model can only pick among code-created alternatives; it never invents a
symbol, size, price, stop or tool call.
"""
from __future__ import annotations

from decimal import Decimal as D

from tradingbot.ai.state import cost_hurdle_note
from tradingbot.strategy.jev import DecisionSpec, JevStrategy, Plan, Target, View
from tradingbot.strategy.registry import register

DIMENSIONS = ("data_quality", "signal_alignment", "market_regime", "risk_check", "execution_quality")
BLOCK_CONFIDENCE = D("0.55")
STOP_ATR_MULTIPLE = D("1.5")
ENTRY_FRACTION = D("0.9")      # one long slot, leaving a fee/slippage buffer
ENTER, SKIP = "enter", "skip"

_PROMPT = {
    "data_quality": "Are the point-in-time inputs (snapshot completeness, quote freshness, warm-up "
                    "state) sound enough to trust this breakout signal?",
    "signal_alignment": "Does the broader evidence (1h/1d return, SMA/EMA position, RSI, SPY and "
                        "sector context) align with a fresh long breakout, or conflict with it?",
    "market_regime": "Is the current regime (realized volatility, session phase, time of day) one "
                     "where a 15-minute breakout tends to follow through rather than fade?",
    "risk_check": "Do imminent events (minutes to the next macro release, days to earnings) or the "
                  "untrusted news make a new long position unusually risky right now?",
    "execution_quality": "Given the quoted spread and fees, is the expected post-breakout move large "
                        "enough to clear the round-trip cost hurdle?",
}
_CRITERIA = {
    "ok": "Supports taking the breakout long.",
    "conflict": "Materially conflicts with or is adverse to the breakout long.",
    "block": "A hard reason not to trade (bad data, imminent event, hostile regime, or sub-cost edge).",
    "insufficient": "Not enough evidence to judge this dimension.",
}


def _dec(features, key):
    value = features.get(key)
    return D(value) if value is not None else None


def _breakout_close(state):
    """The latest close when it clears the prior 1h high on above-average volume, else None."""
    features = state.get("features", {})
    close = _dec(features, "current_close")
    prior_high = _dec(features, "prior_1h_high")
    volume_ratio = _dec(features, "volume_ratio")
    if close is None or prior_high is None or volume_ratio is None:
        return None
    return close if close > prior_high and volume_ratio > 1 else None


def _questions(state):
    hurdle = cost_hurdle_note(state)
    questions = {}
    for dimension in DIMENSIONS:
        instructions = _PROMPT[dimension]
        if dimension == "execution_quality":
            instructions = f"{instructions} {hurdle}"
        questions[dimension] = {"type": "choice", "instructions": instructions, "criteria": dict(_CRITERIA)}
    return questions


@register
class J1Gate(JevStrategy):
    key = "jev_j1_gate"
    arm = "J1"
    ungated_twin = True

    def plan(self, view: View) -> Plan:
        decisions = []
        for symbol, state in sorted(view.states.items()):
            if state is None or symbol in view.positions or symbol in view.entered_today:
                continue
            if _breakout_close(state) is None:
                continue
            atr = _dec(state.get("features", {}), "atr14")
            if atr is None or atr <= 0:
                continue  # a -1.5*ATR stop needs a positive ATR; otherwise no trade
            features = state["features"]
            context = {
                "symbol": symbol, "base_rule": "15m close > prior 1h high with above-average volume",
                "current_close": features.get("current_close"), "prior_1h_high": features.get("prior_1h_high"),
                "volume_ratio": features.get("volume_ratio"), "atr14": features.get("atr14"),
                "ret_1h": features.get("ret_1h"), "ret_1d": features.get("ret_1d"),
                "rsi14": features.get("rsi14"), "ema20_pos": features.get("ema20_pos"),
                "realized_vol_15m": features.get("realized_vol_15m"), "session_phase": state.get("session_phase"),
                "cost": state.get("cost"),
                "stop_distance_usd": str(STOP_ATR_MULTIPLE * atr),
                "gate_rule": "block on any 'block', or a 'conflict' at confidence >= 0.55",
            }
            decisions.append(DecisionSpec(
                key=f"J1-{symbol}",
                questions=_questions(state),
                alternatives={SKIP: (), ENTER: (Target(symbol, ENTRY_FRACTION, STOP_ATR_MULTIPLE * atr),)},
                state=context,
                skip=SKIP, baseline=ENTER, action_class="entry", random_mode="matched",
            ))
        return Plan(decisions=tuple(decisions))

    def choose(self, spec: DecisionSpec, answers: dict) -> str:
        for dimension in DIMENSIONS:
            answer = answers.get(dimension)
            if not isinstance(answer, dict):
                continue
            if answer.get("choice") == "block":
                return SKIP
            if answer.get("choice") == "conflict":
                confidence = answer.get("confidence")
                if confidence is not None and D(str(confidence)) >= BLOCK_CONFIDENCE:
                    return SKIP
        return ENTER
