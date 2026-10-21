"""Current Alpaca retail equity fees as an explicit historical cost scenario.

Sept 17 2026 schedule, not a claim about fees actually charged in earlier years.
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_CEILING

ZERO = Decimal(0)
CENT = Decimal('.01')


@dataclass
class EquityFeeBook:
    totals: dict[tuple[date, str], Decimal] = field(default_factory=dict)
    policy: str = 'alpaca_retail_2026_09_17_counterfactual'

    def charge(self, *, day: date, side: str, price: Decimal, size: Decimal,
               commit: bool = True) -> tuple[Decimal, dict]:
        if side not in {'buy', 'sell'} or price <= 0 or size <= 0:
            raise ValueError('invalid equity fee input')
        raw = {'sec': ZERO, 'taf': ZERO, 'cat': size * Decimal('.000003')}
        if side == 'sell':
            raw['sec'] = price * size * Decimal('.0000206')
            raw['taf'] = min(size * Decimal('.000195'), Decimal('9.79'))
        charged = {}
        for kind, amount in raw.items():
            previous = self.totals.get((day, kind), ZERO)
            total = previous + amount
            charged[kind] = total.quantize(CENT, rounding=ROUND_CEILING) - previous.quantize(CENT, rounding=ROUND_CEILING)
            if commit:
                self.totals[(day, kind)] = total
        evidence = {'policy': self.policy, 'historical_actual_fees': False,
                    'raw': {k: str(v) for k, v in raw.items()},
                    'daily_increment': {k: str(v) for k, v in charged.items()}}
        return sum(charged.values(), ZERO), evidence
