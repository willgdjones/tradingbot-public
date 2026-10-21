# Futures broker comparison

Research date: **2026-09-30 Pacific / 2026-10-01 UTC**. Bead: `tradingbot-k1e`.
Public documentation review only; no account, key, subscription, funding or order was created.

## Decision

**Recommend Interactive Brokers Pro as the eventual Python futures broker, conditionally.** Its documented Python API, futures contract discovery, paper-account integration and $0.25 MGC/MCL base commission fit this bot better than the alternatives. UK and US appear in its supported-country list. This is an engineering recommendation, not confirmation of Will's individual eligibility or authority to fund an account. [IBKR countries][ib-countries], [API requirements][ib-requirements], [paper/API setup][ib-paper], [commissions][ib-fees].

**An unfunded IBKR account does not solve the present research/paper requirement.** Current TWS API documentation explicitly requires a funded, opened Pro account. Live and historical API data generally also require live-data permissions and subscriptions. Keep the PRD's unfunded/$0-data constraints: continue commodity research through the approved free sources and Alpaca commodity ETFs. The owner can consider an unfunded account for onboarding, but automated futures paper trading remains unproven until the broker confirms a permitted unfunded route or the owner later authorizes funding after a passing commodity edge. Do not deposit a token amount simply to unlock API/data benefits. [Requirements][ib-requirements], [data permissions][ib-paper], [PRD §2](../../PRD.md#2-constraints).

No reviewed broker was verified to provide **all three** of permanent realistic futures paper trading, a usable Python order API, and suitable free contract-level history while unfunded. This is a finding about the evidence available, not a claim that every possible broker route is impossible.

**Update (2026-10-04, `tradingbot-qpb`):** For small-account **crypto** futures specifically, Coinbase Derivatives' direct Advanced Trade / US Derivatives REST API is a materially better fit than the commodity-micro path — roughly **$25 nano-Bitcoin day margin**, **$0/month market data**, and a clean **trade-only key** (view+trade, no transfer) — but it offers only a static mock sandbox, not realistic paper, and crypto is a venue, not an edge. IBKR stays the preferred **general** futures broker and now also **resells** Coinbase nano BTC/ETH futures, so those contracts are reachable through the existing IBKR relationship. See the [Coinbase vs IBKR appendix](#appendix-2026-10-04-coinbase-derivatives-vs-ibkr-for-crypto-and-small-account-futures) below. Research only; the owner opens accounts.

## Account eligibility

The PRD says residency and identity requirements. Those facts must all be disclosed accurately; an SSN does not by itself establish the correct broker entity, tax forms, or futures permission. The review cannot adjudicate a dual-residency application. General country access and individual derivatives approval are separate questions.

| Broker | Public evidence | Remaining eligibility question |
|---|---|---|
| **IBKR** | Both UK and US are listed as available countries. | Which entity services the owner's actual legal residence, and will it grant US commodity futures permissions? General country support is the strongest evidence here, not individual approval. [Source][ib-countries] |
| **tastytrade** | Individual international margin accounts can access futures in eligible countries. Futures require the appropriate trading permission. | The linked country-list page returned a CSS/loading error; UK acceptance for this profile was **not independently confirmed**. Do not substitute forum anecdotes. [International accounts][tt-international], [country-list endpoint][tt-countries], [permissions][tt-permissions] |
| **NinjaTrader** | Current US pricing applies to accounts cleared through NinjaTrader Clearing; a separate EEA classification regime exists. | A definitive current UK/US dual-residency admission rule was not found. Confirm entity and country eligibility before relying on US pricing. The UK must not be inferred to be in the EEA. [US pricing][nt-price], [EEA classification][nt-eea] |
| **AMP** | Neither UK nor US appears in the broker's restricted-country image, visually inspected with its September 27, 2026 help article. | Absence from a restriction list is not approval; AMP expressly retains discretion to reject other profiles. [Article][amp-countries], [list image][amp-country-image] |
| **Schwab** | Its futures FAQ allows individual/joint applications from US and non-US residents, subject to approval; it lists margin approval and a $1,500 account minimum. | Confirm the relevant international/domestic entity accepts this profile and enables futures. The published minimum already exceeds today's entire $1k portfolio. [FAQ][sch-faq] |

