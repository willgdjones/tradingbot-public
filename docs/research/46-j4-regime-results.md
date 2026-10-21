# J4 forward paper results

Plan: `46-j4-regime-plan.md` (frozen at `526be61`). Bead `tradingbot-ec9`.

## Admission (2026-10-04)

- Strategy row 13396, $35 allocation, Alpaca paper venue. The existing $140
  shared book is unchanged, and TOM 3298 keeps its allocation.
- Real paper trial **6346**; virtual uniform random-regime twin 6347.
- The running `jev_intraday` service discovers the arm (`active_arms: 4`,
  outside session) and loads the registered `J4Regime` core.
- Zero orders, fills and model requests at admission. No readiness claim.
- The first observable session is Monday 2026-10-05; decisions come at 09:45
  and 12:30 ET.

## Forward results

None yet. Each day allows at most 5 entries, so 30 round trips needs about
2–3 weeks.
