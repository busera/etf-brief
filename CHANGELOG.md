# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-04-17

### Added
- Initial public release.
- Pydantic v2 config validation (`AppConfig` + sub-models, `extra="forbid"`).
- Config-driven allocation rules — each signal level (GREEN / YELLOW /
  ORANGE / RED) maps fund categories to percentage weights. Weights
  validated to sum to 100 per level.
- `scripts/etf_brief/fallback.py` — stooq.com CSV fallback for VIX,
  S&P 500, Treasury yields (10Y / 2Y), and gold futures when Yahoo
  Finance returns 429s (fixes backlog item **etf-brief-003**).
- `scripts/etf_brief/notify.py` — optional Telegram notification helper
  that reads `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` from env vars.
  Silent no-op when unset; never raises.
- Portable `scripts/run.sh` cron wrapper with `$ETF_BRIEF_ROOT`
  auto-detection, mkdir-based lock, stale-lock detection, and
  `ETF_BRIEF_DRY_RUN=1` mode.
- GitHub Actions CI matrix: Python 3.10 / 3.11 / 3.12.
- Docs: `docs/CONFIGURATION.md`, `docs/DATA_SOURCES.md`,
  `docs/TROUBLESHOOTING.md`.

### Fixed
- `scrape_justetf` — JustETF switched its profile page to a
  JavaScript-rendered `<realtime-quotes>` Web Component in early 2026.
  The server-side HTML is skeleton placeholders only, so the old
  selector chain (`span.val`, `div.infobox span.val`, `.quote-val`)
  started returning ISIN/WKN identifiers or zero. The fetcher now calls
  the JSON endpoint the component itself hits
  (`/api/etfs/{isin}/quote?…`) and rejects non-positive prices with a
  warning instead of persisting a zero (fixes backlog item
  **etf-brief-002**).

### Changed
- Switched config loading to pydantic; malformed user YAML now fails
  with a precise validation error at the program boundary rather than
  silently producing wrong analysis downstream.
- Split `fetch_all()` into `_fetch_fund_prices()` + `_fetch_macro_indicators()`
  orchestrators so each stays below the 30-line function ceiling.