These unresolved items are written handoff questions for the owner, not requests to open five accounts or contact brokers automatically.

## Python, simulation and history

| Broker | API fit for the Mac/Python bot | Paper/sim and free-history limits |
|---|---|---|
| **IBKR — preferred future integration** | Official Python support; current minimum Python 3.11 is compatible with this repo's 3.12. Requires TWS or IB Gateway and funded Pro access. Paper accounts use the API. | Appropriate for integration testing once eligible. Historical API data is entitlement-dependent. Expired futures older than two years after expiration are unavailable; bars of 30 seconds or less older than six months are unavailable. Therefore it is not a free, complete long-run futures archive. [Requirements][ib-requirements], [paper/data][ib-paper], [history limits][ib-history] |
| **tastytrade — useful order-flow alternative** | Documented REST/JSON futures orders and streaming; straightforward to call from Python without a Windows bridge. This review did not certify a particular third-party SDK. | Sandbox fills are synthetic: market orders fill at $1; limits below $3 fill immediately; limits at/above $3 remain live. Positions/trades reset every 24 hours, and market-data routes are unavailable. Production REST quotes require funding. Exact accessible futures history and unfunded streaming entitlements remain unverified. Sandbox P&L cannot count as edge evidence. [API][tt-api], [sandbox][tt-sandbox], [market data][tt-data] |
| **NinjaTrader — credible alternative to revisit** | Current official docs include REST trading and WebSocket market data, including a Demo environment. **Do not describe it as C#-only.** Issued API credentials are required; retail API entitlement, costs and approval conditions for Will were not established. | Software simulation is free without a time limit; streaming live data has a 14-day trial. Funded plan benefits include data and replay; unfunded Sim+ continuation is advertised at $35/month. Neither API-accessible historical depth nor a permanent free unfunded data path was verified. [API setup][nt-api], [pricing/trial][nt-price], [Sim+][nt-sim] |
| **AMP — poor fit at this budget** | Access depends on the selected platform/feed. CQG documents a Python-compatible protocol, but that does not establish AMP grants direct WebAPI access. AMP's explicitly priced Rithmic API route costs $125/month before exchange data and routing. | AMP Play provides persistent CQG simulation and CME Level 1 for $20/month. Rithmic history is advertised from 2011, with request limits, but access is not free and each contract starts at its own listing date. Neither paid route fits $0/month. [CQG protocol][cqg-python], [API pricing][amp-api], [Play][amp-play], [history][amp-history] |
| **Schwab — manual paper candidate, weak bot fit** | The broker says futures trade exclusively through thinkorswim. This review found no verified retail futures order API for the Python bot; do not infer API support from a futures quote stream. | paperMoney supports simulated futures. A free Guest Pass lasts 30 days, then credentials/data/settings expire; clients get ongoing platform access. A usable free futures-history export/API was not verified. [FAQ][sch-faq], [paperMoney][sch-paper], [Guest Pass][sch-guest] |

Broker simulations do not replace our execution rules. Any future performance paper run must enforce later trades **through** a maker price, freshness, fees, slippage, reconciliation and the unchanged risk vetoes. Synthetic fills, replayed historical prices and delayed quotes cannot establish a live forward record.

## Fees: distinguish the base commission from the complete cost

USD per contract **per side**, low volume, using public retail schedules. A round trip has two sides; spreads, slippage, data, platform charges and any overnight charges are additional. Exact fees must eventually be verified for the approved entity, exchange membership status, contract and route.

