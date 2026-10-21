# Gotobi-day USD/JPY: preregistration (`tradingbot-z1t`)

2026-10-09, FoggyOwl. **Research only.** No venue, account, key or order. The
trade happens around 03:00–12:00 JST (US evening), so it cannot run on Alpaca
(no FX; FXY is closed). A pass is evidence for funding a futures/FX venue. It is
not a promotion. One plan file, one results file
(`51-gotobi-results.md`). Source: intake
`docs/strategy-intake/2026-10-09-ibs-gotobi-funnel-batch.md` §2.

Written before any FX price was captured or any window return computed. Prior
work this design leans on (so the result is not independent of it):
- Ito & Yamada (2017, *JIE*), "Puzzles in the Tokyo fixing": pre-fix order flow
  is biased toward buying dollars, so the price pattern is predictable.
- Bessho, Sugimoto & Suzuki (2023, arXiv 2301.13204), EBS minute data 2018–2020:
  - On gotobi days USD/JPY rises from about 03:00 JST into the 09:55 fix, then
    drops just after it.
  - Long 03:00→09:55 on gotobi days: N=185, PF 1.46, win rate 0.60, after
    spread. The same trade on non-gotobi days: PF 0.51.
  - Short 09:55→12:00, taken only when the 03:00→09:00 move is positive:
    PF 2.09.
  - Their 2018–2020 sample sits inside our training period, so our training
    result there is not out-of-sample.

## Mechanism
Japanese importers settle dollar invoices on gotobi days (5/10/15/20/25/30 plus
month-end) at the bank TTM rate, which is set at 09:55 JST. Banks buy dollars
ahead of that fix to cover customer demand. Exporters' yen buying does not
cluster on those days. That is a forced, calendar-predictable flow, the kind of
structural edge PRD §3 prefers.

## Frozen calendar
- **Tokyo business day:** a weekday that is not a Japanese national holiday in
  the Cabinet Office list (`syukujitsu.csv`, archived with its hash) and is not
  a bank holiday on Dec 31, Jan 2 or Jan 3.
- **Gotobi day:** the target dates in each calendar month are the 5th, 10th,
  15th, 20th, 25th, 30th (when it exists) and the last calendar day.
  - A target that is not a business day rolls back to the nearest earlier
    business day, even across a month boundary.
  - A business day is a gotobi day if any target maps to it. In a 31-day month,
    the 30th and the 31st can both be gotobi days.
- **Control days:** all other business days, under the same weekday filter as
  the window.
- **Time zone:** JST = UTC+9, with no DST. Every anchor is a fixed UTC minute.

## Frozen windows (all three are reported; one may be selected)
| Id | Trade (USD/JPY) | JST → JST | UTC anchors | Days | Origin |
|---|---|---|---|---|---|
| W1 `open_fix` | long | 09:00 → 09:55 | D 00:00 → D 00:55 | Mon–Fri | bead/intake spec ("Tokyo open → fix") |
| W2 `early_fix` | long | 03:00 → 09:55 | D−1 18:00 → D 00:55 | Tue–Fri | Bessho et al. H1 (03:00 JST Monday is before the weekly FX open) |
| W3 `post_fix_fade` | short | 09:55 → 12:00, only if mid(09:00) > mid(03:00) | D 00:55 → D 03:00 | Tue–Fri | Bessho et al. H2, with their exact condition |

No other start or end times, no moving-average entry filter (Bessho's golden
cross is excluded), and no threshold tuning.

## Data
- **Interval:** UTC 2016-01-01 inclusive to 2026-10-01 exclusive, the same
  bounds as the other daily research.
  - Dataset key `gotobi:<source sha256>`.
  - `HoldoutSplit` 70/30 by elapsed UTC time, so the holdout starts
    **2023-07-11 04:48 UTC**.
  - A trade belongs to a partition only if both its entry and its exit fall
    inside it. Straddles are dropped and counted.
- **Primary source:** FXCM's public candle archive
  (`candledata.fxcorporate.com/m1/<PAIR>/<year>/<week>.csv.gz`).
  - Free, UTC timestamps, bid and ask one-minute OHLC.
  - Every weekly file from 2016 to 2026 for USDJPY and EURJPY is archived raw,
    with sha256 hashes.
  - Dukascopy was the intake's suggestion. It now returns HTTP 429 and points
    to a requester-pays S3 bucket, which needs an AWS account and is not $0.
    It is not used.
- **Anchor price:** the open of the first minute bar starting in [T, T+5 min).
  - With no such bar, the anchor is missing and the day drops out of every
    window that uses it (counted).
  - A bar with ask < bid or a non-positive price is invalid (counted).
  - Mid = (bid + ask) / 2.
