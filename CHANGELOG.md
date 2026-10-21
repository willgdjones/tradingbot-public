# Changelog

## 2026-10-17
- **Nudger stops nudging when nothing is claimable.** `ops/nudge.py` counted every `br ready` row as work, including owner-blocked `blocked:*` beads, so with only `s4s` left it nudged all three panes every 10 minutes. It now applies the same skips its prompt gives agents (`blocked:*` labels, coordinator-assigned) and still nudges whenever any bead is in progress. 4 new tests; the nudge suite passes (8).
- **Dashboard snapshot 13 s → 2.4 s warm (`tradingbot-myj`).** Unknown paths now 404 before any DB work; they used to build the full snapshot first. The backtest-mode ledger replay (about 38k fills) is cached in-process per fingerprint of the backtest fill set (count, max id, id sum), so the numbers stay exact and are recomputed when a backtest adds or removes fills. Leaderboard and gap tables no longer load the multi-MB `Strategy.config` JSON; trial evidence reads only `config['evidence_audit']` (projection by a parallel session). A cold first request still takes ~11 s under load because `Trial.metrics` feeds the trial statistics. All 27 dashboard tests pass, including the 3 server tests that were timing out.
- **Dashboard shows the live kill switch (`tradingbot-a90` part 3).** The Risk / kill-switch panel now lists every connector kill switch stored on `Venue.metadata` (e.g. `alpaca_live_kill_switch_v1`). It shows state, reason, engaged/cleared times and the clear note, plus a banner while any switch is engaged. Read-only; no connector, forward/ or risk code touched, so no cohort rolls. Parts 1 (paper/live base unification, which rolls J/AI/C05/TOM) and 2 (FEE-activity reconciliation; no live fills exist yet) stay open.
- **`tradingbot-v2i` closed without a build: the IBS QQQ paper twin is superseded by the live runner (`tradingbot-752`, trial 8815).** The Alpaca paper venue has a single $140 settled-cash book, which TOM and C05 already draw on. A $140 twin would starve TOM at month end, and giving it its own book means editing the shared paper connector, which rolls every cohort. Paper fills only simulate the NBBO, and the live runner's dry-run book already logs each fill against the official SIP open. Reopen only if the owner wants a paper stage (see `tradingbot-a90`).

## 2026-10-17 (daily session)
- Health: services all up in `tradingbot-svc`. The watchdog respawns worker panes 0.1-0.3 every hour (logged in INCIDENTS.md); panes show live Claude sessions after respawn, but they don't stay up. No ready work beyond owner-gated `s4s`; `v2i` and `a90` are post-freeze follow-ups with no agent claim, left for the workers.
- Intake: X bookmarks scraped (5), none new.

## 2026-10-15 (daily session)
- Health: ntm workers hit a Claude usage limit (resets 08:20 PT); logged in INCIDENTS.md. Postgres restart on 10-14 was handled by the watchdog. Only ready bead is `s4s` (owner decision).
- Intake: 2 X bookmarks evaluated, both rejected (`docs/strategy-intake/2026-10-15-x-bookmarks-batch.md`).

## 2026-10-15
- **Incident, fixed 2026-10-17 21:45 PT:** launching agents via `zsh -lc '...'` made tmux report the panes as `zsh`. Agent recovery took the healthy agents for dead and killed them hourly, and the nudger never dispatched. The swarm did almost no bead work from 2026-10-15 08:47 PT to 2026-10-17; the daily sessions still ran. Recovery now respawns a login shell and types the command, as ntm does.
- **Off the gmail Claude subscription (owner).** Agents were respawned on the two other (pane 1; panes 2–3) subscriptions, and the daily session moved to account 2. Agent recovery now uses tmux respawn with pinned config dirs, because `ntm respawn` fell back to the gmail account.

## 2026-10-15
- **IBS live runner: first pre-open cycle failed in dry run, fixed by 06:02 PT (`tradingbot-752`).** On the session right after its anchor, it asked Alpaca for an inverted calendar range (10-15..10-14, HTTP 400) every tick from 06:00 PT. Nothing was at risk: still dry run, and today's decision is flat either way. It now skips the lookup when no session lies in between. Regression test added (10 pass). Today's decision is flat (IBS 0.181 through 10-14); the first possible entry remains the 10-16 open.

## 2026-10-14
- **Owner: go live now.** IBS QQQ v1 skips paper and goes live on $140 once the live keys are in 1Password (`tradingbot-752`, P0). The live connector is done (`l3r`). The wheel post was parked as capital-blocked; the put-write/covered-call ETF backtest was queued instead (`ae1`).
- **IBS QQQ v1 live runner is running, in dry run until the live keys exist (`tradingbot-752`).** New files only (freeze): `src/tradingbot/live/ibs_qqq.py`, `ops/ibs_live.sh`, service `ibs-live` in `tradingbot-svc`.
  - Live trial **8815** (strategy `ibs-QQQ-live-v1`, $140) starts flat on the Oct 14 bar.
  - Each session from 09:00 ET it steps the unchanged `strategy.ibs.Signal` on SIP daily bars. From 09:30:30 ET it sends fractional marketable DAY limits through `AlpacaLiveConnector` (§6 risk engine, kill switch).
  - Without keys it fills a virtual book and sends nothing. Once the owner adds `ALPACA_LIVE_KEY`/`SECRET` to 1Password, the next restart initializes the $140 live book and trades. That moment is logged in INCIDENTS.md.
  - Every fill is compared with the official SIP open (backtest assumes 10 bp/side; break-even ~33 bp). `uv run python -m tradingbot.live.ibs_qqq status` shows it.
  - 9 new tests; connectors suite 139 pass.
- **Option-income ETFs backtested; XYLD passes PRD §4 but lost to SPY (`tradingbot-ae1`).** Pre-registration and results: `docs/research/52-option-income-{plan,results}.md`.
  - Universe: XYLD and QYLD (selectable; `hold` and a `trend200` filter); JEPI, JEPQ and SPYI (descriptive holds; too young for the 2014-2026 split). PUTW is delisted and was not substituted.
  - **Source amendment before outcomes:** the first freeze failed XYLD/QYLD because Alpaca's adjusted closes are cent-rounded; raw closes agree across Yahoo, Nasdaq and Alpaca. The v2 check (official closes plus Alpaca cash-dividend records) passes every symbol at 99.7-100%. Yahoo lacks five 2014-2017 QYLD distributions (about −3.4% of total return); this is disclosed, not patched.
  - Training (trials 8818-8824) selected **XYLD hold** (+$84.62), $5.96 ahead of QYLD hold. The choice is flagged data-sensitive. Single holdout (trial **8825**): **+$75.24**, max drawdown 16.4%.
  - **Lost to SPY at equal exposure in both partitions** (+$214.13 and +$133.50). XYLD fell −32.4% in the 2020 crash (SPY −33.7%) and cushioned 2022 and 2025 only partly. The 200-day filter gave up nearly all the return.
  - Queued `ready-for-live` for the owner (`tradingbot-s4s`, blocked:owner-input), with a recommendation not to fund it. New files only; no capital, keys, orders or §6 change. 8 tests.