| Broker | Verified base commission / recurring cost | What is missing from that headline |
|---|---|---|
| IBKR | **$0.25** MGC and MCL (they are explicitly included in the micro schedule), or **$0.50 round trip** before other fees. | Exchange/regulatory charges; tiered plans also list overnight position fees. The generic $0.85 standard-futures row is not the MGC/MCL rate. [Schedule][ib-fees] |
| tastytrade | **$0.75** micro opening and **$0.75** closing commission, **$1.50 round trip** before other fees. | Exchange, clearing and regulatory fees on both sides. [Schedule][tt-fees] |
| NinjaTrader | Free plan: **$0.39** micro, **$0.78 round trip** before other fees. | Exchange, clearing and NFA charges. The $0.09 headline belongs to a paid lifetime plan. The current itemized page was dated August 14, 2026 but its product rows did not render, so no all-in MGC/MCL total is asserted. [Plans][nt-price], [itemized schedule][nt-fees] |
| AMP | Commission depends on platform/feed and volume; its official FAQ directs users to the exact-cost calculator. A reproducible MGC/MCL quote was not obtainable in this review. | Calculator access returned 403. Documented Rithmic API technology charges alone are **$125/month**, plus $0.10 per filled contract for live routing and exchange data. Do not mistake ordinary platform/feed access for the API add-on. [Commission method][amp-fees], [API charges][amp-api] |
| Schwab | **$2.25**, **$4.50 round trip** before other fees. | Exchange and regulatory charges. [FAQ][sch-faq] |

For AMP, current published nonprofessional Level 1 exchange data is $5/month per CME-group exchange or $15/month for the bundle. MGC is COMEX and MCL is NYMEX: a single CME/Globex subscription is not both. Those charges are separate from API access. No subscription was purchased. [Exchange data schedule, effective June 1, 2026][amp-data].

## Micro-contract margins and capital fit

The following are **public-page observations during this review, not synchronized market quotes or approved-account requirements**. IBKR uses the page's US-resident/risk-based configuration and shows different long/short initial amounts. AMP labels its figures maintenance and day-trading margin. Comparing an IBKR initial requirement with an AMP day margin as if both buy the same overnight capacity would be wrong. Values can change without notice; search-index snippets already differed from subsequently opened pages.

| Contract | IBKR long overnight initial | IBKR overnight maintenance | AMP maintenance | AMP day trading |
|---|---:|---:|---:|---:|
| MGC, micro gold | $4,153.55 | $3,502.22 | $2,426.00 | $606.50 |
| MCL, micro WTI oil | $2,079.00 | $1,500.00 | $948.00 | $237.00 |
| MNG, micro natural gas (IBKR underlying MHNG) | $678.632 | $581.418 | $326.00 | $326.00 |
| 1OZ, one-ounce gold | $415.26 | $350.226 | $243.00 | $60.75 |

Sources: [IBKR configured table][ib-margin], [AMP margin table][amp-margin]. Machine-readable observations and margin-type labels are in [the snapshot](futures-broker-sources/2026-09-30-margin-observations.json). IBKR's inspected MGC/MCL short initial values were $4,027.55/$1,875.00; the table above deliberately uses long values. These figures are not an all-broker margin ranking.

For **tastytrade**, a numerical current MGC/MCL margin was not verified; its API documents account-specific standard/intraday multipliers. For **Schwab**, the FAQ directs users to current requirements inside thinkorswim. For **NinjaTrader**, the current product margin link did not resolve in this capture, and an old commission PDF returned 404. Its $50 marketing example is for specified equity-index micros, not a verified MGC/MCL requirement. Use live account previews later, not stale search snippets. [tastytrade margin model][tt-margin], [Schwab FAQ][sch-faq], [NinjaTrader pricing][nt-price].

MGC, MCL and MNG have price-point multipliers of $10, $100 and $1,000 respectively; each has a $1 minimum tick value. As an illustrative sensitivity, a five-point gold move, half-point oil move, or 0.05-point gas move produces $50 P&L on one respective micro contract before costs. Margin is collateral, not maximum loss; a stop does not cap a gap loss. [Contract specifications][sch-micro].

All quoted MGC/MCL day/overnight requirements exceed the current approximately $140 slot. Even the $60.75 1OZ day margin is not a reason to bypass the slot, the −$50 global daily halt, or the owner's unfunded restriction: maintenance is $243, fees require cash, and price exposure is larger than collateral. Futures-specific exposure accounting and gap/margin stress must be specified before any connector can establish compliance with §6. This report does not redefine the position cap or any accepted risk.

## Concrete next step

