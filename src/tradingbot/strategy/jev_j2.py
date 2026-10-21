"""J2: frozen numeric-feature, position-dependent Jev menus.

Pure policy only. The runtime owns quotes, typed model calls, account risk,
settlement, actual fills and the mandatory close. No headline enters J2 input.
"""
from copy import deepcopy
from decimal import Decimal as D

from tradingbot.ai.jev import _validate_answers
from tradingbot.connectors.cash import NEW_YORK, timestamp
from tradingbot.data.iex_intraday import SYMBOLS
from tradingbot.risk.limits import STALE_DATA_MAX_SECONDS
from tradingbot.strategy.jev import DecisionSpec, JevStrategy, Plan, Target
from tradingbot.strategy.registry import register


PARAMS = {"revision": "j2-menu-v1", "position_slots": 4,
          "maximum_spread_bps": "10", "macro_window_minutes": 15,
          "minimum_enter_probability": "0.60", "minimum_conviction": "2",
          "minimum_size_factor": "0.5"}


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = D(str(value))
        return result if result.is_finite() else None
    except (ValueError, ArithmeticError):
        return None


def fresh_quote(state, now):
    try:
        quote = state["execution_quote"]
        bid, ask = number(quote["bp"]), number(quote["ap"])
        at = timestamp(quote["t"])
        received = timestamp(state["execution_quote_observed_at"])
        if (bid is None or ask is None or not 0 < bid <= ask
                or at.astimezone(NEW_YORK).date() != now.astimezone(NEW_YORK).date()
                or not 0 <= (received-now).total_seconds() < STALE_DATA_MAX_SECONDS
                or not 0 <= (received-at).total_seconds() <= STALE_DATA_MAX_SECONDS):
            return None
        return (ask-bid)/((ask+bid)/2)*10000
    except (KeyError, ValueError, TypeError, ArithmeticError):
        return None


