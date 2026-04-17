# Example Brief

> **Synthetic illustration — not a real brief.** All prices, percentages,
> macro values, ETF flows, and recommendations on this page are
> fabricated for documentation purposes. Last refreshed 2026-04. The
> macro context will date over time; treat this as a snapshot of the
> *output shape*, not as financial guidance.

This is what `/etf-brief` writes to the configured `vault_dir`. A
matching condensed version goes to Telegram. The example uses a
beginner-sized 2-fund portfolio (gold ETC + global equity ETF) so
the EUR amounts stay tractable; the same structure scales to N funds
at any budget.

**Investor profile assumed:** someone who has just started, with
**~1,000 EUR currently invested** and a **200 EUR/month** saving
budget. Starter split is a 40/60 gold/equity tilt; the brief below
shows how the YELLOW signal flips that to 60/40.

The portfolio in this example:

```yaml
portfolio:
  monthly_investment: 200
  currency: EUR
  funds:
    - name: "iShares Physical Gold ETC"
      ticker: "SGLN.L"
      isin: "IE00B4ND3602"
      type: "ETC"
      category: "gold"
      monthly_contribution: 80
      current_value: 600
    - name: "Vanguard FTSE All-World UCITS ETF (Acc)"
      ticker: "VWCE.DE"
      isin: "IE00BK5BQT80"
      type: "ETF"
      category: "global_equity"
      monthly_contribution: 120
      current_value: 400
```

Allocation rule for the YELLOW level used below: `gold: 60`,
`global_equity: 40`, `cash: 0`.

---

