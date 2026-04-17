"""ETF data fetcher — scrapes prices, performance, and macro indicators.

This is the primary data-gathering entry point for the etf-brief skill.
It pulls per-fund prices from JustETF and Yahoo Finance, and macro
indicators (VIX, Fear & Greed, yield curve, S&P 500, gold) from Yahoo
with a stooq.com CSV fallback.

Outputs a single JSON document to stdout so the consuming skill (Claude
Code `/etf-brief`) can read it without reinventing the data layer.

Run standalone::

    python scripts/fetcher.py

or via the cron wrapper::

    bash scripts/run.sh

Bug-fix notes (2026-04-17):

* ``scrape_justetf`` — JustETF switched the profile page to a
    JavaScript-rendered ``<realtime-quotes>`` Web Component that leaves
    server-side HTML as skeleton placeholders. The old selector chain
    (``span.val``, ``div.infobox span.val``, ``.quote-val``) started
    returning ISIN/WKN identifiers or zeros. This module now calls the
    AJAX endpoint the component itself hits:
    ``https://www.justetf.com/api/etfs/{isin}/quote``. The
    ``price > 0`` guard drops the field and logs a warning instead of
    writing a zero into the output (etf-brief-002).
* Macro indicators gain a ``stooq_quote`` fallback: when Yahoo exhausts
    retries we try stooq's free CSV endpoint before giving up
    (etf-brief-003).
"""

from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path
from typing import Any

import requests
import yaml
from bs4 import BeautifulSoup

# Make the sibling ``etf_brief`` package importable without pip install.
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from etf_brief.datetime_utils import now_berlin  # noqa: E402
from etf_brief.fallback import stooq_quote  # noqa: E402
from etf_brief.http_utils import USER_AGENTS, get_rotating_headers  # noqa: E402
from etf_brief.logging_config import setup_logger  # noqa: E402
from etf_brief.models import AppConfig  # noqa: E402

logger = setup_logger(
    "etf_brief",
    log_dir=_SCRIPTS_DIR.parent / "logs",
)

RATE_LIMIT_SECONDS = 1.5
MAX_RETRIES = 5
BACKOFF_CAP_SECONDS = 30.0
TIMEOUT = 30

# Re-export USER_AGENTS for tests that still grep ``fetcher.USER_AGENTS``
# after the module was split into ``etf_brief.http_utils``.
__all__ = ["USER_AGENTS"]


def _get_headers() -> dict[str, str]:
    """Build request headers with a randomly rotated User-Agent.

    Thin alias around :func:`etf_brief.http_utils.get_rotating_headers`
    kept so tests and call sites continue to work unchanged.

    Returns:
        Dict of HTTP headers suitable for requests to rate-limiting
        data sources (Yahoo, JustETF).
    """
    return get_rotating_headers()


class _RateLimiter:
    """Minimum-interval rate limiter for a single upstream source.

    Encapsulates the previous module-level ``_yahoo_last_call`` global.
    Tests reset state via :meth:`reset` instead of poking the module.
    """

    def __init__(self, min_interval_seconds: float) -> None:
        """Initialise with a minimum seconds-between-calls interval.

        Args:
            min_interval_seconds: Hard floor on inter-call delay.
        """
        self.min_interval = min_interval_seconds
        self.last_call = 0.0

    def wait(self) -> None:
        """Sleep just long enough to satisfy the interval since last call."""
        elapsed = time.monotonic() - self.last_call
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)

    def mark(self) -> None:
        """Record that a call just happened (call after ``requests.get``)."""
        self.last_call = time.monotonic()

    def reset(self) -> None:
        """Reset internal state. Intended for tests only."""
        self.last_call = 0.0


_yahoo_limiter = _RateLimiter(RATE_LIMIT_SECONDS)


def fetch_page(url: str) -> BeautifulSoup | None:
    """Fetch a page and return a parsed soup, or ``None`` on HTTP error.

    Args:
        url: Fully qualified URL.

    Returns:
        A :class:`BeautifulSoup` instance, or ``None`` if the request
        failed. Callers should treat ``None`` as "skip this source".
    """
    try:
        resp = requests.get(url, headers=_get_headers(), timeout=TIMEOUT)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except requests.RequestException as exc:
        logger.warning(f"Failed to fetch {url}: {exc}")
        return None


# --- Fund price scrapers ---


