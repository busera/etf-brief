# Data sources

What the scraper hits, what each endpoint provides, and how the fallback
chain works. No API keys required for any of the sources below.

## Per-fund prices

### JustETF (primary)

- **Endpoint:** `https://www.justetf.com/api/etfs/{isin}/quote?locale=en&currency=EUR&isin={isin}`
- **Provides:** `latestQuote.raw` (EUR close), `dtdPrc.raw` (1-day %),
  `quoteTradingVenue` (XETRA / other), high / low band.
- **Rate limits:** Observed ~1-2 req/sec tolerated with UA rotation.
  User-Agent throttling, not IP-based.
- **Notes:** The `<realtime-quotes>` Web Component on the JustETF
  profile page calls this same endpoint. Direct JSON access is much
  more reliable than scraping the rendered HTML (which is
  skeleton-placeholder-only as of the 2026 UI refactor).

### Yahoo Finance (secondary)

- **Endpoint:** `https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1mo`
- **Provides:** `regularMarketPrice`, `chartPreviousClose`, currency,
  historical close array for 1-month performance calc.
- **Rate limits:** Aggressive 429s. We retry up to 5 times with
  exponential backoff + jitter, honouring `Retry-After` when present.
  Capped at 30s per backoff.
- **Notes:** User-Agent rotation is important; sustained calls with
  a single UA produce 429 storms.

### TradingView (tertiary fallback)

- **Endpoint:** `https://scanner.tradingview.com/europe/scan` (POST JSON).
- **Provides:** Close, change %, Perf.W/1M/3M/6M/YTD/Y, SMA200, currency.
- **Notes:** Only called if both JustETF and Yahoo produce nothing.
  Symbol mapping: `.DE` → `XETR:`, `.L` → `LSE:`.

## Macro indicators

For VIX, S&P 500, Treasury yields, and gold futures, the scraper tries
Yahoo first, falls back to stooq.com on Yahoo exhaustion.

### Yahoo chart API (primary)

Same endpoint as above, with index-style tickers:

| Indicator | Yahoo ticker |
|---|---|
| VIX | `^VIX` |
| S&P 500 | `^GSPC` |
| 10Y Treasury yield | `^TNX` |
| 2Y Treasury yield | `^IRX` |
| Gold futures | `GC=F` |

### stooq.com (fallback)

- **Endpoint:** `https://stooq.com/q/l/?s={symbol}&f=sd2t2ohlcv&h&e=csv`
- **Format:** Single header row + single data row (Symbol, Date, Time,
  Open, High, Low, Close, Volume).
- **Symbol mapping** (Yahoo → stooq):

| Yahoo | stooq |
|---|---|
| `^VIX` | `^vix` |
| `^GSPC` | `^spx` |
| `^TNX` | `^tnx.us` |
| `^IRX` | `^irx.us` |
| `GC=F` | `gc.f` |

- **Rate limits:** Mild. One call per indicator per run is well within
  stooq's tolerance.
- **Failure modes:** `N/D` in any numeric field → treat as missing.
  Non-positive close → treat as missing.

### CNN Business Fear & Greed (no fallback)

- **Endpoint:** `https://production.dataviz.cnn.io/index/fearandgreed/graphdata`
- **Provides:** `fear_and_greed.score` (0-100), `fear_and_greed.rating`
  (`"fear"`, `"extreme fear"`, `"greed"`, …).
- **Notes:** Single source; if CNN is unavailable, the indicator shows
  "data unavailable" in the brief. No meaningful public alternative.

## The no-API-key promise

Every endpoint above works unauthenticated. You can `git clone` this
repo, `cp config.example.yaml config.yaml`, `python scripts/fetcher.py`,
and get output in under 30 seconds — no registration, no key
management, no billing.

If you later choose to add richer data (FRED macro series, news APIs,
etc.), wire them in behind a feature flag so this default pathway
stays frictionless.
