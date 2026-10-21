"""Flat-across-action blackout for unresolved non-cash corporate actions.

Amendment 21 (docs/research/21-corporate-action-blackout.md). Splits, reverse
splits and in-kind distributions whose fractional / cash-in-lieu treatment is
unresolved for the current-account counterfactual are never held through.
The strategy exits at the open of the last session before the ex-date and may
re-enter only from the first session after the payable date. Exit is decided
at the previous session's close, so the action must have been announced by
then; otherwise the event cannot be handled causally and admission fails.
Ordinary cash dividends are out of scope and follow the normal entitlement rule.
"""
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import date

BLACKOUT_KINDS = frozenset({'split', 'reverse_split', 'in_kind_distribution', 'spin_off'})


class UnadmittableAction(ValueError):
    """The action cannot be avoided causally inside the session record."""


@dataclass(frozen=True)
class CorporateAction:
    symbol: str
    kind: str
    announced: date
    ex_date: date
    payable: date
    source: str


@dataclass(frozen=True)
class Blackout:
    action: CorporateAction
    decision: date   # close at which the exit is decided
    exit: date       # open at which the position is sold
    reentry: date    # first open at which a new position may be bought


def plan_blackouts(actions, sessions):
    """Return one Blackout per blackout-kind action, or raise UnadmittableAction."""
    sessions = sorted(sessions)
    plans = []
    for action in actions:
        if action.kind not in BLACKOUT_KINDS:
            continue
        if not action.announced <= action.ex_date <= action.payable:
            raise UnadmittableAction(f'{action.symbol} {action.kind}: inconsistent dates')
        before = bisect_left(sessions, action.ex_date)
        after = bisect_right(sessions, action.payable)
        if before < 2 or after >= len(sessions):
            raise UnadmittableAction(f'{action.symbol} {action.kind}: outside session record')
        exit_, decision = sessions[before - 1], sessions[before - 2]
        if action.announced > decision:
            raise UnadmittableAction(
                f'{action.symbol} {action.kind}: announced {action.announced} after exit decision {decision}')
        plans.append(Blackout(action, decision, exit_, sessions[after]))
    return plans


class BlackoutBook:
    """Per-symbol lookups a replay uses at each decision and execution."""

    def __init__(self, plans):
        self.plans = sorted(plans, key=lambda plan: plan.exit)

    def holdable(self, symbol, session):
        """False from the exit open through the session before re-entry."""
        return not any(p.action.symbol == symbol and p.exit <= session < p.reentry for p in self.plans)

    def forced_exits(self, session):
        """Symbols that must be sold at this session's open regardless of signal."""
        return sorted({p.action.symbol for p in self.plans if p.exit == session})
