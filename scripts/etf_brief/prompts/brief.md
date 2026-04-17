You are generating today's ETF investment brief from the inputs below.

==========================================================================
TODAY (Berlin local date): ${today_iso}
==========================================================================

## INPUT 1 — Fetcher JSON (live prices + macro indicators)

```json
${fetcher_json}
```

## INPUT 2 — Portfolio configuration

${config_summary}

## INPUT 3 — Previous briefs (most recent first; for trend / signal-change detection)

${previous_briefs_summary}

==========================================================================

# Your task

Produce the full ETF brief in **Obsidian markdown**, following the
authoritative template at the bottom of this prompt **exactly**. No
preamble, no meta-commentary, no "here is the brief". Output starts
with the `---` frontmatter line and ends with the disclaimer line.

## Step 1 — Recession signal level

Count the active recession signals from INPUT 1 (use the
`recession_signals.indicators` defined in INPUT 2 to know what
counts as "active"). Then derive the signal level using the
`thresholds` block from INPUT 2:

* GREEN — `active_signals <= thresholds.hold_max_signals`
* YELLOW — `thresholds.decrease_min_signals <= active_signals <= thresholds.decrease_max_signals`
* ORANGE — `active_signals == thresholds.sell_min_signals - 1`
* RED — `active_signals >= thresholds.sell_min_signals`

A single HIGH-weight signal (yield-curve inversion, VIX > 35,
S&P 500 below 200-day MA) bumps the level up by one even when the
total count is low.

## Step 2 — Per-fund recommendations

Apply the per-category rules below to each fund in INPUT 2's
`portfolio.funds` list, keyed on `category`:

**`gold`** — GREEN/YELLOW = HOLD (insurance), ORANGE/RED = INCREASE
(recession hedge). If gold YTD already > +20%, downgrade INCREASE to
HOLD (do not chase).

**`global_equity`** — GREEN = HOLD, YELLOW = HOLD + monitor,
ORANGE = DECREASE, RED = SELL (especially if drawdown from high > 20%).

**`europe_equity`** — same as global, but factor ECB rate trajectory
(cuts = slowing economy), EU-specific risks, and EUR strength.

**Anything else** (custom categories) — explain reasoning explicitly.

## Step 3 — Allocation (config-driven)

Find the `recommendations.allocation_rules` rule for the chosen
signal level in INPUT 2. Apply the percentages to
`portfolio.monthly_investment`:

```
EUR_per_category = monthly_investment * pct / 100
```

The four amounts must sum to `monthly_investment` exactly. Show the
delta from the current `monthly_contribution` per fund where it
differs.

## Step 4 — Bitcoin assessment (mandatory)

Use INPUT 1 + INPUT 2 `bitcoin` block. Output:

* BTC price + 1d/1m/YTD performance
* BTC vs 200-day MA (above / below by X%)
* BTC Fear & Greed
* Halving-cycle position (last halving April 2024)
* Net BTC ETF flows this week (if available; "data unavailable" if not)
* Clear START / WAIT / NOT NOW recommendation with plain-English reasoning
* If START: recommended vehicle (ETP vs direct exchange) + suggested monthly amount

## Step 5 — Alternative ETF (mandatory — at least one)

Recommend at least one ETF/ETC worth watching beyond the current
portfolio. Provide name, ISIN, TER, why **NOW specifically**, and
broker availability (assume `portfolio.broker` from INPUT 2). "Nothing
compelling — stick with current funds" is acceptable only if the
fetcher data genuinely shows no new signals.

## Step 6 — Signal-change detection from INPUT 3

If a previous brief exists and the level changed, prepend the
SIGNAL section with `CHANGED from <old> to <new>`. If unchanged for
5+ briefs, add a one-sentence note in "What's Happening" explaining
why the recommendation persists.

## Step 7 — Footnoted sourcing

Every price, indicator, and macro data point must carry a footnote
citing the source URL and retrieval time. Recommendations carry a
footnote with confidence tag `[HIGH]` / `[MEDIUM]` / `[LOW]` and
the evidence basis. Footnotes go at the bottom of the markdown,
not in any condensed/Telegram form.

==========================================================================

# Output template (authoritative — match exactly)