@register
class JevMenu(JevStrategy):
    key = "jev-j2-menu-v1"
    arm = "J2"
    include_news = False

    def __init__(self, params=None):
        # There is one preregistered variant, not an unlogged tuning grid.
        supplied = {**PARAMS, **(params or {})}
        if supplied != PARAMS:
            raise ValueError("Unregistered J2 parameters require a new reviewed variant")
        super().__init__(deepcopy(PARAMS))

    def entry_veto(self, state, view):
        if state.get("symbol") not in SYMBOLS or state.get("schema") != "jev_state_v1":
            return "invalid_state"
        try:
            if timestamp(state["boundary"]) != view.boundary or timestamp(state["decision_at"]) != view.now:
                return "wrong_observation"
        except (KeyError, TypeError, ValueError):
            return "wrong_observation"
        spread = fresh_quote(state, view.now)
        if spread is None:
            return "stale_or_invalid_quote"
        if spread > D(self.params["maximum_spread_bps"]):
            return "wide_spread"
        features = state.get("features", {})
        close = number(features.get("current_close"))
        if (state.get("quality", {}).get("complete_suffix_intervals", 0) < 2
                or number(features.get("ret_15m")) is None or close is None or close <= 0):
            return "bar_gap_or_warmup"
        events = state.get("events", {})
        until = number(events.get("minutes_to_macro"))
        since = number(events.get("minutes_since_macro"))
        if (events.get("collection_halted") is not False or events.get("macro_status") != "ok"
                or events.get("macro_recent_window_complete") is not True or until is None
                or until < 0 or "minutes_since_macro" not in events
                or events["minutes_since_macro"] is not None and (since is None or since < 0)):
            return "unknown_macro_coverage"
        window = D(self.params["macro_window_minutes"])
        if until <= window or since is not None and since <= window:
            return "macro_window"
        return None

    def spec(self, symbol, *, holding=False, position=None):
        skip, action = ("HOLD", "EXIT") if holding else ("SKIP", "ENTER")
        action_text = (
            f"For {symbol}, use only its numeric observations and market/sector context. "
            "Unknown features provide no positive evidence. Do not use remembered events, "
            "news, external facts or other symbols' proposed actions. "
            "Any expected tradable move must exceed this decision's execution_by_option "
            "hurdle_bps, including spread, regulatory fees and model cost. "
        )
        questions = {
            "action": {"type": "choice", "instructions": action_text + (
                "Choose EXIT to close the current long when continuing to hold offers "
                "no sufficient net advantage; otherwise HOLD. The code exits by close."
                if holding else "Choose ENTER only for a positive long opportunity after "
                "the per-ticket cost hurdle, before today's mandatory close; otherwise SKIP."),
                "criteria": {action: "Close the current long" if holding else "Open a long position",
                             skip: "Retain the current long" if holding else "Remain flat"}},
            "conviction": {"type": "score", "instructions": action_text +
                "Rate conviction that the proposed long has positive net opportunity "
                "until its intraday exit: weak for insufficient evidence, fair for "
                "mixed support, strong for clear support, overwhelming for unusually "
                "consistent numeric support. This ordinal score is not a return forecast.",
                "criteria": ["weak", "fair", "strong", "overwhelming"]},
        }
        return DecisionSpec(symbol, questions,
            {skip: (), action: (Target(symbol, D(0) if holding else D(1)/self.params["position_slots"]),)},
            state={"symbol": symbol, "position": deepcopy(position) if holding else None,
                   "numeric_only": True}, skip=skip, action_class="exit" if holding else "entry",
            minimum_size_factor=D(1) if holding else D(self.params["minimum_size_factor"]))

    def plan(self, view):
        local = view.boundary.astimezone(NEW_YORK)
        quarter = ((local.hour*60+local.minute)-(9*60+30))//15
        if quarter < 1 or local.minute % 15 or local.second or local.microsecond:
            return Plan(memory=deepcopy(view.memory))
        decisions, vetoes = [], {}
        held = {symbol for symbol, p in view.positions.items() if number(p.get("quantity")) is not None
                and number(p.get("quantity")) > 0}
        for symbol in sorted(held):
            state = view.states.get(symbol)
            if symbol in SYMBOLS and state is not None and fresh_quote(state, view.now) is not None:
                decisions.append(self.spec(symbol, holding=True, position=view.positions[symbol]))
        slots = self.params["position_slots"]
        free = max(0, slots-len(held))
        if view.allocation <= 0 or view.available_cash <= 0:
            free = 0
        else:
            free = min(free, int(view.available_cash/(view.allocation/slots)))
        offset = ((quarter-1)*slots) % len(SYMBOLS)
        candidates = SYMBOLS[offset:] + SYMBOLS[:offset]
        entries = []
        for symbol in candidates:
            if symbol in held or symbol in view.entered_today or symbol not in view.states:
                continue
            veto = ("invalid_state" if view.states[symbol].get("symbol") != symbol
                    else self.entry_veto(view.states[symbol], view))
            if veto:
                vetoes[symbol] = veto
            elif len(entries) < free:
                entries.append(symbol)
                decisions.append(self.spec(symbol))
        memory = {**deepcopy(view.memory), "last_boundary": view.boundary.isoformat(),
                  "entry_candidates": entries, "entry_vetoes": vetoes}
        return Plan(tuple(decisions), memory)

    def choose(self, spec, answers):
        try:
            _validate_answers(answers, spec.questions)
            choice = answers["action"]["choice"]
            if spec.action_class == "exit":
                return "EXIT" if choice == "EXIT" else spec.skip
            if (choice == "ENTER"
                    and D(str(answers["action"]["probabilities"]["ENTER"])) >= D(self.params["minimum_enter_probability"])
                    and D(str(answers["conviction"]["score"])) >= D(self.params["minimum_conviction"])):
                return "ENTER"
        except (KeyError, TypeError, ValueError, ArithmeticError):
            pass
        return spec.skip

    def size_factor(self, spec, answers):
        _validate_answers(answers, spec.questions)
        return max(D(self.params["minimum_size_factor"]), D(str(answers["conviction"]["score"]))/3)
