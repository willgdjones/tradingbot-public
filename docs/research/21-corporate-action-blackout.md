# Amendment 21: flat across unresolved corporate actions

Date: 2026-10-01 (daily autonomous session). Written **before any outcome
inspection** for C02, C03, C05, C07 and C08, as the
[common preregistration](07-candidate-shortlist.md) requires for revisions.

## Problem

Five of the eight free-data Alpaca candidates stopped at their data gate for the
same reason. Each one depends on a split, reverse split or in-kind distribution
whose fractional-share, cash-in-lieu or cash-credit treatment is unresolved for
the current-account counterfactual:

- C02/C07: XLF's 2016 XLRE in-kind distribution ([17](17-xlf-action-amendment.md)).
- C05: commodity ETF split fractions ([15](15-c05-commodity-trend.md)).
- C08: USO's 2020 1-for-8 reverse split ([19](19-c08-source-audit.md)).
- C03: shared source repairs ([14](14-c03-source-audit.md)).

Those treatments cannot be proven from free primary sources. Waiting for them
leaves the Alpaca research queue empty. **Every hypothesis stays untested, not
rejected.**

## Rule

For every split, reverse split, in-kind distribution or spin-off on a held
symbol (`src/tradingbot/research/action_blackout.py`):

1. **Exit:** sell the whole position at the open of the last regular session
   before the ex-date. The exit is decided at the previous session's close.
2. **Blackout:** do not buy or hold the symbol from that exit through the
   payable date.
3. **Re-entry:** at the first session after the payable date, the normal
   strategy rule applies. It resizes from current marked equity and settled cash
   under the unchanged T+1 cash rule.
4. **Causality:** archived primary evidence must show that the action was
   announced on or before the exit decision date. Otherwise, or if the event
   sits at the edge of the record, admission still fails for that dataset.
5. **Costs:** both forced legs pay the candidate's fixed 5 bp / 10 bp cost and
   the `EquityFeeBook` fees. The exit cash follows the T+1 cash rule. Forced
   trades count toward the trade count.

The rule never holds a position through an unresolved action. It therefore
needs no fractional or cash-in-lieu assumption. It is a conservative
counterfactual: it pays extra costs and misses the price moves during the
blackout. Ordinary cash dividends still use the existing entitlement rule.

## Scope and limits

- **New strategy version:** each re-attempt is a new version and gets a new
  trials-ledger entry. Earlier failed source trials stay as they are. No
  holdout was ever consumed for C02, C03, C05, C07 or C08, so each gets one
  70/30 holdout run under this version.
- **Unchanged:** dataset intervals, tickers, signals and cost cases.
- **Report blackout days:** for each candidate, report the number of blackout
  sessions and how much of the forced-exit cost falls in the training and
  holdout periods.
- **Not a live-trading rule:** forward or live trading under Alpaca's actual
  treatment needs separate evidence before promotion.
- **No §6 risk limit changes.**
