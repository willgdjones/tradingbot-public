# J1 forward paper results

Plan: `46-j1-gate-plan.md` (frozen at `526be61`). Bead `tradingbot-ec9`.

## Admission (2026-10-04)

- Strategy row 13395, $35 allocation, Alpaca paper venue. The existing $140
  shared book is unchanged, and TOM 3298 keeps its allocation.
- Real paper trial **6343**; virtual twins 6344 (random) and 6345 (ungated).
- The running `jev_intraday` service discovers the arm (`active_arms: 4`,
  outside session) and loads the registered `J1Gate` core.
- Zero orders, fills and model requests at admission. No readiness claim.
- The first observable session is Monday 2026-10-05.
- `tests/forward/test_jev_intraday.py` now hides deployed cohorts in its
  rollback fixture: 33 pass, and all 140 Jev tests pass.

## Forward results

None yet. The weekly review reports P&L after costs, round trips, max
drawdown, regime coverage and twin divergence.
