# C08 USO inventory scarcity: source admission failed

Date: 2026-10-01. Bead: `tradingbot-m2d`. **DATA_FAIL, no promotion.**
The source attempt stops before inventory signals, training, or holdout replay.
USO's 2020 reverse split has an unresolved fractional-share/cash treatment under
the specified current Alpaca cash-account counterfactual. This is an evidence
failure, not evidence that inventory scarcity is unprofitable.

The [machine-readable audit](19-c08-source-audit.json) binds the source hashes,
policy, calendar evidence and code. Local immutable captures are under
`data/research/c08/`; primary action receipts remain in `data/research/c05/documents/`.
Reproduce the offline audit with `uv run python -m tradingbot.research.c08_source_audit`.
The `--record-ledger` option requires committed audit dependencies and records the
same source/code identity only once.

Source/code commit: `e6e464df723ce5fa2fad3f2fe46635e8d98c5292`. Failed source
trial **3550**, strategy **6082**, is independently verified in the ledger:
`idea`, $0 allocation, null performance, zero orders/fills and zero final trials.
The bead is closed using its explicit data-failure acceptance route.

## Fixed candidate and data interval

The specification remains [C08 in the candidate shortlist](07-candidate-shortlist.md):
US commercial crude stocks excluding SPR, divided by the comparable year-ago
value, minus one. The two planned thresholds are 0% and −5%; unchanged long/cash
state retains shares without weekly resizing. Decisions follow actual release
availability, date-only evidence waits until the next calendar day's eligible
session, and a 14-day absence of usable publications requires cash at the next
session. No variant was changed to avoid a source failure.

The exact requested interval is 2018-01-01 through 2026-10-01 exclusive. The
elapsed-time 70/30 cutoff remains **2024-02-15 12:00 UTC**. Dataset identity is
`sweep-c08-v1:cd2f66176c0e65ac417b8bb8ebb08bc55dacd7184c747aaa68735250393625e4`.
This is a source-audit identity, not an admitted replay dataset.

The fresh Yahoo USO request covers all 2,198 expected regular sessions from
2018-01-02 through 2026-09-30. The structural check found no missing/extra
sessions, null OHLC/volume rows, invalid price ranges, duplicate dates or orphaned
actions. Its action fields contain one 1-for-8 split on 2020-04-29 and no
dividends. These checks do **not** certify executable price basis or completeness
of corporate actions. Source SHA-256:
`961f0d9a8f2dd922d856bb574aa37a279cecc7b30ef51d64e0e2a22ba46b1d8b`.

## Concrete action failure

The [USCF announcement](https://www.prnewswire.com/news-releases/uscf-announces-one-for-eight-reverse-share-split-for-the-united-states-oil-fund-nyse-arca-uso-301045001.html)
establishes the split date and ratio, and cash in lieu of fractional post-split
shares. The [current Alpaca process documentation](https://docs.alpaca.markets/us/docs/daily-processes-and-reconcilations.md)
describes reverse-split cash arriving from DTC, whereas its
[2021 fractional-share announcement](https://alpaca.markets/blog/updated-terms-for-payments-in-fractional-shares/)
describes a move away from cash-in-lieu payments. Those archived statements do
not establish this account's effective retention policy, fractional quantity,
payment amount or spendable-cash date for the modeled action.

The [C05 audit](15-c05-commodity-trend.md) records the same source conflict.
Its supplementary OCC option-adjustment cash value does not establish an Alpaca
share-account credit date. No option cash value, approximate pay date, adjusted
price series or assumed permanent fractional holding repairs this gap. No
scarcity calculation was used to test whether the strategy might avoid holding
USO on the split date.

## Bounded EIA layout evidence

The [EIA archive](https://www.eia.gov/petroleum/supply/weekly/archive/), four dated
report pages and their linked Table 1 CSV bytes were saved with request URLs,
HTTP status, retrieval timestamps and hashes. All ten captures, including USO,
succeeded. The probes intentionally stop short of constructing a full macro
series or certifying historical first-release vintages.

| Observation week ends | Actual release | Earliest calendar date for execution |
|---|---|---|
| 2020-09-04 | [2020-09-10, Thursday](https://www.eia.gov/petroleum/supply/weekly/archive/2020/2020_09_10/wpsr_2020_09_10.php) | 2020-09-11 |
| 2022-06-17 | [2022-06-29](https://www.eia.gov/petroleum/supply/weekly/archive/2022/2022_06_17_data/wpsr_2022_06_17_data.php) | 2022-06-30 |
| 2023-11-03 | [2023-11-15](https://www.eia.gov/petroleum/supply/weekly/archive/2023/2023_11_03_data/wpsr_2023_11_03_data.php) | 2023-11-16 |
| 2026-09-25 | [2026-09-30](https://www.eia.gov/petroleum/supply/weekly/archive/2026/2026_09_30/wpsr_2026_09_30.php) | 2026-10-01, outside the sample |

The first example's notice concerns **production** re-benchmarking, not a proven
inventory correction. The two delayed reports explicitly distinguish their
observation dates from publication. The CSV examples separate commercial stocks
excluding SPR from strategic stocks and carry current and comparable prior-year
date columns. No numeric signal or threshold decision was computed. The CSVs
also contain distinct stock and supply sections: a future parser must validate
units, section, definitions and correction history, not simply take the first
number or assume every release arrives Wednesday. The current archive alone
does not prove that bytes were unchanged since first publication.

Full first-release/errata reconciliation, complete price/action validation and
the [prospectus](https://www.sec.gov/Archives/edgar/data/1327068/000207187626000128/i26211_uso-424b3.htm)
exposure-regime analysis remain uncompleted. The required regimes are pre-2020,
changed-2020, September 2023–January 2024 transition and later exposure. No
regime-specific performance is inferred from these probes.

## Decision and what could blow up this account

No idea-to-backtest promotion occurs. Both thresholds at 5 bp and 10 bp remain
unattempted; final holdout claims are zero. Net/gross P&L, fees, trades, marked
drawdown, exposure, turnover, regime results, benchmark returns and luck p-value
are **null**, not zero. The source-only failed trial is retained. USO overlaps
C05's source inspection, and the published commodity hypothesis is known;
neither fact is concealed by the new dataset key. PRD §6 is unchanged.

- **Market/exposure:** USO holds futures, and roll costs or changed holdings can
  overwhelm any relationship between physical inventories and prices.
- **Data/timing:** revised inventory observations or backdated delayed releases
  can manufacture apparent foresight. A year-ago value must be comparable and
  have a positive denominator.
- **Execution:** daily open plus fixed adverse basis points is an assumption;
  gaps, spreads and fractional execution can be worse. Daily data does not
  override the 30-second forward stale-data veto.
- **Cash/actions:** invented split entitlements or early cash credits can fund
  purchases that a $140 settled-cash slot could not make.
- **Concentration/tails:** a single commodity ETF can gap through a stop. The
  existing strategy kill, slot cap and global halt remain mandatory.
- **Operations/model:** missing releases, lost state, network failures and ETF
  exposure changes can leave an inappropriate position. The deliberate PRD §9
  host/resting-order risks remain owner choices.

Ten focused checks passed, including delayed/date-only publication handling,
ambiguous dates/links, exact source bounds and checksums, conflicting action
evidence and an idempotent failed-trial write with null performance and no final
claim. No paper/live transition, keys, capital or orders were requested.
