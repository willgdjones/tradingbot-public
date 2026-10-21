"""Exact monetary inputs and shared fill-fee results.

Fraction arithmetic keeps fee decisions independent of the process's Decimal
context. Public inputs/outputs remain Decimal; binary floats are rejected.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from fractions import Fraction
from typing import Protocol

type ExactNumber = Decimal | str | int


class Liquidity(StrEnum):
    MAKER = "maker"
    TAKER = "taker"


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


def decimal_input(value: ExactNumber) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (Decimal, str, int)):
        raise TypeError("Use Decimal, a decimal string, or an integer; never float")
    value = Decimal(value)
    if not value.is_finite():
        raise ValueError("Monetary values must be finite")
    return value


def as_decimal(value: Fraction) -> Decimal:
    """Convert a terminating rational to Decimal without context rounding."""
    denominator = value.denominator
    twos = fives = 0
    while denominator % 2 == 0:
        denominator //= 2
        twos += 1
    while denominator % 5 == 0:
        denominator //= 5
        fives += 1
    if denominator != 1:
        raise ValueError("Amount has no finite decimal representation")
    scale = max(twos, fives)
    coefficient = value.numerator * (10**scale // value.denominator)
    return Decimal((int(coefficient < 0), tuple(map(int, str(abs(coefficient)))), -scale))


def round_amount(value: Fraction, quantum: Fraction, mode: str) -> Fraction:
    """Round to a monetary grid using exact integer arithmetic."""
    units = value / quantum
    floor, remainder = divmod(units.numerator, units.denominator)
    if mode == "floor":
        rounded = floor
    elif mode == "ceil":
        rounded = floor + bool(remainder)
    elif mode == "half_even":
        twice = 2 * remainder
        rounded = floor + (twice > units.denominator or (twice == units.denominator and floor % 2))
    else:
        raise ValueError(f"Unknown rounding mode: {mode}")
    return rounded * quantum


def aware(timestamp: datetime) -> None:
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("Execution and schedule timestamps must be timezone-aware")


@dataclass(frozen=True, slots=True)
class FeeFill:
    """One execution, priced in dollars per contract (not raw wire units)."""

    price: Decimal
    quantity: Decimal
    liquidity: Liquidity
    side: Side
    executed_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "price", decimal_input(self.price))
        object.__setattr__(self, "quantity", decimal_input(self.quantity))
        object.__setattr__(self, "liquidity", Liquidity(self.liquidity))
        object.__setattr__(self, "side", Side(self.side))
        if not 0 < self.price < 1:
            raise ValueError("Fill price must be strictly between zero and one dollar")
        if self.quantity <= 0:
            raise ValueError("Fill quantity must be positive")
        aware(self.executed_at)


@dataclass(frozen=True, slots=True)
class FeeBreakdown:
    """USD charge: positive is expense, negative is a credited maker rebate.

rounding_rebate is an execution rounding correction, never an estimate of a
liquidity reward or weekly volume rebate.
"""

    schedule_id: str
    exact_fee: Decimal
    trade_fee: Decimal
    rounding_fee: Decimal = Decimal(0)
    rounding_rebate: Decimal = Decimal(0)

    @property
    def net_fee(self) -> Decimal:
        return as_decimal(Fraction(self.trade_fee) + Fraction(self.rounding_fee) - Fraction(self.rounding_rebate))


class OrderFeeModel(Protocol):
    """Instantiate once per venue order; call once for each fill in order."""

    def charge(self, fill: FeeFill) -> FeeBreakdown: ...
