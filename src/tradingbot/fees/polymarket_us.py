"""Standard US CLOB fees, verified 2026-09-30.

Sources: https://docs.polymarket.us/fees and
https://docs.polymarket.us/partners/orders/data-model.
No international, combo, negotiated, or sport-specific fee policies here.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from fractions import Fraction
from zoneinfo import ZoneInfo

from .core import FeeBreakdown, FeeFill, Liquidity, as_decimal, aware, decimal_input, round_amount

CENT = Fraction(1, 100)


@dataclass(frozen=True, slots=True)
class PolymarketUSSchedule:
    schedule_id: str
    effective_from: datetime
    taker_coefficient: Decimal
    maker_coefficient: Decimal
    effective_until: datetime | None = None

    def __post_init__(self) -> None:
        aware(self.effective_from)
        if not self.schedule_id:
            raise ValueError("A dated schedule identifier is required")
        for name in ("taker_coefficient", "maker_coefficient"):
            object.__setattr__(self, name, decimal_input(getattr(self, name)))
        if self.taker_coefficient < 0 or self.maker_coefficient > 0:
            raise ValueError("US taker fees must be nonnegative and maker rebates nonpositive")
        if self.effective_until is not None:
            aware(self.effective_until)
            if self.effective_until <= self.effective_from:
                raise ValueError("Schedule end must follow its start")


PM_US_STANDARD_2026_09_25 = PolymarketUSSchedule(
    schedule_id="pm-us-standard-2026-09-25",
    effective_from=datetime(2026, 9, 25, tzinfo=ZoneInfo("America/New_York")),
    taker_coefficient=Decimal("0.0695"),
    maker_coefficient=Decimal("-0.0125"),
)


@dataclass(slots=True)
class PolymarketUSOrderFees:
    """Cumulative taker cap; independent maker rounding. One instance per order.

The caller selects a verified standard, non-sports market and the applicable
schedule. Replay historical orders with the schedule effective at execution.
"""

    schedule: PolymarketUSSchedule
    _exact_taker: Fraction = field(default=Fraction(0), init=False, repr=False)
    _collected_taker: Fraction = field(default=Fraction(0), init=False, repr=False)

    def charge(self, fill: FeeFill) -> FeeBreakdown:
        if fill.executed_at < self.schedule.effective_from or (
            self.schedule.effective_until is not None
            and fill.executed_at >= self.schedule.effective_until
        ):
            raise ValueError("Fill lies outside the selected fee schedule")
        coefficient = (
            self.schedule.taker_coefficient
            if fill.liquidity == Liquidity.TAKER
            else self.schedule.maker_coefficient
        )
        price = Fraction(fill.price)
        exact = Fraction(coefficient) * Fraction(fill.quantity) * price * (1 - price)
        rounded = round_amount(exact, CENT, "half_even")
        reduction = Fraction(0)
        if fill.liquidity == Liquidity.TAKER:
            self._exact_taker += exact
            cap = round_amount(self._exact_taker, CENT, "half_even")
            collected = min(rounded, cap - self._collected_taker)
            reduction = rounded - collected
            self._collected_taker += collected
        return FeeBreakdown(
            schedule_id=self.schedule.schedule_id,
            exact_fee=as_decimal(exact),
            trade_fee=as_decimal(rounded),
            rounding_rebate=as_decimal(reduction),
        )


def decode_commission(
    commission_notional_collected: int | None, *, price_scale: int, quantity_scale: int
) -> Decimal:
    """Decode signed reported fees; None means a proto3 omitted zero field.

Pass instrument scales explicitly; use quantity_scale=1 only when the reference
data says so (or omits that scale under the documented default).
"""
    for name, value in (("price_scale", price_scale), ("quantity_scale", quantity_scale)):
        if type(value) is not int or value <= 0:
            raise ValueError(f"{name} must be a positive integer")
    if commission_notional_collected is None:
        commission_notional_collected = 0
    if type(commission_notional_collected) is not int:
        raise TypeError("Commission must be an integer wire value")
    return as_decimal(Fraction(commission_notional_collected, price_scale * quantity_scale))
