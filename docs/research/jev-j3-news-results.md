# J3 news reactor — implementation and paper admission

2026-10-02, NavyLantern; bead `tradingbot-369`.

**Running in paper; no performance evidence yet.** The service discovered the
admission and repeatedly reported `outside_session` with one active arm at
22:14:45 and 22:15:00 UTC. The fixed news start is Monday, 2026-10-05 at
13:30 UTC. Regular quarter-hour decisions begin at 09:45 New York time.

| Record | Value |
|---|---|
| Strategy | `jev_j3_news`, ID 12756 |
| Real Alpaca paper trial | 6162, running |
| Informational virtual random trial | 6163, running |
| Admitted | 2026-10-02 22:14:31.008127 UTC |
| Frozen implementation commit | `2514e8cffc44e518b0e39dfe93a8adca17d4fd2b` |
| Strategy/source/parameter identity | `6fa46b00c207095759852160667abbb9296609db71f969bb77c0d507a9b81ee9` |
| Reviewed plan SHA-256 | `a5d34f6cee0190e48da9a958cf3151a1d0c968d705956bc0c0de4a8bce933773` |
| Real arm allocation ceiling | $35 within the existing shared $140 paper book |
| Virtual control actual allocation | $0; separate hypothetical $35 book |

Stored-only verification at 22:15 UTC recomputed both the policy/runtime
identity and [reviewed plan](jev-j3-news-plan.md) hash and found exact matches.
The real and random trials have zero actual orders/fills, and the real trial
has zero model requests. Integrity errors are empty and `ready_for_live` is
false. The service was refreshed to the committed source before admission.
The shared book's initial cash remains $140; TOM trial 3298 remains running
with its original $140 allocation. No capital or risk limits changed.

Validation: **38 pure policy checks and three full-runner integration cases
pass**. These cover all headline thresholds, revision and receipt identities,
duplicates, stale/future/missing news, delayed receipt boundaries, unknown
ATR/gaps/halts/cash, untrusted instructions, 40-symbol coverage, typed SDK
questions, actual connector routing, separate virtual fills, and no replay
after a neutral result or model outage. Model and HTTP calls were fake;
Postgres effects were rolled back. Four additional shared runner checks pass
for frozen quote identity, numeric-only payload exclusion, batching, and quote
receipt after feature cutoff without extending the original deadline. The
only warning was the existing upstream websockets deprecation.

Current net P&L and marked drawdown are initialized at $0 with zero completed
round trips. Those are empty-book counters, not measured returns. Luck odds,
market-regime coverage and real/control fidelity are not yet measurable.
Headline coverage remains limited to the existing five-item per-symbol feed
window; missed quarters are not replayed. Runtime costs, gaps, outages and
control divergence remain visible in the trial/turn records.

The [plan's account-risk review](jev-j3-news-plan.md#what-could-blow-up-this-account)
authorizes paper evidence collection only. The next decision is the existing
weekly qualification rule: at least seven calendar days, 30 completed real
round trips and positive after-cost P&L, with valid evidence and flat confirmed
inventory. The random control is informational only. Keep the service running;
no live promotion or readiness claim is made by closing the implementation
bead.
