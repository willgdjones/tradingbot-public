"""Kalshi quadratic prediction-contract fees, for research only.

Sources: https://kalshi.com/docs/kalshi-fee-schedule.pdf (2026-07-07),
https://docs.kalshi.com/getting_started/fee_rounding (read 2026-09-30).
Select historically supported multipliers and clearing precision explicitly.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from fractions import Fraction

from .core import FeeBreakdown, FeeFill, Liquidity, Side, as_decimal, aware, decimal_input, round_amount

MICRODOLLAR = Fraction(1, 1_000_000)


@dataclass(frozen=True, slots=True)
class KalshiSchedule:
    """Resolved series/event policy; maker/taker multipliers are independent.

General schedule: taker=1, maker=0. A fee-bearing maker series typically uses
maker=1. Do not derive maker multipliers from the API's taker multiplier, nor
guess a policy for unrecognized fee types such as non-quadratic products.
"""

    schedule_id: str
    effective_from: datetime
    taker_multiplier: Decimal
    maker_multiplier: Decimal
    effective_until: datetime | None = None

    def __post_init__(self) -> None:
        aware(self.effective_from)
        if not self.schedule_id:
            raise ValueError("A dated schedule identifier is required")
        for name in ("taker_multiplier", "maker_multiplier"):
            value = decimal_input(getattr(self, name))
            if value < 0:
                raise ValueError("Fee multipliers must be nonnegative")
            object.__setattr__(self, name, value)
        if self.effective_until is not None:
            aware(self.effective_until)
            if self.effective_until <= self.effective_from:
                raise ValueError("Schedule end must follow its start")


@dataclass(slots=True)
class KalshiOrderFees:
    """Rounding carry shared by taker and maker fills of ONE order.

Choose balance_precision explicitly: 0.0001 direct member, 0.01 non-direct/FCM.
This implements the current documented engine. It does not infer the engine's
historical rollout date from the fee PDF; establish applicability per backtest.
"""

    schedule: KalshiSchedule
    balance_precision: Decimal
    _rounding_carry: Fraction = field(default=Fraction(0), init=False, repr=False)

    def __post_init__(self) -> None:
        self.balance_precision = decimal_input(self.balance_precision)
        if self.balance_precision not in (Decimal("0.01"), Decimal("0.0001")):
            raise ValueError("Clearing balance precision must be 0.01 or 0.0001 USD")

    @property
    def rounding_carry(self) -> Decimal:
        return as_decimal(self._rounding_carry)

    def charge(self, fill: FeeFill) -> FeeBreakdown:
        if fill.executed_at < self.schedule.effective_from or (
            self.schedule.effective_until is not None
            and fill.executed_at >= self.schedule.effective_until
        ):
            raise ValueError("Fill lies outside the selected fee schedule")
        price, quantity = Fraction(fill.price), Fraction(fill.quantity)
        revenue = price * quantity * (-1 if fill.side == Side.BUY else 1)
        if (revenue / MICRODOLLAR).denominator != 1:
            raise ValueError("Kalshi fill revenue must align to six-decimal dollars")
        if fill.liquidity == Liquidity.TAKER:
            coefficient = Fraction("0.07") * Fraction(self.schedule.taker_multiplier)
        else:
            coefficient = Fraction("0.0175") * Fraction(self.schedule.maker_multiplier)
        exact = coefficient * quantity * price * (1 - price)
        trade_fee = round_amount(exact, MICRODOLLAR, "ceil")
        precision = Fraction(self.balance_precision)
        change = revenue - trade_fee
        rounding_fee = change - round_amount(change, precision, "floor")
        available = self._rounding_carry + rounding_fee
        rebate = min(
            round_amount(available, precision, "floor"),
            round_amount(trade_fee + rounding_fee, precision, "floor"),
        )
        self._rounding_carry = available - rebate
        return FeeBreakdown(
            schedule_id=self.schedule.schedule_id,
            exact_fee=as_decimal(exact),
            trade_fee=as_decimal(trade_fee),
            rounding_fee=as_decimal(rounding_fee),
            rounding_rebate=as_decimal(rebate),
        )