```markdown
---
date: ${today_iso}
week: <ISO week number>
type: etf-brief
signal_level: <GREEN | YELLOW | ORANGE | RED>
signal_color: <green | yellow | orange | red>
portfolio_value_eur: <total of funds[].current_value or null>
llm_provider: <will be filled by the runner — leave as TBD>
llm_model: <will be filled by the runner — leave as TBD>
---

# ETF Daily Brief -- ${today_iso}

## SIGNAL: <GREEN | YELLOW | ORANGE | RED>
<If changed from yesterday: "CHANGED from GREEN to YELLOW">

## What's Happening & What You Should Do

<3-5 paragraphs in plain English. Cover:
1. What's going on in the markets RIGHT NOW (no jargon, expand acronyms on first use)
2. Why it matters for the user's specific funds (gold / global stocks / European stocks)
3. The concrete recommendation and WHY (explain the reasoning, not just the action)
4. What would change this recommendation (the watch list)
5. Concrete broker actions for this week — or explicit "nothing to do"

Write like you are explaining to a smart friend over coffee who does not follow markets daily.
Be opinionated; no "on the other hand" hedging.>

## Recommendations
- **<Fund 1 name> (<ticker>)**: <HOLD | INCREASE | DECREASE | SELL> -- <reason in one line>
- **<Fund 2 name> (<ticker>)**: <action> -- <reason>
- **<Fund 3 name> (<ticker>)**: <action> -- <reason>

## Suggested Allocation (<monthly_investment> EUR/month)
- <Fund 1>: <EUR amount> EUR (<pct>%)
- <Fund 2>: <EUR amount> EUR (<pct>%)
- <Fund 3>: <EUR amount> EUR (<pct>%)
- Cash reserve: <EUR amount> EUR (<pct>%)
<If different from current monthly_contribution per fund: "Change from current: ..." line>

## Recession Dashboard
| Indicator | Value | Status |
|-----------|-------|--------|
| US Yield Curve (10Y-2Y) | +X.XX% | Normal / Inverted |
| VIX | XX.X | Low / Elevated / High |
| PMI Manufacturing | XX.X | Expanding / Contracting |
| Consumer Confidence | XX.X | Stable / Declining |
| Unemployment Claims | XXXk | Stable / Rising |
| ECB / Fed Rates | X.XX% | Hold / Cut / Hike |
| S&P 500 vs 200-day MA | +X% above/below | Bullish / Bearish |
| Gold Trend (3mo) | +X% | Flat / Rising / Falling |

**Active signals: X / <total> -- <LEVEL>**

## Fund Performance
- **<ticker>**: EUR XX.XX (1d: X% | 1m: X% | YTD: X%)
- ...

## Bitcoin Watch
- **BTC Price**: EUR XX,XXX (1d: X% | 1m: X% | YTD: X%)
- **BTC vs 200-day MA**: above / below by X%
- **BTC Fear & Greed**: XX (<rating>)
- **US BTC ETF Flows**: net inflow / outflow $XXm this week
- **Halving cycle**: ~XX months post-halving (April 2024)
- **Recommendation**: <START | WAIT | NOT NOW> -- <plain-English reasoning>
- **If starting**: <vehicle + suggested monthly amount>

## Alternative ETF Watch
- **<Name> (<ISIN>)**: TER X.XX%, available on <broker>. Why now: <one-line reason>.
<Add more entries if multiple are compelling. "Nothing compelling — stick with current funds" is acceptable when justified.>

## Market Context
<2-3 paragraphs: key macro developments, central-bank stance, geopolitical factors affecting the portfolio. Cite sources via footnotes.>

## Key News
- <headline> -- <source> -- <one-line impact assessment>
- ...

## Sources
- <list of footnote URLs used for data>

---
*Automated analysis for personal use. Not financial advice.*
```

==========================================================================

# Quality checklist (run mentally before emitting)

1. Allocation amounts sum to `monthly_investment` exactly.
2. Every "increase" / "decrease" word matches the direction of the EUR delta.
3. Signal level is consistent with the active-signal count + the threshold rules above.
4. BTC section is present with clear START / WAIT / NOT NOW.
5. At least one alternative ETF is present (or a justified "nothing compelling").
6. No contradictions between "What's Happening" and "Recommendations".
7. Signal change vs INPUT 3 is flagged when applicable.
8. Every data point has a footnote source.
9. Disclaimer line is present.