1. Continue the [free-data commodity ETF candidates](07-candidate-shortlist.md) using their preregistered training/holdout rules. Broker research is not a strategy variant or a promotion, so it creates no synthetic trial result.
2. At the owner's chosen onboarding time, take **IBKR** the complete residence/tax facts and ask for the servicing entity, commodity permissions, unfunded paper/API availability, data permissions/history depth, and a written total MGC/MCL cost/margin quote. The public API funding requirement is the main unresolved conflict with the current unfunded plan. No contact has been sent.
3. If the owner later funds after a passing commodity edge and top-up, first verify account identity, trade-only access, contract expiry/delivery restrictions, exact fees, data entitlements and paper reconciliation. Archive per-contract history prospectively; do not assume a continuous price series can reproduce expiry, roll or settlement behavior. Complete the promotion checklist and account-loss analysis before promotion.

The broker choice is therefore **IBKR for a future approved integration; free-data research now**. No new live-ready designation follows from this comparison.

## Primary sources

All links were reviewed on the research date. A linked source does not imply an account was accessed. Access failures and missing entitlements are recorded above rather than filled with estimates.

[ib-countries]: https://investors.interactivebrokers.com/en/index.php?f=7021
[ib-requirements]: https://www.interactivebrokers.com/docs/tws-api/doc/notes-limitations/requirements
[ib-paper]: https://www.interactivebrokers.com/campus/trading-lessons/installing-configuring-tws-for-the-api/?retakeFinal=1
[ib-history]: https://www.interactivebrokers.com/docs/tws-api/doc/market-data-historical/historical-data-limitations/unavailable-historical-data
[ib-fees]: https://www.interactivebrokers.com/en/pricing/commissions-futures.php
[ib-margin]: https://portal.interactivebrokers.com/en/trading/margin-futures-fops.php?ex=us&hm=us&pm=0&rgt=0&rsk=1&rst=101004110808
[tt-international]: https://tastytrade.com/learn/accounts/account-types/international-account/
[tt-countries]: https://support.tastytrade.com/support/s/solutions/articles/43000435355
[tt-permissions]: https://tastytrade.com/learn/accounts/account-resources/trading-permissions/
[tt-api]: https://developer.tastytrade.com/
[tt-sandbox]: https://developer.tastytrade.com/docs/sandbox/
[tt-data]: https://developer.tastytrade.com/docs/concepts/market-data/
[tt-fees]: https://tastytrade.com/pricing/
[tt-margin]: https://developer.tastytrade.com/docs/concepts/margin-and-risk/
[nt-api]: https://docs.ninjatrader.com/api/getting-started
[nt-price]: https://ninjatrader.com/pricing/
[nt-fees]: https://ninjatrader.com/pricing/commissions/
[nt-sim]: https://support.ninjatrader.com/s/article/Sim-Plus?language=en_US
[nt-eea]: https://support.ninjatrader.com/eu/s/article/how-does-classification-work?language=en_US
[cqg-python]: https://help.cqg.com/apihelp/Documents/gettingstarted.htm
[amp-countries]: https://faq.ampfutures.com/hc/en-us/articles/10797726829463-Restricted-Countries-List
[amp-country-image]: https://faq.ampfutures.com/hc/article_attachments/34904272364951
[amp-fees]: https://faq.ampfutures.com/hc/en-us/articles/10960011527575-What-are-AMP-Futures-commission-rates
[amp-api]: https://faq.ampfutures.com/hc/en-us/articles/360060137993-Rithmic-Pricing
[amp-play]: https://demo.ampfutures.com/play
[amp-history]: https://faq.ampfutures.com/hc/en-us/articles/10800536819351-How-much-Historical-Data-is-included-with-Rithmic
[amp-data]: https://www.ampfutures.com/trading-info/exchange-data-fees
[amp-margin]: https://www.ampfutures.com/trading-info/margins
[sch-faq]: https://www.schwab.com/futures/faqs
[sch-paper]: https://international.schwab.com/thinkorswim/paper-money-trading
[sch-guest]: https://www.schwab.com/trading/thinkorswim/guestpass
[sch-micro]: https://www.schwab.com/futures/micro-futures

---

## Appendix (2026-10-04): Coinbase Derivatives vs IBKR for crypto and small-account futures

