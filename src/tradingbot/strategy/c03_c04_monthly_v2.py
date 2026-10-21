"""C04 sizing repair: apply the unchanged cap at the actual rounded limit."""
from decimal import Decimal as D, ROUND_CEILING, ROUND_FLOOR

from tradingbot.strategy.c03_c04_monthly import InverseVariance, ZERO


class InverseVarianceV2(InverseVariance):
    key = 'sweep_c04_inverse_variance_readmission_v2'

    def _allocate_buys(self, ctx, day):
        allocations = super()._allocate_buys(ctx, day)
        result = {}
        for symbol, (dollars, complete) in allocations.items():
            iid = self.ids[symbol]
            snapshot = ctx.snapshot(iid)
            limit = snapshot.ask.quantize(D('.01'), rounding=ROUND_CEILING)
            # RiskEngine values *all* post-order shares at the requested limit,
            # including already owned shares. The reference-price gap alone
            # would overstate capacity when the frozen target reaches the slot.
            capacity = max(ZERO, D(self.params['slot_usd']) / limit - ctx.position(iid))
            capacity = capacity.quantize(D(self.params['quantity_step']), rounding=ROUND_FLOOR)
            capped = capacity * snapshot.ask
            result[symbol] = (min(dollars, capped), complete or capped < dollars)
            if capped < dollars:
                self.skips.append({'date': day, 'symbol': symbol,
                    'reason': 'buy clipped to unchanged slot at rounded limit',
                    'requested_dollars': str(dollars), 'permitted_dollars': str(capped),
                    'limit_price': str(limit)})
        return result
