"""Stooq CSV fallback for macro indicators.

When Yahoo Finance exhausts retries (typically due to 429 rate limiting),
stooq.com provides a free, keyless CSV quote endpoint that covers the
same instruments. This module wraps it with a small symbol map and a
strict CSV parser.

The endpoint is::

    https://stooq.com/q/l/?s=<symbol>&f=sd2t2ohlcv&h&e=csv

and returns one header line plus one data row::

    Symbol,Date,Time,Open,High,Low,Close,Volume
    ^spx,2026-04-17,22:00:05,5100.12,5120.45,5090.00,5115.33,2310000

Entry points:
    :func:`stooq_quote` — lookup by original ticker (does symbol mapping)
    :func:`stooq_quote_raw` — lookup by stooq-native symbol (for tests)

Return value is ``float | None``:

* float: successful quote (> 0)
* None: HTTP error, empty / malformed CSV, non-positive price, or the
    instrument is not in stooq's universe

Timeout is hard-coded to 15 seconds (macro indicators are hit once per
run). No retries — this is a fallback, not a primary source.
"""

from __future__ import annotations

import csv
import io

import requests
from loguru import logger

from etf_brief.http_utils import get_rotating_headers

STOOQ_BASE_URL = "https://stooq.com/q/l/"
STOOQ_TIMEOUT_SECONDS = 15

# Yahoo → stooq symbol mapping. stooq uses lower-case symbols with
# market suffixes (``.us`` for US equities, no suffix for indices).
# Values are verified to return CSV rows as of 2026-04-17.
YAHOO_TO_STOOQ: dict[str, str] = {
    "^VIX": "^vix",
    "^GSPC": "^spx",
    "^TNX": "^tnx.us",
    "^IRX": "^irx.us",
    "GC=F": "gc.f",
}


def _headers() -> dict[str, str]:
    """Return HTTP headers with a rotated User-Agent.

    Uses :func:`etf_brief.http_utils.get_rotating_headers` and swaps the
    ``Accept`` header for ``text/csv`` since stooq returns CSV rather
    than HTML.
    """
    headers = get_rotating_headers()
    headers["Accept"] = "text/csv, */*;q=0.1"
    return headers


def stooq_quote(symbol: str) -> float | None:
    """Fetch the latest close price from stooq for a Yahoo-style ticker.

    Args:
        symbol: Yahoo-style ticker (e.g. ``"^VIX"``, ``"^GSPC"``,
            ``"GC=F"``). Unknown symbols return ``None``.

    Returns:
        The latest close price as a ``float``, or ``None`` if the symbol
        is unmapped, stooq returned no data, or the response could not
        be parsed.
    """
    mapped = YAHOO_TO_STOOQ.get(symbol)
    if mapped is None:
        logger.warning(f"stooq: no symbol mapping for {symbol!r}")
        return None
    return stooq_quote_raw(mapped)


def stooq_quote_raw(stooq_symbol: str) -> float | None:
    """Fetch the latest close price from stooq by native symbol.

    Args:
        stooq_symbol: stooq-native symbol (e.g. ``"^vix"``, ``"gc.f"``).

    Returns:
        The latest close price as a ``float``, or ``None`` on any error
        (network failure, empty CSV, malformed row, zero/negative price).
    """
    params = {"s": stooq_symbol, "f": "sd2t2ohlcv", "h": "", "e": "csv"}
    try:
        resp = requests.get(
            STOOQ_BASE_URL,
            params=params,
            headers=_headers(),
            timeout=STOOQ_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning(f"stooq HTTP error for {stooq_symbol}: {exc}")
        return None

    price = _parse_close_from_csv(resp.text)
    if price is None:
        logger.warning(
            f"stooq: could not parse close for {stooq_symbol!r} "
            f"(body={resp.text[:80]!r})"
        )
        return None
    if price <= 0:
        logger.warning(
            f"stooq: non-positive close {price} for {stooq_symbol!r}, dropping"
        )
        return None
    return price


def _parse_close_from_csv(body: str) -> float | None:
    """Extract the ``Close`` field from a stooq CSV response.

    Args:
        body: Full response body (header line + data line).

    Returns:
        The close price as ``float``, or ``None`` if the CSV is empty,
        missing a Close column, or contains ``"N/D"``.
    """
    try:
        reader = csv.DictReader(io.StringIO(body))
        for row in reader:
            close = row.get("Close") or row.get("close")
            if close is None or close.strip() in {"", "N/D"}:
                return None
            return float(close)
    except (csv.Error, ValueError):
        return None
    return None