Research date: **2026-10-04**. Bead: `tradingbot-qpb`, from intake [2026-10-02-coinbase-agent-skill](../strategy-intake/2026-10-02-coinbase-agent-skill.md).
Public-documentation review only; no account, key, OAuth grant, MCP connection, subscription, funding or order was created. `help.coinbase.com` and `interactivebrokers.com` returned **HTTP 403 to automated fetching** (bot protection), so retail-help figures below come from Coinbase's published blog and developer docs, a CFTC contract filing, and FCM (futures-broker) product pages, and are flagged where a live-account confirmation is still required. The local browser-harness daemon stalled on CDP calls during this review, so the two help pages were not read through a logged-in browser either.

### Why this comparison exists, and what it is not
The owner was sent Coinbase's "paste this into your agent" skill (remote MCP + "request all scopes" OAuth + x402 autopay). Intake **parked** it: the MCP/OAuth path breaks the trading-only-key rule and adds a prompt-injection surface, and x402 has no documented spend cap. This appendix evaluates only the **sober path** — would Coinbase's **Advanced Trade / US Derivatives REST API with a trade-only key** be a better small-account futures venue than the IBKR pick? Research only; the owner opens any account. No live-ready designation and no trial result follow from it.

### Headline finding
For the **$1k cash account and ~$140 slot**, Coinbase's **nano crypto futures** are the only futures contracts reviewed whose margin actually fits the slot: nano Bitcoin day-trade margin is about **$25** (overnight ≈ **$230**) versus IBKR commodity micros at **$1,500–$4,150** initial. Coinbase also serves **$0/month market data over its own API** and supports a genuine **trade-only key** (view+trade, transfer withheld), which the PRD requires. But Coinbase offers **no realistic unfunded paper environment** — only a static mock sandbox — so, like IBKR, it cannot produce a live-quality forward record while unfunded. And these are **crypto** contracts: a venue, not an edge, and 24/7 crypto volatility makes them a demanding home for a structural strategy.

Net: **IBKR remains the preferred general futures broker** (full commodity-micro suite, consolidated account, documented Python API). **Coinbase direct is the better fit specifically for nano-crypto research** on tiny capital, because of margin size, free API data and the clean trade-only key. **IBKR now also resells Coinbase Derivatives nano BTC/ETH futures**, so the owner can reach those contracts through the existing IBKR relationship — at the cost of IBKR's funded-account/entitlement requirements and without Coinbase's free data.

### Side-by-side

| Dimension | Coinbase direct (Advanced Trade / US Derivatives) | IBKR |
|---|---|---|
| Entity / regulation | Coinbase Financial Markets, CFTC-registered FCM/DCM | IBKR LLC / regional entity; US + UK both listed as supported |
| Fits the ~$140 slot? | **Yes** — nano BTC day ~$25 / overnight ~$230 | **No** — commodity micros $1.5k–$4.15k initial; CME micro-crypto larger than nano |
| Crypto futures | nano BTC (0.01 BTC), nano ETH (0.10 ETH), perp-style BTC/ETH/SOL/XRP (5-yr, re-listed monthly) | CME Micro BTC (MBT, 0.1 BTC), Micro ETH (MET), Micro SOL (MSL) + options; **plus resold Coinbase nano BTC/ETH** |
| Commodity futures | Gold, nano Crude Oil, Micro Crude Oil on the US exchange (depth unproven here) | Full micro suite: MGC, MCL, MNG, 1OZ, … (main table above) |
| Fees (headline) | Intro **0.05% of notional / contract / side**, **$0.20 min**, stated to include exchange + NFA (~$0.10/contract exchange) → ≈ $0.50/side on nano BTC; **verify live** | $0.25 MGC/MCL base; crypto-futures schedule separate, not re-verified |
| Python API | Advanced Trade REST (`/api/v3/brokerage`); CDP keys; no Windows bridge | Official Python API, but needs TWS/IB Gateway **and a funded Pro account** |
| Trade-only key | **Yes** — view+trade; withhold transfer (and receive) → cannot withdraw | Yes (key configuration) |
| Unfunded paper | **Static mock sandbox only** (shape, not fills/liquidity) — not realistic | Realistic paper, **but requires a funded Pro account** |
| Free market data | **Yes — $0/month** over own REST/WebSocket | Entitlement/subscription-gated; futures history truncated (expired >2y, sub-30s bars >6m) |
| Eligibility (UK/US) | US path via a US-regulated entity (Coinbase Financial Markets); UK served by a separate Coinbase entity | UK and US both listed; servicing entity + futures permission still to confirm |
| Main caveat | Crypto 24/7 vol; venue not edge; confirm live fees/margin/eligibility | Funded-account precondition even for paper/API; data cost |

