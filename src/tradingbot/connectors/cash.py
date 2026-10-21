"""Cash-only accounting helpers; no margin or inferred weekday settlement."""

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from tradingbot.fees.core import aware, decimal_input

NEW_YORK = ZoneInfo("America/New_York")
ZERO = Decimal(0)


def amount(value: Decimal | str | int, *, positive: bool = False) -> Decimal:
    result = decimal_input(value)
    if result < 0 or (positive and result == 0):
        raise ValueError("Amount must be positive" if positive else "Amount must be nonnegative")
    return result


def timestamp(value: str | datetime) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    aware(result)
    return result


@dataclass(frozen=True)
class MarketSession:
    trade_date: date
    settlement_date: date
    opens_at: datetime
    closes_at: datetime

    @classmethod
    def from_api(cls, row: dict) -> "MarketSession":
        day = date.fromisoformat(row["date"])
        # Fail closed if the response omits settlement_date. Trading days alone
        # are insufficient: Columbus Day is a trading but not settlement day.
        settlement = date.fromisoformat(row["settlement_date"])
        opens = datetime.combine(day, time.fromisoformat(row["open"]), NEW_YORK)
        closes = datetime.combine(day, time.fromisoformat(row["close"]), NEW_YORK)
        if settlement <= day or closes <= opens:
            raise ValueError("Invalid market/settlement calendar")
        return cls(day, settlement, opens, closes)

    def is_open(self, now: datetime) -> bool:
        aware(now)
        return self.opens_at <= now < self.closes_at


@dataclass(frozen=True)
class CashMovement:
    side: str
    notional: Decimal
    fee: Decimal
    settlement_date: date


@dataclass(frozen=True)
class CashBalance:
    settled: Decimal
    unsettled: Decimal
    reserved: Decimal

    @property
    def available(self) -> Decimal:
        return max(ZERO, self.settled - self.reserved)


def cash_balance(
    initial_cash: Decimal,
    movements: list[CashMovement],
    reserved: Decimal,
    now: datetime,
) -> CashBalance:
    """Debit buys immediately; release net sale proceeds on their settlement date.

    Broker buying_power and cash remain additional submission ceilings. They
    cannot accelerate this local settlement schedule or fund extra allocation.
    """
    aware(now)
    settled, unsettled = amount(initial_cash), ZERO
    today = now.astimezone(NEW_YORK).date()
    for movement in movements:
        notional, fee = amount(movement.notional), amount(movement.fee)
        if movement.side == "buy":
            settled -= notional + fee
        elif movement.side == "sell":
            # Fees are debited immediately; gross proceeds settle T+1. This
            # stays conservative even if a broker books its fee later.
            settled -= fee
            if movement.settlement_date <= today:
                settled += notional
            else:
                unsettled += notional
        else:
            raise ValueError("Unknown cash movement side")
    return CashBalance(settled, unsettled, amount(reserved))