def scrape_justetf(isin: str) -> dict[str, Any] | None:
    """Fetch current price + day-delta from the JustETF quote API.

    JustETF renders fund prices client-side via a ``<realtime-quotes>``
    Web Component; the server-side HTML is skeleton placeholders. The
    component loads data from ``/api/etfs/{isin}/quote?...`` — we call
    that endpoint directly instead of scraping HTML (which used to
    return zero or the ISIN digits misread as a price).

    Args:
        isin: Fund ISIN (e.g. ``"IE00B4ND3602"``).

    Returns:
        ``{"source": "justetf", "isin": ..., "url": ..., "price": ...,
        "currency": ..., "performance": {"1d": ...}}``, or the same dict
        with ``price`` omitted when the API response is malformed or
        non-positive. Returns ``None`` if the HTTP request itself fails.
    """
    api_url = (
        f"https://www.justetf.com/api/etfs/{isin}/quote"
        f"?locale=en&currency=EUR&isin={isin}"
    )
    profile_url = f"https://www.justetf.com/en/etf-profile.html?isin={isin}"

    try:
        resp = requests.get(api_url, headers=_get_headers(), timeout=TIMEOUT)
        resp.raise_for_status()
        payload = resp.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning(f"JustETF API failed for {isin}: {exc}")
        return None

    data: dict[str, Any] = {
        "source": "justetf",
        "isin": isin,
        "url": profile_url,
        "currency": "EUR",
    }

    latest = payload.get("latestQuote") or {}
    raw_price = latest.get("raw")
    if isinstance(raw_price, (int, float)) and raw_price > 0:
        data["price"] = float(raw_price)
    else:
        logger.warning(
            f"JustETF price extraction failed for {isin} "
            f"(got {raw_price!r}) — dropping price field"
        )

    perf: dict[str, float] = {}
    dtd = payload.get("dtdPrc") or {}
    dtd_raw = dtd.get("raw")
    if isinstance(dtd_raw, (int, float)):
        perf["1d"] = float(dtd_raw)
    if perf:
        data["performance"] = perf

    return data


def yahoo_chart_api(ticker: str) -> dict[str, Any] | None:
    """Fetch a quote via Yahoo Finance's chart API.

    Includes a shared RATE_LIMIT_SECONDS delay between calls and
    retries with exponential (or Retry-After-honouring) backoff on HTTP
    429.

    Args:
        ticker: Yahoo-style ticker (e.g. ``"VWCE.DE"``, ``"^VIX"``).

    Returns:
        ``{"source": "yahoo_api", "ticker": ..., "price": ...,
        "currency": ..., ...}`` on success, or ``None`` if all retries
        were exhausted or the response was empty/malformed.
    """
    _yahoo_limiter.wait()

    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {"interval": "1d", "range": "1mo"}
    resp: requests.Response | None = None
    try:
        for attempt in range(MAX_RETRIES):
            resp = requests.get(
                url, headers=_get_headers(), params=params, timeout=TIMEOUT
            )
            _yahoo_limiter.mark()
            if resp.status_code == 429:
                wait = _compute_backoff(resp, attempt)
                logger.info(
                    f"Yahoo 429 for {ticker}, retrying in {wait:.1f}s "
                    f"(attempt {attempt + 1}/{MAX_RETRIES})"
                )
                time.sleep(wait)
                continue
            resp.raise_for_status()
            break
        else:
            logger.warning(
                f"Yahoo API exhausted retries for {ticker} after "
                f"{MAX_RETRIES} 429s"
            )
            return None
    except requests.RequestException as exc:
        logger.warning(f"Yahoo API request failed for {ticker}: {exc}")
        return None

    try:
        return _parse_yahoo_response(ticker, resp.json())
    except (ValueError, KeyError) as exc:
        logger.warning(f"Yahoo API parse failed for {ticker}: {exc}")
        return None


def _compute_backoff(resp: requests.Response, attempt: int) -> float:
    """Return the number of seconds to sleep before retrying a 429.

    Args:
        resp: The 429 response (inspected for a ``Retry-After`` header).
        attempt: Zero-based retry attempt number.

    Returns:
        Seconds to sleep, capped at :data:`BACKOFF_CAP_SECONDS`.
    """
    retry_after = resp.headers.get("Retry-After")
    if retry_after:
        try:
            return min(
                float(retry_after) + random.uniform(0, 1),
                BACKOFF_CAP_SECONDS,
            )
        except (ValueError, TypeError):
            pass
    return min(2 ** (attempt + 1) + random.uniform(0, 1), BACKOFF_CAP_SECONDS)