### Eligibility (eligibility depends on residency)
Coinbase **US-regulated derivatives** (Coinbase Financial Markets, a CFTC-registered FCM/DCM) are available to residents of the **US, Canada and most EEA countries**; UK clients are served through a separate Coinbase UK entity and EEA through CBFSE. A person with **legitimate US residency and an SSN** opens the US entity and applies for futures (accept the futures agreements, pass suitability/qualification). UK **tax residency** is a reporting/tax matter on gains, not by itself an access blocker to the US entity — but it must be disclosed accurately and the UK tax treatment handled. Coinbase International Exchange perpetuals (incl. GOLD-PERP/SILVER-PERP at 25x) are a **non-US institutional** product, out of scope for a US retail cash account. As in the main report, these are **handoff questions for the owner**, not a request to open an account.

### Fees
Coinbase retail futures (Advanced) charge an introductory **0.05% of notional per contract, per side**, with a **$0.20 minimum per transaction**, stated to include exchange and NFA fees; FCM product pages list the nano exchange component around **$0.10/contract**. For nano BTC (~$1,000 notional) that is roughly **$0.50/side** before spread/slippage — order-of-magnitude similar to IBKR's crypto-futures commissions and cheaper than Schwab, but it **must be verified on the live fee schedule** (the help page blocked automated capture). IBKR's $0.25 MGC/MCL base is from the main section; its crypto-futures commissions are a separate schedule not re-verified here.

### Product / commodity coverage
Coinbase US Derivatives lists **nano and standard crypto futures** (nano BTC 0.01 BTC ≈ $1,000 notional, tick $5/BTC = $0.05; nano ETH 0.10 ETH; plus BTC/ETH/SOL/XRP/DOGE/LTC and perp-style 5-year contracts re-listed one month before expiry) **and some commodity futures** — **Gold, nano Crude Oil and Micro Crude Oil** are on the US-regulated exchange — so it touches a little of the same commodity ground as the IBKR micros, though its depth/liquidity there is unproven in this review. IBKR covers the broad commodity-micro suite (main table), CME **Micro Bitcoin (MBT, 0.1 BTC)**, **Micro Ether (MET)** and **Micro Solana (MSL)** futures + options, 11 spot cryptos, **and** the resold Coinbase nano BTC/ETH futures.

### API, paper/sandbox and data (the parts that matter for this bot)
- **API.** Advanced Trade REST (`api.coinbase.com/api/v3/brokerage/…`) exposes US-futures endpoints — e.g. `GET /cfm/balance_summary` (US futures balances) and `POST /orders` — and uses **CDP API keys with granular scopes (view / trade / transfer / receive)**. Placing orders needs only **trade**; moving funds out needs **transfer**. So a **view+trade key with transfer and receive withheld** can run the bot and **cannot withdraw** — exactly the trading-only posture the PRD mandates. **Do not** use the `agents.coinbase.com` MCP or the all-scopes OAuth from the parked skill, and keep **x402 autopay disabled**.
- **Paper/sandbox.** Coinbase's Advanced Trade **sandbox** (`api-sandbox.coinbase.com`) needs no auth but returns **static, pre-defined responses** and covers only Accounts/Orders — it validates request/response shape, not liquidity, fills, latency, halts or eligibility. It is **not** a realistic paper environment, and there is no free funded-quality simulator. This is the **same gap** the main report found across brokers; IBKR's paper account is more realistic but needs a funded Pro account. **Neither venue lets us produce a live-quality unfunded forward record.**
- **Data.** Coinbase serves crypto market data and historical candles over its own API/WebSocket at **$0/month**, with no CME-style exchange-data subscription — a real advantage over IBKR, whose historical/live futures data is entitlement- and subscription-gated and whose futures history is truncated (expired contracts >2y; sub-30s bars >6m). For free crypto research data, Coinbase direct wins.

