# ETF Brief

A Claude Code skill that produces a weekly ETF / ETC investment brief:
recession-signal dashboard, per-fund HOLD/INCREASE/DECREASE/SELL
recommendations, config-driven allocation rules, an optional Bitcoin
watch, and optional Telegram + Obsidian output.

This is decision support, not financial advice. The skill tells you what
the indicators say and what a reasonable response looks like. You make
the call.

## Features

- **Recession dashboard** — 8 weighted signals (yield curve, VIX, PMI,
  consumer confidence, unemployment claims, central-bank rates, S&P vs
  200-day MA, gold trend) with severity levels GREEN / YELLOW / ORANGE /
  RED.
- **Per-fund recommendations** — HOLD, INCREASE, DECREASE, or SELL per
  ETF, driven by recession level + per-fund context.
- **Config-driven allocation rules** — each signal level maps fund
  categories to percentage weights. Add / remove categories freely; a
  pydantic validator enforces that weights sum to 100 per level.
- **Bitcoin watchlist** — optional BTC section covering price, 200-day
  MA, Fear & Greed, halving cycle, and a clear START / WAIT / NOT NOW
  recommendation. Toggle via `bitcoin.status` in config.
- **Alternative ETF scan** — when signal is YELLOW or worse, the skill
  surfaces at least one concrete ETF-to-watch (ISIN, TER, why now).
- **Multiple output channels** — terminal always, Obsidian / local
  markdown file, optional Telegram. Plain text throughout (no parse
  mode shenanigans).
- **Data sources** — JustETF quote API (primary), Yahoo Finance chart
  API (secondary), stooq.com CSV (macro fallback), CNN Business Fear &
  Greed. No API keys required for any of the base sources.

## Installation

### 1. Clone

```bash
mkdir -p ~/.claude/skills
git clone https://github.com/<your-username>/etf-brief ~/.claude/skills/etf-brief
cd ~/.claude/skills/etf-brief
```

### 2. Python environment (recommended: venv)

```bash
python3 -m venv .venv
source .venv/bin/activate          # macOS / Linux
# .venv\Scripts\activate            # Windows PowerShell
pip install -r requirements.txt
```

<details>
<summary><strong>Alternative: conda</strong></summary>

```bash
conda create -n etf-brief python=3.12
conda activate etf-brief
pip install -r requirements.txt
```
</details>

<details>
<summary><strong>Alternative: system / global Python (not recommended)</strong></summary>

Works, but you trade isolation for convenience. Dependency conflicts
become your problem.

```bash
python3 -m pip install --user -r requirements.txt
```
</details>

See [`docs/INSTALL.md`](docs/INSTALL.md) for the full discussion,
including the cron / launchd activation pitfall.

### 3. Configure

Three paths — pick one:

**A. Run the onboarding wizard in Claude Code (recommended for new users):**

```
/etf-brief onboard
```

The wizard asks one question at a time, validates each ISIN against
JustETF, and writes a ready-to-use `config.yaml` on exit.

**B. Run the wizard on the command line (no Claude Code required):**

```bash
PYTHONPATH=scripts python -m etf_brief.onboard_cli
```

Add `--defaults --yes --force` for a fully non-interactive run that
generates a working skeleton without prompts.

**C. Copy the example and edit by hand:**

```bash
cp config.example.yaml config.yaml       # edit to your funds
```

No `pip install -e .` required — `fetcher.py` adds its sibling
`etf_brief/` package to `sys.path` at runtime. `requirements.txt` and
`requirements-dev.txt` are convenience mirrors of the canonical
dependency declaration in `pyproject.toml`.

## Usage

From Claude Code:

```
/etf-brief
```

The skill runs the scraper, analyzes the result, and produces a brief.

Run the scraper standalone to see the raw JSON:

```bash
python3 scripts/fetcher.py
```

Schedule via cron / launchd with the included wrapper:

```bash
ETF_BRIEF_DRY_RUN=1 bash scripts/run.sh   # smoke test
```

The wrapper handles locking, stale-lock detection, and log rotation —
wire in your own driver (e.g. `claude -p "/etf-brief" ...`) where the
file says.

### Standalone brief generation (no Claude Code)

The skill ships a Python brief generator at `scripts/generate_brief.py`
for environments where Claude Code is not available — cron, CI,
remote boxes, or local LLM workflows. It reuses the same fetcher,
config, and output template as the Claude Code path.

```bash
PYTHONPATH=scripts python scripts/generate_brief.py                  # auto chain from config.llm
PYTHONPATH=scripts python scripts/generate_brief.py --provider=ollama --dry-run
PYTHONPATH=scripts python scripts/generate_brief.py --from-json /tmp/snapshot.json
```

The provider chain (Claude CLI → Ollama → Anthropic SDK) is
configured in the `llm` block of `config.yaml`. See the LLM section
of [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md#llm) for the
schema and provider semantics.

## What the brief looks like

[`docs/EXAMPLE_BRIEF.md`](docs/EXAMPLE_BRIEF.md) shows a synthetic
end-to-end brief (Obsidian markdown + Telegram condensed) for a
beginner-sized 2-fund portfolio (1,000 EUR invested, 200 EUR/month)
at a YELLOW signal level. Synthetic data, not financial guidance.

## Configuration

Everything lives in `config.yaml`. See
[`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) for a section-by-section
walkthrough.

- `portfolio.funds` — your ETFs / ETCs (name, ticker, ISIN, category).
- `thresholds` — how many active signals trigger each recommendation.
- `recommendations.allocation_rules` — category splits per signal level.
- `bitcoin` — watchlist / active BTC section. Optional.
- `output.vault_dir` — where to write briefs.
- `output.telegram` — off by default.

## Data sources

See [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md) for a complete list
of URLs hit by the scraper, what each provides, rate limits that apply,
and the no-API-key promise.

Fallback chain for macro indicators:

1. Yahoo Finance chart API (primary)
2. stooq.com CSV endpoint (fallback when Yahoo 429s)
3. Otherwise: record `None` and continue (the skill reports "data
   unavailable" for that indicator)

## Optional: Telegram notifications

Set two environment variables:

```bash
export TELEGRAM_BOT_TOKEN="<token-from-@BotFather>"
export TELEGRAM_CHAT_ID="<your-chat-id>"
```

When unset, `send_telegram()` logs a single INFO line and returns
`False`. It never raises, so your brief runs identically with or
without Telegram configured.

## Development

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

Tests never hit the network — every HTTP path is mocked. Loguru is
redirected to `tmp_path` via an autouse conftest fixture so error-path
tests do not contaminate production logs (TS-14 compliance).

## Troubleshooting

Common issues and fixes:
[`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md).

## License

MIT. See [`LICENSE`](LICENSE).

## Disclaimer

This skill is decision support, not financial advice. The author is
not a licensed financial advisor. ETFs / ETCs / any securities can lose
value. Do your own research. The example configuration in
`config.example.yaml` uses real, public products purely so the skill is
runnable end-to-end out of the box; their presence is not a
recommendation.
