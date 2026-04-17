# Troubleshooting

## Yahoo returns 429 Too Many Requests

**Symptom:** logs show repeated `Yahoo 429 for X, retrying in Ns` lines,
often terminating in `Yahoo API exhausted retries`.

**Expected.** Yahoo's chart API is aggressively rate-limited, especially
for bursts. The scraper now honours `Retry-After` headers and stops
after 5 attempts instead of hammering indefinitely.

**Action:** nothing. For macro indicators the stooq fallback kicks in
automatically (you'll see `stooq fallback succeeded` in the log). For
fund prices, JustETF is the primary source and is generally not
rate-limited.

## JustETF price is missing for one ISIN

**Symptom:** a fund in the output has `sources` populated but no
top-level `price` key; the log shows:

```
JustETF price extraction failed for IE00... (got 0.0) — dropping price field
```

**Possible causes:**

1. **Holiday / weekend.** JustETF returns a stale zero when the
   exchange is closed and the ETF is thinly traded. The next trading
   day's run will succeed.
2. **JustETF schema change.** If this started happening for *every*
   fund at the same time, the quote API response format has changed.
   Inspect a raw response:

   ```bash
   curl -s "https://www.justetf.com/api/etfs/IE00B4ND3602/quote?locale=en&currency=EUR" | python -m json.tool
   ```

   If `latestQuote.raw` is missing or renamed, update
   `scripts/fetcher.py::scrape_justetf`.
3. **ISIN is wrong.** JustETF returns HTTP 404 for unknown ISINs.
   Check with a browser.

## Empty JSON output

**Symptom:** the scraper runs, the process exits 0, but every fund and
every macro indicator has `null` or `None` where a value should be.

**Diagnosis:**

```bash
python3 scripts/fetcher.py 2>&1 | grep -E 'WARN|ERROR'
```

If you see widespread warnings, your network is blocking outbound
HTTPS to public APIs (corporate proxies, VPNs, overly strict firewall).
Whitelist `justetf.com`, `finance.yahoo.com`, `stooq.com`,
`production.dataviz.cnn.io`.

## `pydantic.ValidationError` at startup

**Symptom:**

```
pydantic_core._pydantic_core.ValidationError: 1 validation error for AppConfig
portfolio.funds.0.category
  Extra inputs are not permitted [type=extra_forbidden, ...]
```

The config uses `extra="forbid"` on every model, so an unknown field —
almost always a typo — fails fast. The error path in the message
(`portfolio.funds.0.category`) tells you exactly where. Compare against
`config.example.yaml`.

## Allocation rule weights do not sum to 100

**Symptom:**

```
ValueError: AllocationRule[YELLOW] splits sum to 95.00, expected 100.0 +/- 0.01
```

Edit `recommendations.allocation_rules` in `config.yaml` so the
`splits` values for that level sum to exactly 100. Remember that the
synthetic `cash` category is required to balance to 100 — if you
reduce equity exposure, add the difference to `cash`.

## Telegram messages aren't arriving

**Symptom:** brief runs, log says `Telegram notification skipped
(TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set)`.

Set both env vars:

```bash
export TELEGRAM_BOT_TOKEN="<from @BotFather>"
export TELEGRAM_CHAT_ID="<your chat id>"
```

For launchd / cron, add them to your plist's `EnvironmentVariables`
dict or export them in `scripts/run.sh`.

If env vars are set and you still see no message:

```bash
python3 -c "from etf_brief.notify import send_telegram; print(send_telegram('test from etf-brief'))"
```

Check for HTTP 400 (bad chat_id / stale token) or HTTP 401 (revoked
token).

## `ModuleNotFoundError: No module named 'etf_brief'`

**Symptom:** running `pytest tests/` or `python scripts/fetcher.py`
errors out on the `etf_brief.*` imports.

The `scripts/` directory has to be on the Python path. `fetcher.py`
auto-adds it when run directly; `pytest` uses `pyproject.toml`'s
`tool.pytest.ini_options.pythonpath = ["scripts"]` setting.

If you moved files around, either restore the layout or adjust the
pythonpath entry. Editable install isn't required.

## `ModuleNotFoundError: No module named 'pydantic'` (or yaml / loguru / requests / bs4)

**Symptom:** `python scripts/fetcher.py` errors immediately on an
import of `pydantic`, `yaml`, `loguru`, `requests`, or `bs4`. Or
`scripts/run.sh` exits with

```
ERROR: required Python packages missing.
Run: pip install -r requirements.txt
(from the repo root, after activating your venv or conda env).
```

**Diagnosis:** the interpreter Claude Code / your cron job is
launching is different from the one you installed the packages into.
The classic variant is "it worked when I ran it in my terminal, but
cron fails" — cron inherits none of your interactive shell's state,
including `PATH`.

**Fix options (pick one):**

1. **Activate your venv in the shell that launches Claude Code.** On
   macOS, that's your iTerm / Terminal window. `source .venv/bin/activate`
   from the repo root.

2. **Hardcode the interpreter path in cron / launchd.** Example cron
   line:

   ```cron
   0 8 * * 6 /Users/you/.claude/skills/etf-brief/.venv/bin/python /Users/you/.claude/skills/etf-brief/scripts/fetcher.py
   ```

3. **Set `ETF_BRIEF_PYTHON` when calling `scripts/run.sh`:**

   ```bash
   ETF_BRIEF_PYTHON=/Users/you/.claude/skills/etf-brief/.venv/bin/python bash scripts/run.sh
   ```

4. **Fall back to system Python** (not recommended — see
   `docs/INSTALL.md`) and install packages globally with
   `pip install --user -r requirements.txt`.

Verify with:

```bash
python3 -c "import pydantic, yaml, loguru, requests, bs4; print('ok')"
```

from the same shell that will launch the skill.
