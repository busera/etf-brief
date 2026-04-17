"""Shared pytest fixtures + fixtures for the etf-brief test suite.

TS-14: error-path tests must isolate loguru to a tmp sink so simulated
errors (mocked 429s, network exceptions) never write WARNING/ERROR lines
to a production log. Without this, log scanners downstream would see
phantom alerts on every test run.

The ``isolate_loguru`` fixture is ``autouse=True`` so every test in the
suite automatically redirects loguru output to ``tmp_path``. Any calls
to :func:`etf_brief.logging_config.setup_logger` during test execution
return the redirected singleton.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests
from loguru import logger

# Make the scripts/ directory importable so tests can `import fetcher`
# and `from etf_brief.* import ...` without installing the package.
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


@pytest.fixture(autouse=True)
def isolate_loguru(tmp_path, monkeypatch):
    """Redirect all loguru output to a tmp file for each test.

    Yields control to the test; on teardown, removes the temp handler
    and restores a stderr handler so later tests (in unrelated sessions)
    aren't surprised.
    """
    logger.remove()
    log_file = tmp_path / "test.log"
    handler_id = logger.add(str(log_file), level="DEBUG")

    from etf_brief import logging_config as lc

    monkeypatch.setattr(lc, "setup_logger", lambda name, **kw: logger)
    yield
    try:
        logger.remove(handler_id)
    except ValueError:
        pass
    logger.add(sys.stderr, level="WARNING")


# --- Canned HTML / JSON fixtures ---

# JustETF legacy HTML (kept for a handful of historical edge-case tests
# that exercise the old HTML-scraping code path). Current production
# calls the JSON API; see JUSTETF_API_JSON below.
JUSTETF_HTML = """
<html><body>
<div class="infobox"><span class="val">52.34</span><span class="cur">EUR</span></div>
<table>
<tr><td>1 month</td><td>-2.84%</td></tr>
<tr><td>3 months</td><td>1.15%</td></tr>
<tr><td>6 months</td><td>4.16%</td></tr>
<tr><td>1 year</td><td>8.21%</td></tr>
<tr><td>YTD</td><td>3.45%</td></tr>
</table>
</body></html>
"""

# JustETF quote API response shape (observed live on 2026-04-17 against
# https://www.justetf.com/api/etfs/{isin}/quote).
JUSTETF_API_JSON = {
    "latestQuote": {"raw": 52.34, "localized": "52.34"},
    "latestQuoteDate": "2026-04-16",
    "previousQuote": {"raw": 52.10, "localized": "52.10"},
    "previousQuoteDate": "2026-04-15",
    "dtdPrc": {"raw": 0.46, "localized": "0.46"},
    "dtdAmt": {"raw": 0.24, "localized": "0.24"},
    "quoteTradingVenue": "XETRA",
}

JUSTETF_API_JSON_ZERO_PRICE = {
    "latestQuote": {"raw": 0.0, "localized": "0.00"},
    "latestQuoteDate": "2026-04-16",
    "previousQuote": {"raw": 0.0, "localized": "0.00"},
    "previousQuoteDate": "2026-04-15",
    "dtdPrc": {"raw": 0.0, "localized": "0.00"},
}

YAHOO_API_RESPONSE = {
    "chart": {
        "result": [
            {
                "meta": {
                    "regularMarketPrice": 105.23,
                    "chartPreviousClose": 105.70,
                    "currency": "EUR",
                },
                "indicators": {
                    "quote": [{"close": [103.0, 104.0, 105.23]}]
                },
            }
        ]
    }
}

FEAR_GREED_JSON = {"fear_and_greed": {"score": 35.5, "rating": "fear"}}

# Example stooq CSV response — single data row with ^spx close.
STOOQ_CSV_SPX = (
    "Symbol,Date,Time,Open,High,Low,Close,Volume\r\n"
    "^spx,2026-04-17,22:00:05,5100.12,5120.45,5090.00,5115.33,2310000\r\n"
)
STOOQ_CSV_EMPTY = "Symbol,Date,Time,Open,High,Low,Close,Volume\r\n"
STOOQ_CSV_ND = (
    "Symbol,Date,Time,Open,High,Low,Close,Volume\r\n"
    "^vix,N/D,N/D,N/D,N/D,N/D,N/D,N/D\r\n"
)


# --- Helper mock factories ---


def mock_response(html: str, status_code: int = 200) -> MagicMock:
    """Build a MagicMock mimicking a requests Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = html
    resp.headers = {}
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(
            f"HTTP {status_code}"
        )
    return resp


def mock_json_response(data, status_code: int = 200) -> MagicMock:
    """Build a MagicMock mimicking a requests Response with JSON body."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    resp.headers = {}
    resp.raise_for_status = MagicMock()
    return resp
