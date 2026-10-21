# Family holdout guard

Date: 2026-10-01. Bead: `tradingbot-u1h`. Source: the process-control finding in
[the Opus/Jev intake](../strategy-intake/2026-10-01-opus-jev-agenkit-prompt.md).
This is research infrastructure; no strategy promotion or historical replay.

Changing code or parameters previously created a new strategy version with a
fresh final allowance on the same data. Final admission now checks the stable
research family as well as the version. Dataset renames, different strategy
rows, candidate amendments, renamed reactors and partially shifted intervals
cannot reset that family's recorded exposure.

## Admission contract

- Every final admission atomically commits a trial and a separate family/source
  receipt before the feed is consumed. Failure, interruption, caller rollback,
  empty feeds and sparse actual trades cannot shrink the spent source interval.
- A successor holdout must not overlap any source coverage spent by the family,
  including that source's training portion. It also must not overlap previously
  committed, identifiable training windows. Exact adjacent boundaries are safe:
  intervals use UTC `[start, end)` semantics.
- The original once-per-version index remains. A new version may use an unseen
  window, or the successor can use fresh forward-paper evidence under the
  existing protocol. A new dataset/vendor/symbol label does not make overlapping
  dates unseen. This is deliberately conservative across instruments.
- Candidate root IDs are stable (`C04-readmission` → `c04`, for example).
  TOM's random-window diagnostic shares `turn_of_month` exposure. New families
  declare `Strategy.config.research_family`; rewritten successors keep it.
  Missing/conflicting declarations and reassignment of known strategy/reactor
  aliases are refused. Database triggers prohibit receipt/binding updates.
- One short advisory lock serializes admission and alias registration across
  processes; the feed executes after the lock is released. Refusals commit an
  incident before raising: version reuse, family reuse, prior training overlap,
  or invalid admission metadata. No failed attempt is silently promoted.

Migration `bcf10a202601` adds receipts and alias bindings without updating any
original trial. It obtains declared source bounds from `backtest_datasets`,
not first/last trades. All seven existing final rows are preserved byte for
byte: trials **3281, 3282, 3319, 3910, 3964, 3969 and 4066**. Their before/after
SHA-256 values, canonical families and intervals are in the
[stored-only audit receipt](28-family-holdout-guard.json). The two legacy TOM
finals remain as historical records of already exposed data; migration does not
invent a fresh allowance or retroactively erase one.

An unmapped/conflicting historical final aborts migration for review. An older
process inserting a final without a family receipt blocks subsequent admission
until audited. Downgrade refuses to discard existing family spend. Changes to
shared admission code affect future version hashes; **never replay a consumed
final to refresh those hashes**.

## Verification and limits

**152 regression checks pass** across the shared backtester, family/version
admission, equity runtime, C01, C04 v2, C05, C07 and C08. Alembic is at
`bcf10a202601`; post-test cleanup leaves exactly the original seven finals and
seven matching family receipts, with every original row hash unchanged.

Synthetic regression checks cover changed decimal parameters, an entirely
rewritten reactor and renamed dataset/row, partial overlap, former training
coverage, distinct families, truly unseen adjacent windows, immutable aliases,
concurrent different-version attempts, interrupted/failed finals, durable
incidents, migration backfill and original-row preservation. Existing longshot
and C01 fixture cleanup now removes only their synthetic family receipts before
removing their synthetic trials. It preserves production receipts and aliases.

Training transactions remain caller-owned. Every attempted variant, including
failures, must be committed before final evaluation. A database cannot certify
unlogged, rolled-back, concurrent or externally inspected training as unseen,
or infer common lineage after arbitrary dishonest renaming. Keep the original
family declaration, source-review protocol and promotion checklist. Legacy
full-period research stays contaminated even if a mechanical date check passes.
This guard is additional evidence protection, not a claim that all historical
results are valid or that the strategy is profitable.

No risk limit, allocation, promotion threshold, live key, venue, account or
broker order changed. The accepted operational risks and AI strategy forward
proof requirements remain exactly as specified in the PRD.
