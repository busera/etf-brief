# Configuration guide

Every setting lives in `config.yaml` at the repo root (copy from
`config.example.yaml` on first setup). `config.yaml` is gitignored so
your private portfolio never leaks into version control.

The file is validated with pydantic v2 on load. Unknown keys fail loudly
(`extra="forbid"`), so a typo in a field name becomes a startup error
rather than silent mis-analysis downstream.

## `portfolio`

Top-level saving-plan settings.

| Field | Type | Required | Notes |
|---|---|---|---|
| `monthly_investment` | int | yes | Total EUR per month across all saving plans. |
| `currency` | str | yes | Display currency (e.g. `"EUR"`). Not converted — purely cosmetic. |
| `broker` | str | yes | Your broker name. Informational. |
| `execution_day` | int | yes | Day of month saving plans execute (e.g. `4` for Scalable Capital). |
| `funds` | list | yes | See `FundConfig` below. At least one entry. |
| `total_value` | float | no | Optional snapshot of current portfolio value for display. |
| `total_monthly` | int | no | Optional — useful to cross-check against sum of `monthly_contribution`. |

### `FundConfig` entry

| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | str | yes | Display name. |
| `ticker` | str | yes | Exchange-suffix ticker for Yahoo (e.g. `"VWCE.DE"`, `"SGLN.L"`). |
| `isin` | str | yes | For JustETF lookup (canonical identifier). |
| `type` | `"ETF"` \| `"ETC"` | yes | Literal. |
| `category` | str | yes | Freeform string. Must appear as a key in `recommendations.allocation_rules.*.splits`. |
| `monthly_contribution` | int | no (default 0) | EUR per month for this fund. |
| `current_value` | float | no | Optional — current portfolio position value for display. |
| `total_return_pct` | float | no | Optional — cumulative return since inception, for display. |
| `allocation_pct` | float | no | Optional — actual % of portfolio. Shown in JSON output if set. |

## `bitcoin`

Optional BTC section.

| Field | Type | Required | Notes |
|---|---|---|---|
| `status` | `"watchlist"` \| `"active"` \| `"disabled"` | yes | Controls whether the skill generates a Bitcoin section. |
| `monthly_budget` | float | no | EUR per month if a BTC saving plan is active. |
| `scalable_options` | list | no | Candidate ETP products (name, ISIN, TER, note). |
| `direct_options` | list | no | Direct-purchase venues (exchanges, apps) — add your own. |
| `indicators` | list | no | Search queries for BTC-specific signals. |

## `sources`

Web sources used for WebSearch context. These are hints to the LLM
during brief generation, not hit directly by the scraper.

| Field | Type | Notes |
|---|---|---|
| `price_sources` | list\[str] | Hosts for fund prices (e.g. `"finance.yahoo.com"`). |
| `macro_sources` | list\[str] | FRED, ECB, tradingeconomics. |
| `analysis_sources` | list\[str] | Reuters, Bloomberg, FT, Morningstar. |
| `etf_sources` | list\[str] | ETF screeners. |
| `gold_sources` | list\[str] | kitco, gold.org. |
| `sentiment_sources` | list | Each entry has `source`, `type` (`"reddit"`/`"x"`/`"forum"`/`"other"`), optional `note`, optional `search_terms`. |

## `recession_signals.indicators`

Each indicator is one row in the Recession Dashboard.

| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | str | yes | Display name. |
| `search_query` | str | yes | Passed to WebSearch during brief generation. |
| `weight` | `"low"` \| `"medium"` \| `"high"` | yes | Affects signal-level-bump logic. |
| `signal` | str | no | Descriptor — "inverted", "price_below_ma", "rising_trend", etc. |
| `threshold_warn` | float | no | e.g. VIX > 25 triggers "elevated". |
| `threshold_critical` | float | no | e.g. VIX > 35 triggers "high". |
| `threshold_contraction` | float | no | e.g. PMI < 50. |
| `note` | str | no | Freeform context. |