## 2026-10-13
- **Secrets moved to 1Password (owner request).** `.env` no longer holds any key. The 12 secrets live in the 1Password item `env-tradingbot` (Dev vault of the the owner's personal account 1Password business account), and `.env` keeps `${NAME}` placeholders.
  - `ops/with-secrets <cmd>` resolves them through the read-only `local-automation-laptop` service account (token in `~/.config/op/token`), with no prompts, so services run unattended. The values exist only in the child process's environment.
  - All 7 service scripts, the weekly deploy and the daily session go through it. Services were restarted at 23:06 PT (market closed); no frozen code changed and no cohort rolled.
  - Add or rotate keys (including the future Alpaca live keys) in 1Password, not in `.env`.
- **IBS QQQ v1 independently replicated (`tradingbot-3xw`).** `docs/research/50-ibs-replication.py` re-implements the rule from the plan and the frozen source, without the backtester.
  - Trades are identical for QQQ training (223), the QQQ holdout (98) and SPY training (214). Nets agree to the cent, and there is no look-ahead.
  - The source audit had checked closes only. IBS high/low/close now cross-checked against Alpaca SIP: QQQ agrees on 629/634 crosses since 2016 and 269/269 since 2022. SPY's pre-2022 gaps are Alpaca bad prints.
  - **For `v2i`:** compute IBS from SIP daily bars, not IEX. IEX would have missed 6 of 137 entry signals since 2020 and added 14.
  - Fill-cost break-even is about 33–37 bp per side, against the 10 bp assumed. Read-only: no trial, no database write, no frozen path.

## 2026-10-09
- **Gotobi-day USD/JPY (`tradingbot-z1t`): FAIL. No case for funding a futures/FX venue.**
  - **Data:** FXCM's free one-minute bid/ask (Dukascopy now needs a requester-pays AWS bucket), cross-checked against HistData.
    - Both pairs agree within 5 bp on at least 99.4% of days.
    - HistData's stamps are not its documented fixed EST: they follow New York DST to 2018 and EU dates from 2019. Fixed before training (plan amendments A2–C).
  - **Training (2016 to 2023-07):** long USD/JPY 03:00→09:55 JST on gotobi days made +5.4 bp gross and +2.4 bp net of 3 bp (p 0.01, 488 trades).
    - Gotobi beat control days by 5.8 bp. EUR/JPY replicated. PBO 0.03.
    - The bead's 09:00→09:55 window is real (+2.5 bp) but below cost.
  - **Single holdout, trial 8812 (2023-07 to 2026-09):** +0.24 bp gross, −2.76 bp net (p 0.95, 188 trades). Max DD 5.8% of the slot. The anomaly has decayed.
  - Docs: `docs/research/51-gotobi-{plan,results}.md`. Code: `research/gotobi.py`. No frozen paths touched.
- **Weekly deploy scheduling fixed (`tradingbot-7sh`).** W41 page deployed and verified at 14:00 PT, before the change.
  - `ops/scheduler.sh` used to re-run the full build and Cloudflare deploy every minute after a failure, adding an INCIDENTS line each time. It now retries once an hour.
  - A missed Friday now catches up on Saturday or Sunday.
  - `docs/weekly-report.md` described the retired `com.tradingbot.weekly` LaunchAgent and two resolved October 1 blockers. It now describes the tmux scheduler.
  - Not a frozen path; no cohort is affected.
- Daily session: health OK (ntm swarm up with 3 agents, tradingbot-svc has all 9 service windows, disk 165 GB free, no ready beads, no new incidents). X bookmark pull timed out (browser-harness, 300 s), so no intake today; not an incident. Execution freeze respected; no code changes.
- **IBS mean reversion (`tradingbot-kyn`): QQQ passes; paper queued for after the freeze.** This is the exact Wealth-Lab rule: buy at the next open when IBS crosses under 0.10, sell at the next open when it crosses over 0.90. Run on 2006-2026 adjusted OHLC (both symbols agree with Nasdaq × Alpaca at ≥99.88%), with 10 bp per side plus fees, settled cash and the 70/30 holdout.
  - **QQQ:** training +$142.18 (223 trades, 69% winners, max DD 26.5% in 2008). Single holdout run, trial 8804: **+$71.48** (98 trades, 65% winners, +0.58% net per trade, max DD 12.5%, bootstrap p = 0.024). Equal-exposure buy-and-hold made +$51.41.
  - **SPY:** training +$89.91.
  - **SPY final refused:** the holdout guard counts one final per strategy family, and QQQ used it first. Incident 2049, refused before any holdout data was read. The plan wrongly expected one final per symbol; SPY will not be reopened under a new name.
  - The edge is about half the article's claim once costs are paid. Docs: `docs/research/50-ibs-mean-reversion-{plan,results}.md`. Code: `strategy/ibs.py`, `research/ibs_mean_reversion.py`. No frozen paths touched.

## 2026-10-08
- Daily session: health OK (swarm up, IEX recorder running, disk 62 GB free, no ready beads, no new incidents). Intake of 2 X bookmarks, both rejected, no beads. Execution freeze respected; no code changes.

## 2026-10-07 — J1–J4 and C05 re-admitted onto the hwm repair (`tradingbot-hwm` bundle)

- **Correction to the `hwm` entry:** the J suite *was* affected. `jev_intraday.identity()` hashes the files of its execution types (`AlpacaPaperConnector`, `AlpacaPaperAPI`, `AIPaperCostGuard`), so `bae3637` moved it. After that push, J 8726/8728/8730/8733 reported `code_identity_unchanged=false`. TOM is unaffected.
- **J rollover (22:39:20 UTC, HEAD `d75ccad`):**
  - Steps: broker and local flat checks, a rolled-back dry run, then one atomic commit (status, completion and note only). Re-admitted through `prepare()` on the same reviewed rows, params, plans and $35 allocations.
  - New trials: **J3 8787** (8788), **J2 8789** (8790), **J1 8791** (8792 random, 8793 ungated), **J4 8794** (8795).
  - The restarted worker reports unchanged identities, complete receipts and no integrity errors.
  - Receipts: `data/forward/j-rollover/20261007b/`.
- **C05 re-admission (22:40:24 UTC):** 8761 (never traded) archived. New **trial 8797** (strategy 18978, $35, terminal 2027-01-04). The worker runs on 8797.
  - Receipts: `data/forward/c05-rollover/20261007b/`.
- **All current paper cohorts now run on the same source:** J 8787–8795, AI-1 8770–8773, AI-2 8774–8777, C05 8797. The $140 book, allocations and old records are unchanged.

## 2026-10-07 — AI-1 and AI-2 rolled onto the hwm repair (`tradingbot-5ag`)

- **Why:** `bae3637` (`hwm`) changed `forward/ai_paper_costs.py`, which both AI identities hash. Neither cohort, AI-1 8743–8746 or AI-2 8755–8758, had decided; each had only a missed-window skip turn.
- **Rollover (22:38:50 UTC, under both singleton locks):** broker and local checks passed, then a rolled-back dry run and one atomic commit (status, completion and note only).
  - New cohorts: **AI-1 8770–8773** (rows 18963–18966, identity `21f4985d…`) and **AI-2 8774–8777** (rows 15002–15005).
  - Both plan hashes are unchanged. Both workers restarted bound to the new trials.
  - Receipts: `data/forward/ai-rollover/20261007c/`.
- **Coordination:** done in the bundled `hwm` window; CyanDeer rolls J1–J4 and C05 after this. First decisions are October 8 (AI-2 at 10:15 ET, AI-1 at 10:30 ET).

## 2026-10-07 — Residual quote clock-skew and concurrent-receipt races fixed in shared files (`tradingbot-hwm`)

Follow-up to `tradingbot-jsa`, which fixed these only inside `forward/jev_intraday.py` (its own `SettledQuotes`) to avoid moving the C05/C08 frozen identities. These were the remaining non-jev call sites. Both stem from this host's clock lagging the IEX feed by ~32 ms (`sntp -32 ms`).

- **Race 1 — clock-skew quote refusal.** `connectors/alpaca_paper.py` `_capture_quote`/`submit_limit` and `forward/paper_evidence.py` `fresh_marks` refused a quote stamped a few ms ahead of the host clock for services that do not wrap their API (TOM, C05, C08). **Fix:** `AlpacaPaperConnector.__init__` now wraps its api in a `SettledQuotes` transport (ported into `alpaca_paper.py`) that waits out a lead ≤ `QUOTE_CLOCK_TOLERANCE` (1 s), exactly like J. This covers `_capture_quote` and the `fresh_marks` capture path (both fetch via `connector.api.quote`) without editing `paper_evidence.py` or `jev_intraday.py`. A larger lead is passed through and refused downstream as before; non-quote calls are delegated unchanged; double-wrapping (J already wraps) is idempotent. `api=None` read-only connectors are preserved.
- **Race 2 — concurrent provider receipt.** `forward/ai_paper_costs.py` `account_costs` raised `Future provider receipt in current account view` (and `future paper fill`) when a concurrent cohort committed a Jev receipt/fill microseconds-to-seconds after the as-of-`now` view opened (the 10:15/10:30 ET quarter-hour overlap; C05's 11 Oct 6–7 holds each followed a J Jev call by ~0–1 s). **Fix:** a fill/receipt stamped within `RECEIPT_CLOCK_TOLERANCE` (1 s) after `now` is treated as not-yet-in-view and deferred to the next read; only a timestamp beyond the tolerance still raises (the corruption guard is kept).
- **Blast radius / rollover:** editing `alpaca_paper.py` + `ai_paper_costs.py` moves the frozen identities of cohorts that fingerprint them — C05 (re-admitted by `tradingbot-xhf`, bundled) and AI‑1/AI‑2 (re-admitted by `tradingbot-jxa` owner). J‑suite (`jev_intraday` identity) and TOM (`strategy/turn_of_month.py` identity) do **not** fingerprint these files, so they keep running on the improved behaviour with no re-admission. C08 has no running paper trial.
- **Tests:** 6 new `SettledQuotes` unit tests (`tests/connectors/test_hwm_clock_skew.py`) and 4 new boundary-race tests in `tests/forward/test_ai_paper_costs.py`; 170 connector/J/C05/TOM/AI‑1/AI‑2 regression tests pass. No risk-limit, allocation or paper-status change.

## 2026-10-07 — C05 permanent hold fixed and re-admitted; IEX recorder disk outage (`tradingbot-xhf`)

- **C05 problem:** trial 7852 had been `held_for_resolution` since 2026-10-07 13:30:04Z (incident `evidence-2026-10-07:open`). A held trial skips every phase, so the Oct 30 decision and Nov 2 purchases would have been missed.
  - `_open()` first captures fresh regular-session IEX marks for all five ETFs. USO's first regular-session quote came at 09:30:16 ET, but the capture ran at 09:30:04, so the pre-market USO quote failed as "nonregular".
  - Every phase `ValueError` becomes a permanent hold, even though the 60 s opening window was still open and nothing had been claimed.
  - USO first printed at 09:30:12, 09:30:05 and 09:30:16 on Oct 5–7 (Oct 6 passed by ~1.5 s), so this would recur most mornings.
  - Replays confirmed that the price vintage and pre-open broker activity were fine.
- **Fix (`b748a5c`, `forward/c05_runner.py`):** before a phase is claimed and inside the opening window, a capture failure returns `awaiting_opening_marks` and retries on the next 5 s step. After the window the unchanged missed-window rules apply, and a claimed phase still holds.
  - 2 new tests reproduce the Oct 7 bell and fail on the old code.
  - The legacy stale-batch test keeps its invariant (no intents, no submissions).
  - 125 C05/paper-evidence checks pass. The C08 suites' 10 errors come from the disk floor, not this change.
- **C05 re-admission** (receipts `data/forward/c05-rollover/20261007/`):
  - 7852 never traded (0 orders/fills/positions). After local and broker checks and a rolled-back dry run, it was archived (status, completion and note only).
  - Replaced through C05's own `prepare()` by **trial 8761** (strategy 18958, $35, terminal 2027-01-04). The $140 book and other trials are unchanged. The service runs on 8761.
  - It will be re-admitted once more if NavyHill's `hwm` shared-source fix lands; that bundle also rolls J and AI.
- **Incident — IEX recorder down 14:03–15:08 PT (after the close):** free disk on the shared laptop fell below the recorder's 30 GB floor, so it failed at every restart. That would have left J1–J4, AI-1 and AI-2 with no snapshots at the Oct 8 open.
  - Our nightly dumps (~2.2 GB each, retention 14, heading for ~31 GB) cannot coexist with that floor.
  - Deleted the three oldest full dumps (Oct 1–3); Oct 4–7 are kept. Retention is now 4 in `ops/pgdump.sh` (`a53f5f0`).
  - Free disk is 35.4 GB and the recorder is polling again. No session data was lost.
  - Owner: more free disk would allow deeper backup retention. Most of the remaining usage is other projects and swap.

## 2026-10-07 — AI-2 plan Amendment 1: a bar-less IEX minute no longer skips the day; AI-2 rolled (`tradingbot-jxa`)

- **Problem:** AI-2 could never decide. Its "complete most-recent interval for all 20 stocks" rule failed on every captured session: only 12–16 of the 20 had all 15 IEX minute bars for 10:00–10:15, because free IEX has no bar for a minute with no IEX trade.
- **Fix (`5c26c93`):** every stock still needs a state, a fresh quote and live event collection. An incomplete latest interval now reaches both models as explicit null features with quality flags, never backfilled, and is listed per turn.
  - AI-2-only: J and AI-1 identities did not move.
  - The new test fails on the old rule; 20 AI-2 tests and 72 AI-1/J/cost tests pass.
  - The plan hash is now `19327dd6…`.
- **Rollover (21:55:40 UTC, AI-2 lock only):** 8747–8750 had no decision, only a missed-window skip turn. It was archived after broker and local checks and a rolled-back dry run. **8755–8758** was admitted on the same rows; AI-1 8743–8746 is unchanged. Receipts: `data/forward/ai-rollover/20261007b/`.
- **Trade-off, recorded in doc 44:** on a day like October 7, about half the stocks reach the models with no stock-level price features. The first AI-2 decision is due October 8 at 10:15 ET.

## 2026-10-07 — AI-1 and AI-2 cohorts rolled onto the jsa runner repair (`tradingbot-36r`)

- **Why:** `f29a2ec` changed `forward/jev_intraday.py`, which both AI identities hash, so cohorts AI-1 8369–8372 and AI-2 8373–8376 could make no more decisions.
- **Rollover (21:46:03 UTC, after the close, under both singleton locks):**
  - Checks found no open broker orders and no positions; every cohort order was terminal (AI-1 had 14 filled orders), no Jev request was in flight, and all four turns were terminal.
  - A rolled-back dry run, then one atomic commit, archived both cohorts. Only status, completion time and note changed; every turn, order, fill, position row and receipt was checked byte-identical.
  - New cohorts: **AI-1 8743–8746** (new strategy rows 18952–18955, identity `b255b733…`) and **AI-2 8747–8750** (existing rows 15002–15005).
  - Both plan hashes are unchanged. Both workers restarted bound to the new trials. Receipts: `data/forward/ai-rollover/20261007/`.
- **AI-1, October 6–7:** Amendment 1 held on both days (15.0k and 17.3k tokens, Jev and Claude `ok`, 23–28s deadlines). Real outcomes, two sessions only, not pooled:
  - Ungated: 6 round trips, +$0.046.
  - Jev: 1 round trip, +$0.018.
  - Claude: none.
- **AI-2 has never decided.**
  - October 6 errored, most likely on the cost-view race (`tradingbot-hwm`).
  - October 7 skipped. One cause was quote timestamps 21–26 ms ahead of this host's clock, which `f29a2ec` fixes.
  - The bigger cause: its all-20-stocks-complete rule failed on every captured session. Only 12–16 of the 20 had all 15 IEX minute bars for 10:00–10:15. Filed as a separate bead.
- No risk-limit, capital, key or allocation change, and no decision replay.

## 2026-10-07 — J-suite activity audit: four execution bugs fixed, J cohort rolled (`tradingbot-jsa`)

- **Scope:** October 6–7, the two sessions after eoz. All 200 J turns ran (09:45–15:45 ET); 1 failed (bug 2). 94 of 94 Jev calls since the fix were `ok`. The 25 `uncertain` and 3 `error` rows are all from October 5, before the fix: 24 HTTP 400 `max_tokens_exceeded` (J3 17, J1 4, J4 2, AI-1 1) plus the eoz diagnostic replay (`tradingbot-gdc`), and 3 `invalid_answers`. Real orders: J1 NFLX (+$0.09 gross) and J4 IWM (−$0.03), both October 6.
- **Bugs (fixed in `f29a2ec`, `forward/jev_intraday.py` only).** Of 8 real entries Jev or code chose, 2 filled:
  1. **Research instrument rows.** `instruments()` mapped SPY/QQQ/MSFT to `research:*` rows with the same symbol, so the connector refused them ("does not match Alpaca asset ID"). This lost J4's SPY and QQQ on October 6. Only Alpaca-UUID rows now resolve; two broker rows fail closed.
  2. **Concurrent receipt.** AI-1's Jev receipt committed between J4's clock read and its cost query, failing the 10:30 October 7 view with a permanent `turn_failed` integrity error. Read-only cost views now re-read once.
  3. **Stale limit price.** Limits were priced at the observation ask (up to 30s old), and the connector refused them once its fresh ask moved. This lost J4's XLU/XLB/XLV (09:45 October 6) and J1's GOOGL (October 7). The plans say "at the fresh ask": the limit now uses the guard's pre-submit quote, capped at the cost-proofed notional.
  4. **Clock skew.** Free-IEX quote times led this host's clock by tens of ms; `sntp` showed it 32 ms behind. The busiest symbols failed every `0 <= now − t` check:
     - QQQ/IWM/DIA/SPY/XLK were missing from 16–24% of observations.
     - 11 paid J batches (J1 2, J2 4, J3 5) were discarded when the post-call portfolio mark failed.
     - AI-1 lost 7 entries at the same mark/quote checks.

     `SettledQuotes` holds a quote until the clock reaches its event time (at most 1s). No timestamp, future check or the 30s limit changed.
  - 5 new tests fail on the old code and pass now. 41 J intraday and 107 AI-1/AI-2/costs/J2/virtual checks pass.
  - `ai_paper_costs.py`, `paper_evidence.py` and `alpaca_paper.py` were left untouched, so C05, C08 and TOM keep their frozen identities.
- **Per arm (October 6 / 7):**
  - **J1:** 7 breakout candidates (5/2) and 6 calls. 2 answers were discarded (bug 4); both would have been skipped anyway.
    - Of the 5 answered, Jev blocked 3, each including `data_quality=block` (confidence 0.2–0.36), and passed 2: NFLX filled, GOOGL was refused (bug 3).
    - Twins: ungated 3 virtual round trips (NFLX, AAPL, GOOGL); random 2 (NFLX, GOOGL).
    - **Mixed:** a legitimate gate plus a bug.
  - **J2:** 138 entry decisions, every Jev answer SKIP (12 of them in 4 batches discarded by bug 4). Max P(ENTER) was 0.31 against 0.60, and max expected conviction 0.91 against 2.
    - Per day, the code vetoed about 400 symbol-turns as `bar_gap_or_warmup` and about 310 as `wide_spread` (plus 14 `macro_window` on October 7).
    - Available cash allows 3 slots, not 4: debited costs keep it just under 4 × $8.75.
    - The random twin matched 0 passes.
    - **Legitimate:** Jev is conservative.
  - **J3:** 79 decisions on 109 new headlines; 5 batches were discarded (bug 4). 19 bullish, 11 material > 0.5, but max expected strength was 2.17 against 3, so no headline qualified.
    - Random twin 0.
    - **Legitimate:** Jev is conservative.
  - **J4:** regimes were trend/trend on October 6 and risk_off/risk_off on October 7. October 6 chose 6 entries: IWM filled, SPY/QQQ were refused (bug 1), and XLU/XLB/XLV were refused (bug 3). The random twin filled XLU/XLB/XLV virtually.
    - **Mostly bugs.**
  - No risk-engine veto, settled-cash block or 1-entry-rule block occurred.
- **Projected time to 30 trades** (with the fixes):
  - J4: about 10–15 sessions.
  - J1: about 30 sessions, at roughly one Jev-passed breakout per session.
  - J2 and J3: none expected at the observed calibration. Even the 95% upper bound (0/138 and 0/109) implies 20+ sessions.

  Thresholds are pre-registered and unchanged. Whether J2/J3 remain worth running is an owner question for the weekly review.
- **Rollover** (receipts `data/forward/j-rollover/20261007/`):
  - Archived J 8320–8328 (status, completion and note only) after local and broker checks showed them flat, with no open orders.
  - A rolled-back dry run passed first.
  - Re-admitted from `050ce83` through `prepare()` on the same reviewed rows, params, plans and $35 allocations:
    - **J3 8726** (twin 8727)
    - **J2 8728** (8729)
    - **J1 8730** (8731 random, 8732 ungated)
    - **J4 8733** (8734)
  - Costs, cash, old turns, fills and receipts are unchanged.
  - NavyBear is rolling AI-1 (8369–8372) and AI-2 (8373–8376), whose identities the same commit moved.
- **Not fixed (by design or out of scope):**
  - IEX minutes with no trades leave a 15-minute interval incomplete ("never forward-fill"). This drives J2's warm-up vetoes and J1's `data_quality` blocks; changing it would be a new version.
  - The connector's own submit-time cost view and the AI-1/AI-2 files' own `account_costs` calls can still hit the same concurrent-receipt race.
  - The host clock could be synced more tightly.
  - No risk-limit, allocation, capital or key change.

## 2026-10-07 — PBO/DSR coverage for TOM, c01, c06, c07 and longshot (`tradingbot-9os`)

- **New:** `uv run python -m tradingbot.backtest.monthly_backfill` (dry run unless `--commit`).
  - It derives a monthly USD series for training trials that have no `monthly_marked_net_usd`, from evidence each trial already recorded:
    - ledger fills (TOM);
    - `monthly_returns` (c01);
    - `monthly_net_usd` (c06);
    - daily marked equity (c07);
    - `monthly_marks` (longshot).
  - A series is written only if it reconciles with the trial's own net. It goes under the NEW key `monthly_net_usd_derived`, with its basis and source.
  - It never touches final-holdout trials or existing metrics.
  - 10 tests.
- **Overfitting check:**
  - It falls back to the derived series and marks those families `*`.
  - New `--variance-min-months` option: short series (the 11-month longshot sweep) raise the ledger-wide Sharpe variance from 0.0161 to 0.0364 and over-deflate long families. A 36-month floor restores 0.0166.
- **Ledger:** 47 trials written (TOM 3, c01 6, c06 6, c07 2, longshot 30). The largest reconciliation difference is $1.8e-5.
- **Results** (appended to `docs/research/49-overfitting-ledger-check.md`, receipt `49-overfitting-ledger-check-9os.json`):
  - TOM, on paper: PBO 0.00, `DSR(N)` 0.95, `DSR(L)` 0.14 with the floor. A stable pick among three near-identical variants, not ledger-wide evidence; forward paper carries it.
  - c01: PBO 0.02, `DSR(N)` 0.97.
  - c06 and c07: negative.
  - Longshot: PBO 0.33 from only 6 splits.
  - No paper status, trial result or risk limit changed.

## 2026-10-07 — Backtest-overfitting check (PBO, deflated Sharpe) over the trials ledger (`tradingbot-cs9`)

- **New:** read-only `uv run python -m tradingbot.backtest.overfitting`.
  - For each selection family (dataset split × holdout family) it reports:
    - the CSCV probability of backtest overfitting, over 16 blocks and 12,870 splits;
    - the out-of-sample loss rate;
    - the chosen variant's deflated Sharpe against its own sweep, `DSR(N)`;
    - the same against all 172 completed training trials, `DSR(L)`.
  - Input is `metrics.monthly_marked_net_usd`, with missing exit-month months counted as zero.
  - 8 tests, including a raw-row CSCV cross-check and a ledger adapter test.
- **Results** (`docs/research/49-overfitting-ledger-check.md`, JSON receipt alongside):
  - Nothing survives the ledger-wide deflation; the best `DSR(L)` is 0.56.
  - PBO ≥ 0.5 for c02, c04, c20 and classic-TA awesome: their in-sample picks did no better than chance.
  - c05, now on paper, has PBO 0.33, an out-of-sample loss rate of 44% and `DSR(N)` 0.58. Flagged for the weekly review, not an incident.
  - TOM, c01, c06, c07 and longshot have no monthly series yet.
- **Promotion checklist §2:** new required multiple-testing item (PBO, `DSR(N)`, `DSR(L)`). No risk-limit, allocation, trial or paper-status change.

## 2026-10-06 — Daily session

- Health: ntm swarm up (12 panes, idle); watchdog only resumed stopped iex_intraday service on 10-03; no incidents. `br ready` empty.
- X bookmarks: 2 new, both skipped (TradingView MCP promo; generic "24/7 stock research prompt"). No beads created.

## 2026-10-05 — Whole test suite runs to completion again (`tradingbot-di7`)

- **Problem:** a single `pytest` over `tests/` deadlocked intermittently, and otherwise ended with 14–18 failures and 16–20 errors. This also happened at older commits.
- **Causes:**
  - (1) Seven forward fixtures ran setup between `connection.begin()` and `try:`. A setup error leaked an open transaction holding the `alpaca` venue, and the next `seed()` upsert waited on it forever.
  - (2) The session-scoped paper-DB fixture redirects the cached engine for the **rest of the session**. Later tests needing real rows, their own schema or TimescaleDB functions (`test_event_feeds`, the compression test, `test_c03_repair`) failed with `DuplicateTable`, missing rows or a missing `create_hypertable`.
- **Fixes:**
  - Fixture setup moved inside `try`, and teardown always closes the connection.
  - Paper connections get a 60s `lock_timeout`, so a future leak fails tests instead of hanging the run.
  - The three real-DB tests use a private engine on the same URL.
  - The rule is documented in `tests/conftest.py`.
  - One new guard test. No test assertion was weakened.
- **Result:** full suite **2023 passed, 0 failed, 0 errors in 5:00**. The forward suite is 375/375.

## 2026-10-05 — AI-1 request scope/deadline fix; AI-1 and AI-2 cohort rollover (`tradingbot-mna`)

- **AI-1 bug:** on October 5 (turn 258), both providers got all 40 observations with headlines, about 50.5k estimated tokens against Jev's 32k state+question limit, so Jev was refused. That turn's deadline also came from a 16s-old quote for a non-candidate (LLY), leaving 13.8s; 6 of 8 ungated entries expired.
- **Fix (`28fb006`, plan Amendment 1 `f820772`):** both providers now see only the day's candidates plus SPY (16.1k on the same turn). The deadline is fixed once from those quotes via the shared `turn_deadline`, and each turn records its scope, deadline and token estimate. The regression test fails on the old code; 124 AI-1/AI-2/J-suite/Jev checks pass.
- **AI-2:** no code change. The worst case across the 64 stored October 5 observations was 19.9k state+longest question and 28.5k for the whole request, both within limits.
- **Rollover (04:01:55 UTC):** the unobserved, flat cohorts AI-1 7857–7860 and AI-2 7846–7849 were archived after local and broker checks (no open orders, no positions) and a rolled-back dry run. New AI-1 **8369–8372** (strategy rows 18677–18680) and AI-2 **8373–8376** (existing rows 15002–15005) were admitted from `8ea595f`. Old records, the $140 book, allocations, shared costs and other frozen trials are unchanged. Both workers restarted and report matching identities. Receipts: `data/forward/ai-rollover/20261006/`.
- No risk-limit, capital, key or allocation change, and no decision replay. Qualification still waits on the 24 uncertain Jev reservations (`tradingbot-gdc`) and on forward evidence.

## 2026-10-05 — Audited resolver for uncertain Jev charges; owner billing check pending (`tradingbot-gdc`)

- **Situation:** 24 `paper-trial` Jev requests are still `uncertain` ($0.00275 reserved each). All are 2026-10-05 HTTP 400 `max_tokens_exceeded` rejections (J3 17, J1 4, J4 2, AI-1 1). My diagnostic replay adds one non-paper row, for 25 rows and $0.068813 reserved in total. While any remains, `account_costs().unknown_request_ids` sets `integrity_ok=false`, so **every J/AI-1/AI-2 arm shows `evidence_requires_review`** and cannot queue for live.
- **No evidence about billing:** TypeSafe's docs say only "charged per input token". The error table doesn't cover 400s, and there is no usage or billing API. Whether the rejections were billed can't be established from here, so nothing was zeroed.
- **Added `ops/resolve_jev_uncertain.py`:** it lists uncertain requests, and once the owner's evidence names a settled amount, it applies it. It takes the Jev budget lock and accepts only completed uncertain rows, with actual ≤ reservation. It sets the actual charge, releases the reservation (status `error`) and writes an `info` incident recording the request ids and evidence. It is **dry-run unless `--commit`** and lives outside every frozen identity, so no cohort moves.
- **Tests:** 7 passed. A dry run over all 25 real rows resolved them and rolled back with nothing persisted.
- **Owner action (weekly review):** check the TypeSafe billing dashboard for the 2026-10-05 07:45–12:31 PT rejections. If they were unbilled, run the resolver with `--actual-usd 0 --evidence "<source, who, when>" --commit`.
- **Owner decision to consider:** each uncertain charge is already debited to its trial's P&L at its full reservation, which is its upper bound. Blocking qualification on top of that is therefore double-conservative. Relaxing it is an owner decision, and it would move every cohort's identity (`forward/ai_paper_costs.py` is hashed).

## 2026-10-05 — J1–J4 zero-order first session: diagnosis and fixes (`tradingbot-eoz`)

- **Root cause 1 (J1/J3/J4 never got a decision):** every call carried all 40 symbols' observations, about 76 KB with headlines. Jev's documented limit is **32k tokens for state plus the longest question** (64k per request), not the 64k the wrapper assumed. A replay through `JevClient` returned HTTP 400 `max_tokens_exceeded`; all 23 J1/J3/J4 calls failed this way. J2 (no headlines) worked, but at about 31k of the 32k.
- **Root cause 2 (calls skipped or discarded):** the turn deadline was the minimum over all 40 quotes, so one stale IEX quote anywhere left every arm 3–15s. Afternoon capture took 11–26s under machine load. Later arms skipped the call: J2 lost 7 turns, J1 lost 2 turns with 4–5 breakouts, and J2 had 2 answers discarded as expired.
- **Per arm, 25 turns each (09:45–15:45 ET, runner alive all session):**
  - **J1:** 14 breakout candidates in 7 turns. 4 calls, all 400; 3 turns had no call (deadline).
  - **J2:** 16 calls. 2 `invalid_answers` came before 692a39a; 14 were ok. All 48 choices were SKIP (max P(enter) 0.29 vs 0.60, mean conviction 0.52 vs 2), so **J2's zero orders were legitimate**.
  - **J3:** 19 headline turns. 17 calls, all 400; 2 had no call. Those headlines stay consumed by design.
  - **J4:** both regime calls (09:45, 12:30) were 400. A 10:30 `ValueError` turn (pre-provenance code, non-decision time) had no effect.
  - **Risk vetoes:** none; no order reached the risk engine.
  - **Twins:** the J1 ungated twin made 2 virtual round trips (META, NVDA, net −$0.24); 7 of its entries expired on the deadline and 2 were zero-size because the slot was in use. The random twins correctly stayed flat.
- **Fixes:**
  - (a) `JevClient` checks both documented limits before reserving, using a conservative 1.5 B/token against the observed 1.9. It fails closed as `oversized_request` and records 4xx `http_status` and `provider_error_type` (machine code only).
  - (b) Each call carries only its decisions' observation scope: the decision symbols plus SPY. J4 keeps its 20-ETF universe. Batches are split to fit, and a lone oversized decision fails closed with no call.
  - (c) The turn deadline is computed after planning from the quotes that turn shows or trades. The feature-cutoff +30s bound is unchanged, and execution still re-checks each order's quote.
  - (d) Symbol-independent event snapshot reads now happen once per observation, which makes capture 3.2× faster (2.46s → 0.77s) with identical states.
- **Validation:** every 2026-10-05 turn replays into requests that fit (J4 peak 24k estimated). One live confirmation call (scoped J4 09:45, $0.00086, 20.6k tokens billed) was accepted. 8 new tests (12 cases) passed, plus 567 J/AI-1/AI-2/event/state/strategy/client checks. No risk-limit, allocation, capital or key change, and no decision replay. J1–J4 frozen identities were **already** stale before this change (code changed after admission), and this shared-source change also moves the AI-1/AI-2 identities. The J rollover is `tradingbot-km7` (below); the AI-1/AI-2 follow-up is `tradingbot-mna`. The full suite still deadlocks in forward-paper fixtures under whole-suite ordering, which also happens at the pre-change commit. With the hang deselected, the failure sets match the base apart from the new test hitting the same pre-existing `test_event_feeds` fixture error; every touched suite passes on its own.
- **Not fixed (owner check):** 24 uncertain Jev reservations, mostly today's HTTP 400 rejections, count as unknown account costs. They block every AI arm's qualification until resolved (`tradingbot-gdc`).

## 2026-10-05 — J1–J4 cohort rollover onto fixed source (`tradingbot-km7`)

- Archived J trials **6162/6166/6343/6346** and twins **6163/6167/6344/6345/6347** (stale frozen identities), changing only status/completion/note. They were verified flat: no real orders or fills ever, no virtual positions.
- Re-admitted through the runner's `prepare` from committed `f820772`, with the existing plan/review records, strategy rows, params and $35 allocations (no prior P&L to contaminate):
  - **J3 8320** (twin 8321)
  - **J2 8322** (8323)
  - **J1 8324** (8325 random, 8326 ungated)
  - **J4 8327** (8328)
- An atomic rolled-back dry run passed first. After the commit, the restarted runner (20:56 PT) reports 4 arms with `code_identity_unchanged=true` and no integrity errors.
- J3 keeps its frozen `news_start_at`, so there is no headline replay. No allocation, risk, capital, key or live change. The first prospective turn is October 6 at 09:45 ET.

## 2026-10-05 — AI-1 verified-close cohort transition (`tradingbot-3l9`)

- Broker and local ledger both confirmed flat after TSLA exit order 916923 filled 0.004477552 shares at 19:55:15 UTC; no open/unknown orders. Preserved observed trials 6748–6751 as abandoned, changing only status/completion/note. Original versions, parameters, metrics, turns, fills, provider records and strategy rows/allocations remain intact. Ungated one-round-trip net −$0.020311 and the uncertain Jev $0.002752512 reserve remain accounted for.
- Admitted fresh trials **7857–7860** / strategies **18293–18296**, bound to unchanged plan and current source identity `403463c0…`, using three $15 real ceilings plus an independent virtual random control. The active AI-1 ceiling remains $45 in the same $140 cash book. Fresh trial/strategy rows prevent prior P&L and observations contaminating qualification; old costs still debit the shared account. Unknown provider charges continue blocking cost-complete qualification.
- Validation: exact local/broker fill matching and repeated flat/open-order checks; complete rolled-back admission transaction; atomic commit with old-record, allocation, cash and cost preservation checks; post-restart singleton/hash/zero-activity audit. Existing `%114` launcher resumed worker 62855; other workers unchanged. No runtime-source edit, funding, keys, risk change, decision replay or live promotion. New leader's past-window row 537 is an explicit zero-candidate skip; first prospective decision is October 6 at 10:30 ET. Full receipts and review are in the existing AI-1 results file.

## 2026-10-05 — C-ROX holdout result: FAIL, closed negative (`tradingbot-rox`)

- Ran training (70%, 4 variants × 5/10bp) then the single 10bp holdout final for the selected `k3_retvol` (trial 7851). Results in `docs/research/48-rox-hmm-regime-results.md`.
- **Negative result, closed.** On the locked holdout (2020-07→2026-10) the regime overlay returned **+34.6%** vs **+161.4%** for always-long SPY — it sat in cash ~72% of the time (28% avg exposure), giving up ~127 points of return for a modest drawdown cut (17.1% vs 24.5%). Only **3 holdout trades**, luck p-value undefined. The strong training net (+197, spanning the 2008/2020 crashes) did not generalise to a mostly-bull holdout — textbook regime-dependence, which the preregistration flagged as the main risk.
- Finding: the 1-D `ret` HMM never converges under the frozen `n_iter`/`tol` (all no-decision/null); only the 2-D `retvol` model converges. Deterministic, causal, single-use holdout consumed; no follow-up bead (chasing a better cadence/feature would be post-hoc on a spent holdout). Not promotable, not live-ready. No capital/venue/key/risk change.

## 2026-10-05 — C05 selected total-return paper runtime (`tradingbot-s47`)

- Preregistered prospective paper execution for selected research trials 5385/5401, with a $35 ceiling in the existing $140 shared book and unchanged J/AI/TOM allocations. Reused the unchanged commodity reactor and durable close/open/intent machinery, with small C05-only profile hooks. No historical replay, funding, keys, risk-limit or shared connector changes.
- Added automatic coherent Yahoo close capture, completed-session raw IEX reference checks, paginated bound-account broker nontrade receipts, shared settled-cash/model-fee cost guarding and a finite 2027-01-04 terminal liquidation. No issuer HTML approval or optional blackout blocks admission; actual owned-symbol share/distribution records hold further execution for attribution without inventing income/fills.
- **15 new profile tests and 94 existing C05/source/state/cost checks passed** in disposable schemas. Covers real connector intents/fills, restart/no duplicate POST, unknown reservations, shared costs, failure holds and terminal liquidation. Read-only production price/account/activity probes passed; shell syntax/whitespace/compilation clean. Broker dividends and paper/live fidelity remain explicitly unresolved. Admission/service receipt follows after the committed-source freeze.
- Admitted trial **7852** / strategy **18288** against committed source `74895ae`; all previous allocations, frozen trial identities and prior C05 research records verified unchanged. Service `%116` owns the singleton and reports healthy observation with zero orders/fills/positions. First monthly decision October 30, possible purchases November 2, terminal January 4. Initial book remains $140; no live promotion.

## 2026-10-05 — Jev failure provenance (`tradingbot-by1`)

- Pushed `f641cb3`: failed Jev turns now retain the view/plan/costs/persist/decide/execute stage, exception class and innermost raising file/line, with the same metadata on incidents. Virtual and caught execution failures retain provenance without mixing control evidence or releasing uncertain-order reservations. Exception text, source text and locals are excluded; failed turns are never retried and deadlines stay unchanged.
- **93 focused/regression checks passed** across fault injection, J-suite execution, AI-1, AI-2 and shared paper costs. Restarted only the J worker after all four latest turns completed; its existing launcher resumed four arms with the new source. Observed J/AI-1 trials and holdings were preserved.
- Because diagnostics change the shared source identity, explicitly archived unused AI2 **7508–7511** after locked zero-observation/request/order/fill/position/virtual-attempt checks and admitted **7846–7849** from `f641cb3`. Every original trial field except status/completion/note, all existing paper allocations, other active trials' frozen parameters/versions/commits, the plan hash and $140 initial book were verified unchanged. October 6–23 remains the observation window; no live promotion, capital, account, key or risk-limit change.

## 2026-10-05 — C-ROX backtest runner (`tradingbot-rox`)

- Added `src/tradingbot/research/rox_hmm_regime.py`: a source/train/final runner reusing the single-asset total-return backtester, fees, durable holdout and cross-checked SPY bundle from `c11_total_return`; swaps in `HmmRegimeStrategy`, the four fixed HMM variants (k2/k3 × ret/retvol) and month-end decision gating. One durable final at 10 bp, or none when no training variant is positive. Reuses C11's frozen SPY source (re-verifies its input hashes), so no re-capture.
- 3 runner tests (month-end selection, event gating for the month-end-entry/terminal flags, and a short DB-backed end-to-end run with the kernel monkeypatched). Builds on RusticElk's committed estimator correctness (`4b930af`); all 15 of my ROX tests plus the contract suite pass.
- Pre-run convergence check on real SPY returns (methodology only, no holdout peek): under the frozen `tol=1e-4`/`n_iter=200`, the 1-D `ret` variants do not converge (→ all-no-decision / null, excluded from selection) while the `retvol` variants converge and decide. All four preregistered variants will still be run and reported as-is. No outcomes/holdout consumed yet; bead stays in_progress.

## 2026-10-05 — C-ROX estimator correctness (`tradingbot-rox.1`)

- Require two finite EM likelihood observations with `0 <= delta < tol`; hmmlearn's `converged` flag alone also accepts iteration exhaustion and decreasing likelihood. Reject non-finite full covariance matrices or covariance eigenvalues at/below `1e-12` before decoding. Failed fits remain explicit no-decisions.
- Each monthly target and its audit record now use the same single inference. The preregistered through-t fit, Viterbi decoder, state tie-breaking, execution rules and risk limits remain unchanged.
- **28 synthetic strategy checks passed**, including real-estimator iteration exhaustion, invalid likelihood/covariance cases, thread limits, decision/audit consistency and existing next-open/terminal execution checks. Read-only ledger verification found **zero C-ROX trials** before repair; no historical outcomes or holdout consumed. The parent research runner, benchmark/cost comparison and pre-backtest checklist remain with NavyHill.

## 2026-10-05 — Isolate forward-paper tests (`tradingbot-t19`)

- Reproduced the shared-ledger failure during market hours. Forward/connector tests now use a disposable PostgreSQL schema across the cached engine, existing session factories, `seed()` and raw SQL, with no `public` fallback. Existing rollback fixtures retain their semantics without reading production exposure or locking/updating production venue rows. Production risk/exposure queries and frozen executable sources are unchanged.
- Added five regression cases covering pre-existing and later independently committed background exposure, real portfolio P&L, ORM/alias/join/Core reads, committed fixture writes absent from `public`, unsupported fixture venues still blocking execution, and fills written by another fixture session.
- **Three consecutive full forward-suite runs passed during the open market, 10:59:22–11:05:05 ET:** 456 tests including all connector tests, then 345 and 345 forward tests. Zero failures; each run removed its schemas, while public-book audits retained one actual paper holding and no active orders. Compilation/whitespace checks passed. No runtime deployment, broker call, funding, key, allocation or risk-limit change.

## 2026-10-05 — Preserve observed AI-1 cohort after provider repair

- Shared Jev repair `692a39a` changed AI-1's executable identity after turn 258. Preserved original trials 6748–6751, the ungated TSLA fill/holding, uncertain Jev request and its $0.002752512 reservation, and Claude's separate list-price estimate. New entries/qualification fail closed; the service remains active for risk management and the coded close exit.
- Recorded the incident in the existing AI-1 results file and created `tradingbot-3l9`, deferred until after today's close. A replacement requires verified flatness, no active/unknown broker orders, an explicit new cohort and preserved prior costs/observations. No daily-decision replay, frozen-identity rewrite, funding or allocation change.

## 2026-10-05 — Daily autonomous session

- **Health:** the nightly pg_dump ran (03:25). No risk halts. All services are running: the IEX recorder writes 40/40 snapshots every 15 min, plus event feeds, TOM 3298, J suite, AI-1 and AI-2. The swarm is up: cc_1 and cod_1 are working, and cod_2 was idle. The `startup_failed` lines in `logs/iex-intraday.log` are stale (dated Oct 2).
- **Jev was 0/7 at the J suite's first real session.** Every request with a `score` question failed with `invalid_answers`: Jev rounds probabilities and score to 2 dp, but `_validate_answers` required agreement within 1e-6 (e.g. weighted 0.45 vs reported 0.44).
  - Fixed in `692a39a`: the tolerance now equals the rounding bound (0.005 per rounded value), and wrong answers are still rejected. All three stored live failures and today's diagnostic call now validate.
  - `provider_error` incidents now record the exception class (no text). The other 5 failures were `provider_error` with unknown cause.
  - Restarted the `jev_intraday`, `ai1_gate` and `ai2_basket` runners at 07:39 PT to load the fix. One diagnostic Jev call (~$0.001) went through `JevClient`, inside the cap.
  - Verified: the first post-fix call (07:45) returned `ok` ($0.0014), and all four J-suite turns completed. Logged to `logs/INCIDENTS.md`.
- Single-tick `risk_evidence_unavailable` incidents at 07:41 and 07:47 (the turns retried on the next tick). These may come from the same shared-DB test contamination; noted on t19.
- J4 trial 6346 had a transient `ValueError` while planning the 07:30 turn. Replaying the stored observation offline planned cleanly, and only the class name is retained. Filed **tradingbot-by1** to record the failing stage and source line.
- Forward-paper test suites (`tests/forward/*`, ~40 tests) fail intermittently: today's live paper positions in the shared DB leak into the rollback fixtures. The same failures occur with and without the Jev change. Filed **tradingbot-t19** (P1) and dispatched it to idle cod_2.
- Pipeline gap: C05 commodity trend passed research on 2026-10-01 but was never moved to paper. Filed **tradingbot-s47** (P1); paper admission is needed before the October month-end decision.
- X bookmarks: 5 scraped, 0 new. No phase change, so no agents added. No capital, venue, key or risk-limit change.

## 2026-10-05 — C-ROX runtime + review fixes (`tradingbot-rox`)

- Added the event-driven `HmmRegimeStrategy` (a full `Strategy` subclass) to `src/tradingbot/strategy/rox_hmm_regime.py`: accumulates the daily total-return factor from completed closes, decides at each month-end close via the HMM kernel, and toggles one SPY long/flat position at the next open as a taker order (regime→flat sells; terminal liquidation). 4 DB-free choreography tests (buy-on-calm / sell-on-turbulent, terminal liquidation, foreign-instrument ignore, entry-outside-partition skip).
- Applied RusticElk's pre-outcome review (Agent Mail 7179), all accepted; **no training/holdout trial was consumed**, so nothing is affected:
  - **Convergence/degeneracy/thread** now implemented as the plan promised — a non-converged (`monitor_.converged`) or degenerate/non-finite-variance fit raises `RegimeUndecided("fit_failed:*")` (a no-decision that retains the prior position), and the fit runs under `threadpool_limits(1)` for single-threaded determinism.
  - **Plan amended** (`docs/research/48-rox-hmm-regime-plan.md`): the decision rule now states the HMM is fit on and **Viterbi-decoded over the window ending at t** (causal because the window has no post-t observation), replacing the imprecise "strictly before t"/"filtered" wording so plan and code match exactly.
- 12 ROX tests pass (8 kernel + 4 choreography). Runner (source/train/final) + results are the next slice; bead stays in_progress. No capital/venue/key/risk change.

## 2026-10-05 — AI-1 daily gate plan (`tradingbot-efn`)

- Claimed the explicitly undeferred AI-1 bead and cleared its stale overlap label. Preregistered one 10:30 ET comparison of eight strongest complete first-hour returns: real ungated, Jev and Claude arms plus a virtual matched-count random control. Three $15 paper ceilings share the existing $140 cash book; no funding or J1–J4/TOM allocation change.
- Fixed the probability gate, actual-ungated outcome labels, Brier versus always-yes requirement, daily claim/deadline behavior, paired settled-cash admission, provider pins and full paper risk review before any AI-1 provider request or order. The prospective 7-day/30-trade, net-profit/comparator and 30-signals-per-five-sessions requirements remain unproved.
- Implemented the separate daily cohort over J-suite execution/state/cost machinery and a shared subscription-only Claude typed adapter, without changing J1–J4 source identities. Added durable paired decisions, same-quantity execution qualification, actual ungated outcome calibration, provider failure isolation, continuous risk checks, entry-window cancellation, close exits and weekly AI-1/AI-2 comparison tables.
- **107 distinct checks passed** across the provider, policy, cohort, existing J-suite/state/cost and weekly reporting suites. A harmless Claude fair-coin contract smoke returned the pinned model/typed JSON in 3.6 seconds; its $0.005346 CLI list-price estimate is retained separately from the existing-subscription incremental-cash assumption. Pre-admission audit confirmed the $140 book and all four J arms' $35 allocations/versions unchanged. Forward performance remains pending.
- Committed implementation `62a3d53`, then admitted real trials **6748 ungated / 6749 Jev / 6750 Claude**, each $15, and virtual random **6751**. All source/review hashes match; existing J-suite hashes and the $140 book remain intact. The independent service runs in `%114`, reports three active arms and rejects a second worker. Fixed an observed tmux one-row default-target failure by selecting the tallest pane and logging only successful startup; all existing service PIDs remained unchanged. No AI-1 turns/orders/fills occurred before the scheduled window at deployment verification.

## 2026-10-05 — AI-2 daily analyst basket plan (`tradingbot-cvm`)

- **Pre-observation dependency rollover:** shared Jev fix `692a39a` changed frozen identities after admission. Explicitly abandoned unused 6888–6891 after zero-observation/order/fill/request/exposure checks, preserving their original parameters, versions and metrics byte-for-byte. Admitted replacement **7508 Jev / 7509 Claude / 7510 random / 7511 benchmark** from `f2f95c0`; all hashes match, plan/window/slots and $140 book unchanged. **51 provider/policy checks passed** after the repair. The isolated AI-2 worker resumed in `%115`; J/AI-1 transitions remain with their owners.

- Claimed the owner-undeferred AI-2 bead and cleared its stale overlap label. Superseded the unlaunched October 2 plan before any AI-2 observations/model calls/orders: daily Jev and Claude long/flat baskets over the recorder's 20 stocks, with a virtual matched-count random twin and equal-weight benchmark. Fixed prospective window October 6–23, 10:15 ET entry, code-owned close exits, unchanged 30-second deadline and explicit comparator/subscription-cost limitations.
- The two real paper arms use $35 ceilings and only available cash from the existing $140 shared book. Existing J1–J4/TOM allocations, keys, capital and risk limits stay unchanged. Reuse their execution methods and state builder without editing frozen runtime source; the shared subscription-only Claude adapter is coordinated with AI-1. The plan completes the prospective paper risk review; implementation/admission and future evidence remain pending.
- Implemented the pure 20-stock policy and daily Jev/Claude runtime with durable shared snapshots, fixed-deadline decisions, receipt validation, independent provider failure handling, isolated matched-count/random and equal-weight controls, entry cancellation and actual-fill close accounting. Reports retain costs, calibration, drawdown/regimes, exposure/turnover, execution outcomes and latency; the fixed-end gate requires net profit above the complete benchmark and never promotes automatically.
- **31 focused checks passed**, plus compilation/shell/diff checks. Read-only preflight confirmed all equities registered, the $140 shared book, all four frozen J-arm identities/$35 allocations and TOM 3298 unchanged. Shared Claude adapter and weekly AI-2 reporting shipped with AI-1 in `62a3d53`; admission/service verification follows this implementation commit. Forward evidence remains pending.
- Admitted Jev **6888**, Claude **6889**, virtual random **6890** and virtual equal-weight benchmark **6891** from `af1e8b0`. Code/plan hashes match; zero pre-window turns/orders/fills/model requests and no readiness claim. Service registration `b6969b1` runs two real arms/two controls in `%115`, beginning October 6; singleton and idempotent launch checks pass, preserving every existing service process. The $140 cash book/J identities remain unchanged. Implementation is complete; prospective evidence stays pending in the running trials/weekly review.

## 2026-10-05 — Preregister C-ROX HMM regime filter (`tradingbot-rox`)

- Froze the preregistration `docs/research/48-rox-hmm-regime-plan.md`: a **deterministic** Gaussian-HMM regime filter on SPY that gates a passive long to flat in the lowest-mean-return ("risk-off") state, monthly cadence, walk-forward refit (expanding window, filtered decode, no look-ahead), locked 70/30 holdout, 5/10 bp costs, $140 virtual slot. Four ordered variants (K∈{2,3} × returns / returns+vol), select on positive 10 bp training net, one final on holdout. Headline test is **overlay vs always-long SPY**, not vs cash.
- Unattempted: no data pull, no `hmmlearn` add, no fit/trial/final yet. Statistical power (few regime switches) preserved as the key gate-5 limitation; no profitability/live-readiness claim. Bead `rox` stays in_progress for the implementation slice (add hmmlearn, strategy module, training/holdout, results, tests). No capital/venue/key/risk change.
- Independent pre-outcome review (`rox.1`, RusticElk) found a fit-cutoff/decoder mismatch with the written plan and missing fit-health/thread checks. Synthetic stubs reproduced the failures without market data or holdout consumption. NavyHill retains the parent implementation and accepted an explicit pre-outcome causal fit-through-t/Viterbi plan amendment plus fit-health corrections. Review also identified that hmmlearn's `converged` flag alone accepts iteration exhaustion/decreasing likelihood; verification of the corrected frozen core remains pending. No ROX strategy result has been claimed.

## 2026-10-05 — Strategy intake: X bookmarks batch (5)

- Evaluated the 5 `new` X bookmarks pulled into `docs/strategy-intake/bookmarks.jsonl` (ops/x_bookmarks.py, 13:27 UTC) against the intake rubric. Desk triage only — no capital/venue/key/risk change. One lean batch file: `docs/strategy-intake/2026-10-05-x-bookmarks-batch.md`.
- **Pursue (1):** @RitOnchain "HMM regime-detection" → created `tradingbot-rox` (P3) for a **deterministic** HMM regime *filter* on daily ETFs (overlay vs always-on baseline, walk-forward, locked 70/30 holdout, costs). Structural/statistical — no LLM/Jev calls — so distinct from J4 (Jev-decided regime switcher) and absent from the c-series.
- **Salvage/Park (2):** @confinedape 12-paper reading list (lead; full thread not retrievable this session) and @51bodila point-in-time/vintage-data principle (already our standard). No beads.
- **Reject (2):** @0xSoural and @mattshumer_ — AI agent/coding-workflow content, not trading strategies.
- Marked bookmarks `done` (1–3) / `skipped` (4–5) with `eval`/`verdict`/`bead` refs; added the intake log row.

## 2026-10-04 — Classic TA holdouts completed (`tradingbot-ob1`)

- Ran the four selected finals once after selection commit `9d8ab07`: **Awesome QQQ +$64.80 / 17 trades**, **RSI QQQ +$19.95 / 4 trades**, **SAR QQQ +$3.09 / 57 trades**, **Heikin-Ashi MSFT −$2.75 / 36 trades** (trials 6398–6401, separate $140 virtual slots). Final marked drawdowns were $23.21, $7.43, $36.92 and $26.39 respectively. Every final ended flat with zero rejections/halts.
- The first three are only candidate base rules for a separately preregistered J1 study; Heikin-Ashi fails the net-profit holdout criterion. RSI/Awesome have short samples; SAR's descriptive p-value is 0.4465 and its training drawdown/regime weakness remains explicit. No daily rule is silently converted into a validated intraday policy.
- Read-only audit matched **all 36 trials**, source/selection/artifact hashes, frozen final versions and exactly one family receipt per selected rule. The one results file includes all outcomes, missing-price/specification dispositions, drawdowns, regimes, costs, passive diagnostics and limitations. **30 tests passed**. No actual capital, account, key, risk limit, deployed paper strategy or model-spend change; no promotion.

## 2026-10-04 — Classic TA training selection frozen (`tradingbot-ob1`)

- Logged all **32 configurations**, trials **6366–6397**: 15 completed training replays, nine price/history DATA_FAILs, four MACD missing-default dispositions and four Shooting Star no-long-rule dispositions. Every completed replay ended flat with zero rejections/halts. Exact Bollinger defaults generated no trades.
- Selected only from training: **RSI QQQ +$16.25**, **SAR QQQ +$61.56**, **Heikin-Ashi MSFT +$108.73**, **Awesome QQQ +$100.44**, each from a separate virtual $140 run. Committed selection receipt `0a37b008...661f50b` and frozen strategy versions before any final. Drawdowns, costs, trade counts, regime losses, exposure and passive diagnostics are in `docs/research/47-classic-ta-results.md`; these are not live allocations or alpha claims.

## 2026-10-04 — Classic TA batch source/default freeze (`tradingbot-ob1`)

- Claimed by DarkMeadow. Preregistered a fixed SPY/QQQ/AAPL/MSFT panel and retained eight Apache-2.0 source scripts at upstream `611b73f`; plan/source attribution committed as `ed47752` before price capture. MACD has no numeric defaults, and Shooting Star is short-only with future-data dependencies; these receive explicit specification dispositions instead of invented rules.
- Added causal long/flat Bollinger, RSI, SAR, Heikin-Ashi and Awesome reactors over the shared total-return ledger/risk runtime. Fixed 10 bp/side plus raw-share-equivalent fees, settled cash, next-open fills, terminal liquidation, and one family-bound final per rule selected on training only. Risk limits and deployed paper strategies are unchanged.
- Source gate: SPY 99.88053% (independent Nasdaq/Alpaca factors), QQQ 99.77778% and MSFT 99.29630% pass; AAPL 98.70370% fails. All disagreeing/unpaired dates are archived. IEX has one session, insufficient for Dual Thrust's five-session warmup. No strategy outcomes have been read at this slice. An early synthetic integration-fixture admission refusal is annotated as a test incident; no real final was consumed.
- Validation: **30 tests pass**, including 17 batch checks plus shared equity-runtime and durable holdout tests. Synthetic checks cover prefix causality, source-specific directions/defaults, warmup, position bounds, fees, next-open fills, settled-cash refusal, terminal liquidation and repeated-final rejection.

## 2026-10-04 — Venue research: Coinbase Derivatives vs IBKR (`tradingbot-qpb`)

- Appended a Coinbase-vs-IBKR comparison to `docs/research/08-futures-broker.md` for the small-account crypto/futures question raised by the parked Coinbase agent-skill intake. Research only; no account, key, OAuth grant, MCP connection, funding or order.
- **Finding:** Coinbase nano crypto futures are the only reviewed contracts whose margin fits the ~$140 slot (nano BTC day ~$25 / overnight ~$230 vs IBKR commodity micros $1.5k–$4.15k). Coinbase direct also gives $0/month API data and supports a true **trade-only CDP key** (view+trade; withhold transfer/receive → cannot withdraw) via the Advanced Trade REST US-futures endpoints (`/cfm/balance_summary`, `POST /orders`) — satisfying the PRD trading-only-key rule and avoiding the parked all-scopes OAuth MCP + x402. **But** Coinbase's only unfunded "sandbox" is a static mock (shape, not fills), so like IBKR it cannot produce a live-quality unfunded forward record; crypto is a venue, not an edge.
- **Recommendation unchanged at the top level:** IBKR stays the preferred general futures broker (full commodity-micro suite, Python API) and now also **resells** Coinbase nano BTC/ETH futures; Coinbase direct is the better fit specifically for nano-crypto research on tiny capital. No live-ready designation, no trial result, no capital/key/risk-limit change.
- Access note: `help.coinbase.com` and `interactivebrokers.com` returned HTTP 403 to automated fetching and the local browser daemon stalled, so help-center figures (fees ≈0.05%/contract/side min $0.20; margins) are taken from Coinbase blog/dev docs, a CFTC filing and FCM product pages and flagged for live confirmation.

## 2026-10-04 — Recover exited ntm workers (`tradingbot-hzp`)

- Added a shared recovery helper to the minute watchdog and ten-minute nudger. It checks actual foreground commands in worker panes `tradingbot:0.1–0.3`, records exited shells in `logs/INCIDENTS.md`, and runs `ntm respawn tradingbot --force` with only their unique tmux pane IDs. A real dry-run showed numeric pane indices also select service panes in other windows; unique IDs avoid that collision and preserve healthy workers.
- A process lock and atomic, flushed timestamp share a one-hour recovery limit across both callers, including command failures/timeouts. The nudger skips shells and freshly restarted workers, then rechecks a healthy pane immediately before dispatch. Recovery works independently of bead availability and of the scheduler.
- **32 ops tests pass**, including 18 new cases covering targeted recovery, cooldown/retry, concurrent callers, failed or changing pane snapshots, corrupt/unwritable state, dispatch safety, and the real watchdog shell entrypoint with fake CLIs. Shell syntax and diff checks pass. A live helper smoke check found all three agent CLIs running and made no restarts. No trading, capital, key, or risk-limit change.

## 2026-10-04 — Daily session: swarm respawned; J1/J4 admitted to paper (`tradingbot-ec9`)

- **Incident:** all three ntm agents (cc_1, cod_1, cod_2) had exited to bare zsh by 2026-10-03 08:00 PT. That morning's nudge was typed into the shell, and the nudger stopped dispatching after that. The last agent commit was 2026-10-02 23:07. Yesterday's "swarm is up, idle" was wrong: ntm reported shells as idle. Respawned them with `ntm respawn tradingbot` (the Claude account shows 97% of its weekly limit used). Services, the watchdog and the nightly backup (`tradingbot-20261004-031504.dump`) were healthy. There are no risk halts. The watchdog SIGCONT'd the IEX recorder twice more on Oct 3. Logged in `logs/INCIDENTS.md`.
- **J1 and J4 admitted.** J1 (`1tc`) and J4 (`32i`) had been implemented and closed on Oct 2 but never admitted, so the runner showed `active_arms: 2`.
  - Froze one plan each with the risk review (`46-j1-gate-plan.md`, `46-j4-regime-plan.md`, `526be61`).
  - Created $35 strategy rows 13395/13396.
  - Admitted **J1 trial 6343** (random twin 6344, ungated twin 6345) and **J4 trial 6346** (uniform random twin 6347) via `--prepare`.
  - The running service now shows `active_arms: 4` and loads both cores. The daemon postdates the last shared-code change, so no restart was needed. The first session is Monday 2026-10-05.
  - No capital, key, venue or risk-limit change.
- **Test isolation fix (`15a7202`).** The J3 integration test collided with the real `jev_j3_news` row, and admitting J1 would have broken every arm-J1 fixture test. The intraday fixture now hides deployed cohorts and strategy keys inside its rollback transaction, as the J2 test does. All 140 Jev tests pass.
- `br ready`: `ob1` (TA batch, P2) and `qpb` (futures venue research, P3) are left to the respawned swarm.

## 2026-10-03 — Daily session: frozen services resumed; watchdog guard (`tradingbot-dxv`)

- **Incident:** at about 19:54 PT on Oct 2, every process in the tmux `services` window was frozen in state T by a machine-wide SIGSTOP (83 processes, many unrelated to the bot): TOM 3298, the IEX recorder, the event feeds, the Jev intraday runner and the scheduler. The freeze came after the close, so no session bars were lost and no orders were affected. Overnight news snapshots are missing. The frozen scheduler also explains why no agent was nudged onto `ob1`/`qpb` overnight. Resumed everything with SIGCONT at 07:51 PT, and all services are polling again. Logged in `logs/INCIDENTS.md`.
- Added `ops/resume_stopped.sh`, which SIGCONTs stopped processes under the given root pids. `ops/watchdog.sh` now runs it every minute over the services panes; it logs any resumed pids to `watchdog.log` and appends an incident line. Added 1 test (`tests/ops/test_resume_stopped.py`). No strategy, capital or risk-limit change.
- Health: Postgres is up and last night's backup wrote fine (`tradingbot-20261003-031500.dump`). The swarm is up (1 Claude + 2 Codex, idle). The Jev arms have recorded zero turns so far, as expected because they were admitted after Friday's close; the first session is Monday Oct 5. `br ready`: `ob1` (TA batch, P2) and `qpb` (futures venue research, P3), both unclaimed. They're left to the swarm via the now-running nudger. No phase change, so no agents were added.

## 2026-10-02 — Weekly page: Jev arms section (`tradingbot-2xm`)

- Extended `ops/weekly_report.py` with three read-only Jev sections. **Jev arms vs controls** lists each J1–J4 real arm beside its random twin (and the J1 ungated twin) with net-after-costs, trades, model cost and the arm's ready-for-live gate — grouped from `Trial.metrics["jev_intraday_v1"]` (`arm`/`twins`), with P&L/trades labelled as current cumulative paper snapshots (not weekly). **Jev month-to-date spend** shows settled + outstanding `JevRequest` spend vs the hard `MONTHLY_CAP_USD` ($20) UTC-month cap. **Jev decision latency this week** reports settled-call count and median/p95 `latency_ms` over the review window (paper-trial scoped).
- Added module-level `jev_arm_row()` and `jev_quantile()` (nearest-rank) helpers for testability. **4 new tests** (quantile nearest-rank + empty, real/twin row formatting, section render + HTML escaping) plus the existing render test updated for the new keys; 13/13 pass. Smoke-verified `snapshot()`/`render()` against the live schema. Read-only reporting; no order/capital/risk change. Completes the Jev suite reporting.

## 2026-10-02 — J3 Jev news reactor (`tradingbot-369`)

- Admitted **real paper trial 6162 / virtual random 6163** under `2514e8c`, with a $35 ceiling and frozen Monday 2026-10-05 13:30 UTC news start. The refreshed daemon discovers the arm and waits outside session. Recomputed code/parameter and review hashes match; zero orders/fills/model requests, empty integrity errors and no readiness claim. Shared initial cash stays $140 and TOM 3298 stays running at its existing allocation. One plan/results pair records the risk review, source limits and verification.
- Froze the registered pure news policy and one prospective risk plan: per-headline direction/strength/material questions, bullish + strength ≥3 + material probability >0.5, code-owned 90% slot requests and 1.5 ATR stops. Revision receipts are consumed before model outcomes; no missed-quarter replay. The existing five-headline window is explicit coverage, and the random twin shares the same candidate groups. **38 policy checks and three full-runner J3 checks pass**, with fake model/broker calls and rollback-only Postgres.
- Added quote receipt time alongside source time so a quote arriving after the feature cutoff is not falsely future-dated. Its integration check confirms that the original 30-second deadline does not move. Together with the earlier three shared payload checks, all four shared integration checks pass. Paper admission follows this source freeze; no J3 forward result exists yet.
- Claimed the next unheld strategy arm; prospective headline classification and a fixed paper plan are in progress. No J3 model call or order has occurred.
- The runner now exposes its actual validated observation quote as `execution_quote`, so policy vetoes can inspect source time and current spread. Added the `include_news=False` policy option for J2's numeric-only inputs; raw headlines remain in the immutable turn audit. Three integration checks pass for shared quote identity and both batched payload modes.

## 2026-10-02 — J4 Jev Regime switcher arm (`tradingbot-32i`)

- Added `src/tradingbot/strategy/jev_j4.py`: `J4Regime` (registered `JevStrategy`, `arm="J4"`, no ungated twin) for the `tg6` runner. At the 09:45 and 12:30 ET boundaries it asks Jev one bounded **Choice** to classify the regime — `trend` / `chop` / `risk_off` — from SPY/breadth/volatility observations; `plan()` returns an empty plan at every other boundary.
- Code owns the baskets: `trend` → top-3 ETFs by 1-day momentum (`ret_1d`), `chop` → the 2 most-oversold ETFs by RSI (`rsi14`), `risk_off` → cash. Each regime alternative carries its target longs (3×0.3 / 2×0.45 of the slot) **plus `fraction=0` exits for currently-held symbols outside the new basket**, so the chosen regime reconciles the whole portfolio; the runtime flattens everything by the close. ETFs missing the needed feature are excluded from ranking.
- Twin: a uniform random regime (including cash) via `random_mode="uniform"`, `random_options=(trend,chop,risk_off)`; no ungated twin. The model only picks the regime label — code owns symbols and fractions. **6 focused unit tests** (decision-time gate, basket ranking, held-position reconciliation, missing-feature exclusion, three-way question validation, choose). Read-only policy; no order/capital/risk change. Runner integration for regime arms is covered by `tests/forward/test_jev_intraday.py`.

## 2026-10-02 — J2 numeric menu policy (`tradingbot-pxk`)

- Admitted and verified **real paper trial 6166 / virtual random trial 6167**, strategy 12768, with a $35 ceiling inside the existing $140 shared paper book. The running service discovers both J2 and J3; J2 has zero turns, orders, fills and model charges, no integrity errors and no readiness claim. TOM 3298 remains running at its original $140 allocation. All 29 identity-bearing source files and the plan hash match the frozen admission (`f49e34f`, policy source `8ea4364`); forward evidence begins with future regular-session observations.
- Final validation covers **86 distinct checks**: 85 policy/event/state cases and one complete runner/fake-broker round trip. Quotes received after the feature cutoff use their real receipt timestamp without renewing the 30-second deadline; J2 model payloads exclude headlines while the immutable audit retains them. The integration verifies conviction-scaled entry, matched random sizing, actual broker-fill accounting, full-size exit and virtual-ledger isolation. Its rollback-only fixture remains usable after live paper cohorts exist. Closed the implementation/admission bead; continuing paper evidence is evaluated by the unchanged seven-day/30-round-trip/positive-after-cost rule and weekly review.
- Froze the forward plan and implemented J2's position-dependent ENTER/SKIP and HOLD/EXIT menus. Entry requires P(ENTER) ≥ 0.60 and expected ordinal conviction ≥ strong; code sizes four bounded slots by `max(0.5, score/3)`, rotates eligible candidates before answers, and preserves held positions, settled cash and daily entry reservations. A fresh-quote 10 bp spread ceiling, bar-gap checks and a symmetric 15-minute macro window veto entries; exit consideration remains available. Missing/invalid responses fail closed.
- Added receipt-time previous-macro timing and explicit coverage of the preceding 15 minutes to the shared event/state input, including outage and month-boundary unknowns. **84 policy/event/state tests pass**, including exact thresholds, malformed answers, candidate bounds, source-quote freshness and exits during entry vetoes. The single plan completes the AI-specific paper risk review. Shared runner quote/news plumbing and admission verification follow; no J2 model request, order, capital or risk-limit change at this slice.

## 2026-10-02 — J1 Jev Gate arm (`tradingbot-1tc`)

- Added `src/tradingbot/strategy/jev_j1.py`: `J1Gate` (registered `JevStrategy`, `arm="J1"`, `ungated_twin=True`) for the `tg6` intraday runner. Base rule (code-owned): the latest completed 15-min close is above the prior 1h high on above-average volume (reading `current_close`/`prior_1h_high`/`volume_ratio` from `ai/state.py`). Each firing symbol gets a five-dimension Jev **Choice** gate (data_quality, signal_alignment, market_regime, risk_check, execution_quality; options ok/conflict/block/insufficient); `choose()` returns `skip` on any `block` or a `conflict` at confidence ≥ 0.55, else `enter` one long slot with a −1.5×ATR stop (`atr14`).
- Exits (−1.5×ATR stop, session close) are runtime-enforced — the arm emits no exit decisions. Twins: the ungated base-breakout (`baseline="enter"`) and the matched-pass-rate random control. The execution_quality question states the round-trip cost hurdle via `cost_hurdle_note()`, so a sub-cost move is treated as no edge.
- A model only picks among code-created alternatives — it never invents a symbol, size, price or stop. **16 focused unit tests** (base rule + all skips, spec/target/stop shape, the five-dimension gate semantics, question validation through the real `_validate_questions`, cost-hurdle statement, default size factor). Read-only policy module; no order/capital/risk change. Runner integration for `arm="J1"` policies is already covered by `tests/forward/test_jev_intraday.py`.

## 2026-10-02 — Jev intraday execution infrastructure (`tradingbot-tg6`)

- Closed the infrastructure bead after refreshing the service to `15dc9a1` and observing repeated healthy zero-arm waiting ticks. J1–J4 policy implementation/admission and the weekly reporting integration are unblocked; no forward-performance evidence exists yet.
- Completed the persistent runner: immutable shared observations, bounded/pinned Jev batches, durable turn and entry claims, real Alpaca paper routing, complete-portfolio cost/risk review, T+1 cash, code stops and close-window exits, actual partial-fill tracking and residual-exposure incidents. Readiness queues after seven calendar days/30 completed round trips/positive after-cost P&L and rechecks weekly while paper continues; it never enables live transport. All provider charges/reservations count, including skipped/failed decisions.
- Fixed state integration so missing/incomplete bars reset windows; prior-session RSI/ATR/trend and same-clock 1d returns require the immediately preceding broker-calendar session's point-in-time closing snapshot. Preserved news revision/receipt identities and source digests. Friday has 40 closing snapshots, only seven fully complete sessions and 34 complete final intervals; gaps remain unknown. Batched free-IEX quote capture preserves the original 30-second deadline and leaves TOM's single-symbol behavior unchanged.
- Virtual controls have independent settlement/risk books and shared per-cohort fee rounding. Random passes count unavailable candidates as nonpasses; control failures cannot invalidate the real arm. J2 supports code-owned conviction sizing within predeclared bounds, with conservative minimum-ticket hurdles and matched control sizing. J4 declares its three regime options separately from an unavailable no-action sentinel, with cash expressed as explicit exits. **132 distinct checks pass** across the runner, controls, state, cost guard and existing Alpaca transport/connector/cash tests. The real `--once` smoke check and service pane `%39` report `waiting_for_admitted_strategies` with zero arms; a duplicate worker is rejected by the singleton lock. The existing $140 paper book and TOM trial 3298 remain unchanged. No paid model calls, real orders, capital changes or risk-limit changes were made during implementation.
- Claimed the runner prerequisite and published a finite-choice policy contract for J1–J4, durable per-boundary turn claims, seeded decision-rate controls, and an isolated equity paper book. Virtual fills cannot enter Alpaca cash/risk ledger tables. Conservative BBO taker fills cap raw IEX size at a one-share lower bound; makers remain unsupported without later trade-through evidence.
- **17 focused simulator/control checks pass** (T+1/weekend cash, partials, no repeat entries, stale/crossed/future quotes, risk veto, idempotent resume, exact matched decision counts and regime draws). Applied `jevturn01`; Alembic reports no schema drift. Existing capital, risk constants and TOM are unchanged; runtime integration and service activation followed in the next slices.

## 2026-10-02 — Jev state builder (`tradingbot-8hs`)

- Added `src/tradingbot/ai/state.py`: `build_state(session, symbol, *, decision_at, boundary=None)` returns a compact JSON-serializable point-in-time numeric snapshot per symbol — read-only over the yma IEX snapshot store (`load_snapshot`) and the 96t event feeds (`events_asof`) — or `None` when no fresh same-session snapshot is known. Features (Decimal→string, null + listed in `warmup` when insufficient history): 15m/1h/session returns, realized vol, SMA20/EMA20 trend position, RSI14, volume z, IEX spread bps, distance below day-high / above day-low; plus SPY-market and GICS sector-ETF context, session-phase bucket, minutes-to-next-macro, days-to-earnings, and a separate length-capped untrusted `news` field.
- Carries a `cost` block with `hurdle_bps` = bid/ask spread + modeled round-trip `EquityFeeBook` fees on the $140 slot, plus `cost_hurdle_note()` so any Jev question states the hurdle (a predicted move must beat spread+fees to be a tradable edge). Establishes that convention for the J1–J4 arms.
- Read-only: no model call, order, store mutation, capital or risk change. **11 focused tests** (pure Decimal indicators + stubbed-accessor assembly, cost hurdle, SPY/sector context, news capping, warm-up nulls, missing-snapshot/outside-universe). Unblocks the J1–J4 Jev runner (`tg6`).

## 2026-10-02 — Point-in-time event feeds (`tradingbot-96t`)

- Recorder is running in its own services pane: **51/51 latest source scopes healthy**, all 53 raw response hashes verified, news/macro context healthy for all 40 symbols. Earnings are 20 ETFs not applicable, 16 stock estimates and four unknowns. Existing $140 paper cash/TOM allocation remain unchanged. Infrastructure bead completed; older AI-2 remains deferred under `blocked:scope-overlap`, with its unattempted plan preserved.
- Applied `eventfeed01` with a clean schema check and verified real read-only capture: 110 headlines, October/November CPI/jobs, three GDP/seven FOMC events, and all 46 earnings-calendar dates through November 16. Fixed Nasdaq's required compatibility header while preserving the five earlier unavailable receipts. Added news refresh during slow calendar sweeps and a durable rolling error halt using unchanged PRD constants. **28 event-feed + 43 IEX/paper-cost checks pass**; service activation uses a dedicated tmux pane.
- Claimed the common P1 prerequisite and implemented free Alpaca headlines, BLS CPI/jobs, BEA GDP, Fed FOMC and Nasdaq earnings feeds. Immutable receipt-time snapshots preserve revisions/removals and mark outages explicitly; the state-builder API returns bounded untrusted news, calendar context and reproducible source receipts. Earnings dates remain estimates; missing coverage is never "no event."
- **25 focused tests pass** using isolated real PostgreSQL and fake HTTP, including the actual migration's update/delete protection, timestamp cutoffs, DST, revision history, stale/outage behavior, pagination, archive integrity and secret-safe failures. Source probes found usable free endpoints without new keys. No model calls, strategy trials, orders or risk/capital changes; runtime activation follows the implementation slice.

## 2026-10-02 — C20 conditional January small-cap recovery (`tradingbot-6f0`)

- **After-fee profit criterion met on the sparse holdout final.** Final **trial 5686** earned **+$3.917812** on $140 (+2.80%) with $4.78 marked drawdown (3.35% of peak), flat with zero rejected orders/halts, under commit `ae3ca3e`. The strategy sits in cash >99% of the time (0.91% average exposure); the result rests on three qualifying January entries and is carried by the January-2026 bounce (+$6.01) net of a January-2025 loss (−$3.08). Positive but luck-compatible, not a statistically established edge — remain in backtest, actual allocation $0.
- Froze and ran the plan's four training trials (H=5/10 × 5/10 bp) under commit `5ad9878`; all completed positive, flat and rejection-free. Selected **H=5 at 10 bp** (trial 5683, +$2.669) by highest positive 10 bp net, then pinned the selection receipt (SHA `3effe967…`, version `3325d021…`) before the one final. 3 of 14 training and 3 of 6 final Decembers qualified (IWM December total return strictly negative and strictly below SPY's).
- Captured and froze the IWM+SPY source bundle (SHA `58175627…`): Yahoo primary 5,218 sessions 2006–2026; independent Nasdaq-close × Alpaca-factor second source over 2,511 paired days from 2016-10-03 at **99.92% (IWM) / 99.88% (SPY)** 5 bp agreement, pre-2016 single-source Yahoo disclosed. Added the pure IWM-traded/SPY-reference reactor on the shared total-return backtest/ledger/risk interface with **10 focused tests** (real-Postgres savepoint). Backtest-only: no shared paper-book, capital, key, venue or risk-limit change; data spend $0.

## 2026-10-02 — Shared IEX intraday capture (`tradingbot-yma`)

- Final recorder `860c874` is running and verified: fresh health and advancing minute revisions, with per-symbol quote gaps explicit. Closed the source-infrastructure bead. Existing TOM 3298 stays running, allocation and shared paper initial cash both $140; no active paper orders. The overlapping legacy AI-1 experiment remains unlaunched.
- Implemented free-IEX capture for all 40 symbols, receipt-time minute revisions and immutable quarter-hour snapshots in two new TimescaleDB hypertables. Actual quote timestamps feed the existing risk tape; gaps, stale/invalid quotes and raw round-lot units remain explicit. Added bounded polling/storage, duplicate-process locking and an additive tmux service. Migration applied with no schema drift; **93 focused/AI-forward/risk checks pass**. Initial source smoke: 11,529 minute revisions / 40 snapshots, 15 complete latest intervals, 33–39 fresh valid quote symbols. No orders, model requests or paper-cash changes.
- Claimed the common P1 data prerequisite for the owner's new J1–J4 suite. Frozen contract: 40 approved symbols, explicit free IEX, versioned receipt-time bars, immutable 15-minute observations, genuine quote freshness and bounded storage. The older AI-1 scope is being reconciled with the newer suite before any model calls or orders; the existing $140 paper book and TOM trial remain unchanged.

## 2026-10-02 — AI-2 prospective Jev basket (`tradingbot-cvm`)

- Added a shared paper cost guard with account/day regulatory-fee reconciliation, durable Jev charge/reservation debits, complete-portfolio fresh marks and original-decision deadlines. It preserves dated T+1 cash, existing stronger guards and every risk limit; **15 focused real-Postgres/fake-HTTP tests pass**. The component is not enabled account-wide. The older AI-2 plan remains unlaunched while its relationship to the owner's newer J1–J4 scope is reconciled; no candidate model calls, trial activation or orders.
- Claimed the next available P2 bead after AI-1 was claimed by OrangeCove. Froze a 20-stock numeric-state Jev long/flat basket and an actual-fill equal-weight paper comparator before candidate price retrieval or model calls: October 5–23, open+35-minute entry/close−15-minute exit, one batch per day, two $40 simulated ceilings within the existing $140 book. Shared cash coordination, cost guard and source preflight precede activation; TOM 3298 remains unchanged.
- The single plan records the AI-specific paper admission/account-loss review, point-in-time inputs, exact fees/benchmark/calibration labels, fixed end and 7-calendar-day/30-model-round-trip/profit/outperformance gate. No forward result or eligibility claim exists yet; actual capital/data spend $0.

## 2026-10-02 — Jev budget and calibration wrapper (`tradingbot-3mj`)

- Added the sole runtime TypeSafe entry point, `JevClient.decide()`, with a global **$20 UTC-month cap**, Decimal returned-usage billing at the official **$0.042/M input / free output** price, pinned `jev-1.13.0`, disabled retries and a 10-second HTTP-operation timeout. PostgreSQL serializes and commits maximum-context reservations before requests; unknown charges survive failures, restarts and month rollover. Unreviewed response models/token bounds halt further calls. Errors, refusals and uncommitted audits return no decision.
- Applied additive migration `jev20cap2026` for durable spend/control and the question/state-hash/answer/probability/confidence/model/latency audit. Added immutable, timestamp-checked outcome labels for later calibration, masked key configuration, sanitized incident logging and operating/API notes. No direct paid test calls or strategy/risk changes.
- Validation: **38 Jev tests** using isolated real Postgres transactions, fake clients and the real SDK over fake HTTP; concurrent last-budget admission, crash/timeout reserves, rollover, malformed replies, secret suppression (including JSON escapes), persistent/in-flight halts and storage failures. **124 existing AI-forward/risk/ledger checks pass** (one upstream websockets deprecation warning).

## 2026-10-02 — C18 country-equity reversal (`tradingbot-ifc`)

- Recorded null-performance source failure **trial 5651 / strategy 10573** after freeze `d49249d`. Stored-only verification confirms 44 input/five code hashes, exact trial parameters, one source trial and zero orders/fills/final spends. One plan/results pair completes the account-risk hold decision. Research bead closed as the permitted scoped price failure; no measured alpha claim, allocation/data spend $0, original variants/final preserved and risk limits unchanged.
- **Price DATA_FAIL:** fixed six-fund source check passes EWC/EWG/EWJ/EWU but fails EWA (**98.44683%**) and EWS (**97.80964%**) on 2,511 paired returns through the registered Nasdaq × Alpaca-factor route. Direct Alpaca also fails for those two; Stooq provides no CSV. Preserved all source bytes, discrepancies and unmatched dates, without patching prices, dropping funds or relaxing the 99%/5 bp gate. Froze 44 input files and a source-only auditor with **22 focused checks passing**. Four planned training configurations remain unattempted; no ranking, strategy replay or C18 final.
- Claimed the next unheld research bead while NavyLantern owns the new P1 Jev wrapper. Preserved the six-country universe, 36/60-month lookbacks, fixed 12-month skip and original 70/30 interval. All six Yahoo primary histories contain 5,218 sessions; independent source checks precede ranking or strategy replay. The long final warm-up and sparse independent sample remain explicit; actual allocation $0.

## 2026-10-02 — C16 yield-curve source investigation (`tradingbot-1rl`)

- **SIGNAL_EVIDENCE_GAP:** bounded ALFRED public-form/graph attempts returned no usable vintage bytes; the documented API requires an unconfigured key. No revised-yield substitution or invented historical cash decisions. This is a session access limitation, not proof that history is unavailable. Price evidence passes independently; all four training cases remain unattempted and no C16 final is consumed.
- Shipped the source-only audit and one plan/results pair in `2d1face`, with **29 focused checks passing**. Recorded source failure **trial 5648 / strategy 10570** with null performance. Stored-only verification confirms 25 input/four code hashes, exact ledger parameters, one source trial, zero orders/fills and no final spend. Account-risk review holds at idea/source preparation; actual $0, data spend $0 and no promotion or risk/live change.
- Claimed the next unheld P2 bead and retained the frozen 0/1 percentage-point monthly TLT rules. Revalidated the existing 5,218-session TLT archive and all 22 source hashes: 2,509/2,511 paired returns agree within 5 bp (99.92035%), with all mismatches and unmatched dates retained. Historical ALFRED vintages remain a separate signal prerequisite; current revised yields cannot substitute. No training/final replay or actual allocation.

## 2026-10-02 — C19 correlation-conditioned hedge (`tradingbot-n7j`)

- Sole final **5646** meets the historical after-fee profit criterion: **+$81.704996**, **$30.03 / 19.28% peak / 21.45% initial** marked drawdown, 11 round trips / 102 fills, flat with zero rejected orders/halts. The final lost $17.10 in 2022; fixed 50/50 benchmarks returned more, and only 10 exit-month clusters leave the registered p-value null. Completed regimes/years/benchmark and account-risk review. Stored-only five-trial audit verifies every adverse fill price, frozen target/reserve, settled cash, fees/net, flat quantities and monthly/drawdown totals, plus one canonical final. Research bead closed; remain in backtest pending paper fidelity, actual $0, no funded promotion or risk/live change.
- Four fixed training trials **5642–5645** completed positive, flat, with zero rejects/halts. Selected **126 sessions at 10 bp**, trial **5645**, **+$143.026601** net, **24.06%** peak drawdown, 5 round trips / 214 fills but only four exit-month clusters and three hedge switches (luck p-value null). Stored-only audit reconciles each fill, adverse price, frozen target/reserve, settled cash, fees/net and monthly/drawdown totals. Exact selected trial/version/receipt committed before any C19 final; actual $0.
- Claimed the highest unheld P2 bead and froze the original 63/126-session Pearson-correlation rule, 5,218 sessions per SPY/IEF/GLD and 27 raw input hashes. Paired-return agreement is 99.880573% / 100% / 99.037037%, retaining every discrepancy and unmatched earlier date. **47 focused checks pass**, covering correlation branches, equal-half sizing, pro-rata settled cash, hedge replacement, unchanged risk/ledger and durable single-use final. No real strategy outcomes precede this freeze; actual $0.

## 2026-10-02 — C15 low-volatility sector source test (`tradingbot-xwy`)

- **Price DATA_FAIL:** all nine Yahoo histories contain 5,218 sessions. Direct adjusted Alpaca comparisons fail the fixed 99%/5 bp gate; the registered Nasdaq × Alpaca-factor route passes seven sectors, but XLE reaches **97.57069%** and XLU **98.80526%** across 2,511 paired returns each. Preserved all disagreements/unpaired dates and unusable Stooq responses. No primary patch, sample/universe substitution or relaxed gate; penny precision in adjustment factors is a documented limitation.
- Added a source-only audit with **22 focused checks passing**, froze 64 inputs and recorded failure **trial 5589 / strategy 10469** after commit `c361b9b`. Stored-only verification confirms all performance fields null, one source trial, no orders/fills and no C15 final spend. All four planned training cases remain unattempted. One plan/results pair includes the complete hold/account-risk decision; actual allocation $0, risk limits unchanged and no promotion.

## 2026-10-02 — C17 credit signal (`tradingbot-t87`)

- Single final **5587** meets the historical net-profit criterion: **+$45.485000**, 9 round trips / 32 fills, flat with no rejected orders/halts. Marked drawdown **$48.29 / 33.15% of peak / 34.49% of initial**, a **−$42.12** marked 2022, and only nine exit-month clusters limit the evidence; SPY buy/hold returned more with smaller peak drawdown in the final. Completed regime/year/benchmark and account-risk review; stored-only five-trial/fill/cash/fee/monthly/drawdown audit confirms exactly one canonical C17 final. Hold in backtest, actual $0; no funded promotion or risk/live change.
- Four fixed training cases **5583–5586** completed positive, flat and rejection-free. Highest 10 bp net selects **126 sessions**, trial **5586**, **+$160.15**, **11.77%** peak drawdown, 11 round trips / 84 fills. Stored-only fills/cash/fees/monthly/drawdown reconciliation passes; p-value is null with only 11 exit-month clusters. Exact trial/version/selection hashes committed before the single canonical C17 final; actual $0.
- Claimed the next unheld P2 bead and froze all 4,716 SPY/HYG/IEF sessions, 34 hash-bound inputs and the unchanged 63/126-session monthly credit rules. Independent reference agreement is 99.880573% / 99.840701% / 100%; every discrepancy and pre-2016 unmatched date is retained. **41 focused checks pass**, including settled cash, adverse full-target sizing, unchanged risk kills and durable single-use family admission. No real candidate outcomes precede this source/code freeze; actual $0.

## 2026-10-02 — Batch 3 preregistration (`tradingbot-y74`)

- Completed primary-source review and six candidate research beads: C15 low volatility (`tradingbot-xwy`), C16 yield curve (`tradingbot-1rl`), C17 credit signal (`tradingbot-t87`), C18 country reversal (`tradingbot-ifc`), C19 correlation hedge (`tradingbot-n7j`) and C20 conditional January small caps (`tradingbot-6f0`). Each links its sole `43-cXX-*-plan.md`; ranked priorities, source limitations and account-risk reviews are explicit. All six frozen rule sections match commit `62f30fa`; cutoffs and child dependencies were verified. Twelve variants / 24 training cases are planned, with at most one eligible final per family. No candidate outcomes were fetched or calculated; actual allocation remains $0.
- Claimed the next unassigned ready bead after NavyLantern claimed C10. Froze six distinct C15–C20 hypotheses in one plan each: low-volatility sectors, yield-curve-conditioned TLT, credit signals for SPY, multi-year country reversal, correlation-conditioned hedging, and conditional January IWM exposure. Twelve signal variants / 24 main training cases are fixed before any new candidate price or outcome retrieval.
- Plans specify universes, exact elapsed-time 70/30 cutoffs, 5/10 bp costs, $140 virtual cash, settled-cash execution, one eligible final per family, regime/benchmark reporting and individual account-risk reviews. C18/C20 explicitly disclose limited independent samples. No outcome, trial, real order, funded allocation, paid data or PRD6/PRD9 change; primary-methodology review and per-family research beads follow this rule freeze.

## 2026-10-02 — C10 adjusted-total-return re-evaluation (`tradingbot-wdr`)

- **Measured FAIL:** single final **5529** lost **$3.400678** after costs over 74 round trips/148 fills, with **14.19%** marked drawdown, $2.96 fees, flat ending and zero rejected orders/halts. Completed regime/benchmark/exposure review, account-risk decision and stored-only reconciliation of all five trials, fills, cash, fees/net and drawdown. Original trial 4584/strategy 7163 remain unchanged; exactly one canonical C10 final is consumed. Research bead closed; actual $0, no promotion or risk/live change.
- Completed four positive training cases **5525–5528**, each with 174 round trips, flat ending and zero rejections/halts. Third-to-last entry nets +$34.86/+$10.07 at 5/10 bp; fifth-to-last +$70.73/+$46.21. Froze **fifth-to-last at 10 bp**, trial **5528**, **9.83%** marked drawdown, with exact selection/version hashes in the results file before its sole final. Prior source failure remains unchanged; actual allocation $0.
- Froze 5,218 adjusted TLT sessions and 22 source inputs. Yahoo/reference daily returns agree within 5 bp on **2,509/2,511 paired days (99.92035%)**, retaining two discrepancies and 2,706 earlier unpaired returns. Implemented the two fixed month-end reactors, Sandy/Ford execution delays, settled-cash sizing, share-equivalent fees, shared risk/ledger and durable single-use final. **17 focused checks pass**; each variant has 174 training and 74 possible final windows. Source trial 4584/strategy 7163 are preserved; no real strategy outcomes precede this implementation freeze.
- Claimed the highest-priority ready bead under owner comment 26. Preserved the original two TLT month-end variants, 2006–2026 interval/cutoff, costs, $140 virtual slot and risk limits. One plan records the adjusted-price cross-check, explicit unexpected-closure handling, selection and single-final rule before outcomes. Prior source trial 4584 and all `30-c10-*` receipts remain unchanged; actual allocation $0.

## 2026-10-02 — Daily session: unstuck idle swarm (C10 re-run, batch 3)

- **Health:** Postgres up; the nightly pg_dump wrote `tradingbot-20261002-031500.dump` (the circular-FK warnings on TimescaleDB `continuous_agg` are benign). Swarm is up with one Claude and two Codex panes. The services window is running both the TOM paper runner (trial 3298, next entry Oct 27) and the scheduler. No incidents.
- **Stuck:** `br ready` was empty and all agents were idle overnight. The nudger only fires when there is open work, so it went quiet after 18:00. C10 (`tradingbot-wdr`) was the only batch-2 equity candidate still blocked on the old full share-action and calendar-provenance requirements. The 2026-10-01 research data standard drops those requirements.
- **Unblocked:** retargeted `tradingbot-wdr` (now P1) to an adjusted-total-return C10 re-evaluation following the C09/C12 pattern, with the same variants, interval, cutoff, costs and limits. Created `tradingbot-y74` (P2) to preregister candidate batch 3 (C15+) of free-data equity/ETF edges, since C01–C14 are otherwise exhausted.
- **Ops:** committed the nudger's `--pane=0.N` target fix. Bare `--pane=N` became ambiguous once the tmux `services` window existed. Nudged both idle Codex panes onto the new beads. No agents were added, because no phase dependency changed.
- No capital, keys, venues, risk limits or public posts were touched.

## 2026-10-01 — Explicit equity summary date bounds (`tradingbot-luy`)

- Replaced misleading inherited `2016_2022` / `2023_2026` / `2025_2026` metrics in future runs with `exit_date_regimes`: explicit inclusive/exclusive bounds, New York exit-date attribution and first/last observed exit dates. Open-ended periods are named `before_2023`, `from_2023` and `from_2025`; the bounded 2023–2024 period is explicit. Existing dashboard/report readers do not consume the removed keys.
- **29 focused checks pass**, covering pre-2016 and post-2026 exits, New York midnight boundaries, empty samples, ordering, saved trial metadata and shared replay integrations. Stored-only comparison confirms all columns of 24 protected historical trials and three consumed family receipts are byte-identical. No historical replay, receipt migration, P&L/accounting, risk-limit or live change.

## 2026-10-01 — C09 total-return recovery after Treasury auctions (`tradingbot-5hl`)

- **Measured FAIL:** sole final **5495** lost **$38.435118** over 74 round trips, with **27.86%** marked drawdown, $2.96 fees, flat ending and zero rejected orders/halts. Completed the two diagnostic training controls, source/ledger verification, regime review and full hold/account-risk decision. Actual $0; no promotion. Original source failure 4585 and the consumed final remain intact. Logged `tradingbot-luy` for an inherited legacy regime-label defect; canonical dated diagnostics and these results are unaffected.
- Completed four training cases **5489–5492**, all flat with zero rejections/halts. Five-session net is −$6.28/−$25.92 at 5/10 bp; ten-session net is +$35.82/+$13.22. Froze **ten sessions at 10 bp**, trial **5492**, 163 round trips and 12.42% marked drawdown, with exact selection/version hashes before its one final. Controls remain diagnostic only.
- Revalidated all 242 dated nominal ten-year auctions, 23 special notices and their original Treasury receipt; preserved old source failure 4585. Frozen IEF adjusted source has 5,218 sessions and 100% agreement within 5 bp on 2,512 independently cross-checked daily returns, with 2,705 older unmatched returns disclosed.
- Implemented fixed five/ten-session post-auction holds, frozen settled-cash targets, overlap skips and cash delays that retain the original exit. Shared ledger/risk and raw-share fee conversion retain durable single-use final admission. **14 focused checks pass**. Four training cases and two controls follow this committed implementation; no real C09 outcome inspected yet. Actual allocation $0.

## 2026-10-01 — C12 adjusted-total-return macro research (`tradingbot-qb5`)

- **Measured FAIL:** all four main training cases **5511–5514** lost money: Employment −$14.62/−$33.83 and CPI −$40.44/−$53.48 at 5/10 bp per side. Their 10 bp marked drawdowns are **31.21%/40.47%**; both lose in every covered regime. Four shifted training controls **5515–5518** are also negative. All eight finish flat with zero rejections/halts. No eligible winner, **no final attempted**, actual $0 and no promotion. Stored-only verification reconciles fills, cash, fees/net and drawdown, verifies frozen inputs/dependencies, and preserves source trial 4591/strategy 7170. Completed the one results file and account-risk decision; research bead closed.
- Repaired and reconciled 496 published BLS issues plus the two canceled October 2025 identities, dated shutdown/replacement evidence and 21 advance Fed schedules. Frozen source binds the 5,218-session SPY total-return history and its 99.8806% two-source daily-return agreement, retaining all three discrepancies and 2,705 older unmatched returns. Built decision-time revisions, FOMC/shifted-window filters, fixed exits, settled-cash targets and the durable single-use final adapter. **28 focused checks pass**; source trial 4591 is unchanged and no new real outcomes precede this implementation commit. The one results file records provenance limits and the pre-backtest account-risk checklist; actual allocation $0.
- Claimed the only eligible unassigned ready bead after the coordinator nudge. Preregistered the original Employment/CPI variants, 2006–2026 interval and fixed 70/30 cutoff, causal decision/entry/exit rules, FOMC exclusions, costs and shifted controls in one plan under the owner’s revised adjusted-price standard. Prior source trial 4591 remains immutable; no new strategy outcomes yet.
- New discovery located the October 3, 2013 official CPI suspension notice and a timestamped November 21, 2025 official BLS post announcing December 18 CPI, advancing the earlier calendar gaps. Completing monthly announcement and revision evidence before the replay; exact historical share mechanics are no longer prerequisites.

## 2026-10-01 — C03 adjusted-total-return cross-asset momentum (`tradingbot-h5b`)

- **Profit test PASS:** single final **5485** earned **$70.915728** over 26 round trips, **25.55%** marked drawdown, $1.65 fees, no rejections/halts and flat ending. Final cluster p-value is null (22 exit months); both buy/hold benchmarks outperformed it. Completed source/metrics verification and the concise risk/fidelity decision: historical diagnostic, actual $0, no promotion. Preserve old source failures and the consumed final. Continuing the next ready C09 auction bead.
- Completed all six fixed training cases, trials **5478/5479/5481/5482/5483/5484**, all flat with zero rejections and positive net. Froze unfiltered **top-two at 10 bp**, trial **5482**, net **$142.654445**, 62 round trips and **13.90%** marked drawdown, with exact selection/version hashes in the same plan before its one final.
- Preserved the five funds, three monthly momentum variants, six cost cases and original 70/30 cutoff. Frozen total-return source has 5,218 sessions per fund; two-source overlapping daily-return agreement is SPY 99.8806%, IEF/EFA 100%, GLD 99.0370%, VNQ 99.9204%, with every exception and older unmatched return disclosed. Historical fractional/action mechanics no longer block the test under AGENTS `d267cf7`.
- Built the pure ranking/filter reactor and shared ledger/risk replay with frozen pro-rata targets, conservative settled cash, independent raw-share fee conversion, simultaneous five-fund marks and durable final admission. **13 focused checks pass**. The source hash is pinned in the single plan; no real C03 outcomes before the implementation commit. Original failed source trials remain untouched.

## 2026-10-01 — C08 adjusted-total-return re-evaluation (`tradingbot-ndl`)

- **Research profit criterion PASS:** sole revised final **5480** earned **+$7.668053** at 10 bp per side, four round trips, **16.41%** marked drawdown, flat terminal holdings and no rejected orders or halts. Preserved old final3910 and all prior fingerprints; recorded calendar/USO exposure regimes, small-sample limitations and account-risk checklist in the one results file. Closed the owner-amended research scope; funded allocation remains $0, with no paper/live action or claim that earlier forward requirements are satisfied.
- Completed four training paths (5474–5477). The 0% threshold hits the permanent kill and retains exposure after exit vetoes; both cases are ineligible, with marked loss recorded. The −5% threshold at 10 bp is selected: +$102.284030, three round trips, 26.62% marked drawdown, flat and no rejections. Committed the exact selection receipt/version in the one results file before its sole final. **53 focused checks pass.**
- Preregistered the owner-authorized new accounting model with the original two inventory thresholds, EIA publication timing, 2018–2026 interval and fixed 70/30 cutoff. All 2,197 daily returns across 2,198 sessions agree within 5 bp between Yahoo adjusted closes and free Nasdaq; no missing endpoints or exceptions. One plan and one results file contain the source evidence; optional blackout omitted and exact historical share mechanics are approximated by adjusted units.
- Added a narrowly authorized C08 family revision after C02 final 5408 completed, preserving old final 3910 and the shared single-use guard. Synthetic checks cover continuous holdings through the split, cash reconciliation, terminal liquidation and permanent-risk-kill exit vetoes. No revised real strategy outcomes before this implementation commit; no risk, key, account, capital or live change.

## 2026-10-01 — C02 monthly sector momentum under Amendment 21 (`tradingbot-0qk`)

- **Measured PRD §4 PASS (both partitions positive), not alpha, not promotable.** Single holdout **trial 5408** (mean5, 10 bp) earned **+$91.03** over 2020-07-10 → 2026-09-30 on the $140 virtual slot (+65.0%): +$76.62 execution + $14.41 dividends, 49 round trips, 132 fills, **zero rejections**, flat terminal portfolio, **14.9%** max marked drawdown, p = **0.013** (1-sided descriptive), 10/10 blackout symbol-sessions (the 2025-12-05 splits) handled at ~$0.04 fees. Diagnostic cost-free fully-invested benchmarks beat it in both partitions (holdout: SPY +161.5%, equal-weight 9-ETF +145.6% — both at higher drawdown), so monthly rotation was lower-drawdown but trailed buy-and-hold. `promotion_eligible=false`: Amendment 21 cash/execution counterfactual on free Yahoo bars over a previously inspected SPY window; needs the promotion checklist + a 7+ day / 30+ trade forward run before any `ready-for-live`. Results: `docs/research/24-c02-momentum-results.md`.
- Trained six variants (ret12 / ret6 / mean5 × 5/10 bp) over the first 70%, trials **5402–5407**, all complete with zero rejections and all positive. At 10 bp: mean5 +$127.92 (DD 42.5%), ret6 +$119.65 (DD 48.8%), ret12 +$107.98 (DD 45.3%); none reached the §6 −40%-of-allocation kill. Froze **mean5** (highest positive complete 10 bp net; version `fc96077107e5f997…`) in `24-c02-momentum-selection.json` and committed it before the single holdout. The locked family-`c02` holdout is now consumed (`family_holdout_spends` trial 5408); the prior failed C02 source trial is preserved.
- Built the engine on the admitted nine-ETF Amendment 21 frozen source (C02 lineage, 12-c02 → 22-c02): `strategy/c02_sector_momentum.py` (pure monthly-rebalance momentum reactor — top-3 equal within 95%, hold stayers / sell leavers, pro-rata rationing with 5% reserve + sub-$1 skip, blackout exclude/force-exit/reentry) and `research/c02_sector_momentum.py` (self-contained hardened replay over the shared RiskEngine/Ledger: next-open execution, EquityFeeBook costs, conservative T+1 cash, ex-date dividends, terminal liquidation, durable single-use holdout admission). **15 focused checks pass** (10 reactor, 5 replay). No §6 change; `research_only`; no live keys.

## 2026-10-01 — C11 revised research model and adjusted-price cross-check (`tradingbot-jfv`)

- **Measured FAIL:** single final **5399** lost **$37.879554** over 75 completed round trips, with **30.97%** marked drawdown, $3.00 fees, no rejections/halts and flat ending. Preserved the final receipt, four main training cases and four controls (one explicitly incomplete after its risk kill). Completed the lean results/risk decision; actual allocation $0 and no promotion. Source/code hashes verified from stored evidence; prior source failure 4589 unchanged. C03 is next.
- Completed four registered training cases, trials **5378/5383/5384/5388**, 174 round trips each, flat with zero rejected orders. Froze **next-open at 10 bp**, net **$16.268694**, as the higher-cost winner in the single plan with its exact strategy version and immutable selection hash. The final remains unattempted at this selection commit; shifted-calendar controls are diagnostic only.
- Reconciled independent closing-price conventions with free Nasdaq closes and Alpaca-only dividend factors: **99.8806%** of 2,512 overlapping SPY daily returns agree within 5 bp. Preserved three exceptions and the unpaired earlier history. Froze the source hash and calendar/cost controls in the same plan, then implemented the total-return reactor and shared-ledger replay with raw-share-equivalent fees and durable single-use final admission. **17 focused checks pass**; no real strategy outcomes before this implementation commit.
- Applied the coordinator's `d267cf7` research standard, claimed C11 and queued C03. The single C11 plan preserves frozen variants, costs and holdout bounds while using adjusted total-return equivalents; prior failures and finals remain intact.
- Added a reusable immutable capture/return-comparison helper with **six focused checks passing**, including exact 99%/5bp boundaries and missing-endpoint handling. Reused full Yahoo history and captured free Alpaca adjusted SIP overlap; Stooq returned a verification page. Paired 2016–2026 returns currently agree at 93.59% for SPY and 99.04% for GLD; all disagreements and coverage are retained. SPY closing-price convention reconciliation continues before strategy outcomes.

## 2026-10-01 — C05 adjusted-total-return re-evaluation (`tradingbot-lsr`)

- **Research profit criterion PASS:** sole final **5401** earned **+$47.127360** at 10 bp per side on $140 virtual cash, with 34 round trips and **18.25%** maximum marked drawdown. Flat terminal portfolio, no rejected orders or halts; $57.11 of ending equity remains modeled unsettled sale proceeds. Preserved the six training cases and all prior trial/final fingerprints. One plan and one results file contain coverage limits, regimes, descriptive luck and account-risk review. No paper/live action or funded allocation. Closed the owner-amended research scope and advanced to C08.

- Completed all six adjusted-total-return training cases (5371, 5377, 5381, 5385, 5393, 5398). The fixed rule selects positive 126-session momentum at 10 bp: net +$30.421484, 57 round trips, $49.33 maximum marked drawdown, flat terminal portfolio and no rejected orders or halts. Committed selection/version in the same results file before the sole final.

- Cross-checked all five unchanged Yahoo total-return series against independently dividend-adjusted Nasdaq closes over 2,512 daily returns per fund: GLD/SLV/USO 99.9204%, UNG/DBA 100% within 5 bp. Disclosed older uncovered years and retained original failed SIP/rounded-factor diagnostics. Implemented the adjusted-unit adapter over the existing strategy, risk engine and durable ledger.

- Pre-registered the owner-authorized material model revision: unchanged five-fund universe, three signals, six cost cases and original cutoff; two-source 5 bp/99% daily-return comparison. One plan and one results file. Prior final 3964 remains consumed and disclosed.
- Added a narrow explicit revision identity to the shared final-admission guard; all siblings within this revision remain single-use, and no old receipt or risk limit changes.

## 2026-10-01 — C14 source and cash-collateral feasibility (`tradingbot-ddw`)

- Claimed the remaining unblocked ready bead and committed its frozen plan. Re-audited eight original options queries/eleven pages (38,823 records) and twelve C13 source/capability captures by exact hash, without new quote or account probes. Historical BBO/chain and assignment-lifecycle admission remain failed; four training cases and the final are unattempted.
- The original collateral rule allows $133 initially, implying a necessary $1.33 strike ceiling before unknown reserves; a $1.50 strike cannot fit. Historical affordability remains unknown, not zero, and premium credit cannot fund collateral. Preserved the five-name universe, variants, cutoff, fees policy and risk limits.
- Added reproducible local source audit, guarded idempotent null-failure recording and complete hold/account-risk review in `docs/research/37-c14-source-audit.md`. **46 focused checks pass** (19 C14, 15 C13, 12 archive). No outcomes, final use, account change, forward activation or orders.
- Pushed implementation **3c07551**, then recorded source failure **trial 5325 / strategy 10085**, all eight performance fields null, idea/$0 and zero C14 orders/fills/finals. Stored-only verification preserves 12 prior trials, venue records and risk bytes; all 26 dependencies match the recorded commit. Closed under the explicit source-failure route; only new historical evidence can reopen admission.

## 2026-10-01 — C13 options source/capital feasibility: parked (`tradingbot-0cm`)

- Re-audited all eight original options queries/eleven raw pages (38,823 records) and preserved twelve new primary-documentation/current-paper-capability captures. The approved bundle still lacks historical executable BBO and decision-time F/NOK/SNAP chain/deliverable/tick evidence; all four training cases and the final remain unattempted.
- Preserved the fixed universe, 3/5-session variants, original interval/cutoff, costs and risk limits. The $49 opening cap implies a necessary combined-ask bound of $0.45 per share before fees/tick rounding; affordable-event count remains unknown. Current paper level 3 is not live permission, and Trading API support-email DNE is not the partner Broker API endpoint.
- Added immutable capture, reproducible source/capital audit and guarded idempotent failure recording. **15 new C13 checks and 12 existing options checks pass**. Full admission hold, remaining prerequisites and account-risk decision: `docs/research/36-c13-source-audit.md`.
- Pushed implementation **8bafa91**, then recorded failed source **trial 5322 / strategy 10083** with all eight performance metrics null, idea/$0 and zero C13 orders/fills/finals. Stored-only verification confirms eleven protected prior trials, venue records and risk limits unchanged, and all 22 code/policy dependencies match the recorded commit. Closed under the explicit source-failure route; reconsideration requires materially new free historical evidence, not an unchanged-input replay.

## 2026-10-01 — Informational dashboard and weekly statistics (`tradingbot-ss4`)

- Added Sharpe, drawdown, net execution hit rate and OOS t with per-row sample definitions. Known marked-equity receipts support descriptive annualized Sharpe; legacy equity final executions require flat inventory and full P&L reconciliation for their separately labelled t-statistic. Missing/undefined values stay null, failed audits remain visible, and no promotion criterion or historical row changes.
- Added a complete final-holdout table and safe expandable statistic scopes. Batched dashboard reads preserve existing ledger totals while avoiding per-strategy query growth. Weekly execution statistics explicitly use the seven-day window; dashboard execution statistics use all-time scope.
- Validation: **56 checks pass**, including numerical edge cases, mode/holdout isolation, incomplete trades, multipliers, HTML escaping, real HTTP queries and encryption/decryption. Stored-only comparison confirms original ledger totals and final/SPY trial rows unchanged. Local representative dashboard and weekly renders reviewed; final report encryption/decryption with an isolated test password verified (123 recent trials, seven final holdouts). No public deployment.
- Operational incident: the configured weekly password does not meet the existing minimum of 20 characters, so the normal build refuses encryption. The password and policy are unchanged; owner-input follow-up `tradingbot-ud2` records this blocker. No password value or exact length was logged.

## 2026-10-01 — C13 source/capital feasibility preparation (`tradingbot-0cm`)

- Claimed the highest-priority unblocked unheld ready bead. Preserved the frozen F/NOK/SNAP universe, two entry variants, four cost cases, $140 virtual slot/$49 opening cap and December 2025 cutoff.
- Added a bounded immutable primary-documentation capture and read-only paper-capability projection. Source audit will recheck the existing options archive and document capital constraints; no historical P&L, forward activation or option order while execution evidence is missing.

## 2026-10-01 — C03 cash evidence recovered; ex-date conflict holds admission (`tradingbot-2wh`)

- Reconciled all four 2006 VNQ full cash amounts and payment dates across newly archived component/full-total records. December's $1.133 ordinary income plus $0.361 capital gain explains the original $1.494 total; upstream independence and original issuer notices remain unproven.
- Full secondary history has 83 events and no overlapping amount breach, but June 2009 remains June 24 in Yahoo/DividendHistory versus June 25 in other archives. All payment evidence agrees on June 30; that cannot resolve entitlement. Preserved every source date and the original universe, split, variants, costs and risk limits.
- Thirteen immutable captures retain the direct SEC 403 and report-mirror 404. Added reproducible source-only reconciliation and idempotent null-trial recording. All 25 focused checks pass; no strategy outcomes, final, allocation or order. Full hold/checklist and account-risk decision: `docs/research/35-c03-source-repair.md`. Ledger receipt follows committed implementation.
- Implementation `f3d1aa2` recorded failed source trial **5314**. Stored-only verification confirms all result metrics null, no C03 orders/fills/finals, nine prior rows unchanged and every dependency equal to its committed bytes. C03 remains idea/$0; closed this source attempt with conditional new-evidence follow-up `tradingbot-h5b` (`blocked:source-evidence`).

## 2026-10-01 — C05 durable runner and income consumer integration (`tradingbot-dk3`)

- Implemented disabled preparation, explicit activation, monthly close/open orchestration, durable reactor targets and independent attempts, reductions before buys, actual known-fill receipts and finite terminal completion. Unknown submissions are never resent; partial, late, vetoed, dust and missed forced exits preserve exposure and hold further decisions.
- Integrated complete portfolio marks, shared fee/cash evidence, pre-ex queued ordinary distributions and explicit settlement completion receipts. C08 activation/review binding now uses the same pre-ex queue, with rollback on failed admission. No actual account was opted in or funded.
- Preserved first causal issuer-action review across daily watches and captured all held/pending equity reference closes. The actual five-fund watch has complete independently checked 127-close windows, but DBA HTTP 406 and unresolved USCF notices keep source admission held. One historical DBA broker distribution is explicitly unreconciled; no empty-page clearance or signal calculation.
- Validation: **66 focused C05/shared/compatibility tests pass**, including **17 C05 runner cases**, plus **23 existing C08 runner tests**. Earlier SPY compatibility checks remain valid. The CommodityTrend reactor, historical finals, cash book and PRD6 limits are unchanged; actual forward execution/action/cash evidence remains outstanding.
- Committed runner `6e921b5` recorded failed source-admission **trial5311**, with zero orders/fills and null performance. Stored-only verification preserves training3959, all seven finals, SPY3298, earlier preparations and unchanged venue metadata/$140 cash. Closed implementation `tradingbot-dk3` with the explicit hold/checklist in report34; conditional new-source/account admission and actual scheduled evidence are tracked in **`tradingbot-lsr`** (`blocked:source-evidence`). No account migration or activation occurred.

## 2026-10-01 — C03 older VNQ source preparation (`tradingbot-2wh`)

- Claimed the highest-priority unblocked available research task and froze the original universe, intervals, variants, costs and payment rule before outcomes. Added bounded immutable public capture with source identity, byte hashes and the existing error budget.
- Captured four new secondary archives and the current issuer page. December 2006's $1.494 total now has an explicit $1.133 ordinary/$0.361 capital-gain explanation; payment reconciliation continues. New archives expose a June 2009 ex-date disagreement that must be resolved before admission. No signals, outcomes, final or orders.

## 2026-10-01 — Ex-open income recognized before shared risk checks (`tradingbot-dk3`)

- Fixed a cross-consumer ordering risk: an admitted dividend could previously be absent when SPY or another runner first marked the ex-date price drop. Ordinary events can now be queued before ex-open; every account evidence check derives each strategy's prior ownership and recognizes the receivable before evaluating risk, even if the source strategy runner is offline.
- Unresolved pre-ex orders hold ownership, same-ex buys gain no entitlement, later direct income receipts reconcile without double counting, and late/conflicting scheduling is refused. Model income still cannot credit broker cash or duplicate funding.
- Validation: 29 shared-account tests pass, including an ex-open price drop that would incorrectly trigger the strategy kill without the admitted receivable, multiple owners, pending ownership, same-ex buys and receipt deduplication. No real income event, account opt-in or order was submitted.

## 2026-10-01 — C08 paper adapter integrated, source admission held (`tradingbot-5l3`)

- Implemented disabled preparation, separate activation, finite opening/closing execution, durable core/intent state, known-order reconciliation and explicit flat-hold resolution. Incomplete/unknown/risk-vetoed exits remain incidents; a terminal date cannot report success while exposure remains.
- Integrated the shared account fee/mark/cash evidence with C08 entitlement accounting and reviewed completion receipts. Modeled income never credits the broker cash book; nominal settlement labels cannot release sale proceeds. Actual fill/quote timing and separate modeled-cost metrics remain auditable.
- All **235 affected tests pass**, including **52 C08 checks / 23 runner integration cases**, existing connector/SPY regressions and shared-account accounting/migration checks. No actual paper order, account opt-in, funding change, final replay or risk-limit change. Full hold/promotion-risk decision, runbook and ledger receipt: `docs/research/33-c08-forward-integration.md` and `.json`.
- Committed runner **88e4cae** recorded failed source-admission **trial 5195**, with all performance metrics null and zero C08 orders/fills. Stored-only comparison confirms all seven historical finals, training3907, preparation4176, SPY3298, the one $140 book and C08's existing backtest/$140 allocation are unchanged. Every recorded dependency matches its committed bytes. Closed implementation bead `tradingbot-5l3`; conditional source repair/account activation/actual execution evidence is `tradingbot-ndl`, labelled `blocked:source-evidence`.

## 2026-10-01 — C05 source admission and durable state (`tradingbot-dk3`)

- Added bounded five-fund issuer/action/income and adjusted-close capture, independent IEX close comparison at the existing Amendment 21 audit bound, complete raw-receipt reconciliation and explicit dated source reviews. Empty vendor pages and unresolved dynamic issuer content cannot clear a fund; prior C08 USCF receipts can be reused with their original timestamps and hashes.
- Added C05-local causal action planning and typed JSON reactor state. Each close replaces all 127 observations on one coherent adjustment basis before delivering the actual day's close once; monthly targets, cash delays, attempted tags and forced exits survive restart without historical replay.
- Added a reviewed account-guard migration API that binds existing funding and running trial identities, acquires each consumer's process lock, and changes only the evidence opt-in. Active runners and changed reviews are refused. This API has not been run on the real paper account.
- Validation: 15 C05 source/state tests and 24 shared-account tests pass. The actual USCF dynamic notice scripts observed by the C08 agent returned HTTP 500, so issuer coverage remains held. No signals, actual orders, historical final or account allocation changed.

## 2026-10-01 — C08 state and first-seen source watch (`tradingbot-5l3`)

- Added a finite hash-bound phase calendar, exact Decimal reactor restart state and causal prior-close action plans. Release review must precede the scheduled open; archive vintage uncertainty remains disclosed without changing the original 14-day expiry or adding statistical gates.
- Added immutable EIA/issuer/broker/nontrade capture and explicit named review of all bytes and notice links. A watch expires after 24 hours; changed/unknown notices, calendar changes and unhandled nontrade activity hold admission. The original shared budget and evaluated reactor remain unchanged.
- The actual read-only watch archived September 30 EIA page/CSV/PDF and current methodology/errata, issuer product/news/notices and exhausted empty broker/nontrade queries. Issuer dynamic content remains unresolved: three exact linked scripts returned HTTP 500. Empty page templates cannot clear the watch. Twenty-five state/source tests pass; full runner tests also pass in isolated transactions, with final accounting/receipt work continuing.

## 2026-10-01 — SPY compatibility for shared forward accounting (`tradingbot-dk3`)

- The existing turn-of-month runner can now adopt the account evidence guard after explicit venue opt-in without changing its trial, schedule or sizing rule. It applies account-wide fees/income before risk evaluation, checks all exposures, and preserves known fills when fresh evidence is unavailable. The default behavior remains covered; no running account was opted in.
- Froze C05's first-minute opening and completed-close observation windows, durable-attempt rules, causal action schedule and promotion hold in `docs/research/34-c05-forward-runner.md`. Actual execution evidence remains future work after source and account admission.
- Validation: 21 SPY tests pass, including four guard-enabled integration cases and all 17 existing runner cases. SPY trial 3298, paper funding, historical finals and risk limits remain unchanged.

## 2026-10-01 — Shared forward paper evidence (`tradingbot-dk3`, C05/C08)

- Added an account-wide modeled fee/income/cash book over the existing Alpaca paper ledger. One dated fee accumulator spans strategies and partial fills; sale proceeds remain unavailable until documented completion and a subsequent regular open. Income receivables enter modeled P&L without fabricated fills or broker cash credits. No virtual funding is duplicated.
- Added an explicit quote capture and locked evidence callback with complete held/pending exposure coverage, stale/changed-source rejection, conservative fee reservations and frozen submission deadlines. The connector retains uncertain submissions and actual fills when evidence is unavailable. Account enforcement remains unactivated while C05/C08 and the existing SPY runner are integrated.
- Validation: 22 accounting and rollback-only Postgres integration checks pass, including unknown POST idempotency, partial-fill retention, settlement holidays, fee sharing, income timing and deadline/metadata races. No actual orders, historical replay, risk-limit or allocation changes.

## 2026-10-01 — Shared paper execution evidence hook (`tradingbot-5l3`)

- Added an optional venue-locked evidence guard that can tighten account/strategy cash ceilings, provide complete portfolio marks and apply modeled fee/income P&L before the unchanged risk triggers. A durable account opt-in prevents unconfigured consumers from sending new intents; no actual account opt-in occurs in this slice.
- Guard diagnostics persist with the reservation before POST; unknown outcomes and repeated request IDs retain existing behavior. Reconciliation preserves actual fills on evidence failure, while known-order cancellation remains available. Default connector and SPY regressions pass; nine new guard tests cover cash, restart, unknown POST, income/fee trigger ordering and failed-evidence fill preservation.

## 2026-10-01 — C08 durable execution contract (`tradingbot-5l3`)

- Atomically claimed the highest-priority ready bead and coordinated C08/C05 file ownership. Froze first-minute opening execution, after-close observation, missed/unknown-attempt behavior and finite terminal sessions before activation or orders.
- Specified durable unchanged-reactor state, causal EIA/issuer/broker review, conservative completed-settlement cash and account-wide fee/portfolio-risk integration around the existing shared Alpaca paper book. Historical final3910, running SPY trial3298, funding and PRD6 limits remain unchanged. Implementation and evidence work continue; no paper activation or replay.

## 2026-10-01 — C12 source admission fails before outcomes (`tradingbot-lna`)

- Audited 74 immutable public captures, including 14 original BLS release PDFs, FRASER issue inventories, original OMB schedules and 27 Fed notices. Preserved original event identities, canceled October 2025 denominators, missing next-release announcements, Good Friday and same-day revision ambiguity. Current revised calendars cannot establish prior decision-time knowledge; no date/interval/variant substitution.
- Implemented reproducible source-only extraction and a failed-trial recorder with exact split/configuration checks. Complete BLS revision chronology remains unresolved; full Fed exclusion reconciliation, SPY share-action admission and replay stop at that gate. Both variants, four training cases and controls remain unattempted. P&L, fees, trades, drawdown, regimes and luck are null; no selection, final, promotion, allocation or order.
- Implementation `07c02e7` recorded source trial **4591** / strategy **7170** at idea. Stored-only verification confirms one idempotent null-metric trial, zero C12 finals and all seven prior final rows unchanged. **28 focused checks pass**. Report/checklist: `docs/research/32-c12-source-audit.md`. Conditional new-evidence repair **`tradingbot-qb5`** is `blocked:source-evidence`; closed research bead `tradingbot-lna` under documented failed-admission acceptance. All PRD6 limits remain unchanged.

## 2026-10-01 — C11 source audit fails before outcomes (`tradingbot-e76`)

- Rechecked the exact SPY open/close amendment, 83 issuer payments, 15 archived public responses and the exhausted 40-record all-type broker action query. Known earlier cash omissions prevent treating an empty noncash response as full share-action evidence; processing-date bounds and late events remain explicit.
- Visually reviewed Cboe 2024–2026 standard expirations and reconciled their overlap with OCC's current API. Preserved December 2015 SPY's grandfathered Saturday legal expiry, holiday adjustments and legacy 404s. Full historical/advance calendar provenance remains incomplete. Fractional CLS is unsupported; the close variant lacks execution evidence.
- Added reproducible source checks, immutable receipt, idempotent failed-trial recorder and complete hold/account-risk decision in `docs/research/31-c11-source-audit.md`. Both variants and all four training cases remain unattempted; returns/drawdown/regimes/luck are null and no final, allocation, order or promotion occurs. All **35 affected checks pass**, including 25 C11 checks. Risk limits and source/variant boundaries are unchanged; ledger receipt follows the committed audit.
- Committed audit `ebf79b9` recorded failed source trial **4589** (strategy 7168). Stored-only verification confirms one idempotent null-metric trial, zero C11 orders/fills/finals, $0 allocation and unchanged original seven final rows. Closed the research attempt under its explicit source-failure acceptance; conditional repair **`tradingbot-jfv`** is `blocked:source-evidence`.

## 2026-10-01 — C12 bounded calendar archive (`tradingbot-lna`)

- Preserved BLS index/notice access failures, original BLS PDFs, free FRASER issue indexes and revised-calendar copy, OMB original schedules/publication history, and Fed advance schedules/revisions. Every raw response is immutable and hash-bound; network failures remain distinct from HTTP success.
- Added ordinary public-archive transport, response/disk bounds and error-budget checks. Original release dates survive later postponements/cancellations; contemporary revision availability still fails admission. No C12 prices, outcomes, final or orders.

## 2026-10-01 — C11 expiration-calendar source preparation (`tradingbot-e76`)

- Archived 15 free primary responses: current Cboe/OCC calendars and API, dated 2013 expiration transition, 2022 weekday expansion, broker order/action documentation and two retained legacy-calendar 404s. Added bounded GET-only capture and immutable checksums; four capture/pagination checks pass.
- Preserved the exact SPY open/close amendment and frozen C11 interval/variants. Full causal calendar and share-action coverage remain unproven; Alpaca's fractional order table rejects closing-auction TIF. An exhausted all-type SPY action query contains 40 cash records, not full-history evidence. No C11 strategy outcomes, final, allocation or risk-limit change.

## 2026-10-01 — C12 causal announcement-source preparation (`tradingbot-lna`)

- Claimed C12 after resolving a simultaneous C11 claim with OrangeCove; C11 remains theirs. Frozen C12's Employment Situation/CPI variants, prior-release announcement requirement, fixed exit despite later postponements, advance FOMC exclusions and unchanged 2006–2026 interval/risk/cost rules before any outcomes.
- Added bounded immutable official-calendar capture, exact archive-link selection and source-identity checks. A current revised release calendar cannot supply causal schedules; exceptional cancellations/revisions require dated primary evidence. No C12 market return, selection, final, promotion or order.

## 2026-10-01 — C09 source admission fails before outcomes (`tradingbot-b8y`)

- Completed dated offering/original-CUSIP/occurrence reconciliation for all 242 Treasury events and hash-bound review of 23 special announcements. Retained the December 2020 PDF 404 and admitted its official linked XML identity/date/13:02 release evidence. Emergency and contingency auctions remain included; no auction result metric selects a signal.
- Full IEF noncash-action coverage remains unresolved despite 5,218 valid sessions, 248 reconciled issuer cash distributions and 2,701 SIP/1,553 IEX raw open/close overlaps within the fixed 1% bound. The broker's 127 IEF action rows omit 121 known pre-2016 payments plus August 2016, so an empty noncash response cannot prove full action coverage. No strategy or interval substitution.
- Implementation `780b2c2`, recorded under HEAD `5f0a104`, produced failed source trial **4585** with null performance metrics; both hold variants and all four cost cases remain unattempted. Stored-only verification confirms idempotence, zero C09 finals and all seven original final rows unchanged. No P&L, promotion, allocation, order or PRD6 change. **61 affected checks pass**, including 40 C09 checks. Report/checklist: `docs/research/29-c09-source-audit.md`; conditional new-evidence repair **`tradingbot-5hl`** is `blocked:source-evidence`.

## 2026-10-01 — C10 source admission fails before outcomes (`tradingbot-eu4`)

- Audited all 5,218 frozen TLT Yahoo sessions, 248 typed issuer distributions, 1,553 independent raw IEX opens/closes and an exhausted 127-record all-type action query. Preserved Yahoo's missing 2012-11-01 issuer dividend and Alpaca's missing 2016-08-01 event; incomplete pre-2016/action history cannot establish full share-action admission. Stooq returned verification HTML, not prices. No source or interval substitution.
- Archived dated Sandy closure/reopening, NYSE baseline and BlackRock listing notices, plus failed primary-document retrievals. Reused primary calendar PDFs by hash and recorded the distinction between originally announced exchange sessions, realized sessions and settlement eligibility. Full causal calendar admission remains unfinished after the source gate failed.
- Added reproducible source-only checks, an idempotent failed-trial recorder and a complete hold/account-risk decision in `docs/research/30-c10-source-audit.md`. Both variants and all four training cases remain unattempted; all return metrics are null, no winner/final/promotion/order/allocation occurs and risk limits are unchanged. Validation: all 20 focused capture, source-integrity and transactional ledger checks pass.
- Committed audit `66e9f9f` appended failed source trial **4584**, verified idempotent with null metrics and zero C10 finals; seven existing final rows are unchanged. Closed `tradingbot-eu4` with conditional new-evidence repair **`tradingbot-wdr`**.

## 2026-10-01 — C09 auction-source preparation (`tradingbot-b8y`)

- Added bounded immutable Treasury capture and strict dated-notice/CUSIP parsing for the frozen IEF auction-recovery candidate. Captured 242 in-interval offerings, 2005 lineage documents and 23 distinct special announcements, retaining emergency and contingency auctions. Verified all offering dates and original-10-year lineages before strategy outcomes.
- Rechecked IEF's 5,218 sessions, 248 issuer cash payments and fixed-tolerance raw open/close overlaps. Identified incomplete independent share-action history and preserved a missing Treasury occurrence PDF for follow-up. Source admission remains closed; no strategy return, training case, final, allocation or risk-limit change.
- Validation: 18 focused capture/parser integrity checks pass. Source procedure and exact unresolved scope are documented in `docs/research/29-c09-source-plan.md`.

## 2026-10-01 — C10 month-end source preparation (`tradingbot-eu4`)

- Claimed the highest-priority unassigned ready research bead and froze dedicated TLT price/distribution/action/calendar admission before outcomes. Preserved the two third/fifth-last announced-session entry rules, first-next-month exit, 2006–2026 source interval, elapsed 70/30 split and unchanged sizing/risk limits.
- Added bounded immutable public-source and existing-key read-only IEX/action capture. Identified the causal calendar distinction: Sandy closures must delay the original planned entries, and the late Ford closure delays the originally planned January 2007 exit. Existing settlement calendars alone cannot establish those announced exchange schedules. No strategy signal, return, final or promotion was computed.

## 2026-10-01 — C05 forward preparation (`tradingbot-ggg`)

- Added GET-only, account-bound five-ETF readiness capture with immutable source/quote/calendar/action/nontrade receipts, complete inventory validation and the existing five-errors/minute halt. Preserves training 3959 and consumed final 3964 through stored-row checks; the explicit recorder can append only a failed preparation with zero trades and null result metrics.
- Added tested ordinary-distribution entitlement/receivable/payable helpers, distinct from verified broker cash, and the conservative post-completion trade-cash bridge. Preserved the evaluated reactor, five 19% sleeves, monthly 126-session rule, fee scenario and risk limits. Documented source/action admission, shared cash, full-portfolio marks, durable execution and actual fill/credit gaps in `docs/research/27-c05-forward-readiness.md`; decision remains hold before ordering.
- Validation: 132 affected readiness/reactor/replay/blackout/paper-connector checks pass; all 44 C05 readiness checks pass after five additional raw-source reconciliation cases. Independent read-only review found and verified fixes for generator cash accounting, premarket quotes, observed-vintage timing and receipt bindings. No strategy replay, broker order, promotion, allocation, account or key change.
- Initial immutable capture passed source/account/asset access but held stale UNG/DBA quotes. Its pre-record audit exposed Decimal-versus-JSON equality in the stored training luck value; normalized that metadata to an exact string with a regression check. No trial was appended by the failed audit, and original historical rows are unchanged. A new committed capture follows the fix; the first receipt remains preserved.
- Committed capture `adc52f4` verifies the existing account, five fractional assets, 127 completed closes per ETF, one historical DBA action record and no C05 nontrade credits. Its quotes pass freshness, but USO is about 242 bp wide; the retained first capture fails stale UNG/DBA marks. Appended failed preparation **4579**, zero trades and null results. Stored-only audit verifies 36 children, unchanged 3959/3964 rows, one canonical final spend and the unchanged shared $140 paper book. All 45 final readiness checks pass. Decision stays hold with $0 activated; remaining durable runner, income/cash/risk integration and actual execution evidence are tracked in **`tradingbot-dk3`**.

## 2026-10-01 — Family holdout reuse guard (`tradingbot-u1h`)

- Closed the version-reset loophole: final admission now binds stable research families and refuses overlapping prior source/training coverage across code/parameter, dataset, row and reactor changes. New families require a stable declaration; candidate amendments retain their root family. Concurrent admissions, failure/interruption and caller rollback preserve the allowance and durable refusal incidents.
- Applied migration `bcf10a202601`, adding immutable alias/exposure receipts and backfilling all seven existing finals from declared dataset coverage. Stored-only before/after SHA-256 checks confirm original trials 3281/3282/3319/3910/3964/3969/4066 remain byte-identical. Untracked legacy admissions fail closed; no real holdout replay occurred.
- Added synthetic attack, overlap, concurrency, migration and rollback coverage, and updated C01/longshot synthetic cleanup for the new foreign key. Documented stable lineage declarations, caller-owned training limitations and the fresh-window/forward-paper route. No risk limit, promotion, account, key, capital or order changed.

- Validation: all 152 affected regression checks pass. Alembic is at the new head; post-test audit leaves exactly seven original finals and matching receipts, with all row hashes unchanged.

## 2026-10-01 — C08 forward preparation (`tradingbot-gx2`)

- Added immutable, read-only C08 operational capture using existing Alpaca paper access and dated primary EIA releases. Binds profitable training 3907 and consumed final 3910 without replay; records fresh IEX quotes, fractional asset status, raw action pages, shared cash state and first-observed publication timing. The separate ledger command records only failed preparation, idempotently, without a trading result or strategy promotion.
- Implemented and tested the conservative post-completion cash bridge. The current shared paper connector spends sale proceeds sooner than the historical C08 rule, so it cannot be adopted silently. The initial capture found $140 shared virtual cash, no paper orders/fills/positions and existing SPY trial 3298; USO/action/calendar access works, but empty action data is not advance-notice proof and no C08 opening fills exist. Documented a hold-before-ordering decision and the concrete remaining execution contract in `docs/research/26-c08-forward-readiness.md`.
- Bound the sanitized account probe to the existing cash-book fingerprint and connector account checks; a different paper account is reported as failed evidence without printing its identity.
- Validation: 91 focused checks pass; 27 readiness checks pass after the path-year and account-identity checks. Repaired the C08 synthetic final-guard test's empty-database assumption without changing the guard or historical evidence. No reactor, historical final, risk limit, account, key, capital or broker order changed. Committed capture from `4e0ad4e` completed with no probe errors and confirmed the paper account matches the cash book; final IEX quote was fresh but about 236 bp wide, which is not proof of the historical 10 bp execution cost. Appended failed preparation trial **4176** (zero trades, null result metrics); read-only audit confirms original 3907/3910 rows unchanged and one final only. Published exact source receipts and risk/readiness decision; implementation and future execution evidence are tracked in **`tradingbot-5l3`**.

## 2026-10-01 — Candidate batch 2 preregistration (`tradingbot-5n1`)

- Froze six new candidate families before new outcome downloads: IEF auction recovery, TLT month-end demand, SPY standard expiration week, SPY scheduled employment/CPI risk, earnings long call/put pairs, and conditional cash-secured cheap-stock entry. Recorded exact universes, entry/exit/sizing rules, two variants each, source intervals and elapsed-time 70/30 boundaries, with Amendment 21 as the default.
- Saved primary-source summaries, proxy/selection limitations, full account-risk review and one follow-up bead per candidate. Options start with source/capital/model feasibility: existing indicative data does not establish historical BBO or point-in-time chains, and a whole cash-secured contract may not fit $140. No strategy P&L, final holdout, real allocation, permission change or order occurred.
- Validation checks document/index consistency, the shipped `HoldoutSplit` boundaries, six distinct follow-up beads and source/link integrity. Independent read-only reviews cover the calendar rules and feasibility assumptions; no strategy tests or market-data requests are needed for this documentation slice.

## 2026-10-01 — C07 training complete, no eligible winner (`tradingbot-pdw`)

- Recorded all six preregistered weekly-reversal training cases: 4031, 4043, 4050, 4057, 4064 and 4065. Four top-three cases hit unchanged risk kills and failed closed before the 2016 XLF action; the 10 bp top-one case lost $56.01 and was killed flat. The only clean full execution, top-one at 5 bp, lost $25.93 on $140 virtual cash. No winner, final holdout, paper/live promotion or risk-limit change.
- Published the report, frozen null selection and independent stored-evidence audit: 7,666 fills and 36,186 open/close marks reconcile across all six runs. Original failed source strategy 6080 / trial 3548 remain byte-identical. The selection review export removes only duplicate full mark sequences retained in the hash-bound archives and database.
- Validation: 38 focused source/reactor/replay/audit tests passed before outcomes; all six stored-run audits pass afterward. Reported fees, trades, marked drawdowns, regimes, dependence-aware p-values, risk-vetoed inventory and blackout counts; retained every failed attempt and closed the research bead without consuming the final.

## 2026-10-01 — Consumed-final regression fixture

- Corrected the synthetic C05 family-guard test to expect the earliest consumed final, including a real final already present in the database. All 10 C05 replay tests pass. Strategy/runtime code and consumed final 3964 are unchanged; no historical replay occurred.

## 2026-10-01 — C07 replay preparation (`tradingbot-pdw`)

- Added the fixed weekly sector-reversal reactor and source-bound replay through the shared risk engine, ledger and exact fee model. Weekly targets, mandatory exits, settlement delays, action blackouts and payable dividend receivables follow the preregistration; all risk limits remain unchanged.
- Added durable attempt/final guards and an independent stored-evidence auditor, including partial failed runs and simultaneous ETF distributions. Preserved original failed strategy/trial rows. Source and synthetic checks precede the six fixed training cases; no C07 outcome or final holdout has been consumed at this boundary.
- Validation: all 38 focused source, blackout, reactor, replay and independent-audit checks pass on synthetic or source-only data.

## 2026-10-01 — C03/C04 source re-admission (`tradingbot-y2d`)

- Claimed the next ready source-repair bead and froze a pre-outcome amendment using the admitted SPY open/close bundle. C03 still requires payment-date, share-action and independent-price evidence for its remaining ETFs.
- Preserved full-row hashes for original failed source trials 3516/3377. Fixed universes, variants, date boundaries, once-only final policy and §6 limits remain unchanged; no new strategy outcome has been inspected.
- C04 source re-admission passes on the frozen 5,218-session / 83-distribution SPY bundle. Added its pure full-month inverse-variance reactor, source-bound shared-risk/ledger replay, durable configuration/final guards and written account-risk review. Synthetic checks cover sample variance, partition warm-up, dividend entitlement, cash/ledger reconciliation, terminal exits and interruption/reuse refusal; real training remains pending this preparation commit.
- Validation: 30 focused C04/source checks passed. Broader checks found an existing C05 test expecting its synthetic final instead of the correctly refused earlier consumed real final; notified its owner, with no execution or consumed-trial changes.
- C04 v1 training trials 4016–4021 completed with positive modeled net but 65–100 buy rejections each. The unchanged risk cap prices the entire position at the rounded limit, while requested additions used a reference-mid gap. No configuration qualified and no final was consumed. Preserved all six full-row hashes/artifacts and recorded incident 974.
- Added a separately versioned C04 sizing repair that clips buys to the existing $140 cap at the rounded limit; sources, signals, parameters and §6 remain fixed. Eleven synthetic v2 checks cover the original cap repro, full-slot compounded equity, cash/dividend reconciliation and final admission. Original v1 code/trials remain immutable; v2 training follows this commit.
- Adjusted the synthetic full-slot fixture to supply a large documented test distribution: the earlier fixture correctly retained its cash reserve and never reached a clipped buy. All 11 v2 checks now pass, including an exercised clip and zero risk rejects; v2 real training remains unattempted until this follow-up is committed.
- C04 v2 training trials 4058–4063 completed with zero rejects and flat endings. The fixed best-positive-10-bp rule selects c=0.04 (trial 4063): +$181.451416 net, $53.097999 maximum marked drawdown (30.90% of peak), one completed lifecycle, null luck p-value. The stored-ledger audit verifies all buys at the rounded-limit cap, fees/partitions/artifacts and unchanged original/v1 row hashes. Selection is frozen for one final; no promotion given near-budget drawdown, prior SPY inspection and unvalidated forward execution.
- C04 final 4066 completed once at the frozen 10 bp choice: +$121.931558 net, $38.094083 maximum marked drawdown (20.26%), 67 fills, one lifecycle, zero rejects/halts, flat inventory and null luck estimate. Stored-only audit reconciles all seven v2 runs' fees, source-open costs, ex-date ownership, cash/receivables, cap/bounds and immutable prior rows; exactly one family final exists. Published regime/benchmark and account-risk review; no promotion or real allocation.
- C03 re-audit validates IEF/EFA issuer payments and reconciles all seven EFA/VNQ independent-price breaches to primary Arca prints. VNQ's current issuer history omits 43 older ex-dates; secondary records leave five dates without dual coverage and conflict on December 2006's total. Source remains failed before any C03 signal, ranking, return or holdout. Four parser checks pass; all archives, original failed trials, time boundaries and §6 limits remain intact.
- Recorded C03 source-failure trial 4067 under committed audit 904e3ae. Final verification: 55 focused source/reactor/replay checks pass, including both C04 versions refusing family reuse after real final 4066 exists. C04 final audit is stored-only; no consumed final was replayed. Original failed source rows and all v1/v2 training hashes remain intact.
- Closed `tradingbot-y2d` with C04's admitted, consumed and audited final plus C03's honest source-failure result. Created P3 `tradingbot-2wh` for the five specifically unresolved older VNQ distributions and remaining full-universe action admission; no C03 holdout or outcome was consumed. All work is pushed and research-only.

## 2026-09-29

### Project kickoff
- Grilling session completed; all decisions captured in `PRD.md`.
- Researched: the Jev/TypeSafe claims (unproven for trading), which retail venues are open from the UK vs the US, papers on hedge fund and prediction markets, and a broad survey of structural edges outside sports.
- First batch chosen: Kalshi longshot bias, liquidity rewards (Kalshi + PM US), SPX ranges vs options, weather settlement mechanics, end-of-day LETF flow, turn of the month, promotions. X mention-spike study runs on paper.
- Stack: Python with official SDKs, Postgres + TimescaleDB, hosted on the local Mac.

### Handoff package
- Saved the research reports to `docs/research/`, added `AGENTS.md` (start-here guide plus ntm work split) and `CLAUDE.md` (points to AGENTS.md).
- Zipped the repo so work can continue on another laptop.

### Set up on the new laptop
- Imported the handoff repo to `~/Documents/tradingbot` and created a private GitHub remote.
- **Kalshi blocked:** the owner could not set up an account.
  - Polymarket US becomes the first live prediction venue.
  - Kalshi history is kept for research only.
  - #3 and #4 are deferred.
  - Updated PRD §5 and AGENTS.md.
- Added `.env.example`. `.env` holds the Polymarket US, Alpaca paper and X keys; the Alpaca paper and X keys were checked and work.
- Tooling added:
  - Python 3.12 via uv.
  - Postgres 18 + TimescaleDB (the Homebrew TimescaleDB formula requires PG18).
  - launchd jobs for caffeinate, the watchdog, the nightly pg_dump and the daily autonomous session.
  - Beads seeded from the build order.
  - ntm swarm (Claude + Codex).

## 2026-09-30

### Equity source repair evidence (`tradingbot-900`)
- Archived the 2006 SPY prospectus supporting the disputed July31 payment and the issuer annual report identifying XLF's exact XLRE distribution. Preserved original sources and failed audits.
- Raw primary-exchange closing prints reconcile all three SPY outlier prices; added rejection checks for conflicting or unsuitable auction evidence. Fifteen source/calendar checks passed.
- Frozen source receipt and partial amendment; full settlement calendar and fractional distribution cash remain unresolved. No dataset admission, return analysis or holdout replay.

### C01 admission repair and failed evidence audit (`tradingbot-bbw`)
- Claimed the next ready P1. Final admission now commits before lazy feed loading/simulation, and a consumed candidate/dataset returns stored facts even when a repair changes its source hash. Failed/interrupted attempts remain consumed; stored exports never invent absent trade details or overwrite existing files.
- Quarantined C01's real-data CLI as an archive reader. Withdrew the original PRD §4 PASS in the report/JSON while retaining every numeric result and the prior verdict. The audit confirms shared RiskEngine/Ledger bypass, compounded orders above the $140 slot (up to $414.96 training/$186.07 final), proxy dividend/settlement dates, inconsistent terminal metrics, future dividends in benchmark drawdown and incomplete source checks/provenance. No historical replay, deletion, new strategy variant or promotion.
- Validation: 26 synthetic C01/holdout checks pass, including independent-connection proof of pre-feed admission, repeated/changed-version invocation, admission failure, interruption/caller rollback, legacy CLI refusal and read-only export. All 17 C01 checks passed again after making the execution receipt distinguish first simulation from stored export.
- Repair `0f08a9b` is pushed. Recorded incident 920 and strategy 5080's failed-evidence annotation; original trials 3313–3319 match the pre-audit full-row SHA-256 exactly. Allocation remains $140 and status remains `backtest`. The real CLI reads final 3319 without replay; the machine-readable audit receipt preserves both hashes and the original artifact fingerprint.

### C02 sector momentum source audit (`tradingbot-7l3`)
- Captured the fixed nine Yahoo ETF histories: 5,218 complete sessions each, no null/session gaps. Stopped before any rankings or returns: the Alpaca calendar applies a two-day date in July 2017 before the documented T+2 transition, and Yahoo encodes XLF's actual XLRE in-kind distribution as an approximate split.
- Created and claimed shared data-repair bead `tradingbot-900` so subsequent candidates address these prerequisites before consuming any outcomes. Failed C02 data-audit trial: 3491.
- Added a conservative settlement-calendar constraint validator with six passing tests. It proves dates only from consistent source observations and rejects ambiguous or contradictory dates; no calendar was invented or admitted to a replay. Recorded the failed source attempt; all six training cases and the holdout remain unattempted.

### C04 inverse-variance SPY source audit (`tradingbot-wri`)
- Archived actual issuer distribution dates and free Alpaca calendar/IEX overlap; Yahoo's 5,218 sessions and 83 dividend ex-dates reconcile, but the issuer's June 2006 payment date precedes its record date. Historical native settlement dates also do not provide the preregistered T+1 counterfactual; daily-close basis differences remain unresolved.
- Stopped at the required data gate, with raw hashes and failed-audit ledger evidence. No candidate return calculations, training configurations, holdout attempt or promotion; source bounds and risk limits unchanged. Added strict, tested issuer-workbook parsing for a future documented data repair.
- Reloaded the already-authorized TOM paper LaunchAgent after NavyLantern's committed aggregate equity-cap repair (`1deb744`); it remains trial 3298, awaiting its first scheduled cycle.

### AI forward-paper harness (`tradingbot-tph`)
- Claimed the next ready engine bead. Corrected Alpaca paper's aggregate held-plus-pending exposure check to call the existing owner-approved asset-class cap function; it still used the prediction-market $25 constant after `h2i`. Pending buys remain aggregated and settled-cash/strategy allocation checks remain in force. No risk-limit values changed.
- Validation: 55 connector and scheduled TOM forward checks pass, including a $90 equity order within a $100 fixture slot and rejection when aggregate pending exposure exceeds the slot. No broker orders or paper activation in this slice.
- Added a forward-only `AIForwardStrategy` harness over the existing Alpaca connector, RiskEngine and Ledger, with frozen code/model/prompt identity, strict bounded JSON decisions, news-as-data observations, durable provider receipts and restart-safe order reconciliation. Real elapsed observation time, completed round trips, costs, drawdown, monthly P&L and descriptive luck odds feed the 7-day AND 30-trade profitable-after-costs review gate. Known model costs reduce paper cash and feed unchanged loss limits; unknown costs and interrupted decisions prevent qualification.
- Added explicit preparation/run/status/finish commands and operating guidance in `docs/research/10-ai-forward-harness.md`. Preparation requires an already reviewed paper strategy, cash book and completed loss-risk record; no provider SDK, keys, account, capital, model calls, strategy activation or automatic promotion was added. Validation: 36 AI checks plus 94 existing connector/forward/risk/interface checks pass (129 in the combined run; one corrected cancellation-status fixture passed on focused rerun). The existing SDK deprecation warning remains.
- Harness committed and pushed as `927f3e4`; bead closed. Separately confirmed C01's final simulator runs before `claim_final` and its reuse handler publishes recomputed results. Filed P1 `tradingbot-bbw` for repair and preregistration-fidelity audit, and notified the research agents. Existing consumed finals remain untouched; no C01 replay or promotion performed.

### Futures broker comparison (`tradingbot-k1e`)
- Compared IBKR, tastytrade, NinjaTrader, AMP and Schwab for the owner's UK-tax/US-residency profile, Python integration, simulation, history, fees and micro-contract margins in `docs/research/08-futures-broker.md`. Recommend IBKR Pro conditionally for a future approved integration; its documented funding/data requirements do not meet today's unfunded/$0-data plan.
- Recorded current primary-source evidence, access gaps and a typed margin snapshot. Distinguished base commissions from all-in costs, initial/maintenance/day margin, tastytrade's synthetic sandbox fills, NinjaTrader's current REST API, and AMP's paid API/sim routes. Free-data commodity ETF research remains the immediate path; no account, keys, funding, subscription, strategy trial, holdout or order was created, and no §6 limit changed.
- Validation: checked reference/local links, JSON/report margin agreement, round-trip arithmetic and contract sensitivities; reviewed source caveats and documentation diff. No execution code changed.

### Slot-sized #6 revalidation preparation (`tradingbot-gat`)
- Training is complete on the first 70% only: trials 3277/3279/3280 earn $63.483911 / $55.885888 / $43.158389 at 2/5/10 bp, each with 90 round trips and zero rejected orders. Diagnostic 3278 measures a 45.08 bp mean advantage over duration-matched non-TOM windows in training. The primary was fixed at 2 bp before evaluation; exact versions and artifact hashes are frozen in `09-turn-of-month-slot-selection.json` before either final attempt. Runtime/artifact writes also retain the active disk-budget gates.
- Claimed the next ready bead after completing `zgn`; `h2i` and `zgn` dependencies are closed. Preregistered the fixed $140 maximum / settled-cash-sized TOM rule, 1-cent entry fee reserve, three training cost scenarios, one preselected 2 bp final holdout, and matched-month five/six-session random-window drift diagnostics. Exact source bounds/cutoff and prior full-sample contamination are explicit in `docs/research/09-turn-of-month-slot-plan.md`.
- Added an optional read-only available-cash context shared by equity research and TOM forward adapters; the same TOM reactor now supports slot sizing that shrinks after losses and parks gains above the slot. Existing $24.90 experiments retain their parameters. Dividend-adjusted controls are logged nonexecution diagnostics, use fixed seed/10,000 draws, and consume their holdout through the same durable enforcement. Entry regime reporting uses only prior 200-session closes; research execution dependency hashes cover fee/data/calendar helpers.
- Validation: 39 strategy, research, forward and holdout checks pass, including loss-driven sizing, modeled fee reserves, flat-market controls, planted calendar jumps, deterministic samples and missing-control failure. No real-data strategy returns, holdout attempts, orders, paper activation, new capital or §6 edits in this preparation slice.

### Paper feed ordering repair (`tradingbot-27p`)
- Took the next ready P1 after closing the strategy sweep. The live paper reader now returns only the earliest global quote/trade batch from one database snapshot, preserving both committed channel cursors and the existing trade-before-quote tie order. A later trade can no longer skip an earlier cancellation quote and create a false fill.
- Added regressions for asymmetric backlogs, page sizes 1/3/500, equal timestamps, filters and snapshot consistency; the original false-fill repro now consumes the later trade and passes. Validation: 11 targeted checks; affected paper/review/rewards suite **59 passed, 1 existing blackout-timer xfail**. Code `f13c952` and closure `1d6d5ec` are pushed. No §6 limits, execution rules, venue activation or real orders changed.

### Alpaca candidate sweep (`tradingbot-cfe`)
- Ranked eight free-data candidates in `docs/research/07-candidate-shortlist.md` against the intake rubric: SPY trend, sector/cross-asset momentum, cash-capped inverse variance, commodity ETF trend, month-end underweight flows, sector reversal and USO inventory scarcity. Saved primary-source notes and a read-only asset snapshot: all 18 selected ETFs currently report tradable/fractionable on Alpaca paper.
- Created one P2 `strategy,sweep` bead per candidate, each depending on `tradingbot-zgn`: `8yz`, `7l3`, `wn9`, `wri`, `9ri`, `kc4`, `a9d`, `m2d`. Fixed hypotheses, universes, entry/exit, sizing, settlement, 23 signal variants / 46 training cost configurations, source intervals and exact 70/30 time cutoffs before return inspection. Each family selects one training-profitable frozen variant for one final 10 bp holdout run.
- Recorded data failure gates, prior-inspection contamination, drawdown/regime/luck reporting and account-risk decisions. Parked options, AI, COT and other incomplete ideas with concrete reasons; no duplicate #5/#6 strategy, paid data, price backtest, holdout consumption, capital change or order. No §6 or execution code changes in this slice.

### Locked chronological holdout (`tradingbot-zgn`)
- Enforced the owner-approved PRD §4 split in the shared backtester and its equity adapter: full dataset bounds are locked, normal replays reject events and settlement labels on/after the 70% time cutoff, and every new replay records its partition and exact code/parameter version.
- Final evaluation claims a durable trial before consuming the feed. A unique index and transaction lock permit one attempt per version across concurrent workers, research row IDs and run/dataset names; reuse is refused and committed to incidents even if the caller rolls back. Failed/interrupted attempts remain consumed. Added migration `abce7d924010` and applied it locally; Alembic reports no drift.
- Adapted TOM, LETF and longshot callers to partition their feeds and require one explicitly chosen final variant. Complete calendar cycles stay within one partition, and longshot scoring requires observed resolution times. Preserved historical trials and documented that previously viewed history is not fresh holdout evidence. No actual strategy holdout or capital was used in validation.
- Validation: 41 backtester/equity integration checks passed, then 17 focused checks passed after the execution-class hash and renamed-strategy/dataset regression were added. All nine holdout checks passed again after making Decimal parameter fingerprints lossless. Synthetic cases cover cutoff equality, settlement leakage, locked bounds, failures/rollback, durable incidents, concurrency and changed parameters. An earlier parallel test invocation hit a shared venue-seeding deadlock; a fresh sequential run passed.

- **Daily marked-equity repair (`tradingbot-1oh`):** daily P&L now measures cash flows plus end inventory value minus its UTC-start value, including overnight, partially/fully closed, short/flipped and unattributed holdings. Prior-day gains/losses are not counted again on sale; fee rebates, multipliers, dated marks, historical queries and UTC halt days are covered. No limit constants or cap-selection logic edited. Validation: 188 affected integration tests pass (2 remaining review xfails), plus 13 dedicated accounting/repro tests. Fixed synthetic FX fixture isolation after the actual paper ECB import. Trial 2344 remains prepared and unactivated: the subsequent owner-directed `gat` holdout/allocation re-run governs continuation.

- **#6 paper trial prepared:** code `eba9e77`, trial **2344**, $140 simulated cash / $24.90 entries, exact future exchange calendar and prior-day ECB FX. No orders or real capital added. Launchd remains unloaded pending `tradingbot-1oh`; closed preparation bead `u6a` and claimed that next ready repair. Focused suite: 52 passed; broader suite: 501 passed, 6 skipped, 3 known xfails.

- **Primary #6 forward preparation (`tradingbot-u6a`):** added a scheduled paper-only Alpaca runner using the unchanged `TurnOfMonth` reactor, existing connector, ledger and risk engine. Durable daily claims prevent restart/unknown-POST duplicates; owned partial fills determine exits, missed windows never catch up, residual exits are incidents. Added New York calendar/early-close handling, dated ECB FX, separate modeled-fee equity/drawdown, launchd job and promotion/risk record. Read-only calendar/FX probe succeeded: first entry October 27, exit November 4. The initial 52 focused tests pass; paper activation awaits the confirmed shared overnight daily-PnL repair (`1oh`). Connector fixtures now isolate the Alpaca venue inside their rollback transaction so a prepared cash book does not contaminate tests.

### Bounded full-year history capture (`tradingbot-oma`, first slice)
- Read known Parquet pages as individual files, avoiding dataset discovery for every validated archive page. A 100-page / 80.2-million-character PM read benchmark fell from 6.55 to 1.26 seconds with identical content length; 23 archive/loader/audit checks pass, including checksums, schema, chain validation and transactional reruns. Existing workers remain resumable; this changes no selection, record or strategy code.
- Kept large venue-level event archives out of ordinary catalog/tape identity reads; auxiliary-document imports still load and lock their evidence. Twelve loader integration checks pass. All 436 selected catalog pages have now committed; restarting the resumable importer with the lighter read path before the multi-million-row tape phase.
- Batched page reference lookups and avoided copying already-imported snapshots. A profiled 3,000-reference rerun fell from 68.8 seconds / 5,070 ORM executions to 12.2 seconds / 72 executions; both added zero snapshots. Page transactions, row locks, source ranking and rollback remain unchanged. All 82 data tests pass against Postgres, including repeated newer/older entities within one page. PM tape capture is complete: 201 exhausted requests, 2,754 pages and 2,657,334 source records (~240 MB compressed); Kalshi capture and DB loading continue.
- Replaced redundant capture tree scans with cross-process, fsynced write reservations: every batch still scans all `data/`, active writes rescan within 30 seconds/128 reservations, and every fetch/write checks real free space. DB loading scans each 32-page batch and checks free space around each transaction. The 20 GB / 30 GB limits are unchanged; completed archives remain resumable. Added request audits that distinguish empty, partial, missing and zero-volume-skipped tapes, verify empty Bitcoin catalog dates, and count missing outcome mappings separately from missing payouts. Validation: 23 archive/disk/orchestration/loader checks passed, followed by all five loader/audit checks including the two new regressions; capture/loading remain in progress.
- Added a cohort-scoped page-atomic loader, complete-request validation, incremental missing-job reporting, disk-gated chunk compression and monthly/category database audits. Terminal PM resolution-event timestamps now override scheduled catalog closes without inventing oracle payouts; later incomplete catalogs cannot erase them. Catalog/tape imports no longer hold unrelated venue-row locks. All 74 data tests pass against local Postgres, including settlement-time preservation. Capture remains in progress; all 201 resolution requests are complete.
- Migrated only public `trades.price` / `trades.size` to lossless NUMERIC and enabled daily Timescale compression policies for tape/quotes older than seven days. Execution/accounting column types and §6 stay unchanged. A rollback-only integration check verifies >18-place source decimals survive compression and deduplicated reruns. All 69 data tests pass with DB checks enabled; Alembic reports no drift. PM trade queries group up to 20 conditions per the official v2 contract, preserving the fixed cohort.
- Fixed a thirteen-month non-sports cohort before return analysis: Kalshi NYC weather, S&P close and daily 17:00 Bitcoin ranges; international PM NYC weather and daily Bitcoin direction. Added resumable bounded orchestration, source-based series categories and gates that keep all `data/` below 20 GB and preserve at least 30 GB free plus write headroom.
- Verified the current official PM v2 condition feed serves three years and documents taker-only fills. A September 2025 condition returned 42 rows with an exhausted cursor. Added a distinct verified taker-history dataset; previous mixed-side activity remains ineligible for maker fills. Thirty focused tests pass. Bulk capture/loading and compression remain in progress; some real PM price decimals exceed the existing tape column scale and require lossless storage widening before loading.

- **Paper / PM US / rewards review (`tradingbot-b64`):** confirmed three P1 defects: overnight loss excluded from the daily halt (`1oh`), feed batching can skip an earlier cancellation quote (`27p`), and quiet feeds leave rewards quotes inside the scheduled blackout (`vzf`). Added rollback-only behavioral repros (3 strict xfails, all confirmed at final assertions with `--runxfail`) and `docs/reviews/2026-09-30-paper-pmus-rewards.md`. No risk limits or live orders changed.

### Liquidity-rewards candidate and evidence (`tradingbot-8r4`)
- Pushed e41b96b and recorded baseline trial 1811 as failed data readiness, with no fabricated P&L, drawdown or luck odds. 36 focused tests pass; final repository suite: 476 passed, five optional skips, one existing SDK warning. 8r4 remains deferred on e3t full-depth/dated-term evidence and 31w existing-authentication repair; `br ready` is empty.
- Claimed the next ready bead after closing the PM US connector. Preregistered a five-contract BBO maker baseline, the PRD's $15 net-inventory cap, one fill per rolling minute and a five-minute event blackout. Added daily pool/depth ranking, exact target-depth/discount/Max Spread calculations and mandatory reviewed non-sports/event inputs.
- The same pure strategy runs in all modes. A ledger adapter supplies individual fill receipts, including recent history across flat restarts; missing or conflicting execution evidence stops quoting. Inventory includes binary short liability, and cancellation acknowledgment precedes replacement. No shared risk constants or accepted-risk choices changed.
- Archived a reproducible public discovery snapshot: 139 program groups, 21 non-sports. Public templates and current books do not establish historical reward income or account eligibility; recorded estimates remain outside the ledger. Full historical depth/dated program data and a live notification/timer driver remain prerequisites for operational promotion.


### EOD LETF research complete (`tradingbot-8v6`)
- Closed 8v6 after c1s. Immediately checked `br ready`: no unclaimed ready issues remain (PM US rewards is already claimed by OrangeCove); no blocked or assigned work was taken over.
- Completed all six preregistered 2023–2026 SPY/QQQ cash-account variants in trials 1546, 1547, 1710, 1753, 1754 and 1760. Every variant loses after costs: primary 305 trades net -$11.276807; threshold sensitivities -$18.221741/-$4.172050; 5/10 bp stresses -$15.828925/-$23.409736; close benchmark -$10.681932. All end flat; no risk halt or funding/promotion.
- Captured and validated 935 pages / 62,454 source records covering 939 trading sessions and 931 afternoon windows. All required minute bars exist. Two 0.5%-variant entries were correctly rejected on October 10, 2023 for insufficient settled cash; negative signals remain unimplemented shorts under the cash-account constraint.
- Saved compact/full provenance, year/subperiod/symbol metrics, drawdown, p-values and written account-risk/decision records in `docs/research/06-letf-results.*`; expanded the SPY report with the same decision record. Shared execution dependencies are now included in code-provenance checks. Trials ran from committed 5eaef1c; 23 focused tests passed there and 13 shared-DB dashboard/longshot compatibility tests passed after the research rows were persisted. Transient disk-full capture failure recovered by resumption; no unrelated cleanup.

### EOD LETF runner and execution checks (`tradingbot-8v6`)
- Added the shared pure LETF strategy and all-six-variant ledger runner with prior-observation signals, negative-signal counts, alternating settled-cash halves, pooled daily fee rounding, per-symbol/year/subperiod and day-aggregated statistics.
- Research metrics now retain simulated risk-halt evidence and marked open positions if a risk veto prevents exit. No risk constants, live halt rows or accepted-risk choices changed. Synthetic tests verify same-bar future values are unused, both ETFs share daily fees, cash halves alternate and killed books reconcile. 23 focused tests pass.
- Afternoon capture briefly failed with ENOSPC after 550 sessions; available space recovered before intervention and exact resumable capture restarted without deleting unrelated files. Final coverage checks remain mandatory.

### PM US durable live execution (`tradingbot-wtn`)
- Added an explicit live limit connector over the ledger and unchanged risk limits: existing live allocation/trial and profitable same-parameter historical proof are required. Venue status/ticks/BBO, trading-only key evidence, collateral, buying power, pending orders and binary short liability gate submissions.
- Pending intents commit before POST; uncertain responses never resend. Individual reported executions, commissions and dated FX create tax records even under a halt. Durable execution evidence, duplicate checks and terminal-quantity checks preserve reservations through disconnects, cancel races and missing data; repair is explicit.
- Added a raw-JSON private-stream adapter and operating documentation; 54 focused transport, wire and Postgres tests pass. Full suite: 438 passed, five optional skips, two unrelated seeded-row-count assertions failed after research rows were added; reported to the test owner. Verified no residual PM US test strategies, orders or venue metadata. Constructor/snapshots do not reconcile; GTC orders retain the accepted no-dead-man behavior. No real orders or account changes. Authenticated verification remains blocked by the existing HTTP 401 incident.


### EOD LETF study started (`tradingbot-8v6`)
- Claimed 8v6 immediately after closing c1s. Preregistered six SPY/QQQ variants restricted to 2023–2026, raw daily-move thresholds, explicit bar execution assumptions, current fees and two alternating cash halves. Bearish signals are counted but not shorted in the approved cash account.
- Added resumable 15:29-to-close SIP minute capture for both ETFs, skipping early closes and rejecting dates outside the required sample. Six downloader tests pass.

### SPY turn-of-month study complete (`tradingbot-c1s`)
- Persisted trials 849–853: four complete variants, 128 trades each, and the preregistered midmonth diagnostic retained as failed corporate-action validation. Primary net $9.221030 after $5.12 fees; 5/10 bp stresses net $7.300585/$4.102634; daily-close benchmark $8.960114.
- Saved reproducible parameters, source/code hashes, trade counts, p-values, drawdown, annual/subperiod results and execution limitations in `docs/research/05-turn-of-month-results.*`. Ledger, cash and flat-ending checks pass. No live orders, funding or §6 changes. Primary qualifies for forward paper validation under the owner’s historical-profit criterion.

### PM US live connector transport (`tradingbot-wtn`)
- Claimed wtn immediately after completing pef. Added an official retail SDK adapter with exact Decimal JSON requests/responses, bounded timeouts and no automatic retries; a strict order/execution decoder distinguishes retail USD Amount commissions from institutional scaled integers. Sixteen focused tests pass.
- Order writes require recorded trading-only/no-withdrawal key verification bound to the key fingerprint. The adapter exposes no funding or key-management methods. Current retail docs have no client idempotency key, so uncertain submissions must remain reserved and must not be resent; durable connector handling follows in the next slice.
- Incident: two read-only authenticated balance checks using the existing configured PM US keys returned HTTP 401. Environment names are correct and server/host clock difference was zero seconds. No account/key changes or orders were attempted; authenticated integration remains unverified. Public source references and limitations will be in the connector README.

### Reproducible SPY study runner (`tradingbot-c1s`)
- Added all-variant ledger execution with immutable run identities, code/data/FX provenance, failed-attempt audit rows, full cash/P&L reconciliation and marked-equity/year/subperiod metrics. Synthetic rollback tests verify complete and failed runs.
- Full data validation confirms all 128 turn-of-month windows. The preregistered midmonth diagnostic hits a corporate-action factor change and will retain a failed validation trial; its unhandled dividend return is not compared with the clean month-end sample.

### Equity research ledger adapter (`tradingbot-c1s`)
- Added the pure SPY calendar strategy and an adapter over the shared Backtester, Ledger and unchanged RiskEngine limits. Simulated settled cash, explicit current equity fees and dated ECB reference FX are recorded on every backtest fill; no broker orders or funded allocation changes.
- Captured all 128 completed monthly windows from 2016 through September 2026. Exact archives include 2,701 raw and adjusted daily bars, 512 minute bars, trading/settlement calendars and corporate-action reference data. Archive integrity, prior-day FX, fee rounding, settlement holidays, size and short-sale checks have focused tests.
- Registered the equal-duration midmonth diagnostic before calculating returns, alongside the four existing variants. Corporate-action coverage is partial; holding-window validation also checks adjusted/raw factor bands allowing for cent rounding.

### Durable forward paper runtime (`tradingbot-pef`)
- Final boundary checks reserve binary short payout liability at `1 - price`, preventing low-priced sells from bypassing the unchanged $25 limit, and prevent new variants from inheriting an unfinished trial's positions. 43 paper tests pass. The broader suite passed 347 tests with five optional skips before these isolated boundary additions; database verification found no residual test strategies or paper-engine orders.
- Added PM US paper execution of the shared Strategy contract over committed live recorder rows. Each event atomically records orders/fills and cursors; exact standard fees/rebates and dated USD/GBP rates go through the ledger. Explicit resume restores persisted context and requires caller-restored strategy state; stops and failures retain resting orders.
- Maker fills require a strictly later venue trade through the price, capped by shared observed volume across trials. Takers require fresh executable BBO depth; repeated books cannot manufacture liquidity. Risk refresh/veto applies before orders and fills, with the same $25 cap also covering pending orders across strategies/outcomes. No §6 constants or accepted-risk choices changed.
- Added a foreground runner and operational README. 41 paper tests pass, including Postgres transactions, all five vetoes, partial fills, fee rebates/FX, duplicate tape, cross-strategy volume, explicit resume, callback rollback, stale BBO, close/expiry gates and quiet-feed loss monitoring. No paper run or venue order was started.

### SPY turn-of-month research started (`tradingbot-c1s`)
- Claimed c1s and fixed the calendar rule, four execution/slippage variants, sample, current-fee counterfactual and reporting requirements in `docs/research/05-turn-of-month-plan.md` before return analysis. No schedule optimization or risk-limit changes.
- Added a read-only official Alpaca SDK archive for SIP daily/minute bars and the full trading/settlement calendar, preserving exact response text and symbol-first pagination. Research archives are separate under gitignored `data/equities/`. Five tests cover cursor exhaustion, exact decimal text, repeats/resume, partial captures and trading-day window selection.
- Existing paper credentials successfully retrieved historical SPY/QQQ SIP bars and settlement dates. No account settings or broker orders were changed. Bulk capture and all-variant fee-aware backtests follow.

### Paper fill causality (`tradingbot-pef`, first slice)
- Reused the backtest trade-through matcher with stricter forward-paper checks: venue execution time must follow submission, receipt must be fresh, and known aggressor direction must oppose the maker. Quotes, touches, delayed old prints and missing timestamps cannot create maker fills.
- Added stable trade/book identities for duplicate-volume accounting and a bounded adapter for committed live-recorder rows that preserves venue trade timestamps and excludes historical observations. Eleven pure tests pass; persistent runtime/ledger/risk integration follows.

### Alpaca paper connector integration (`tradingbot-7mr`)
- Completed the paper-only connector on the existing Ledger/RiskEngine. Adds a persisted explicit cash budget, T+1 sale-proceeds settlement, broker `buying_power`/cash ceilings, pending-order reservations, owned-share sell checks and the unchanged §6 vetoes. Market exposure includes pending buys across strategies.
- Added durable client-order intents, idempotent paginated execution ingestion with dated USD/GBP snapshots, cancel/fill race handling and retained reservations after uncertain submissions. Postgres venue-row locking coordinates connector processes; no schema or risk-limit changes, startup reconciliation or dead-man behavior.
- Supports regular-session marketable DAY limits and fractional quantities, with paper-fee/fill provenance and documented simulation limits. Added a read-only connectivity CLI and strategy integration guide. The SDK timeout adapter uses `requests` as an explicit dependency.
- Validation: 48 connector tests pass; full suite 268 passed / 5 optional loader tests skipped. Real read-only paper checks verified account/asset/quote/calendar behavior. No broker orders or account-setting changes; integration fixtures use savepoints and leave no test book, orders, strategies or FX rows behind.

### Historical loading complete (`tradingbot-pu9`)
- Documented loader commands, venue/instrument identities, quote/trade semantics, settlement snapshots, point-in-time caveats and exact capture coverage in `src/tradingbot/data/LOADING.md`; added handoff notes to the backtester and live recorder beads.
- Final rerun: zero inserted observations, reference/document changes or identity upgrades; 13,866 source observations skipped. Verified all source values against 13,862 unique rows (8,254 trades + 5,608 price observations), with zero orphans. Venue identities/enabled flags and strategy/trial/ledger/FX/incident/risk state match the baseline. Eight of 25 captures remain partial; this unblocks implementation, not strategy promotion.
- All 51 data tests passed, including transaction rollback, duplicate/conflict checks, decimal/UTC identity compatibility, venue separation and settlement precedence. Closed `tradingbot-pu9`; no schema or PRD §6 changes.

### Historical identity compatibility (`tradingbot-pu9`)
- Canonicalized numeric fingerprints so equivalent decimal spellings deduplicate, with an in-place upgrade for earlier derived identities. Native venue trade IDs remain unchanged. Added regression coverage; 51 data tests pass against the existing schema.
- Fixed a timezone conversion in that upgrade. A development run had created 5,032 duplicate price rows before stopping; exact content/provenance comparisons verified the duplicates, which were removed transactionally while preserving the original 5,608 observations and restoring their UTC identities. No trading or risk tables were involved.

### Historical database loader (`tradingbot-pu9`, implementation slice)
- Added a page-atomic loader into the existing markets/instruments and TimescaleDB quotes/trades tables, with archive checksum/request-chain checks, exact numeric precision checks, advisory-lock serialization and idempotent trade/price identities. Catalog snapshots, settlement evidence and provenance stay in namespaced metadata; older catalogs cannot overwrite newer state.
- Loaded all 35 captured pages from 25 jobs into local port 5433: 84 markets, 1,138 instruments, 8,254 trade projections/activity rows and 5,608 sampled/display-price observations. Eight captures remain explicitly partial. Price observations do not populate BBO/last-trade fields or qualify for maker fills.
- Passed 48 data tests, including rollback-only DB checks for overlap deduplication, conflicting IDs, missing mappings, settlement precedence and venue separation. Schema and PRD §6 are unchanged; rerun and backtester handoff verification follow.

### Alpaca paper connector foundations (`tradingbot-7mr`, in progress)
- Added a paper-only official-SDK transport with decimal-string orders, bounded request timeouts and no automatic order retries. Credentials load from `.env` via python-dotenv; no live endpoint or account-setting methods are exposed.
- Added cash reservation and T+1 settlement primitives using the API's explicit `settlement_date`, including settlement holidays and New York date boundaries. Ten tests pass; read-only paper probes verified SPY fractional eligibility, IEX quote shape and the October 9 → October 13 settlement holiday. Ledger/risk integration follows in the next slice.

### Alpaca PDT implementation check
- Completed `tradingbot-sbl`: Alpaca confirms the replacement intraday margin framework has been in production since June 4, 2026. The current paper-account response matches the documented removal of legacy PDT fields.
- Recorded dated Alpaca/FINRA sources and sanitized read-only evidence in research 04. Preserved the PRD's cash-only, T+1 and §6 rules; paper leverage is not strategy permission.

### X API budget check
- Completed `tradingbot-09f`: official recent counts cost $0.005/request, so 500 tickers polled daily cost $75–$77.50/month. Documented lower-cost collection tradeoffs without changing the $50 ceiling or study scope.
- Verified one existing-token count-only request returns two daily buckets; no public post or account/billing changes. Recorded the 300/15-minute limit and observation-time requirement in research 04.

### Alpaca options data check
- Completed `tradingbot-dkt`: verified indicative versus OPRA terms and historical coverage with current docs and read-only paper-key probes. Indicative SPY/SPXW quotes work; current OPRA quotes require the unsigned agreement. Historical SPY trades return February 2024 and a January 18 sample; full SPX quote-history coverage remains unproven.
- Recorded account-entitlement evidence and the SDK/REST history discrepancy in research 04, without storing secrets or making account changes.

### Exact prediction-market fee models
- Completed `tradingbot-di9`: added per-order PM US standard and Kalshi quadratic research fee models under `src/tradingbot/fees`, using Decimal inputs/outputs and exact arithmetic. Includes signed maker rebates, cumulative corrections, clearing precision and explicit dated policies.
- Added 76 passing fee tests against venue examples and rounding/state edge cases. Documented the Kalshi PDF/API precision discrepancy and limits on historical fee reconstruction in research 04. No §6 edits or live trading.

### PM US fee and incentive check
- Completed `tradingbot-2ej` in `docs/research/04-open-items.md` against current primary sources: signed maker rebate, half-even rounding, cumulative taker fee cap, reward depth/spread qualification, payout threshold and program-level pools.
- Kept non-sports opportunity availability unproven and incentive estimates separate from collected fees/rewards. No risk limits changed.

### Strategy intake
- Added `docs/strategy-intake/`: a rubric and log for evaluating strategies the owner sends.
- First submission: the Opus+Jev prompt X post. Verdict **Salvage**: the LLM-alpha strategy is rejected, and the ideas for drawdown/regime backtest reporting and a blow-up section in promotion reviews are kept.

### Foundation: database schema (tradingbot-0yj)
- Added `tradingbot.db`: SQLAlchemy 2.0 models + Alembic migrations (PG18 + TimescaleDB, port 5433). Initial migration `603bae9dd448` creates 13 tables and passes `alembic check` (no drift) with a clean downgrade→upgrade round-trip.
- Tables: `venues`, `markets`, `instruments`; `quotes`/`trades` as TimescaleDB hypertables on `time` (the tape drives paper fills); `strategies`, `trials` (trials ledger); `orders`, `fills`, `positions` (the ledger — each fill snapshots `usd_gbp_rate` for tax, PRD §10); `incidents`, `risk_halts`, `fx_rates`.
- One code path for backtest/paper/live via a `mode` column; money is `NUMERIC`, never float; controlled vocabularies are `VARCHAR` + `CHECK`.
- Added `tradingbot.config` (pydantic-settings, loads `.env`, forces the psycopg3 driver) and `tradingbot.db.seed` (idempotent: 4 venues + the 8 PRD §5 strategies).

### Foundation: ledger (tradingbot-845)
- Added `tradingbot.ledger` — the single source of truth for orders, fills, fees and P&L. `Ledger` records orders/fills, auto-computes prediction-market fees via the per-order `tradingbot.fees` models (explicit venue-reported fee for live), snapshots the USD/GBP rate per fill (PRD §10), and maintains the `positions` book (average-cost, signed, with flip-through-zero).
- `accounting.py`: pure `Decimal` position maths (`apply_fill`, `settle`, `iter_round_trips`) — realized P&L is gross, fees tracked separately so "profit after fees" = realized − fees.
- `stats.py`: dependency-free luck p-value (one-sample Student's t-test built from the regularized incomplete beta; no scipy). `strategy_report()` returns P&L after fees, trade count (round trips), and the luck p-value (PRD §4); `finalize_trial()` writes them onto the trials ledger.
- 33 tests (pure accounting, stats cross-checked against closed-form values, and DB-backed ledger incl. cumulative taker fees, settlement, USD/GBP snapshot). Full suite: 132 passing.

### Foundation: risk engine with §6 hard limits (tradingbot-s94)
- Added `tradingbot.risk` — absolute-veto enforcement of all five PRD §6 limits: per-strategy −40% permanent kill, −$50 global daily halt, $25 per-market position cap, 30s stale-data halt, and 5-errors/minute API halt. Limits are hard-coded constants in `risk/limits.py` and **never** configurable (AGENTS.md; PRD §9).
- `RiskEngine.evaluate_order()` is the pre-trade gate the execution layer must obey; `refresh_halts()` recomputes P&L (realized-after-fees from the ledger plus open unrealized when marks are supplied) and trips the daily halt / per-strategy kills, persisting to `risk_halts` and logging `incidents` so kills survive a restart. Days bounded in UTC.
- Added a `test_limits_match_prd_section_6` canary that fails loudly if any §6 value is edited. 14 risk tests; full suite: 146 passing.

### Local read-only dashboard (tradingbot-39k)
- Added `tradingbot.dashboard` — a localhost read-only dashboard (`python -m tradingbot.dashboard`, default `127.0.0.1:8787`). Stdlib `http.server`, no new deps, GET-only (writes → 405), never commits.
- Shows the leaderboard (P&L after fees, trade count, luck odds), the backtest-vs-live gap, active kill-switch/halts with a banner, the incident log, and pipeline status — all read straight from the ledger/risk tables via `Ledger.strategy_report`. `?mode=backtest|paper|live` selects the mode.
- Split into `reports.py` (pure read queries → dicts), `render.py` (pure snapshot→HTML, dark-mode aware, HTML-escaped), and `server.py`. 18 tests (reports, rendering incl. XSS-escaping, and a real-HTTP server smoke test). Full suite: 164 passing.

### Kalshi public historical data (`tradingbot-31b`)
- Added a research-only public downloader under `src/tradingbot/data/` for recent and archived markets/trades, event/series metadata, and historical series/event fee changes. No account or trading access is used.
- Added lossless API-page Parquet envelopes under gitignored `/data/`, query manifests, atomic checkpoints, resume validation, pagination-cycle checks, request pacing and bounded retries. Anchored the data ignore so source and tests remain tracked.
- Added official venue SDK and Arrow dependencies for the historical-data workstream; the PRD-named Kalshi SDK needs explicit `cryptography` and raw transport for archive endpoints.
- Verified against public CPI market/trade history and fee-change endpoints; eight offline tests cover lossless storage, failures/resume, pagination, HTTP status handling and both Kalshi tiers. DB loading remains deferred to `tradingbot-pu9`.

### Polymarket public historical data (`tradingbot-sp8`)
- Added separate US and international downloaders using the official SDKs and the shared lossless Parquet archive. US supports catalog filters, book-derived display-price history and settlement prices. International uses Gamma keyset catalogs and Data API v2 sampled prices, recent public trades and resolution records.
- Added daily US history windows and 15-day international windows with cursor exhaustion inside each window, complete-range job identity, and repeated-page detection across US catalog resumes. Unsupported filters fail explicitly; raw price observations are never labelled as trades.
- Documented sampling/retention limits, mutable-catalog caveats, identifier mappings, SDK integration points and loader requirements in `src/tradingbot/data/README.md`; added the data contract to `tradingbot-pu9`.
- Validation: 23 data tests pass. Real public samples include US Bitcoin catalog, 83 broad-history and 2,235 daily-window price observations plus settlement; international catalog/events, 562 broad-history and 410 hourly-window price observations, cursor-paginated recent trades and resolution records. Real catalog resume and completed-query no-op checks pass. Captures remain gitignored in `data/`; DB loading remains deferred.

### Historical loader normalization (`tradingbot-pu9`, first slice)
- Added pure Decimal normalization for Kalshi and Polymarket archives using the existing market/instrument/quote/trade vocabulary. Keeps event/condition grouping, outcome-token mappings, raw provenance inputs, fractional payouts and separate settlement evidence.
- Public trade projections retain native IDs; Polymarket activity uses conservative economic fingerprints and does not infer aggressor direction. Sampled/display prices stay explicitly labelled quote observations with no invented BBO or trade volume. Unresolved oracle sentinels and old zero-price arrays are not settlement results.
- Seventeen normalization tests pass; all 35 existing archive pages normalize successfully. Database writing and idempotent ingestion remain in progress on the same bead. No schema or §6 changes.

### Live Polymarket US market-data recorder (`tradingbot-xgt`)
- Added `src/tradingbot/recorder/`: captures the Polymarket US order book and public trade tape into the existing TimescaleDB `quotes` / `trades` hypertables over the venue's market websocket. Split into pure, unit-tested units (wire-frame decoders, a `FeedHealth` heartbeat, a slug→instrument store) and a thin async driver that owns the socket lifecycle, subscriptions and reconnect backoff.
- Staleness heartbeat for the §6 gate: book updates and trades are written straight through; `tick()` re-snapshots each subscribed market's top-of-book on a cadence derived from `STALE_DATA_MAX_SECONDS` (so a connected-but-quiet market never trips the 30 s gate falsely), and stops re-snapshotting when the feed goes silent (so genuinely stale data ages out and the gate halts trading). A silent feed logs one `connectivity` incident; a websocket error feeds the §6 five-errors-per-minute API halt. Row `time` is our receive clock (venue event time kept in metadata) so staleness measures time since we last observed data.
- Slug resolution keys on `markets.external_id` → the Yes (long) leg, matching the historical loader's mapping (coordinated with the loader author). Live rows are tagged `metadata.source`; the recorder never reads or overwrites the loader's historical display-price quotes. No schema, migration or §6 changes. 33 recorder tests pass (decoders, heartbeat cadence, driver keep-alive/silence/error handling, an async run smoke test, and DB-backed store + risk-gate tie-in); full suite green.

### Strategy interface + backtester (`tradingbot-ltj`)
- Added `src/tradingbot/strategy/`: the one-code-path contract (PRD §4, §7). A strategy is a pure reactor — one subclass of `Strategy` per file — that receives `MarketEvent`s and returns `Intent`s (`PlaceOrder` / `CancelOrder`) via the read-only `StrategyContext` (`now`, `mode`, `params`, `position`, `snapshot`, `resting_tags`). It never touches the DB, a venue, the risk engine or the mode, so the same code runs unchanged in backtest, paper and live. A small registry lets strategies self-register by `key`; a `ThresholdMaker` reference strategy is included as a template.
- Added `src/tradingbot/backtest/`: the backtester runtime. It replays a time-ordered event stream and routes **every** intent through the same §6 risk veto and the same ledger the live path uses (fees, positions, P&L and the luck p-value all from the one source of truth), then writes a `trials` row for every run including losers (PRD §4). The fill model enforces PRD §7: a resting maker order fills only when a later public trade goes *strictly* through its limit (at the limit price, capped by the trade's size); taker/market orders cross to the far touch; display/sampled observations are marks and never fill a maker. A DB feed normalizes historical display/sampled quotes (value in metadata, NULL BBO) and eligible trades into the event stream.
- 26 tests: pure fill-model and interface/registry tests, plus DB-backed end-to-end runs (maker round trip through the DB feed, strict trade-through boundary, the $25-cap veto rejecting an order, hold-to-settlement close, and display-price quotes not filling makers). No schema, migration or §6 changes; full suite green (294 passed).

### Strategy #1 — favourite–longshot bias backtest (`tradingbot-0s0`)
- Added `src/tradingbot/strategy/favourite_longshot.py` (PRD §5 #1, registry key `longshot`): a pure maker reactor that rests on the backtest-picked side of each market (`buy_favourite` buys the favourite, `sell_longshot` lays the longshot), commits to one outcome per market and holds it to settlement. Adverse-selection guards are built in: a per-market fill cap that cancels the resting remainder once hit, a quote-pull blackout before the scheduled event, and a price band that steers clear of near-certain favourites. All reference data (which markets, scheduled close, sibling outcomes) is passed in as params — it never reads a settlement value or the DB.
- Added `src/tradingbot/backtest/favourite_longshot.py`: the driver. Selects settled markets with a known payout **by category** (Kalshi series ticker / PM category), windows each to its last 7 days before resolution (PRD §5's "resolves within 7 days"), replays maker-only, settles at the payout, and scores **after exact Polymarket US fees** — the current PM US coefficients applied to the historical tape, since #1 trades on PM US (PRD §5) and the PM US maker fee is a rebate. Each variant (2 side rules × 3 offsets) runs inside a rolled-back SAVEPOINT so its orders/fills/positions never persist or contaminate the next; only a clean `Trial` summary per variant is kept — that *is* the trials ledger (PRD §4). `uv run python -m tradingbot.backtest.favourite_longshot`.
- Ran it: **6 variants written to the trials ledger** (trials 833–848), all `complete`. The only maker-fillable tape in the current capture is a single Kalshi market, `KXCPI-26JUN` (category KXCPI); PM US ships display prices with no trades, so a maker there never fills and no PM US category produced fills. Best variant `buy_favourite` offset 0.05 → **+$3.89 after PM US fees** over **1 round trip** (fees −$0.02, i.e. the maker rebate was credited — proof PM US fees, not Kalshi's, were charged).
- **This does not prove the edge.** One near-50/50 market that resolved once gives a single round trip, so the luck p-value is uncomputable (`None`) and both sides look profitable only because the favourite happened to win. Treat it as mechanism validation, not evidence. The strategy stays `idea` (not promoted — PRD §4 proof criteria are not met); `data/LOADING.md` already flags that the current capture is implementation-sample size, not strategy-validation history.
- Tests: 9 pure strategy-reactor tests (both side rules, favourite/longshot classification, one-side-per-market, no-stacking, fill-cap cancel, blackout, price band) + 4 DB-backed driver tests (category selection, one trial per variant with a per-category pick, PM US maker rebate applied, and SAVEPOINT isolation — zero orders/fills/positions leak). No schema, migration or §6 changes; full suite green (364 passed, 5 DB-gated skipped).

### Backtest report: drawdown + regime; promotion checklist blow-up section (`tradingbot-l0v`)
- Salvage from the Jev-prompt intake (`docs/strategy-intake/2026-09-30-opus-jev-prompt.md`): filter backtest survivors on drawdown as well as return, check several regimes, and make every promotion write a "What could blow up this account?" section.
- **Max drawdown in the report.** Added a pure `max_drawdown(pnls)` to `ledger/stats.py` (worst peak-to-trough fall of the cumulative net-P&L curve, same absolute-USD definition the equity research runtime uses). `Ledger.strategy_report` now returns `max_drawdown` and a time-ordered `round_trips()` helper feeds it; `finalize_trial` writes `Trial.max_drawdown` (previously always null for backtester runs).
- **Per-regime breakdown.** New `src/tradingbot/backtest/report.py`: `regime_breakdown()` splits a run's round trips by a regime labeller (default = calendar month `YYYY-MM`; pass a custom `regime_fn` to split by a real market/monetary/vol regime) and reports each regime's P&L after fees, trade count, drawdown and luck p-value. `drawdown_regime_report()` combines the overall drawdown with the regime split for a (strategy, mode[, trial]) scope.
- **Wired into strategy #1 + the dashboard.** The favourite-longshot driver now stores `max_drawdown` on each trial and the `by_regime` breakdown in `Trial.metrics`. The dashboard gained a "Backtest trials (P&L, drawdown, regime)" table (`reports.backtest_trials` + render), additive — the live leaderboard is unchanged. Re-ran strategy #1 so its 6 trials carry the full metric set (drawdown $0 over one round trip, regime `2026-07`), replacing the 6 pre-feature rows from the 0s0 run (same variants, now complete).
- **Promotion checklist.** Added `docs/promotion-checklist.md` — the PRD §4 idea→backtest→paper→live review gate, with a mandatory written "What could blow up this account?" section (tail/gap risk, adverse selection, counterparty/venue, untrusted inputs as data-not-instructions, reproducibility, correlation) plus drawdown/regime gates and a §6 limits reaffirmation. AGENTS.md now points to it for every promotion.
- Tests: pure `max_drawdown` cases, pure + DB-backed regime/drawdown report tests, and dashboard report/render tests for the new table. Made the leaderboard test robust to the shared DB (research strategies committed by other runners) and the strategy-#1 driver test scope to its own trial ids. No schema, migration or §6 changes; full suite green (440 passed, 5 DB-gated skipped).
- Intake: the JEVUP Robinhood Chain memecoin post was evaluated with the owner. Verdict **Park → staged research**: first a chain base-rate backtest with no Jev and no wallet, pre-registered with 5 exits and a pass bar of p<0.10. The Jev paper test only happens if that passes. Going live would need a PRD vote on the no-LLM-alpha rule and a swap-only smart-contract wallet.

## 2026-10-01

### C07 amended source admission (`tradingbot-pdw`)
- Claimed the next ready unheld bead. Preserved original failed trial 3548 and all original sector captures. Verified 5,218 sessions for each of nine ETFs, 18 independent daily reference series and 19 primary auction windows. Two derived opens are corrected with primary evidence; all other disputed opens/closes reconcile.
- Wrote the source amendment before outcomes: 746 issuer ordinary distributions, 11 material vendor discrepancies with explicit issuer precedence, three broker rates normalized to issuer six-decimal precision, duplicate and in-kind rows separated from cash, and availability after the latest documented payable. Verified XLRE's ex-close solely for XLF's economic total-return signal; no XLRE ranking or trading.
- Reverified all six timely corporate-action announcements and the five training/ten final blackout symbol-sessions. Nineteen focused tests pass. Source admission precedes reactor implementation and all six training cases; no C07 rankings, returns, holdout, promotion, capital, keys or §6 changes in this slice.

### C05 final completed and held for forward evidence (`tradingbot-qdd`)
- Ran the frozen 126-session rule once on the final partition after selection commit `0ae082f`. Final trial 3964 / strategy 6473 retains selected version `de0dad8696f3`: +$47.08 net on $140, 161 fills, 34 round trips, $1.74 execution fees and $2.36 DBA dividend income. Marked max drawdown is $30.31 (18.25% from peak); daily-close drawdown $29.63 (17.91%). No rejections, open ending positions or risk halts.
- Both historical profit gates pass (+$30.42 selected training, +$47.08 final). Final p is null because 34 trips yield only 26 exit-month clusters. All 12 training/two final blackout symbol-sessions were already flat, with zero forced-leg costs. Report 23 includes calendar regimes/years, USO dislocation/transition attribution, sleeve results, fees, benchmarks and limitations.
- Independent stored-ledger audit passes all seven runs and confirms exactly one final; original failed rows 6032/3518 remain unchanged. No strategy replay was used for the audit. No paper/live or ready-for-live promotion: prior USO outcome overlap and actual fractional execution/action/cash fidelity require forward evidence. Created `tradingbot-ggg` for that work; no new account, key, venue, capital or §6 change.

### C05 six training cases and frozen choice (`tradingbot-qdd`)
- Completed all six preregistered cases without rejections or terminal positions: 252-session net −$0.61/−$2.04, 126-session +$32.30/+$30.42, SMA200 +$11.61/+$9.67 at 5/10 bp respectively. Trials 3954/3955/3956/3959/3960/3961 preserve every attempt.
- Selected only the 126-session 10 bp case: 251 fills, 57 round trips, $3.09 fees, $49.33 marked max drawdown (26.75% from peak), descriptive monthly-block p≈0.264. All 12 training blackout symbol-sessions were already flat, so forced-leg costs are zero. The final period remains unconsumed at this commit.
- Added an independent stored-ledger audit of all six cases: exact scenario prices/dated fees, settled-cash buys, prior-owned dividends, blackout-flat positions and all 3,303 daily marks reconcile. Preserved original failed rows 6032/3518 and committed selection/dependency identity before the single final attempt.

### C05 tested replay before training (`tradingbot-qdd`)
- Added the pure monthly five-sleeve reactor and candidate-local adapter over the unchanged shared backtester, ledger, fee book and risk engine. Frozen targets, proportional settled-cash buys, sub-$1 skips, actual-share blackout exits/re-entry and last-open liquidation follow the written rules.
- Added separately evidenced dividend receivables and delayed spendable cash without fabricating execution fills. Net results reconcile the execution ledger plus dividend income; simultaneous ETF marks avoid order-dependent transient risk decisions.
- Ten synthetic tests pass, including all three warm-up/equality rules, cash delays after reductions, no redistribution of skipped budgets, prior-owned dividend entitlement, split blackouts, durable training admission and final-family reuse refusal. Source-only reloading confirms the frozen receipt and exact 2021-02-14 14:24 UTC cutoff. Idea-to-backtest checklist and account-failure analysis are recorded before outcomes.

### C05 source admission before returns (`tradingbot-qdd`)
- Wrote the candidate-local report 23 amendment before outcomes: six primary-auction open corrections, nullable actual payable dates separate from explicit split blackout endpoints, and all seven DBA dividends reconciled to primary payment evidence. Archived provider-extracted primary text separately from failed direct HTTP requests; preserved all original captures and failed trial 3518.
- Froze 4,716 five-fund sessions at receipt `05774a5a2f1c`, with 12 training and two final blackout symbol-sessions. Historical ex-date inference is explicit, DBA's duplicate 2018 record-date event is excluded, and dividend cash is delayed until the first regular open after payment. No C05 returns or holdout consumption yet.
- Twenty focused source/auction tests pass. Admission validation caught a reversed transcription of the six open corrections and a Decimal serialization issue during development; both were fixed before admission. Separate source hashes and prior-outcome overlap limitations remain recorded.

### C05 Amendment 21 source preparation (`tradingbot-qdd`)
- Claimed the next ready P1 and preserved original failed source trial 3518/strategy 6032. Captured the full five-fund broker action query, ten free raw SIP/IEX reference series and eleven targeted primary auction windows; all original Yahoo series retain 4,716 valid sessions.
- Added strict source identity, pagination and compound split-conversion checks. Five close differences reconcile to primary Arca prints; six 2016–2017 opens conflict by more than the unchanged 1% bound and remain unresolved in the preparation receipt. Missing older payable fields, SLV payable-before-ex ordering and duplicated DBA 2018 broker events require explicit source treatment before admission.
- Eighteen focused source/auction checks pass. Documented the exact discrepancies and remaining gates in `docs/research/23-c05-blackout.md/.json`; no signals, strategy outcomes, holdout, promotion or shared execution/risk changes.

### Longshot full-history study completed (`tradingbot-yg2`)
- Selection `2fa6db3` was pushed before final admission. The sole selected international BTC sell-longshot .05 version completed final trial 3969 once: +$15.638289 net ($9.798289 gross plus $5.84 modeled maker rebates), 111 trades/events/exit dates, $83.283383596 marked drawdown (59.49% of the initial virtual $140 slot), no kill or seven-day holding breach, per-trip/date p-values 0.43536. The other four category finals remain unconsumed.
- The stated counterfactual after-fee profit condition passes in both partitions, but retain the candidate in research: training drawdown is $175.07, final Q3 loses $32.00 after June's gain, and native PM US fills/fees/cash-release fidelity remains unproven. No retuning, new statistical gate, loss-limit change, funding, key, paper/live promotion or public post.
- The completed audit verifies all 31 attempts / 2,240 trips / 7,562 fills, exact native execution identities and fee/settlement arithmetic, fully funded filled exposure, terminal-flat books, calendar aggregates and unchanged six legacy trials. The final cash/ledger residual is −$0.00000013, within the declared precision. Frozen execution sources remain unchanged from `73d02c5`; their 56 affected checks passed before outcomes.
- Saved full decision, trade counts, p-values, marked/realized drawdowns, all-variant regimes, adverse-selection/dependence caveats and mandatory account-risk paragraphs in `20-longshot-results.md/.json`, with final/audit JSON and a deterministic 31-member execution-receipt archive. Verified every archive member against its audited hash, all report artifact hashes/local links, 30 completed training rows and exactly one completed final. The report builder reads sealed receipts and never replays strategy returns. Free space remains over 90 GB.

### Longshot full training and final selection (`tradingbot-yg2`)
- All 30 preregistered training variants completed under frozen implementation `73d02c5`; two were profitable, 28 triggered the simulated permanent kill, and none breached seven days held. All 30 pass the independent source/fill/cash/fee/trip/regime audit. The last weather trials 3937/3939/3957/3962/3965/3967 all lose after costs.
- Froze the exact complete training and selection JSON plus training audit and written decision in `20-longshot-training.json`, `20-longshot-selection.json/.md` and `20-longshot-training-audit.json`. Only international BTC sell-longshot .05 / trial 3935 is selected by the declared rule. The other four category finals stay unconsumed. Its +$121.781966 training net is qualified by $175.07 marked drawdown, a losing 2026 Q2 and descriptive p-values near .22.
- Final count is zero at this commit boundary. The exact selection must be pushed before the single unchanged-version final admission. No retuning, risk-limit changes, paper/live promotion or funding.

### Longshot international BTC training (`tradingbot-yg2`, study still running)
- Completed all six fixed international BTC variants. Buy trials 3925/3927/3929 lose $63.690881/$56.970832/$62.241832 over 18/17/20 trades. Sell trials 3931/3933/3935 net −$65.601207/+$10.360168/+$121.781966 over 252/260/250 trades. The .05 sell variant has the best positive training result under the declared rule; the global selection is not yet frozen and no final has been admitted.
- Profit does not establish risk suitability: trial 3935 has $175.06646047 marked peak-to-trough drawdown (125.05% of the initial virtual $140 slot) and −$108.39424007 in the 2026 Q2 training bucket. Its initial-allocation loss kill did not fire; peak drawdown and loss from initial allocation are different measures. Trial 3933 has an even larger $252.8694273 drawdown. No new threshold, parameter change or promotion was applied after these outcomes.
- All 24 completed variants / 1,934 trips / 6,611 fills pass the read-only receipt/regime audit. International fractional cash-to-ledger residuals remain within the declared accounting precision. The six weather variants continue; the updated partial snapshot remains explicitly incomplete. Data totals 1.43 GB and free space 92.1 GB at this checkpoint, within unchanged capture limits.

### Longshot index training (`tradingbot-yg2`, study still running)
- All six fixed KXINX variants completed at a loss. Buy trials 3913/3915/3917 and sell trials 3919/3921/3923 net −$57.90/−$54.66/−$55.59 at offsets .01/.02/.05, respectively, over 45/48/45 trades per side. Marked drawdowns are $74.62/$73.39/$83.08; every variant triggered the simulated permanent kill and none held over seven days. The matching paired outcomes are dependent evidence, not independent replications.
- BTC, temperature and index all lack a positive-net training candidate, leaving their finals unconsumed. The receipt audit now passes all 18 completed variants / 1,117 trips / 3,585 fills and preserves legacy rows; its partial snapshot is updated. The two international PM categories continue under the unchanged frozen implementation. This is not study completion or promotion.

### Longshot temperature training (`tradingbot-yg2`, study still running)
- All six fixed KXHIGHNY variants completed. Buy trials 3821/3823/3833 net −$53.78/−$48.53/−$52.09 over 24/22/115 trades; sell trials 3888/3908/3911 net −$48.61/−$47.53/−$49.70 over 24/22/53 trades. Every variant triggered the simulated permanent kill; none held over seven days. Temperature has no positive-net training candidate and its final stays unconsumed. KXINX training is next; three categories remain unfinished.
- Extended the independent receipt audit to reconcile each round trip, unique event/date counts, daily aggregates and all monthly/quarterly gross/net/fee/trade totals. Source and fee checks remain exact; weighted-average trip arithmetic permits only a sub-1e-40 Decimal remainder. All 12 completed variants / 841 trips / 2,731 fills pass; updated the explicit partial audit snapshot. Execution sources and limits are unchanged, with no strategy replay or final admission for this reporting check.

### Longshot receipt verification and reporting (`tradingbot-yg2`, study still running)
- Preserved standalone receipt-audit and sealed-result reporting scripts in `docs/research/20-longshot-*.py`. The audit matches native execution IDs, through prices, times, volume, fees, payouts and ledger cash, and independently reconstructs filled collateral against the unchanged $140 virtual book / $25 contract caps. Pending reservations remain covered by the frozen runner checks and reported maximum; fill receipts do not reconstruct canceled orders.
- All ten completed training trials pass 2,462 fill checks in `20-longshot-partial-audit.json`, including unchanged legacy trials and empty terminal inventory. The report requires all 30 training variants and matching audited attempts, distinguishes failed attempts from completed losses, and retains all-regime/risk/sample evidence plus each mandatory account-risk paragraph. Both scripts compile. Training continues under `73d02c5`; no frozen execution source, parameter, selection or final admission changed.

### C08 historical study completed (`tradingbot-8lk`)
- Preserved the original failed source rows and admitted 455 dated EIA releases, two explicitly unavailable releases and 2,198 USO sessions with source exceptions fixed before outcomes. Source/implementation `90fcde2` preceded all four training cases; selection `ebba4b8` preceded the single final.
- The frozen −5% inventory threshold at 10 bp per side earned $102.29 training net (three trips; $0.12 fees; 26.61% maximum marked drawdown) and $7.67 final net (trial 3910; four trips; $0.16 fees; 16.41% drawdown). Luck p-values remain null; training profit is concentrated in one trip and final 2026 loses $12.04. Both 0% cases remain failed partial attempts after unchanged loss vetoes prevented the blackout exit.
- Independent read-only audits reconcile all fills/fees/trips, verify final entry publication eligibility and exactly one final attempt, and confirm original failed rows and execution dependencies are unchanged. Fifty-six focused checks passed before outcomes. Report and receipts are in `docs/research/22-c08-*`; no replay or promotion. Created `tradingbot-gx2` for separate forward action/cash/execution evidence and the promotion checklist; risk limits and account state remain unchanged.

### C08 source admitted before strategy outcomes (`tradingbot-8lk`)
- Froze receipt `63c4d5619290…`: 2,198 USO sessions, 455 usable dated EIA releases, two unavailable pages, five PDF field fallbacks and one independently resolved publication typo. All 457 index entries are accounted for, with original responses and complete notice/errata review preserved.
- The fixed interval/cutoff, 0%/−5% thresholds, 5/10bp cases and $140 virtual slot are unchanged. Archived methodology and errata support dated-archive admission; independent release-day byte capture is explicitly not claimed. Original failed trial3550/strategy6082 are protected by full-row hashes.
- Committed the account-risk review and pinned the runner to the immutable source receipt before any real strategy returns. Training and final counts remain zero at this boundary; no capital, risk or live-state changes.
- Ran the fixed four training cases once from `90fcde2`. Threshold0 trials3904/3905 hit the permanent loss veto, then failed the required blackout exit with an open position; partial ending marked equity ~$23.26, 33 rejections each, no limit bypass. Threshold−5% trials3906/3907 complete with +$102.88/+$102.29 after costs, three trips, $0.12 fees, no rejections; selected10bp marked drawdown $54.80 (26.61%).
- Froze threshold−5%, trial3907/version`739e205972e6…`, before a single10bp final. Training-only fill/cost/fee/ledger audit has zero execution-reference residuals and verifies unchanged original rows. The selected rule was flat during both blackout sessions, so forced-leg costs are zero. Luck p-value is null with three trips; no extra gate or retuning. Final count remains zero at this selection boundary.

### C08 publication and blackout reactor (`tradingbot-8lk`)
- Preserve EIA HTTP-200 application errors as missing releases; resolve an incomplete observation heading only through its attached dated CSV/PDF and a full page publication date. No URL-date guess or revised-series substitution.
- Added a candidate-local pure reactor for strict inventory thresholds, unchanged long quantities, the fixed 14-day expiry, frozen cash-delayed targets, terminal liquidation and Amendment21 forced exits/re-entry. A failed forced exit refuses to carry an unresolved action. All 37 synthetic/source/blackout checks pass; no real strategy outcomes or final admission.
- Source review also records USO's January2026 roll-window change alongside the required 2020 and 2023–2024 exposure regimes. Full EIA capture/revision-notice audit continues.
- Added the source-bound shared-engine runner with durable training admission and a C08-family final-reuse guard, preserving interrupted attempts and refusing real data until a complete source receipt exists. Calendar/year/exposure diagnostics include marked P&L, costs, drawdown and both forced legs; no new risk limits or outcomes.
- Found one stale 2019 CSV and four inconsistent 2020 aggregate totals. Their original dated PDFs independently validate dates, units, stock definition and rounded components; explicit fallback retains 0.1-million precision and every original CSV. Linked 2019/2020/2023 notices exclude changes to the commercial-crude stock field. All 53 focused reactor/source/risk/cash/holdout tests pass; the complete EIA review remains pending.
- Finished collecting all 457 EIA report pages. The June24 2026 page incorrectly says June14 publication before June19 observations; its exact archived full report explicitly dates release June24 on page ii. Added a hash-pinned publication exception using that evidence, never the URL, and tests refusing missing/conflicting proof.
- Failed C08 runs now retain partial fees, marked loss, positions and processed-through time in the ledger/artifact; completed replay is still required for selection. Preserved the deterministic rule's promotion wording without imposing the AI-decided strategy's separate paper minimum. Fifty-six focused checks pass across the affected suites; content-hash PDF text caching avoids repeatedly parsing identical methodology/errata documents.

### Longshot first category training (`tradingbot-yg2`, study still running)
- Completed all six preregistered Kalshi BTC variants under the frozen `73d02c5` implementation. Trials 3808/3810/3812 (buy-favourite offsets .01/.02/.05) net −$49.49/−$58.32/−$55.24 over 118/99/82 trades; 3815/3817/3819 (sell-longshot) net −$49.49/−$58.87/−$43.04 over 118/99/65 trades. No positive-net training candidate, so this category's final remains unconsumed. Four other categories remain in the grid; this is not study completion.
- Stored all six summaries, source hashes, risk/regime metrics and the partial receipt audit in `20-longshot-btc-training.json`. The first four completed variants independently reconcile 1,299 fills to native prints, fees and terminal cash with zero residual. Their remaining counterparts await the complete-study receipt audit. The .01 buy/sell pair shares all 250 entry execution identities with complementary prices/equal sizes: correlated economic exposure, not two independent replications. No execution/risk code or live state changed.

### C08 Amendment 21 source preparation (`tradingbot-8lk`)
- Claimed the reopened USO inventory candidate and preserved original source failure 3550. Fixed the unchanged interval, thresholds, cost cases and holdout boundary before outcome inspection.
- Added a bounded, resumable EIA archive collector and strict commercial-stock field checks. Actual report publication dates, delayed releases, PDF units/methods and errata precede source admission; no inventory signal or return is computed.
- Flagged Amendment 21's split payable-date ambiguity for a common clarification: USCF proves April28 conversion/April29 trading, not an Alpaca fractional cash date. Shared execution dependencies remain untouched during the active longshot frozen run.
- Validation: 18 focused C08 source/publication checks pass. The first bounded capture is in progress; no source admission, strategy replay or holdout claim.
- Captured free raw USO SIP/IEX references (2,198/1,554 sessions). Actual-share Yahoo open/close agrees with every SIP bar within the unchanged 1% diagnostic bound. Primary Arca closing prints resolve the sole IEX close outlier at $2.81 without changing a price; IEX open differences remain separate-venue diagnostics. Twenty-one source/auction checks pass.
- After an EIA transport timeout, retained completed captures and resumed with bounded retries/four report workers; the full 457-report source collection and blackout endpoint clarification remain in progress. No strategy returns or final admission.
- Resolved the blackout endpoint with the archived Alpaca USO action: payable/ex/process dates are April29. Together with the timely issuer announcement, unchanged Amendment21 yields April27 decision, April28 exit, April30 re-entry; two training sessions are blacked out and no fractional cash credit is assumed.
- The first 22 EIA bundles pass independent PDF/CSV date/unit/rounding and archived-methodology checks. Fixed excessive per-request full-tree disk scans by using existing coordinated periodic scans/reservations plus atomic capture completion, preserving storage gates and saved responses. Twenty-five source/blackout checks pass; full source audit and all strategy returns remain pending.

### Daily autonomous session (07:30)
- **Health:** Postgres is up and the 03:15 backup was written (2.2 GB; only pg_dump warnings about circular foreign keys). The watchdog shows no problems since the 09-30 morning start. The ntm swarm is running with 4 panes. The TOM paper runner (trial 3298) is alive and waiting for its Oct 27 entry. Incident 921, the weekly LaunchAgent blocked by macOS Documents access, is still waiting on the owner. No new incidents.
- **Triage:** `br ready` was empty. Two panes were idle, and the nudger was pinging pane 2 every 10 minutes for nothing. Only `yg2` (OrangeCove) was in progress. Five of the eight Alpaca candidates (C02, C03, C05, C07, C08) had stopped at their data gates, waiting on corporate-action or dividend-cash evidence that free sources cannot prove.
- **Unblock:** wrote [amendment 21](docs/research/21-corporate-action-blackout.md) before any outcome inspection. Positions are flat from the open before each unresolved split, reverse split or in-kind ex-date through the payable date. The action must have been announced before the exit decision, or admission fails. Added `tradingbot.research.action_blackout` with 8 passing tests.
- **New beads:** C08 `8lk`, C05 `qdd` and C02 `0qk` (P1); C07 `pdw`, the C03/C04 re-audit `y2d`, and batch-2 preregistration `5n1` (P2). No agents were added: the existing idle panes now have ready work. No §6 change, no keys and no promotions.

### Longshot replay preparation (`tradingbot-yg2`)
- Froze the full 74,768-outcome reference manifest and explicit 53-contract exclusions, verified twelve capture receipts, and protected the six legacy trials with a full-row hash. Added the full-history CLI with exact decimal tape caches, post-blackout marks, durable training admission, once-only final admission, immutable identity/selection checks, execution receipts, accounting reconciliation, date-aggregate p-values and calendar/price-band metrics.
- Added source-admission and written account-risk review in `20-longshot-preparation.md/.json`. The affected suite passes 56 checks; 24 focused driver/runtime checks also pass after different-price fractional-entry and fee/risk-identity verification. This slice prepares the fixed 30 training variants without reading expanded-cohort returns or consuming a final.
- Added a prediction research runtime over the shared strategy, RiskEngine and Ledger. It verifies binary identities, reserves held/pending collateral (including short liability), parks exposure above the virtual slot, uses observed UTC marks for permanent/day loss limits, and records marked drawdown and simulated halts without changing live state. Known blackouts cancel before later prints; surprise-price risk is evaluated after existing orders meet the print.
- Public execution identities accompany simulated fills; available volume rounds down to ledger quantity precision. Identical repeated rejections retain one ledger order plus the complete attempt count, preventing millions of redundant rows. Twelve new synthetic book checks pass; the combined affected suite passes all 44 checks with one existing SDK deprecation warning. No real-data strategy replay yet.
- Preregistered the fixed cohort, full-source 70/30 boundary, declared anomaly exclusions, six training variants, binary-contract grouping, collateral/risk accounting, calendar/price-band reports and single selected final per category in `docs/research/20-longshot-plan.md`. Source-only timestamp checks distinguish Kalshi contract metadata from event aggregates; no expanded-cohort strategy returns or holdout consumed.
- Fixed the generic backtester to require a strictly later timestamp for maker fills and apply terminal settlements chronologically, canceling remaining orders before later events. Simulated order timestamps now use the replay clock. The longshot driver defers price-feed loading until after durable final admission.
- Validation: 23 causal/admission/driver checks and 9 equity/report compatibility checks pass; all 7 generic backtester tests pass again after settlement order timestamp verification. No risk-limit values, funded allocation or live trading state changed.

### Full historical capture verified (`tradingbot-oma`)
- Completed the frozen thirteen-month Kalshi/Polymarket international cohort: 35,762 complete request chains, 40,353 compressed pages, 37,384 contracts and 74,768 outcome instruments. Independent source, load, physical-row and monthly audits reconcile 10,149,700 stored trade rows; every category has observations in all thirteen months.
- Full venue replays matched 10,324,572 normalized observations with zero inserts, identity/reference changes or new documents. The 174,872 repeated Kalshi outcome observations do not create extra rows. All 100 chunks older than seven days are fully compressed and both scheduled policies are enabled; current physical sizes are reported separately from compression statistics.
- Saved `docs/research/08-history-capture.md` and its JSON audit, including twelve hashed receipts, source/eligibility counts, date gaps, five positive-volume contracts with empty complete tapes, eleven invalid catalog intervals and the two unverified payouts for one condition. No missing records or settlement labels were invented.
- Final budget snapshot: `data/` 1,022,950,624 bytes; 106,059,444,224 bytes free. Capture/load kept the strict 20 GB ceiling and 30 GB abort floor. Focused capture/storage/loader checks and final reconciliation assertions passed. No strategy returns, holdout attempt, promotion, capital/key changes or PRD §6 edits.
- Pushed the completion audit as `1521567`, closed `tradingbot-oma`, and claimed `tradingbot-yg2`, the sole next ready P1. Its handoff records the fixed cohort and required source-anomaly/holdout treatment before any return analysis.

### Historical catalog coverage and chronology (`tradingbot-oma`)
- Added scheduled-close date coverage separate from event/contract counts, plus database reporting of invalid Polymarket catalog trading windows. Seven cohort/storage checks pass, including sibling-strike versus duplicate-event/date counting.
- Preserved and documented two empty Kalshi daily BTC catalog dates, Polymarket date gaps, two NYC weather events on May19 (one with eleven reversed opening/closing windows), and a January19 index event closed early on January17. Raw cohorts stay unchanged; no outcome replay or replacement event selection.

### Historical capture recompression verification (`tradingbot-oma`)
- Fixed the final storage pass to revisit eligible chunks already marked compressed, folding in late historical inserts. Space reservations now include both rowstore and compressed storage.
- Six cohort/storage tests pass, including a real Timescale late-insert regression: the pass restores fully compressed state, preserves 1,100 rows and their sum, and is repeatable. Test objects roll back; the live import is still running and final compression awaits completion.
- Documented the precise one-condition Polymarket payout gap: resolved lifecycle versus proposed Gamma catalog, with separate source hashes. No oracle proposal/display price is promoted into an unverified token payout.
- Profiled the growing archive: a full 124,000-entry disk scan took 9.6 seconds, compared with 1.0 second for a 622-point strict database comparison. Future load passes scan every 128 pages or after 30 seconds; the current pass continues unchanged. Both disk floors, free-space checks before/after every page, and capture-write reservations remain unchanged.
- The capture uses 128-job batches with a checkpointed restart to reduce duplicate scans. Worker/request-rate caps, 30-second/128-write scan gates, per-page reservations, exact cohort and immutable archive reuse are unchanged.
- Fifteen capture/disk-budget checks pass. The old capture exited through its normal interruption cleanup; the restart receipt hashes its cache and unchanged cohort before resuming 28,416 completed jobs. The database loader continues independently.

### C08 USO inventory source audit (`tradingbot-m2d`)
- Captured the exact 2018–2026 USO source (2,198 complete sessions) and ten total Yahoo/EIA source responses, including dated delayed-release examples and linked tables. Hashes and the unchanged 2024-02-15T12:00Z cutoff are committed; first-release macro vintage and full exposure/price checks remain uncompleted.
- Stopped before scarcity signals or returns because the issuer's 2020 fractional split treatment and conflicting Alpaca documentation do not establish retained shares versus cash-in-lieu or spendable-cash timing. All four training cases and the final remain unattempted; no promotion or §6 changes.
- Added a source-only failed-trial recorder and written decision/blow-up record. Ten focused publication, integrity and ledger checks pass.
- Source/code `e6e464d` pushed; failed trial 3550/strategy 6082 independently verified with null performance, zero allocation/orders/fills/finals. Closed the bead under its explicit data-failure route; no next ready issue remained.

### C07 sector reversal source admission (`tradingbot-a9d`)
- Verified the original nine sector captures (5,218 sessions each), SPY open/close amendment and fixed 2006–2026 bounds before any rankings or returns. The XLF action receipt and primary hashes still fail fractional allocation/delivery/cash evidence; the closed repair bead does not admit the dataset.
- Recorded a candidate-specific DATA_FAIL decision and written account-risk analysis. Three variants, all six training cases and the final remain unattempted; performance/drawdown/regimes/luck are null, not zero. No promotion, source rewrite, parameter/risk change or new allocation.
- Eight focused source/ledger tests pass, including tamper rejection, fixed holdout boundary and idempotent failed-trial recording without holdout consumption. Audit code is committed before recording the real ledger receipt.
- Committed audit `bc4758f` records failed data trial 3548 (strategy 6080, idea, $0 allocation). Verified repeated recording returns the same sole trial, all performance fields remain null and no final is consumed. The read-only-source CLI preserves the recorded trial identity on repeated checks; closed the candidate under its data-failure acceptance.

### XLF in-kind evidence and disposal declaration (`tradingbot-vx0`)
- Archived and visually verified the issuer's signed Form 8937; reconciled its tax values and dates with the original issuer annual report, prospectus supplement and OCC memo. Tax amounts and conditional option deliverables do not establish retail fractional cash or availability. Retained the Business Wire timeout and HTTP403 reprint response.
- Added an offline, hashed source audit preserving the exact rejected Yahoo split and Alpaca cash-dividend/record-date fields. Declared an incidental XLRE disposal and cash-availability policy before outcomes; it remains unexecutable pending documented delivery, fractional treatment and validated disposal prices.
- Closed under the bead's explicit unresolved-data acceptance: C02/C07 remain unadmitted. Thirteen focused tests passed and two offline receipt builds matched. No returns, ranks, holdout consumption, source rewrites, risk changes or new strategy trials.

### C06 month-end flow source admission (`tradingbot-kc4`)
- Completed all six preregistered training cases, trials 3541–3546. At 10 bp per side the .600/.595/.590 variants lost $26.06/$19.40/$15.84 after costs; 61/38/31 round trips and max marked drawdowns $26.85/$24.71/$22.34. All 5 bp cases also lost. No profitable variant was selected and no final holdout was consumed.
- Preserved exact metrics, monthly-block luck estimates, calendar/annual regimes, flow-window and buy-and-hold diagnostics in the frozen training receipt and result report. Independent DB readback confirms completed trials, flat positions, zero rejected orders, entry limits below $140 and zero final trials. Decision: stop/hold the family; no retuning or paper/live promotion.
- Added the causal SPY/IEF month-end reactor and a source-bound adapter through shared RiskEngine/Ledger. Decision targets stay frozen; actual scenario orders obey settled cash, reserve, fractional minimum, current fees and the unchanged equity slot. Holdout claims precede lazy feed consumption; frozen-version mismatch and repeated CLI final attempts refuse without data iteration.
- Completed the idea-to-backtest risk/checklist record. All 29 source/reactor/runner and existing equity-runtime checks pass together, including gap halts, fee/cash reconciliation, intraday partition cutoff, yearly marked P&L and guarded final preflight. Fixed the failed-preflight ledger registration caught by the synthetic test. No real-data strategy outcome or holdout in this implementation slice.
- Froze SPY's explicit open/close amendment with IEF's 5,218 fixed Yahoo sessions and 248 reconciled issuer distributions. Exact issuer ex-dates match; amounts differ only within the existing rounding rule. Independent IEX/SIP closes pass the unchanged 1% bound across 1,553/2,701 sessions; Stooq's HTTP404 is archived and independent pre-2016 coverage is not claimed.
- Recorded immutable source hashes, unchanged 70/30 cutoff, cash/price policies and prior-inspection limitations before candidate outcomes. All 247 calendar-eligible SPY round trips avoid dividend entitlement; the source guard refuses a future collision until the execution ledger supports it. Ten parser/reconciliation checks pass and the source build reproduced identical hashes; no strategy returns or final attempt in this slice.

### C05 commodity ETF trend source audit (`tradingbot-9ri`)
- Captured the fixed free GLD/SLV/USO/UNG/DBA histories: 4,716 official sessions each, six split events and seven DBA distributions. Exact responses, dates, adjustment policy, code dependencies and 2021-02-14 14:24 UTC cutoff are hashed; no signal or strategy outcome was computed.
- DATA_FAIL at fractional-action treatment: five archived USCF reverse-split notices specify fractional cash-in-lieu, while Alpaca's captured 2021 fractional-share announcement and current delayed-DTC-cash documentation leave the applicable account treatment unresolved. OCC supplies a USO cash rate but not an Alpaca credit date. Preserved blocked HTTP attempts and web-only supplemental evidence without claiming complete issuer/price admission.
- Added source audit, receipt and account-risk decision. Eight focused tests pass, including split numeric normalization, missing evidence, provenance and idempotent failed-trial recording. All six training cases and final remain unattempted; performance fields remain null. Code/source slice precedes the durable ledger receipt.
- Recorded source-failure trial **3518** for strategy **6032** against committed code `5c6f253`; independent DB readback confirms one failed trial, null performance, zero orders/fills/finals and `idea` status with zero allocation. Closed the attempt under its data-failure stop rule; source/action amendment and remaining admission checks are required before any future replay.

- Closed shared source repair `900` with SPY open/close-only validation and explicit unresolved XLF admission failure; the in-kind fractional/disposal evidence is tracked in `vx0`. Prior failed trials and consumed holdouts remain unchanged. Claimed next ready C06 `kc4`; its IEF reference-source admission precedes any candidate return calculation.

### Frozen SPY source amendment (`tradingbot-900`)
- Validated a source-only SPY bundle with 5,218 open/close observations and 83 issuer distributions, unchanged sample/holdout bounds and no strategy outcomes. Bound exact inputs, conservative cash timing, build code and derived data to immutable hashes.
- Added an opt-in, exact-hash/exact-row payment amendment for the June2006 issuer error; the original workbook and strict default failure remain intact. Alpaca independently corroborates the December2021 issuer amount/pay date.
- A broader opening-price audit found Yahoo's November7 2016 open equals the previous close; primary Arca opening trades prove $211.47. The correction is explicit and all original prints remain archived. High/low/volume/adjusted close are excluded from the new source scope; the existing 1% overlap threshold is unchanged. All 44 focused checks pass. XLF fractional distribution policy is still not admitted.

### C03 cross-asset momentum source audit (`tradingbot-wn9`)
- Captured exact free Yahoo SPY/IEF/GLD/EFA/VNQ daily sources and immutable receipts. Each has 5,218 official sessions with no missing/extra/null/invalid rows or recorded splits; dividend event counts are 83/248/0/40/83. Fixed 2006–2026 bounds and 2020-07-10 14:24 UTC holdout cutoff remain unchanged.
- DATA_FAIL before ranking/replay: the unchanged primary SPY workbook has a payment date before its record date. Shared repair now supplies a reconciled settlement schedule and proposed SPY correction, but its amended action/price/cash policy remains unadmitted. Remaining issuer and independent price checks are explicitly incomplete after the failed gate.
- Added a reproducible source audit, provenance receipt and written risk/decision record. Seven focused tests pass, including failed-trial idempotence/no holdout consumption. All six planned training cases and the final remain unattempted; P&L/fees/trades/drawdown/regimes/luck remain null. Code/source slice is committed before the durable failed-audit ledger receipt.
- Recorded failed source trial **3516** for strategy **6030**, bound to committed audit code `08768a5`. Database readback confirms one trial, null performance, no orders/fills and no final attempt; strategy remains `idea` with zero allocation. Closed the candidate attempt under its data-failure stop rule; shared repair and remaining source checks are prerequisites for any documented retry.

### Historical tape DST identity repair (`tradingbot-oma`)
- The actual Polymarket idempotence pass stopped on a false conflict at November2 2025 09:49:33 UTC: PostgreSQL returned the same instant in the repeated Los Angeles hour, where Python cross-zone datetime equality rejects an otherwise identical value.
- Compare timestamp fields as exact UTC instants while retaining all other value/evidence checks. Two rollback-only PostgreSQL tests cover both repeated-hour instants and reject a one-hour change; a unit check also rejects a one-microsecond change. All 20 loader/cohort checks passed. Full idempotence validation continues before capture handoff.

### Equity settlement evidence (`tradingbot-900`)
- Reconciled a finite 2006–2026 schedule from FINRA annual calendars and DTC/NSCC notices. All 291 applicable modern T+1 workbook pairs match; independent session comparison identifies 37 bank-only closures and five exchange-only closures in the fixed sample.
- Preserved and corrected the FINRA November10 2023 conflict using DTC's specific schedule. Recorded June29 2026 settlement rollover to June30 separately from the nominal calendar; proposed cash convention waits until the next regular-session open after completion.
- Added hashed evidence and finite-calendar validation; 32 focused checks pass. Expanded the immutable receipt to 114 HTTP archives and nine Alpaca diagnostic pages, retaining the previous receipt hash and provider corporate-action conflicts. No strategy outcomes, source admission, holdout reuse or risk-limit changes; XLF fractional treatment remains unresolved.

### Encrypted weekly review build (`tradingbot-v0w`)
- Added a read-only weekly report over the ledger, every new trial (including failures), cumulative final holdouts and audit annotations, drawdown/regime breakdowns, promotion/ready queues, incidents/halts, beads and intake log. Live/paper realized P&L and weekly completed trips remain separate; independent backtest variants are never aggregated into account profit. C01 is explicitly FAILED AUDIT.
- Pinned StatiCrypt/Wrangler with a lockfile. Every report is encrypted in a private temporary directory, decrypted locally for exact verification, and reduced to an allowlisted three-file upload bundle. Password/venue secrets never enter command arguments or uploaded source; initialized the previously blank report password only in gitignored `.env`.
- Added a Friday 14:00 local LaunchAgent, deployment/remote-content verification command and operations guide. Eight focused tests pass, including week boundaries, fees, multipliers, failed audits, HTML escaping, encryption round trips and secret exclusion. Initial local build: 40 trials / 3 final holdouts. Cloudflare deployment and schedule verification follow in the completion slice.
- Published the encrypted report to `https://tradingbot-weekly.pages.dev`; Cloudflare reports success and the served file matches the local ciphertext exactly. The upload contains only encrypted `index.html`, `_headers` and `robots.txt`; no plaintext intermediates remain. Added current evaluation-verdict precedence (the JEVUP index was stale), with all nine focused tests passing. Browser automation is unavailable on this session; the deployed HTML/password input and response security headers are verified directly.
- **Ops blocker (incident 921):** installed the Friday 14:00 calendar, but the first kickstart stalls in `uv` before Python while opening the Documents project. `tccd` records a denied Full Disk Access preflight (`kTCCServiceSystemPolicyAllFiles`, `authValue=0`) for `/Users/USER/.local/bin/uv` with an unsigned identity. Starting from HOME with an explicit project also stalls. Stopped only the weekly test, restored the standard launcher and kept its schedule loaded; no macOS permission changes. Owner review of filesystem access is required before unattended publication can be verified. The existing TOM launchd process is also still in uv; its owner was notified, with no trading-job restart performed. Refreshed the encrypted page to include this incident and the blocked bead; HTTPS ciphertext verification passed again.

### Pivot to Alpaca-first, open-minded research (owner grilling)
- Both Polymarket US keys return `401 API key not found`. Our signing and endpoint were checked and are correct; the owner is contacting Kalshi and Polymarket US support for verification. Prediction-market live work is deferred.
- PRD changes made by the owner:
  - Venues: Alpaca only for now. A futures broker will be researched and opened for research only.
  - Data budget: $0.
  - Edges: open-minded. The LLM-alpha non-goal is removed.
  - §6: the per-position cap for equities, ETFs, options and futures is now the strategy's slot. Prediction markets stay at $25.
  - §4: the last 30% of each dataset is a locked holdout. AI-decided strategies need a forward paper run of 7+ days and 30+ trades.
  - Weekly page: StatiCrypt on Cloudflare Pages, Fridays after the US close.

### Robinhood Chain memecoin base-rate = FAIL → intake Reject (`tradingbot-x6a`)
- Ran the pre-registered Stage-1 base-rate backtest of the "JEVUP" dumb gated snipe rule on real Robinhood Chain on-chain data — **read-only, no Jev, no wallet, no money**. Chain constants verified from official sources only (chain self-reports id 4663 via `eth_chainId`; Uniswap V3 factory from Uniswap dev docs; WETH from docs.robinhood.com) — never from the referral post.
- Public RPC is pruned (no historical state), so price/reserves/liquidity/ownership are all reconstructed from event logs. Chain is a firehose of pools (~hundreds of thousands); universe sampled timeline-uniformly (a dedicated/archive provider would need an owner-approved API key).
- Result (run `stage1-20260930`, 2,400 sampled / **242 qualifying** WETH-quoted launches): mean net return **≈ −59%/launch** across **all five** pre-registered exits (hold 5m/1h/24h, TP+100%/SL−50%, trail −40%), one-sided **p ≈ 1.0** (Holm-adjusted), **negative in every monthly regime**; ~70% of qualifying launches couldn't be sold within 24h (honeypot/dead-on-arrival = −100%). Pass bar (mean>0 & Holm p<0.10 & ≥200) → **FAIL**.
- Intake verdict **Park → Reject** (no revisit without new evidence). Stage 2 (Jev paper, `tradingbot-rb1`) and Stage 3 (live) do not proceed; `rb1` closed as won't-do.
- New: `src/tradingbot/research/robinhood_chain.py`, `robinhood_memecoins.py`, 17 unit tests, `docs/research/08-robinhood-chain-memecoins-{plan,results}.md` + results.json. Trials ledger: strategy `rhmeme_fbc4716d6e221e8238b36eac` + 5 `Trial` rows. Commits `85d1638`, `87904f0`.

### #6 slot-sized locked holdout and control (`tradingbot-gat`)
- Frozen primary training 3277 earned $63.483911 / 90 trades; the single final holdout 3282 earned $11.409438 / 38 trades after costs, max marked drawdown $23.734629 (16.95% of $140), p=0.2642. Both share one strategy version; the final was consumed once. Training-only 5/10 bp trials 3279/3280 also passed; they were not evaluated on the holdout.
- Random-window diagnostics 3278/3281 show the calendar premium reversing: final TOM mean net 20.61 bp versus random 5/6-interval means 35.50/41.28 bp. Final profit depends on three below-trend entries; 35 above-trend entries lost $1.47. Documented prior full-sample inspection, model limits, regime breakdown and full account-risk/promotion record; no calendar-edge or ready-for-live claim.
- Added explicit slot-paper preparation from matching profitable training/final trials, preserving original trial parameters and refusing supersession if there are prior attempts, orders, fills or holdings. Existing simulated cash cannot be increased/reset. Same evaluated strategy source and current §6 limits remain unchanged.
- Validation: 17 focused forward integration/unit tests passed, including wrong-version/unprofitable evidence and refusal to replace used trials. No holdout rerun or live order.
- Prepared **paper trial 3298** linked to 3277/3282; superseded unused 2344 without rewriting its parameters. Verified zero orders/fills at transition and passed a one-step runner check. Loaded the existing paper-only LaunchAgent, first entry Oct 27 / exit Nov 4. Closed `gat`; future fidelity is explicitly deferred as `78y`, with no ready-for-live claim. Claimed next-ready `lwv` free-options-data research while `oma` continues; `k1e` broker comparison belongs to NavyLantern.

### History-capture connection reuse (`tradingbot-oma`)
- Keep one public SDK connection pool per worker/venue across jobs and storage batches; previously each contract closed its pool and repeated connection setup. Request pacing stays at four per second with four workers, and every disk gate/resume check is unchanged.
- Validation: 15 capture/disk tests pass, including reuse across the 32-job batch boundary and client cleanup on an HTTP failure. Saved pages remain the resume authority.

### Free options research archive (`tradingbot-lwv`)
- Added `data.alpaca_options` GET-only SDK harness for explicit active/inactive contract catalogs, current indicative chains/quotes and bounded historical bars/trades. Exact JSON, request/retrieval/checksum/cursor provenance stays in compressed Parquet; resumable symbol-first pagination and global 20 GB/30 GB disk reservations are enforced.
- Preserves contract sizes/deliverables and dated open interest; records quote age/availability, incomplete/empty responses and missing symbols. No current catalog is relabelled historical chain membership; no indicative snapshot or trade is used as executable historical BBO. Historical endpoints expose no feed selector and are labelled provider-unspecified.
- Free read-only sample: F/SPY current chains 206/458 snapshots; expired SPY Feb16 2024 catalog 362 contracts; two Feb2024 option contracts return 22 daily bars and 37,107 trades across four complete pages; four explicit latest indicative quotes. Eight queries / 11 pages, with response-set hashes in `10-options-data-harness-results.json`. No account, entitlement, order or paid API action.
- Documented cash-account size/collateral implications, missing options execution/assignment modeling, and short-history limitation: even complete Feb2024–Oct2026 coverage leaves only 291.9 days in its final 30%; the actual two-week sample is not a multi-year strategy dataset. Validation covers free-feed/GET allowlist, exact prices, scope filters, resume, repeated pages, empty/missing data and global disk containment.
- Final verification: 12 options tests pass; the independent audit rechecked all 11 real pages (38,823 records) including request scope and checksums. Closed `lwv` and claimed next-ready `wri` (C04 inverse-variance SPY); `oma` capture/import remains active.

### C01 SPY monthly trend — original results superseded by `bbw` audit (`tradingbot-8yz`)
- New free-data slice: `data.free_history` fetches/archives Yahoo daily bars (raw response + URL + UTC retrieval ts + sha256, re-verified on load; coverage validated before any return). Captured SPY 2006-01-03..2026-09-30 (5218 sessions, 0 splits, 83 dividends). Stooq cross-check unavailable (JS/bot challenge) → Alpaca IEX 2016+ overlap documented; no feed switched to rescue a result.
- C01 Faber long/cash monthly SMA: pure rule (`strategy.spy_monthly_trend`) + causal backtester (`research.c01_spy_monthly_trend`) — next-open execution, EquityFeeBook 2026-09-17 + 5/10bp slippage, T+1 settled cash, 95% cap, fractional round-down + sub-$1 skip, dividends on a payment-date proxy, trade-only-on-signal-transition, terminal liquidation. Locked 70/30 via shipped `HoldoutSplit` (dataset `sweep-c01-v1`, cutoff 2020-07-10T14:24:00Z, matches candidate index).
- The original simulator recorded all six variants positive and selected **L=8** (+$315.82 training, +$68.07 final). Its claimed PRD §4 pass and single-use/mechanical correctness were later withdrawn by `bbw`; risk/cash/admission failures also invalidate a clean benchmark-drawdown conclusion. Numeric outputs remain as legacy evidence. **FAILED_AUDIT; hold in research, do not promote.**
- Disclosed: SPY history overlaps prior #5/#6 inspection (contaminated, not pristine holdout); a reporting-only JSON bug preceded the canonical run (selection is training-only, holdout deterministic; prior trials cleared so the ledger holds one clean version). 24 new tests pass. Docs: `docs/research/09-c01-spy-monthly-trend.md` + results.json. Ledger: strategy `sweep_c01_spy_monthly_trend`, trials 3313–3319.
- Intake: the Opus+Jev v2 (AgenKit) prompt was evaluated. Verdict **Salvage**: no strategy and AgenKit is rejected. Kept: Brier/reliability calibration logging for AI-decided strategies, a holdout-reuse guard against self-improvement loops, and Sharpe/drawdown/hit-rate/t-stat shown for information.
- Coordinator: added a research data standard to AGENTS.md (adjusted total-return series cross-checked between two free sources; exact corporate-action mechanics only at paper/live; lean docs). This unblocks the candidates stuck on `blocked:source-evidence`. Moved the TOM paper runner, weekly page and nudger from launchd into a tmux `services` window, because launchd-spawned uv/Python is blocked by macOS TCC and the TOM runner had stalled for 16h.

## 2026-10-02

- Intake: the Jev trading repos and playbook posts were evaluated. Verdict **Salvage**: the repos are rejected (Monad, Hyperliquid and OKX are not tradeable for us; sub-second races; no evidence). The Jev gateway claim was checked and not confirmed: Jev isn't listed on Cloudflare Workers AI or Vercel AI Gateway. Added two forward-paper AI candidates: AI-1, an LLM trade-gate A/B, and AI-2, an LLM analyst basket. Both use headless Claude, so no new keys are needed.
- The owner added a Jev API key; connectivity was verified (0.11 s, about 340 tokens per call). Added the `typesafe-sdk` dependency, a Jev wrapper bead with the $20/month cap, and made Jev the decider for AI-1 (a three-arm A/B: ungated vs Jev-gated vs Claude-gated) and AI-2. Added a 4th agent on the owner's second Codex subscription (Business plan with credits).
- Removed the 4th Codex agent: the second subscription is out of credits too. The Jev wrapper bead (`3mj`) returns to the pool.
- Jev strategy suite planned with the owner: J1 gate (QuantDinger-style), J2 menu trader (Beebots-style), J3 news reactor, J4 regime switcher. All run intraday on Alpaca paper with virtual random twins. Patterns taken from a survey of five public Jev repos, none of which publishes profit evidence. Beads created; the Jev wrapper (`3mj`) was already done.
- Intake, three submissions:
  - **Coinbase agent skill:** parked as a futures venue candidate. Its MCP asks for all OAuth scopes and allows uncapped x402 spending, so it's not used.
  - **je-suis-tm/quant-trading:** salvaged as a pre-registered batch of 8 classic TA rules, with default parameters, costs and a holdout.
  - **RohOnChain CLAUDE.md:** a duplicate of the AgenKit prompt; no action.

## 2026-10-05

- Added X bookmarks intake: `ops/x_bookmarks.py` reads the owner's bookmarks read-only via browser-harness and their logged-in Chrome. The daily session now evaluates new ones through the intake rubric. First pull: 5 bookmarks.
- Undeferred AI-1/AI-2 now that J1–J4 are built and live on paper.

## 2026-10-07
- Daily session: health OK (pgdump ok, swarm alive with 3 Claude agents, no ready beads). Intake of 3 X bookmarks (1 reference, 1 skipped, 1 bead for PBO/deflated-Sharpe tooling).
- Coordinator: froze shared paper-execution code from Oct 8 to Oct 15 (incident fixes only) so the J1–J4, AI-1/AI-2 and C05 cohorts admitted on Oct 7–8 can build their 7-day/30-trade records without more rollovers.
- The nightly backup now keeps only data that can't be recreated (owner decision): it excludes the row data of the historical `trades` tape, which is re-downloadable. The dump went from 2.2 GB to 130 MB. A test restore into a scratch DB matched live row counts for orders, fills, trials, holdout spends, Jev requests and strategies. Removed the two old 2 GB dumps; free disk +4.3 GB.

## 2026-10-08

- **Incident:** the tmux server died about 07:41 PT, taking the whole tradingbot session down for about 6 hours, which covered most of the trading session. Services now run in a dedicated `tradingbot-svc` tmux session that `ops/services.sh` (called by the watchdog every minute) recreates whenever a tmux server exists. Agents were respawned (3× Opus). No change to frozen execution paths; cohorts were not rolled.

## 2026-10-09

- Intake batch: **IBS mean reversion** on QQQ/SPY (Pursue, pre-registered backtest); **Gotobi-day yen flows** (Pursue as research; trading parked until an FX/futures venue exists); the "Claude funnel" posts were rejected (no rule, selection bias).

## 2026-10-12 (daily session)
- Health: ntm session `tradingbot` running (4 panes, idle); no new incidents; watchdog log last entry 2026-10-08. No commits since yesterday; `br ready` empty (nothing actionable).
- X bookmarks: `ops/x_bookmarks.py` did not finish within 2 min (Chrome/harness likely unavailable); skipped, not an incident. No new intake entries.

## 2026-10-13 — Alpaca live connector (`tradingbot-l3r`)
- New `src/tradingbot/connectors/alpaca_live.py`: `AlpacaLiveConnector` with the paper connector's public interface. It uses `mode='live'` and its own cash book (`Venue.metadata[alpaca_live_v1]`).
  - **Transport:** `AlpacaLiveAPI` reads `ALPACA_LIVE_KEY`/`SECRET`, refuses to run without them or with a paper `PK` key, and is pinned to `api.alpaca.markets`. It has no transfer or withdrawal methods.
  - **Account:** cash accounts only (multiplier 1, no shorting); a paper account number is refused.
  - **Risk:** orders need a running live trial and go through the unchanged §6 `RiskEngine` in live mode.
  - **Kill switch:** persistent. CLI `kill`/`clear-kill`/`status`. Engaging it cancels open live orders and logs a critical `kill_switch` incident; clearing it needs a note.
  - **Dry run:** runs every gate and sends nothing.
  - **Fees:** each live fill records a conservative per-fill ceiling of the dated SEC/TAF/CAT fees.
- Tests: 13 new, using a fake broker, rolled-back Postgres and a dry-run payload comparison against paper. The connectors suite passes (130).
- No frozen file was edited (`alpaca_paper.py`, `alpaca_api.py`, `forward/`, `ai/`, `risk/`), so no cohort rolls. No live keys exist, and no live request was made.
- Follow-up bead `tradingbot-a90`, deferred to Oct 16: unify the paper and live connectors, reconcile actual FEE activities, show the kill switch on the dashboard, and add an owner-approved path for increasing capital.

## 2026-10-13 (daily session)
- Health: ntm session `tradingbot` up (4 panes, all idle); watchdog quiet since 2026-10-08. `br ready` empty, no commits since yesterday's changelog. No incidents.
- X bookmarks: `ops/x_bookmarks.py` did not finish within ~3.5 min (Chrome/harness likely awaiting approval); no new entries. Not an incident; retry next session.

## 2026-10-14 (daily session)
- Health: ntm session `tradingbot` up (4 panes idle); `tradingbot-svc` 8 windows up; launchd jobs loaded. Watchdog log silent since 2026-10-08. `br ready` empty; no new commits except ops/secrets work on Oct 13. No new incidents.
- X bookmarks: 5 new scraped; all rejected/skipped (`docs/strategy-intake/2026-10-14-x-bookmarks-batch.md`). No beads.

## 2026-10-16 (daily session)
- Health: worker panes 0.1-0.3 exit every hour and are respawned by agent-recovery (24 incidents logged); no agent is staying alive. Ready beads: v2i (IBS QQQ paper runner, freeze over), a90, s4s (owner decides).
- X bookmarks: 1 new (@RohOnChain promo post), skipped at gate 1.

## 2026-10-18 (daily session)
- Health: ntm session up (4 panes idle). Watchdog shows no agent-recovery respawns after 04:26 UTC, so the login-shell fix (coordinator, Oct 17) holds. No new incidents.
- Work: `br ready` has only s4s (XYLD, owner decides; agent recommends no slot). Nothing to advance.
- X bookmarks: 5 scraped, 0 new.

## 2026-10-19 (daily session)
- Health: ntm session up (4 panes idle); `tradingbot-svc` up. Watchdog silent since 2026-10-18 04:26 UTC. No new incidents.
- Work: `br ready` has only s4s (XYLD, owner decides). No commits since yesterday. Nothing to advance.
- X bookmarks: see scrape result; no new entries to evaluate.

## 2026-10-20 (daily session)
- Health: ntm session up (4 panes idle). Watchdog silent since 2026-10-18 04:26 UTC. No new incidents.
- Work: `br ready` has only s4s (XYLD, owner decides). No commits since yesterday. Nothing to advance.
- X bookmarks: 5 scraped, 0 new.
