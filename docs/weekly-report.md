# Weekly review

The report is published at https://tradingbot-weekly.pages.dev. `ops/scheduler.sh`
(the `svc-scheduler` window of the `tradingbot-svc` tmux session) deploys it once
per ISO week from Friday **14:00 local time** (America/Los_Angeles on this laptop;
17:00 Eastern). Keep the laptop timezone set accordingly. If Friday is missed, it
runs on Saturday or Sunday. The displayed generation timestamp is the actual
snapshot time; weekly changes cover the preceding seven days.

## Run

```sh
npm ci --prefix ops/weekly --ignore-scripts --no-audit --no-fund
uv run python ops/weekly_report.py          # build + verify encryption locally
uv run python ops/weekly_report.py --deploy # build, verify, publish, verify remote
```

The report reads `WEEKLY_PAGE_PASSWORD`, `CLOUDFLARE_API_TOKEN` and
`CLOUDFLARE_ACCOUNT_ID` from the gitignored `.env`. It uses existing Cloudflare
credentials and the `tradingbot-weekly` Pages project on production branch `main`.
If that project is absent, the deploy command creates it in the configured account.
It never creates API keys. To initialize an empty report password, run:

```sh
uv run python ops/weekly_report.py --init-password
```

This stores a random 256-bit password only in `.env`; it does not print it or
replace an existing password. Open `.env` locally to retrieve
`WEEKLY_PAGE_PASSWORD`. Passwords shorter than 20 characters are rejected.
Use the password field on the site; no password or password-bearing link is
included in logs, commits, command arguments or the deployment.

## Report semantics

- PostgreSQL reads use a repeatable-read, read-only transaction. No trading,
  promotion, risk or ledger mutation is performed.
- Live and paper leaderboards are separate. Weekly realized P&L subtracts fees
  charged during the window, including fees on positions still open. All-time P&L
  is shown alongside it. Open-position value is excluded. A round trip that exits
  this week includes its earlier entry when calculating the trade statistic.
- Luck p uses weekly completed round trips and the existing ledger statistic. It
  is a test against zero mean, not a posterior probability that a strategy is luck.
- Sharpe, drawdown, hit rate and OOS t are informational, with per-row measurement
  scopes and sample counts. No threshold changes PRD §4 promotion or readiness.
  Weekly paper/live drawdown uses realized execution-ledger P&L including entry
  fees, with a zero baseline at the window start; it excludes unrealized marks and
  model-only income/fees. Hit rate counts profitable net completed execution
  round trips (including their full entry fees), with breakevens in the denominator.
  Open trades do not count as hits. Both metrics cover this week; dashboard
  leaderboards use all-time scope, so their values can differ.
- Trial Sharpe uses only known stored marked-return schemas (daily C05/C04;
  complete interior months for C08) with sample standard deviation, a stated 0%
  cash benchmark and √252/√12 annualization. OOS t uses the recorded final
  marked sample, or explicitly labelled fully reconciled net execution round
  trips for legacy equity trials without a marked series. It is descriptive IID
  t, without a serial-dependence correction; training and open cycles cannot qualify.
  Failed audits and prior-inspection limitations still apply. Missing/unsupported
  series or undefined variance remain “—”. Existing scalar Sharpe/win-rate fields
  retain their producer's basis; execution P&L is not substituted for returns.
  [Full definitions and formula source](../src/tradingbot/dashboard/README.md#informational-statistics-tradingbot-ss4)
  are shared with the dashboard. No stored trial or consumed final is rewritten.
- Backtest variants are listed individually and never summed into an account
  result. Missing metrics remain unmeasured, distinct from zero. Trial trade
  counts retain each runner's definition. New trials include failed/running rows;
  previously started trials completed this week are listed separately.
- Final holdouts are shown cumulatively with current audit status. A strategy's
  failed evidence audit overrides historical completion/positive returns; C01's
  preserved numbers are explicitly marked as ineligible evidence.
- Promotion records come from completed beads labelled `promotion`. Current
  paper/live stages are shown separately because the database does not have a
  transition-history table. Use that label when recording future promotions.
- The ready queue includes open/in-progress beads explicitly labelled
  `ready-for-live` or `ready:live`; returns never infer readiness.
- Incidents cover this week plus older unresolved records. Halts include active
  ones and those triggered this week. Killed strategies, open work and the curated
  intake log are also included. A current `## Verdict:` heading in an intake's
  linked evaluation overrides a stale index-table verdict.

## Publication boundary

StatiCrypt 3.5.4 and Wrangler 4.145.0 are pinned with an npm lockfile under
`ops/weekly/`. Encryption uses `STATICRYPT_PASSWORD` in a minimal subprocess
environment, a fresh salt per build, and disables remembered passwords. Every
build is decrypted locally and compared byte-for-byte before it can be published.
See [StatiCrypt's documentation](https://github.com/robinmoisson/staticrypt#readme)
and [Cloudflare's Pages command reference](https://developers.cloudflare.com/workers/wrangler/commands/pages/).

Plaintext exists only inside an automatically cleaned mode-0700 temporary
directory. The upload folder `data/weekly/site/` contains exactly:

- encrypted `index.html`;
- `_headers`, with no-store/noindex and a policy blocking external assets,
  connections, form submissions and framing;
- `robots.txt`, disallowing crawling.

The code rejects unexpected files, symlinks and known plaintext markers. The
password is absent from the uploaded bytes. No reports, dependencies, source code,
database export or environment file are deployed. The encrypted page can be
downloaded publicly; its report content is encrypted, with access controlled by
the password. Changing that password protects future uploads, not copies someone
already downloaded with an older password.

The deployment command requires a successful Cloudflare production deployment
and checks that the served HTML exactly matches the encrypted local file. Metadata
(timestamp, hash, trial counts, deployment ID) goes to ignored
`data/weekly/last_run.json`. Logs omit subprocess output and exception details that
could contain secrets. A file lock prevents simultaneous report runs.

## Schedule and validation

The scheduler runs once a minute in the tmux services session, not launchd:
macOS TCC blocked launchd-spawned `uv` from reading `~/Documents` (the original
`com.tradingbot.weekly` LaunchAgent stalled on October 1 and was retired in
`394366d`). The watchdog recreates the window via `ops/services.sh` if it dies.

- Success touches `logs/.scheduler/weekly-<ISO week>`; nothing more runs that week.
  Output goes to `logs/weekly.log`.
- A failed deploy writes one line to `logs/INCIDENTS.md` and retries **once per
  hour** (marker `weekly-<week>-failed-<YYYYMMDDHH>`), not every minute: each
  attempt is a full build plus Cloudflare deploy.
- To publish now, run `uv run python ops/weekly_report.py --deploy` from a
  terminal; the file lock prevents a clash with the scheduler.

The October 1 password blocker (`tradingbot-ud2`) is resolved: the W40 scheduled
deploy on October 2 built, encrypted and verified. Never paste that password into
a bead, report, command argument or chat.

```sh
uv run pytest tests/ops/test_weekly_report.py -q
```

Tests cover the week boundary, fee attribution, instrument multipliers, mode
isolation, failed audits, escaping, missing metrics, secret isolation and actual
encryption/decryption with plaintext-exclusion checks. The current intake-verdict
override is also covered. Initial deployment was verified via HTTPS against the
exact local ciphertext, password input and restrictive response headers; browser
automation was unavailable in that session.