### Security / rules reaffirmed (intake carry-over)
Any future Coinbase use goes through the **Advanced Trade / US Derivatives REST API with a trade-only CDP key (view+trade; no transfer, no receive)**, **x402 disabled**, and **never** the remote MCP or all-scopes OAuth. Keys live only in the gitignored `.env` and permit trading, never withdrawals — consistent with the PRD secrets rules and the intake verdict.

### Concrete next step
1. Keep futures as **research only**; the whole $1k stays on Alpaca (current priorities). This appendix creates no trial result and no promotion.
2. If crypto-futures research is later pursued on tiny capital, **Coinbase direct** is the cheapest path to start (free API data, ~$25 nano margin, clean trade-only key) — but design a **structural** crypto strategy first (e.g. funding/basis, calendar roll), not a directional 24/7 punt, and remember the sandbox cannot validate it. A forward paper run would have to be built on Coinbase's **live** feed with our own through-price fill, freshness, fee, slippage and risk-veto rules; the static sandbox does not count.
3. If/when the owner consolidates on **IBKR**, the resold **Coinbase nano BTC/ETH** contracts are reachable there too, trading one funded relationship and entitlement set against Coinbase's free data and tiny margins.
4. Before any promotion: full `docs/promotion-checklist.md`, the "what could blow up this account?" section, max-drawdown and per-regime breakdown, and exact live fee/margin/eligibility confirmation for the chosen entity.

### Sources (Coinbase comparison, reviewed 2026-10-04)
All links reviewed on the research date; a linked source does not imply an account was accessed. Access failures are recorded rather than filled with estimates.

- Coinbase Derivatives overview — https://www.coinbase.com/derivatives
- nano Ether futures listing (Coinbase blog) — https://www.coinbase.com/blog/coinbase-derivatives-exchange-to-add-nano-ether-futures-contract
- Oil & gold futures expansion (Coinbase blog) — https://www.coinbase.com/blog/coinbase-derivatives-expands-futures-offering-to-include-oil-and-gold
- GOLD-PERP / SILVER-PERP launch, non-US (Coinbase blog) — https://www.coinbase.com/blog/the-future-of-gold-and-silver-trading-is-on-coinbase
- CFTC filing, nano Bitcoin Perp-Style listing — https://www.cftc.gov/filings/ptc/ptc06262524818.pdf
- nano Bitcoin specs / margin / fees (FCM product page) — https://lpfutures.com/nano-bitcoin-futures-contract/
- Coinbase Derivatives product list (FCM) — https://info.tradovate.com/coinbase-derivatives-futures-products
- Futures leverage & margin (help; **403** to automated fetch) — https://help.coinbase.com/coinbase/trading-and-funding/derivatives/futures-leverage-margin
- Derivatives fees (help; **403** to automated fetch) — https://help.coinbase.com/en/coinbase/derivatives/derivatives-fees
- Get started with US Derivatives (help) — https://help.coinbase.com/en/coinbase/derivatives/us-derivatives-intro
- US derivatives eligibility / regions (help) — https://help.coinbase.com/en/international-exchange/getting-started/application-qualification-faq
- Advanced Trade REST, US-futures endpoints (dev docs) — https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/rest-api
- API key permission scopes (dev docs) — https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/data-api/get-api-key-permissions
- Advanced Trade sandbox, static (dev docs) — https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/sandbox
- Coinbase MCP (the parked all-scopes path; **not used**) — https://docs.cdp.coinbase.com/ai-agents/coinbase-for-agents/coinbase-mcp
- IBKR adds Coinbase Derivatives nano BTC/ETH (Barchart) — https://www.barchart.com/story/news/133450/interactive-brokers-expands-crypto-futures-offering-with-coinbase-derivatives
- IBKR CME Micro Bitcoin (**403** to automated fetch) — https://www.interactivebrokers.com/en/trading/cme-micro-bitcoin.php
- IBKR cryptocurrencies — https://www.interactivebrokers.com/en/trading/products-cryptocurrencies.php