```markdown
---
date: 2026-04-11
week: 15
type: etf-brief
signal_level: YELLOW
signal_color: yellow
portfolio_value_eur: 1000
llm_provider: example
llm_model: example
---

# ETF Daily Brief -- 2026-04-11

## SIGNAL: YELLOW
CHANGED from GREEN to YELLOW

## What's Happening & What You Should Do

The headline this week is that US manufacturing slipped into
contraction territory. ISM's monthly factory survey came in at 49.8 --
anything below 50 means more firms are pulling back than expanding.
At the same time, the VIX (the market's "fear gauge") jumped above 22
on the back of softer earnings guidance from a handful of large-cap
US tech names. Consumer confidence has now ticked down for the third
month in a row. None of these are crisis-level on their own, but
together they're enough to bump the recession dial from GREEN to
YELLOW.

For your two saving plans this means *no panic moves*, but you should
shift the mix slightly defensive. Gold has been the big winner so far
this year (+18.2% YTD on the SGLN ETC) -- it acts as portfolio
insurance and is doing exactly what insurance is supposed to do when
the macro mood sours. Global equities (VWCE) are still positive YTD
(+4.5%) but momentum has clearly cooled; the index is only just above
its 200-day moving average and the next leg depends on how the next
two weeks of earnings + the ECB's April 30 decision land.

The concrete recommendation: **HOLD both positions**, but **rebalance
your monthly contributions toward gold** (80 EUR -> 120 EUR) and
**reduce global equity** (120 EUR -> 80 EUR). This matches the
YELLOW allocation rule (60 / 40 split) without selling anything you
already own. Selling triggers a taxable event; pausing or
re-weighting a saving plan does not. If the level worsens to ORANGE
in coming weeks (sell threshold = 4 active signals), the next step
would be to build a small cash buffer rather than chase further into
gold.

What to watch this week: the **ECB's April 30 rate decision** is the
big one -- the market is split roughly 50/50 between hold and a 25 bp
cut. A surprise cut would confirm the slowdown narrative and likely
push us toward ORANGE. On the other side, a clean US payrolls print
on May 2 could pull us back to GREEN.

In Scalable: change the SGLN saving plan from 80 to 120 EUR, change
VWCE from 120 to 80 EUR. That's it.

## Recommendations
- **iShares Physical Gold ETC (SGLN)**: HOLD -- already up 18.2% YTD,
  no need to chase higher. Increase the monthly amount instead.
- **Vanguard FTSE All-World (VWCE)**: HOLD but MONITOR -- still above
  the 200-day MA, but momentum is fading and earnings risk is
  elevated.

## Suggested Allocation (200 EUR/month)
- Gold ETC (SGLN): 120 EUR (60%)
- Global Equity (VWCE): 80 EUR (40%)
- Cash reserve: 0 EUR (0%)

Change from current: SGLN +40 EUR, VWCE -40 EUR. No change to total
monthly contribution.

## Recession Dashboard
| Indicator | Value | Status |
|-----------|-------|--------|
| US Yield Curve (10Y-2Y) | +0.18% | Normal (re-steepened from late-2025 inversion) |
| VIX | 22.4 | Elevated |
| PMI Manufacturing | 49.8 | Contracting |
| Consumer Confidence | 102.1 | Declining (3rd month) |
| Unemployment Claims | 218k | Stable |
| ECB / Fed Rates | 2.25% / 4.00% | Cutting cycle |
| S&P 500 vs 200-day MA | +2.1% above | Bullish (marginal) |
| Gold Trend (3mo) | +5.4% | Rising |

**Active signals: 3 / 8 -- YELLOW**

(Active = VIX > thresholds.threshold_warn, PMI < contraction
threshold, Consumer Confidence on a 3-month decline.)

## Fund Performance
- **SGLN.L**: EUR 56.78 (1d: +0.4% | 1m: +3.1% | YTD: +18.2%)
- **VWCE.DE**: EUR 124.50 (1d: -0.8% | 1m: -1.4% | YTD: +4.5%)

## Bitcoin Watch
- **BTC Price**: EUR 78,420 (1d: -2.1% | 1m: +5.8% | YTD: +12.4%)
- **BTC vs 200-day MA**: above by 6%
- **BTC Fear & Greed**: 42 (neutral)
- **US BTC ETF Flows**: net inflow $410m this week
- **Halving cycle**: ~24 months post-halving (April 2024)
- **Recommendation**: WAIT -- still above the 200-day MA but
  correlation with equities has been creeping up; if VWCE breaks its
  200-day MA, BTC will likely follow. Reassess at GREEN or after a
  >15% drawdown from the cycle high.
- **If starting**: Bitwise Physical Bitcoin ETP (BTCE.DE, TER 0.20%)
  at 10-20 EUR/month -- keep BTC under 10% of total monthly budget
  while still on the watchlist.

## Alternative ETF Watch
- **Xtrackers II Eurozone Government Bond UCITS ETF (LU0290355717)**:
  TER 0.16%, available on Scalable Capital. Why now: with the ECB
  signalling further cuts and PMI in contraction, EUR-zone government
  bond duration becomes attractive as a defensive complement to gold.
  Worth a starter saving plan if YELLOW persists into May.

## Market Context

The macro picture this week is one of *soft data deteriorating faster
than hard data*. Survey-based indicators (PMI, consumer confidence)
have rolled over, but the labour market and corporate earnings are
holding up. This is the textbook YELLOW pattern -- not a recession
yet, but a meaningful slowdown signal.

Central banks are in different places: the ECB is well into its
cutting cycle (current policy rate 2.25%, two more 25 bp cuts priced
in by year-end) while the Fed is still on hold at 4.00%. The
EUR-USD widening means euro-denominated portfolios get a small
tailwind on USD-priced assets like gold and US-heavy global equity
ETFs.

Geopolitical: nothing acute, but watch the US-China trade headlines
into the May G20 summit -- a fresh tariff round would push us toward
ORANGE quickly.

## Key News
- ISM Manufacturing PMI 49.8 -- Reuters -- first sub-50 print since
  Aug 2025; new orders sub-index particularly weak.
- ECB sources flag "openness" to faster cuts -- Bloomberg -- raises
  probability of a 25 bp move on April 30.
- Gold ETF holdings reach 2-year high -- World Gold Council -- net
  inflows of $4.2bn in March; institutional demand strong.
- US consumer confidence falls for 3rd month -- Conference Board --
  expectations index now below the 80 threshold that historically
  precedes recession.

## Sources

- ISM PMI report (ismworld.org)
- ECB monetary policy statement (ecb.europa.eu)
- World Gold Council monthly report (gold.org)
- Conference Board consumer confidence (conference-board.org)
- JustETF quote API for SGLN, VWCE
- Yahoo Finance chart API for VIX, S&P 500, gold futures
- CNN Business Fear & Greed (BTC F&G)

---
*Automated analysis for personal use. Not financial advice.*
```

## Telegram (condensed) version

The same brief sent via Telegram drops the dashboard tables and
sources, keeping only the action layer:

```
ETF Brief -- 2026-04-11 -- YELLOW
SIGNAL CHANGED from GREEN to YELLOW

RECOMMENDATIONS:
- Gold ETC: HOLD (already +18% YTD; raise monthly contribution)
- Global: HOLD + MONITOR (200d MA holding, momentum fading)

Allocation: 120 / 80 EUR (was 80 / 120 -- swap weights)

Recession signals: 3/8
VIX: 22.4 | Yield curve: normal | PMI: 49.8 (contracting)

Performance (1d / 1m / YTD):
- SGLN: +0.4% / +3.1% / +18.2%
- VWCE: -0.8% / -1.4% / +4.5%

Soft data is rolling over (PMI sub-50, consumer confidence -3 months,
VIX > 22). Hard data still OK. Shift contributions toward gold,
no selling. ECB Apr 30 is the next big checkpoint -- a surprise cut
would push us to ORANGE.

Full brief in vault.
```

If signal level were ORANGE or RED, the Telegram message would be
prepended with `** MARKET ALERT **`.