## `thresholds`

| Field | Type | Notes |
|---|---|---|
| `hold_max_signals` | int | Signal count at or below which HOLD is default. |
| `decrease_min_signals` | int | Count above which DECREASE is default. |
| `decrease_max_signals` | int | Above this, SELL takes over. |
| `sell_min_signals` | int | Count at or above which SELL is default for equities. |
| `increase_gold_min_signals` | int | Count at or above which INCREASE gold fires. |
| `drawdown_warn` | float | Per-fund % drawdown to warn at (negative number). |
| `drawdown_sell` | float | Per-fund % drawdown to trigger SELL (negative number). |
| `rally_take_profit` | float | % 30-day rally that triggers take-profit guidance. |

## `output`

| Field | Type | Notes |
|---|---|---|
| `vault_dir` | str | Directory to write briefs to. Use `"./output/"` for local runs, or an Obsidian vault path. |
| `telegram` | bool | If `true`, the skill sends a condensed version via Telegram when env vars are set. |

## `analysis`

| Field | Type | Notes |
|---|---|---|
| `lookback_days` | int | Day window for trend analysis (default 30). |
| `ma_period` | int | Moving-average period for price-vs-MA signals (default 200). |
| `sentiment_weight` | float | Weight applied to Reddit / X sentiment when scoring (0-1). |

## `recommendations.allocation_rules`

Heart of the config-driven allocation.

```yaml
recommendations:
  allocation_rules:
    - level: GREEN
      splits:
        gold: 33
        global_equity: 34
        europe_equity: 33
        cash: 0
    - level: YELLOW
      splits:
        gold: 40
        global_equity: 30
        europe_equity: 30
        cash: 0
    # ... ORANGE, RED
```

- One rule per signal level. The canonical four are `GREEN`, `YELLOW`,
  `ORANGE`, `RED`, but `level` is free-form — you can model custom
  regimes (e.g. `EXTREME`) as long as each level appears at most once
  across the rule set. Level strings are upper-cased on load, so
  `yellow` and `YELLOW` are the same level.
- `splits` keys must match the `category` values of your funds — plus the
  synthetic `cash` category (money held outside the saving plan). A
  pydantic cross-field validator rejects any unknown category with
  `allocation_rules.splits references unknown category 'X' — not in
  funds[].category or 'cash'`.
- Weights are percentages. A pydantic validator rejects the config
  if weights for any level do not sum to 100 (tolerance 0.01).
- The `/etf-brief onboard` wizard rounds percentages to whole numbers
  and absorbs any residual into the largest split so each level sums
  to exactly 100. A hand-computed 33.34 / 33.33 / 33.33 renders as
  34 / 33 / 33.

### Example: 3-fund vs 5-fund portfolio

3-fund (gold + global + europe, same as `config.example.yaml`):

```yaml
splits:
  gold: 33
  global_equity: 34
  europe_equity: 33
  cash: 0
```

5-fund (add emerging + bonds):

```yaml
splits:
  gold: 25
  global_equity: 25
  europe_equity: 15
  emerging_markets: 15
  bonds: 15
  cash: 5
```

Remember to add matching `category: "emerging_markets"` etc. to your
`portfolio.funds` entries. Categories not present in any fund are
allowed (they become synthetic cash-like buckets).

To compute EUR amounts:

```
EUR per category = monthly_investment * pct / 100
```

At 500 EUR/month with GREEN weights 33/34/33/0:

- Gold: 500 × 33 / 100 = 165 EUR
- Global: 500 × 34 / 100 = 170 EUR
- Europe: 500 × 33 / 100 = 165 EUR
- Cash: 500 × 0 / 100 = 0 EUR

## Tuning knobs (advanced)

A handful of HTTP-behaviour constants live in `scripts/fetcher.py` as
module-level constants rather than config keys. The defaults are
tuned for Yahoo + JustETF at the current 2026 rate limits and
should not need changing for normal use. If you hit sustained
429s, drop the interval; if the scraper feels slow on a good
connection, raise it.