- **Cross-check source:** HistData.com free one-minute ASCII bars.
  - Bid only, timestamps in EST without DST (UTC−5 fixed). Yearly files for
    2016–2025, monthly files for 2026-01 to 2026-09.
  - For every business day, compute each window's **bid-to-bid** log return
    from both sources, using the same anchor rule.
  - **Admission:** for each pair and window, at least 99% of commonly covered
    days agree within **5 bp** (the coordinator's research data standard), and
    common coverage is at least 95% of business days.
  - The source phase also reports the median, the 99th percentile and the
    signed mean of the per-day differences.
  - Agreement is checked on prices only. Nothing in the source phase splits
    days by gotobi status.
  - A pair that fails admission gets DATA_FAIL. No price is patched.

## Returns, costs and P&L
- **Gross trade return:** r = direction × ln(mid_exit / mid_entry), in bp
  (direction is +1 for long, −1 for short).
- **Verdict cost (`venue`): 3.0 bp per round trip, deducted from the gross mid
  return.**
  - This is an assumption, not a quoted venue fee. It roughly covers crossing a
    one-tick spread on a ~$8k micro JPY futures contract (about 1.5 bp) plus
    commission and exchange fees of about 0.5–0.7 bp per side, rounded up.
  - A retail spot account would pay at least this, because a $2 minimum
    commission on an $8k ticket is about 2.5 bp per side.
- **Diagnostic cost (`quoted`):** buy at the FXCM ask and sell at the bid, with
  no commission. This is the cheapest realistic case.
- **Break-even cost:** the mean gross bp per trade. Reported, because it tells
  the owner which venue cost would still work.
- **USD P&L:** non-compounding $140 notional per trade (the PRD §6 slot):
  - net USD = 140 × net bp / 10,000.
  - Max drawdown is reported in USD, as a % of the $140 slot, and in bp.
  - `monthly_marked_net_usd` is recorded for the overfitting checks.

## Statistics and selection (training only; USD/JPY selects, EUR/JPY replicates)
For each pair × window, on training gotobi days:
- **Per-trade results:** trade count, mean and median gross bp, standard
  deviation, and mean net bp at both costs.
- **Luck test:** win rate, then the t statistic and the one-sided p-value for
  mean net (`venue`) > 0, using `tradingbot.ledger.stats.luck_probability`.
- **Monthly luck:** the repo's descriptive 3-month block-bootstrap p-value on
  monthly USD.
- **Gotobi vs control:** the same window on control days (W3's control applies
  the same 03:00→09:00 condition). Report the control mean, then the Welch
  difference in gross means (gotobi − control) with its one-sided p-value.
- **Breakdowns:**
  - per year;
  - fixed regimes: 2016–2019, 2020–2021, 2022, and 2023 up to the holdout cut;
  - Mondays separately for W1;
  - month-end-only gotobi days against 5/10/…/30 gotobi days. This is
    diagnostic only.

**Admission (USD/JPY):** a window is admitted to the final only if all three
hold:
1. training mean net (`venue`) > 0;
2. the one-sided t-test p < 0.05 on net (`venue`);
3. the Welch gotobi − control gross difference is > 0, with one-sided p < 0.05.

Among admitted windows, the one with the highest training t statistic on net
(`venue`) is selected. If none is admitted, there is **no final**: the holdout
stays unspent and the verdict is FAIL (training).

**Final (one run, family `gotobi`):**
- Run through `tradingbot.backtest.holdout.claim_final`, which commits the
  admission before any holdout price is read.
- Only the selected window runs on USD/JPY. EUR/JPY runs the same window in the
  same pass as a replication diagnostic. EUR/JPY cannot select, rescue or veto
  anything.
- **PASS** (case for a venue) only if, on the USD/JPY holdout, all three hold:
  1. mean net (`venue`) > 0;
  2. the one-sided t-test p < 0.05;
  3. the gotobi − control gross difference > 0.
  Anything else is **FAIL**.
- The final covers only the 2023–2026 regime. Training regimes stay in the
  report.

**Multiple testing:** three windows on one pair, and the selection is
reported as such. The training trials go into the ledger with monthly series,
so `tradingbot.backtest.overfitting --dataset-key gotobi:<sha>` can report PBO
and DSR for the family.

**Trials ledger:** Strategy rows `gotobi-<window>-<pair>-train-v1` (six
training trials) and `gotobi-<window>-USDJPY-final-v1` (at most one final).
DATA_FAIL and unadmitted configurations are still logged.

## What could blow up this account?
- **Leverage:** the smallest realistic instrument, one micro JPY future, is
  about $8k notional. That is roughly 8× the whole $1k account and about 60×
  the PRD §6 slot.
  - Trading it would need an explicit owner decision on the futures position
    limit (the PRD caps futures at the slot) as well as a funded venue.
  - Nothing in this study changes a risk limit.
- **Intervention and event gaps:** MoF/BoJ interventions (2022, 2024) and
  BoJ policy surprises have moved USD/JPY 2–5 yen within minutes.
  - A 3% move against one ~$8k contract costs about $240, nearly 5× the
    global −$50 daily halt.
  - W2 is held through the US close and the start of Asian trading.
- **Crowding and decay:** the anomaly is published (2017, 2023) and widely
  discussed by retail traders.
  - Banks may pre-hedge earlier, and importers may move away from gotobi
    settlement.
  - The holdout (2023–2026) is the decay test.
- **Cost model:** 3 bp is an estimate. Asian-session liquidity in micro
  futures can be thin, and a wider real spread would erase a small edge. The
  break-even is reported for this reason.
- **Data:** a retail feed (FXCM) is not EBS, so quotes around 09:55 can lag or
  be filled in. The second source bounds this.

## Source amendments (2026-10-09, before any training outcome)
The first source run (`source-attempt1.json`, sha256 `f786ecc3…630a0d`, kept)
failed admission for both pairs: 58–62% of days agreed within 5 bp, and
coverage was 90–92%.

Everything examined to diagnose this was price-only:
- level alignment between the two sources;
- per-anchor missing and invalid counts;
- the raw quotes of the invalid bars.

No window return was split by gotobi status, and no training code ran. The
amendments below correct the harness. They do not tune the hypothesis.

- **A. HistData time zone.** HistData documents its stamps as EST without
  DST, but the files are New York local time *with* DST.
  - Every week opens at 17:00 local in summer and in winter. FXCM's UTC open
    moves from 22:00 to 21:00.
  - Median absolute bid-level difference against FXCM at the same UTC minute
    (USD/JPY):

    | Test weeks | Fixed EST (as documented) | New York local time with DST |
    |---|---|---|
    | Winter 2016 | 0.085 bp | 0.085 bp |
    | Summer 2016 | 7.118 bp | 0.195 bp |
    | Summer 2021 | 3.197 bp | 0.091 bp |
    | Winter 2021 | 0.096 bp | 0.096 bp |

  - Shifting either convention by one minute makes the match worse.
  - Fix: parse HistData with `America/New_York`.
- **B. Crossed FXCM quotes.** Under the old rule, FXCM had 53 bars with ask <
  bid at the 09:55 fix minute (USD/JPY), and no more than 21 at any other
  anchor.
  - These are small, momentary crosses (about 0.6 pip), where the bar opens on
    a crossed previous close.
  - Dropping them would remove days selected on fix-minute activity, the very
    thing under study.
  - New rule: a crossed quote stays valid. Its mid is used. The quoted-cost
    diagnostic fills it at mid, so a crossed quote earns no negative-spread
    credit.
  - Only a non-positive price is invalid now. Crossed counts are reported.
- **C. Coverage denominator.** FXCM's archive returns 404 for these weekly
  files, the same weeks for both pairs:
  - 2024 weeks 35, 51 and 52;
  - 2025 weeks 1, 2, 29 and 30;
  - 2026 weeks 18–31.

  FXCM's 2019/1, 2020/1 and 2024/1 files are also 404, but those dates fall
  inside the 2018/53, 2019/53 and 2023/53 files, which are present.

  The days in the missing weeks have no primary price, so the study can never
  use them. They are excluded from the gotobi and control groups alike, and
  they fall almost entirely in the holdout.

  New coverage rule: of the days with complete FXCM anchors for a window, at
  least 95% must also have complete HistData anchors. The 99%-within-5-bp
  agreement rule is unchanged. FXCM-missing days are reported separately.

- **A2. HistData DST calendar (supersedes A).** The second run
  (`source-attempt2.json`, sha256 `6f782776…bfd2d`, kept) passed coverage
  (97–99.9%), but agreement was only 95.6–96.5%.
  - In USD/JPY, 3–5% of anchors still differed by more than 2.5 bp. From 2019
    they cluster in March and late October/early November, and the best-fit
    shift is −60 minutes.
  - Those are the weeks between the US and EU DST switches. The FX week
    opens at Sunday 17:00 New York.
    - FXCM's first bar is at that time in UTC (21:00 or 22:00) every week.
    - HistData's first bar is at 16:00 local in the 2019 and 2023 gap
      weeks, and at 17:00 in the 2017 gap week.
    - So from 2019 HistData switches DST on EU dates, and it is HistData,
      not FXCM, that is off by an hour in those weeks.
  - Fix: read each HistData week's UTC offset (4 or 5 h) from its first
    Sunday bar against the 17:00 New York open.
    - A week whose first bar fits neither offset falls back to New York
      local time.
    - The offset counts and FXCM's own week-open check are reported in the
      source.
  - Diagnosis was still price-only: level differences, best-fit offsets and
    week-open stamps.

## Freeze receipts
Appended below after each phase, never edited. The source hash is committed
before training, and the selection hash before the final.

### Source (2026-10-09, after amendments A2–C)
- **`source.json` sha256 `bb30c4a29617f8ac31408e70742aff70a74c89c5867ff165ac6353a4c2e59297`**
  - It hashes 1,119 raw inputs: the FXCM weeks, the HistData files and the
    Cabinet Office CSV.
  - The calendar has 2,624 Tokyo business days, 818 of them gotobi days.
- **Both pairs are admitted.** Window bid-to-bid returns, FXCM against HistData:

  | Pair | Window | FXCM-usable days | Coverage | Within 5 bp | Median abs | p99 abs | Mean signed |
  |---|---|---:|---:|---:|---:|---:|---:|
  | USDJPY | open_fix | 2,506 | 99.92% | 99.68% | 0.21 bp | 2.80 bp | −0.08 bp |
  | USDJPY | early_fix | 2,044 | 97.65% | 99.65% | 0.20 bp | 3.33 bp | −0.07 bp |
  | USDJPY | post_fix_fade | 2,045 | 99.85% | 99.71% | 0.19 bp | 2.91 bp | +0.07 bp |
  | EURJPY | open_fix | 2,506 | 99.84% | 99.56% | 0.24 bp | 3.27 bp | −0.11 bp |
  | EURJPY | early_fix | 2,044 | 97.85% | 99.40% | 0.24 bp | 3.77 bp | −0.05 bp |
  | EURJPY | post_fix_fade | 2,045 | 99.85% | 99.61% | 0.23 bp | 3.42 bp | +0.10 bp |

- **FXCM gaps:** 118 business days in the 404 weeks have no FXCM price, and
  the 03:00 anchor is also missing on Mondays (Sunday 18:00 UTC is before the
  weekly open).
- **Crossed FXCM opens (USD/JPY):** 11 at 03:00, 9 at 09:00, 53 at 09:55 and
  21 at 12:00. They are kept at mid (amendment B).
- **HistData week offsets (USD/JPY):** 327 weeks at UTC−4, 211 at UTC−5, and
  19 that fall back to New York local time.
- **FXCM week opens:** 51 of 539 USD/JPY week files start away from 17:00 New
  York. They are holiday weeks (Christmas/New Year) or thin Sunday opens 16–60
  minutes late. None starts an hour early.

### Selection (2026-10-09, training only)
- **`selection.json` sha256 `827f21daa2f122aaa57d4445e8e92f1778307b4d8bf1173b87ab6912f2e6bb00`**
- **Selected: `early_fix` (03:00 → 09:55 JST, long USD/JPY, Tue–Fri).** It is
  the only admitted window.
- Training trials:

  | Trial | Window | Pair | Trades | Gross bp | Net bp | t-test p | Gotobi − control | Admitted |
  |---|---|---|---:|---:|---:|---:|---|---|
  | 8806 | open_fix | USDJPY | 568 | 2.47 | −0.53 | 0.82 | +1.95 bp, p 0.002 | no (net ≤ 0) |
  | **8807** | **early_fix** | **USDJPY** | **488** | **5.42** | **+2.42** | **0.0099** | **+5.76 bp, p 3e-6** | **yes** |
  | 8808 | post_fix_fade | USDJPY | 312 | 3.38 | +0.38 | 0.31 | +2.35 bp, p 0.016 | no (p) |
  | 8809 | open_fix | EURJPY | 568 | 2.09 | −0.91 | 0.95 | +2.25 bp, p 0.0002 | replication only |
  | 8810 | early_fix | EURJPY | 488 | 5.38 | +2.38 | 0.006 | +4.40 bp, p 5e-5 | replication only |
  | 8811 | post_fix_fade | EURJPY | 302 | 1.64 | −1.36 | 0.97 | +1.13 bp, p 0.12 | replication only |

- **Overfitting check** (`tradingbot.backtest.overfitting`, before the final):
  - The family has 6 variants over 91 months, with PBO 0.03.
  - DSR(N) is 0.61 for the best in-sample variant (EUR/JPY 8810), and DSR(L)
    against the 180-trial ledger is 0.00.
