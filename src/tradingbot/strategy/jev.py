"""Pure, finite-choice intraday policies shared by paper/live/replay runtimes.

Policies receive observations, never a database, model client or broker. The
runtime inserts validated answers into a second event and owns all execution.
Each alternative consists of code-created long/flat targets; a model cannot
invent a symbol, size, price, stop or tool call.
"""
from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal as D
from typing import Literal

from tradingbot.ai.state import MARKET
from tradingbot.data.iex_intraday import SYMBOLS
from tradingbot.strategy.interface import Strategy


@dataclass(frozen=True)
class Target:
    symbol: str
    fraction: D  # fraction of the arm's frozen allocation, zero means exit
    stop_distance: D | None = None  # dollars from actual weighted entry fill

    def __post_init__(self):
        if (self.symbol not in SYMBOLS or not isinstance(self.fraction, D)
                or not self.fraction.is_finite() or not 0 <= self.fraction <= 1):
            raise ValueError("Invalid code-owned target")
        if self.stop_distance is not None and (
                not isinstance(self.stop_distance, D) or not self.stop_distance.is_finite()
                or self.stop_distance <= 0):
            raise ValueError("Stop distance must be finite and positive")


@dataclass(frozen=True)
class DecisionSpec:
    key: str
    questions: dict
    alternatives: dict[str, tuple[Target, ...]]
    state: dict = field(default_factory=dict)
    skip: str = "skip"
    baseline: str | None = None
    action_class: Literal["entry", "exit", "regime"] = "entry"
    random_mode: Literal["matched", "uniform"] = "matched"
    random_options: tuple[str, ...] | None = None
    minimum_size_factor: D = D(1)

    def __post_init__(self):
        if (not self.key or len(self.key) > 100 or not self.questions
                or self.skip not in self.alternatives or self.alternatives[self.skip]
                or self.baseline is not None and self.baseline not in self.alternatives
                or self.action_class not in {"entry", "exit", "regime"}
                or self.random_mode not in {"matched", "uniform"}):
            raise ValueError("Invalid finite decision specification")
        if self.random_options is not None and (
                len(self.random_options) < 2 or len(set(self.random_options)) != len(self.random_options)
                or any(k not in self.alternatives for k in self.random_options)):
            raise ValueError("Random options must name distinct declared alternatives")
        if (not isinstance(self.minimum_size_factor, D) or not self.minimum_size_factor.is_finite()
                or not 0 < self.minimum_size_factor <= 1):
            raise ValueError("Sizing bounds must be finite and within the declared ceiling")
        for targets in self.alternatives.values():
            if (not isinstance(targets, tuple) or any(not isinstance(t, Target) for t in targets)
                    or len({t.symbol for t in targets}) != len(targets)
                    or sum((t.fraction for t in targets), D(0)) > 1):
                raise ValueError("Alternatives must fit one code-owned slot")


@dataclass(frozen=True)
class View:
    now: datetime
    boundary: datetime
    states: dict[str, dict]
    positions: dict[str, dict]  # quantity, avg_price and stop_distance strings
    available_cash: D
    allocation: D
    entered_today: frozenset[str]
    memory: dict


@dataclass(frozen=True)
class Plan:
    decisions: tuple[DecisionSpec, ...] = ()
    memory: dict = field(default_factory=dict)

    def __post_init__(self):
        if len(self.decisions) > 40 or len({d.key for d in self.decisions}) != len(self.decisions):
            raise ValueError("At most 40 distinct decisions per arm and boundary")


class JevStrategy(Strategy):
    """Implement plan and choose; all parameters must be JSON-serializable.

    ``plan`` consumes news/rebalances through its returned durable memory.
    ``choose`` returns exactly one of the spec's alternative keys. J1/J3 stops
    are attached to targets. The runtime enforces session-close exits even
    when plan/choose, data, or the model fail. The risk veto remains absolute.
    """
    arm: str = ""
    ungated_twin: bool = False
    include_news: bool = True  # J2's numeric-only policy opts out of raw headlines

    @abstractmethod
    def plan(self, view: View) -> Plan: ...

    @abstractmethod
    def choose(self, spec: DecisionSpec, answers: dict) -> str: ...

    def observation_symbols(self, spec: DecisionSpec) -> frozenset[str]:
        """Symbols whose observations accompany this decision's typed call.

        Each symbol state already carries its own market and sector context, so
        the default is the decision's own symbols plus the market. The whole
        universe exceeded Jev's 32k state limit on 2026-10-05.
        """
        symbols = {t.symbol for targets in spec.alternatives.values() for t in targets}
        if spec.state.get("symbol") in SYMBOLS:
            symbols.add(spec.state["symbol"])
        return frozenset(symbols | {MARKET})

    def size_factor(self, spec: DecisionSpec, answers: dict) -> D:
        """Optional code-owned scaling, bounded by spec.minimum_size_factor..1.

        J2 implements max(0.5, conviction/3) here. The model supplies a validated
        score; code applies this formula, quantity precision and hard ceilings.
        Exit quantities are never scaled. The default retains the fixed target.
        """
        return D(1)

    def selection(self, spec, answers):
        choice = self.choose(spec, answers)
        if choice not in spec.alternatives:
            raise ValueError("Policy returned an unreviewed alternative")
        factor = (self.size_factor(spec, answers) if choice != spec.skip
                  and any(t.fraction > 0 for t in spec.alternatives[choice]) else D(1))
        if (not isinstance(factor, D) or not factor.is_finite()
                or not spec.minimum_size_factor <= factor <= 1):
            raise ValueError("Sizing function exceeded declared bounds")
        return choice, factor

    def on_event(self, ctx, event):
        # The same policy callbacks are usable from any Strategy runtime. This
        # interface emits targets; the runtime translates them to order intents.
        view = event.meta.get("jev_view")
        if view is None:
            return ()
        spec = event.meta.get("jev_spec")
        if spec is None:
            return self.plan(view).decisions
        choice, factor = self.selection(spec, event.meta["jev_answers"])
        return tuple(Target(t.symbol, t.fraction*factor, t.stop_distance) for t in spec.alternatives[choice])