| Constant | Default | Meaning |
|---|---|---|
| `RATE_LIMIT_SECONDS` | `1.5` | Minimum seconds between consecutive Yahoo chart-API calls (hard floor, enforced by `_RateLimiter`). |
| `MAX_RETRIES` | `5` | Upper bound on Yahoo 429-retry attempts. After this many `Retry-After` sleeps the fetcher gives up and returns `None`. |
| `BACKOFF_CAP_SECONDS` | `30.0` | Absolute ceiling on per-retry sleep. Caps both exponential backoff and `Retry-After` headers — protects against pathological server responses. |
| `TIMEOUT` | `30` | `requests.get` timeout (seconds) for every fetch. Applies to JustETF, Yahoo, TradingView, and Fear & Greed. |

These are module-level constants, not config keys. Users who need
to tune them edit `scripts/fetcher.py` directly. Keep any changes
local to your fork — they are not part of the `config.yaml` schema.

## `llm`

Optional. Configures the **standalone Python brief generator**
(`scripts/generate_brief.py`). The Claude Code skill (`/etf-brief`)
ignores this block entirely — it always runs inside the Claude Code
session that loaded `SKILL.md`. This block matters only when invoking
the generator from cron, CI, or any environment without Claude Code.

```yaml
llm:
  primary: claude
  fallback_order: [claude, ollama]
  ollama:
    enabled: false
    endpoint: "http://localhost:11434"
    model: "qwen2.5-coder:7b-instruct-mlx"
    temperature: 0.3
    num_predict: 4096
    timeout_seconds: 120
  anthropic_sdk_model: "claude-sonnet-4-6"
```

| Field | Type | Default | Notes |
|---|---|---|---|
| `primary` | `"claude"` \| `"ollama"` \| `"anthropic_sdk"` | `"claude"` | First provider tried. |
| `fallback_order` | list[str] | `["claude", "ollama"]` | Subsequent providers, in order. Duplicates of `primary` are dropped. Unknown keys are silently ignored. |
| `ollama.enabled` | bool | `false` | When `false`, Ollama is removed from the chain even if listed. |
| `ollama.endpoint` | str | `"http://localhost:11434"` | Base URL of the Ollama HTTP server. Trailing slash is stripped. |
| `ollama.model` | str | `"qwen2.5-coder:7b-instruct-mlx"` | Model name as known to Ollama (`ollama list`). |
| `ollama.temperature` | float | `0.3` | Sampling temperature. |
| `ollama.num_predict` | int | `4096` | Max tokens to generate. |
| `ollama.timeout_seconds` | int | `120` | HTTP timeout for `/api/chat` per request. |
| `anthropic_sdk_model` | str | `"claude-sonnet-4-6"` | Model passed to `anthropic.Anthropic().messages.create()`. Requires `ANTHROPIC_API_KEY` and the `anthropic` package. |

### Provider availability

* **Claude CLI** — available iff `claude` is on `PATH`. Detected
  via `shutil.which("claude")`.
* **Ollama** — available iff `GET {endpoint}/api/tags` returns 200
  within 5 s. Probed once at construct time.
* **Anthropic SDK** — available iff the `anthropic` package is
  importable AND `ANTHROPIC_API_KEY` is set in the environment.

Providers that fail their availability check are silently dropped
from the chain (with a debug-level log line). If every provider is
unavailable or every provider fails, the generator exits non-zero
with all per-provider error strings joined into the message.

### CLI override

`scripts/generate_brief.py --provider=<name>` force-enables the
chosen provider as the *only* chain entry — bypassing
`ollama.enabled`, `primary`, and `fallback_order`. Use this for
testing a specific provider:

```bash
python scripts/generate_brief.py --provider=ollama --dry-run
python scripts/generate_brief.py --provider=claude
```

`--provider=auto` (the default) honours the chain configured in
`config.yaml`.