def scrape_tradingview(ticker: str) -> dict[str, Any] | None:
    """Fetch a quote from TradingView's scanner endpoint.

    Tertiary source — used only when JustETF + Yahoo have both failed.
    Maps Yahoo-suffix tickers to TradingView exchange-prefix form.

    Args:
        ticker: Yahoo-style ticker (e.g. ``"VWCE.DE"``, ``"SGLN.L"``).

    Returns:
        Quote dict with ``price``, ``change_pct``, ``performance``,
        ``sma200`` and ``currency`` keys on success; ``None`` on any
        error or empty response.
    """
    tv_map = {".DE": "XETR:", ".L": "LSE:"}
    tv_symbol = ticker
    for suffix, exchange in tv_map.items():
        if ticker.endswith(suffix):
            tv_symbol = exchange + ticker.replace(suffix, "")
            break

    url = "https://scanner.tradingview.com/europe/scan"
    payload = {
        "symbols": {"tickers": [tv_symbol]},
        "columns": [
            "close", "change", "change_abs",
            "Perf.W", "Perf.1M", "Perf.3M", "Perf.6M",
            "Perf.YTD", "Perf.Y", "SMA200", "currency",
        ],
    }
    try:
        resp = requests.post(
            url, json=payload, headers=_get_headers(), timeout=TIMEOUT
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning(f"TradingView failed for {ticker} ({tv_symbol}): {exc}")
        return None

    if not data.get("data"):
        return None
    vals = data["data"][0].get("d", [])
    if not vals or len(vals) < 11:
        return None

    out: dict[str, Any] = {
        "source": "tradingview",
        "ticker": ticker,
        "tv_symbol": tv_symbol,
    }
    if vals[0] is not None:
        out["price"] = round(vals[0], 2)
    if vals[1] is not None:
        out["change_pct"] = round(vals[1], 2)

    perf: dict[str, float] = {}
    for idx, key in [
        (3, "1w"), (4, "1m"), (5, "3m"),
        (6, "6m"), (7, "ytd"), (8, "1y"),
    ]:
        if idx < len(vals) and vals[idx] is not None:
            perf[key] = round(vals[idx], 2)
    if perf:
        out["performance"] = perf
    if vals[9] is not None:
        out["sma200"] = round(vals[9], 2)
    if vals[10] is not None:
        out["currency"] = vals[10]
    return out


def _parse_yahoo_response(ticker: str, data: dict[str, Any]) -> dict[str, Any] | None:
    """Extract price, currency, and 1-month performance from a Yahoo payload.

    Args:
        ticker: Original ticker, used only for logging / output metadata.
        data: Parsed JSON body returned by the Yahoo chart API.

    Returns:
        A result dict, or ``None`` if the payload has no usable
        ``chart.result[0]`` entry.
    """
    result_data = data.get("chart", {}).get("result", [])
    if not result_data:
        return None

    meta = result_data[0].get("meta", {})
    price = meta.get("regularMarketPrice")
    prev_close = meta.get("chartPreviousClose") or meta.get("previousClose")
    currency = meta.get("currency", "")

    out: dict[str, Any] = {
        "source": "yahoo_api",
        "ticker": ticker,
        "currency": currency,
    }

    if price:
        out["price"] = round(price, 2)
    if price and prev_close and prev_close > 0:
        out["change_pct"] = round((price - prev_close) / prev_close * 100, 2)

    closes = (
        result_data[0]
        .get("indicators", {})
        .get("quote", [{}])[0]
        .get("close", [])
    )
    if closes and price:
        valid_closes = [c for c in closes if c is not None]
        if valid_closes:
            first_close = valid_closes[0]
            if first_close > 0:
                out.setdefault("performance", {})["1m"] = round(
                    (price - first_close) / first_close * 100, 2
                )
    return out


# --- Macro indicator scrapers ---


def _yahoo_with_stooq_fallback(
    yahoo_ticker: str, indicator_name: str
) -> tuple[float | None, str | None]:
    """Try Yahoo, then stooq, return (price, source_name).

    Args:
        yahoo_ticker: Yahoo-style ticker (e.g. ``"^VIX"``).
        indicator_name: Human name used in logs.

    Returns:
        ``(price, source)`` where ``source`` is ``"yahoo_api"`` or
        ``"stooq"`` on success, and ``(None, None)`` if both failed.
    """
    api_result = yahoo_chart_api(yahoo_ticker)
    if api_result and "price" in api_result:
        return api_result["price"], "yahoo_api"

    logger.info(
        f"{indicator_name}: Yahoo unavailable, trying stooq fallback"
    )
    stooq_price = stooq_quote(yahoo_ticker)
    if stooq_price is not None:
        logger.info(f"{indicator_name}: stooq fallback succeeded")
        return stooq_price, "stooq"

    return None, None


def scrape_vix() -> dict[str, Any]:
    """Fetch the CBOE VIX (volatility) index.

    Returns:
        ``{"name": "VIX", "value": float, "source": "yahoo_api"|"stooq"}``
        on success; ``{"name": "VIX", "value": None, "error": ...}`` on
        total failure.
    """
    value, source = _yahoo_with_stooq_fallback("^VIX", "VIX")
    if value is None:
        return {"name": "VIX", "value": None, "error": "fetch failed"}
    return {"name": "VIX", "value": value, "source": source}


def scrape_fear_greed() -> dict[str, Any]:
    """Fetch the CNN Business Fear & Greed Index.

    Returns:
        ``{"name": "Fear & Greed Index", "value": float|None,
        "rating": str|None, "source": "cnn"}`` on success;
        ``{"value": None, "error": ...}`` on failure.
    """
    url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
    try:
        resp = requests.get(url, headers=_get_headers(), timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        score = data.get("fear_and_greed", {}).get("score")
        rating = data.get("fear_and_greed", {}).get("rating")
        return {
            "name": "Fear & Greed Index",
            "value": score,
            "rating": rating,
            "source": "cnn",
        }
    except (requests.RequestException, ValueError, KeyError) as exc:
        logger.warning(f"Fear & Greed fetch failed: {exc}")

    return {"name": "Fear & Greed Index", "value": None, "error": "fetch failed"}


def scrape_treasury_yield() -> dict[str, Any]:
    """Fetch US 10-year and 2-year treasury yields (yield-curve proxy).

    Yahoo is tried first for both legs; stooq covers the gap when Yahoo
    429s.

    Returns:
        ``{"name": "US Yield Curve", "ten_year": float|None,
        "two_year": float|None, "spread": float|None,
        "inverted": bool, "source": "mixed"}``.
    """
    ten, ten_src = _yahoo_with_stooq_fallback("^TNX", "US 10Y Yield")
    two, two_src = _yahoo_with_stooq_fallback("^IRX", "US 2Y Yield")

    spread = round(ten - two, 3) if ten is not None and two is not None else None
    return {
        "name": "US Yield Curve",
        "ten_year": ten,
        "two_year": two,
        "spread": spread,
        "inverted": spread is not None and spread < 0,
        "ten_year_source": ten_src,
        "two_year_source": two_src,
    }


def scrape_sp500() -> dict[str, Any]:
    """Fetch the S&P 500 index level.

    Returns:
        ``{"name": "S&P 500", "price": float, "source": ...}`` on
        success; a dict without ``price`` on failure.
    """
    value, source = _yahoo_with_stooq_fallback("^GSPC", "S&P 500")
    out: dict[str, Any] = {"name": "S&P 500"}
    if value is not None:
        out["price"] = value
        out["source"] = source
    return out


def scrape_gold_price() -> dict[str, Any]:
    """Fetch COMEX gold futures (USD).

    Returns:
        ``{"name": "Gold Futures", "price_usd": float, "source": ...}``
        on success; a dict without ``price_usd`` on failure.
    """
    value, source = _yahoo_with_stooq_fallback("GC=F", "Gold Futures")
    out: dict[str, Any] = {"name": "Gold Futures"}
    if value is not None:
        out["price_usd"] = value
        out["source"] = source
    return out


# --- Main orchestration ---


def _build_fund_data(fund: Any) -> dict[str, Any]:
    """Fetch price + perf for a single fund and return the JSON dict.

    Args:
        fund: A :class:`etf_brief.models.FundConfig` instance (or any
            object with the same attribute surface).

    Returns:
        Fund data dict with ``sources``, consolidated ``price`` /
        ``price_source`` / ``performance`` keys when available.
    """
    logger.info(f"Fetching data for {fund.name} ({fund.ticker})")
    fund_data: dict[str, Any] = {
        "name": fund.name,
        "ticker": fund.ticker,
        "isin": fund.isin,
        "category": fund.category,
        "sources": [],
    }
    if fund.allocation_pct is not None:
        fund_data["allocation_pct"] = fund.allocation_pct

    justetf = scrape_justetf(fund.isin)
    if justetf:
        fund_data["sources"].append(justetf)
        logger.info(
            f"  JustETF: price={justetf.get('price', 'N/A')} "
            f"perf={bool(justetf.get('performance'))}"
        )

    yahoo = yahoo_chart_api(fund.ticker)
    if yahoo:
        fund_data["sources"].append(yahoo)
        logger.info(f"  Yahoo API: {yahoo.get('price', 'N/A')}")

    for src in fund_data["sources"]:
        if "price" in src:
            fund_data["price"] = src["price"]
            fund_data["price_source"] = src["source"]
            break
    for src in fund_data["sources"]:
        if "performance" in src:
            fund_data["performance"] = src["performance"]
            break
        if "change_pct" in src:
            fund_data.setdefault("performance", {})["1d"] = src["change_pct"]

    return fund_data


def _fetch_fund_prices(config: AppConfig) -> list[dict[str, Any]]:
    """Fetch price + performance for every fund in the portfolio.

    Args:
        config: Validated :class:`AppConfig`.

    Returns:
        List of fund-data dicts, one per configured fund.
    """
    return [_build_fund_data(fund) for fund in config.portfolio.funds]


def _fetch_macro_indicators() -> list[dict[str, Any]]:
    """Fetch all macro indicators (VIX, F&G, yield curve, S&P, gold).

    Returns:
        List of macro-indicator dicts in a stable order.
    """
    logger.info("Fetching macro indicators...")

    vix = scrape_vix()
    logger.info(f"  VIX: {vix.get('value', 'N/A')}")

    fg = scrape_fear_greed()
    logger.info(
        f"  Fear & Greed: {fg.get('value', 'N/A')} "
        f"({fg.get('rating', 'N/A')})"
    )

    yields = scrape_treasury_yield()
    logger.info(
        f"  Yield spread: {yields.get('spread', 'N/A')} "
        f"(inverted: {yields.get('inverted', 'N/A')})"
    )

    sp500 = scrape_sp500()
    logger.info(f"  S&P 500: {sp500.get('price', 'N/A')}")

    gold = scrape_gold_price()
    logger.info(f"  Gold: ${gold.get('price_usd', 'N/A')}")

    return [vix, fg, yields, sp500, gold]


def fetch_all() -> dict[str, Any]:
    """Run every scraper and return the consolidated JSON document.

    Returns:
        ``{"timestamp": "...", "funds": [...], "macro": [...]}``. The
        document is safe to pass to :func:`json.dumps` directly.
    """
    config = load_config()
    return {
        "timestamp": now_berlin().isoformat(),
        "funds": _fetch_fund_prices(config),
        "macro": _fetch_macro_indicators(),
    }


def load_config() -> AppConfig:
    """Load and validate the user config (``<repo>/config.yaml``).

    Returns:
        A validated :class:`AppConfig`.

    Raises:
        FileNotFoundError: If ``config.yaml`` is missing.
        pydantic.ValidationError: If the file is structurally wrong.
    """
    config_path = _SCRIPTS_DIR.parent / "config.yaml"
    return AppConfig.load_from_yaml(config_path)


def load_raw_config() -> dict[str, Any]:
    """Load the raw YAML dict (skipping pydantic) — test helper only.

    Returns:
        Raw dict from ``yaml.safe_load``.
    """
    config_path = _SCRIPTS_DIR.parent / "config.yaml"
    with config_path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def main() -> None:
    """Run the full fetch pipeline and emit JSON to stdout.

    Log line at completion splits any-price / JustETF / Yahoo success
    counts so runs where Yahoo was silently rate-limited are visible
    (see backlog etf-brief-001).
    """
    logger.info("ETF fetcher run started")
    start = time.monotonic()

    result = fetch_all()

    total_funds = len(result["funds"])
    yahoo_success = sum(
        1
        for f in result["funds"]
        if any(
            s.get("source") == "yahoo_api" and "price" in s
            for s in f.get("sources", [])
        )
    )
    justetf_success = sum(
        1
        for f in result["funds"]
        if any(
            s.get("source") == "justetf" and "price" in s
            for s in f.get("sources", [])
        )
    )
    any_price = sum(1 for f in result["funds"] if "price" in f)

    macro_with_value = sum(
        1
        for m in result["macro"]
        if m.get("value") is not None
        or m.get("price") is not None
        or m.get("price_usd") is not None
        or m.get("spread") is not None
    )

    elapsed = time.monotonic() - start
    logger.info(
        f"ETF fetcher run complete: funds {any_price}/{total_funds} with "
        f"any price (JustETF {justetf_success}/{total_funds}, Yahoo "
        f"{yahoo_success}/{total_funds}), "
        f"{macro_with_value}/{len(result['macro'])} macro indicators, "
        f"duration={elapsed:.1f}s"
    )

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
