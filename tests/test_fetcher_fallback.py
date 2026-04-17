"""Tests for the stooq fallback + JustETF zero-price rejection.

Covers the two backlog fixes folded into the public release:

* etf-brief-002 — JustETF API returning zero → drop the price, log a
    warning, do not persist a zero.
* etf-brief-003 — Yahoo 429s-exhausted → try stooq CSV endpoint, use
    its close price when available.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import requests

import fetcher
from etf_brief import fallback
from conftest import (
    JUSTETF_API_JSON_ZERO_PRICE,
    STOOQ_CSV_EMPTY,
    STOOQ_CSV_ND,
    STOOQ_CSV_SPX,
    mock_json_response,
    mock_response,
)


# --- etf-brief-002: JustETF zero-price rejection ---


class TestJustETFZeroPriceRejection:
    @patch("fetcher.requests.get")
    def test_zero_price_dropped_and_logged(self, mock_get):
        """Zero raw price → no price field, warning logged once."""
        mock_get.return_value = mock_json_response(JUSTETF_API_JSON_ZERO_PRICE)

        captured: list[str] = []
        sink_id = fetcher.logger.add(
            lambda msg: captured.append(str(msg)), level="WARNING"
        )
        try:
            result = fetcher.scrape_justetf("IE00BK5BQT80")
        finally:
            fetcher.logger.remove(sink_id)

        assert result is not None
        assert "price" not in result
        assert any("JustETF price extraction failed" in m for m in captured)


# --- etf-brief-003: stooq fallback for macro indicators ---


class TestStooqFallbackDirect:
    """Unit tests for the stooq client module itself."""

    @patch("etf_brief.fallback.requests.get")
    def test_parses_close_from_csv(self, mock_get):
        mock_get.return_value = mock_response(STOOQ_CSV_SPX)
        price = fallback.stooq_quote("^GSPC")
        assert price == 5115.33

    @patch("etf_brief.fallback.requests.get")
    def test_returns_none_for_empty_csv(self, mock_get):
        mock_get.return_value = mock_response(STOOQ_CSV_EMPTY)
        assert fallback.stooq_quote("^GSPC") is None

    @patch("etf_brief.fallback.requests.get")
    def test_returns_none_for_nd_row(self, mock_get):
        mock_get.return_value = mock_response(STOOQ_CSV_ND)
        assert fallback.stooq_quote("^VIX") is None

    @patch("etf_brief.fallback.requests.get")
    def test_http_error_returns_none(self, mock_get):
        mock_get.side_effect = requests.ConnectionError("boom")
        assert fallback.stooq_quote("^VIX") is None

    def test_unmapped_symbol_returns_none(self):
        assert fallback.stooq_quote("SOMETHING.UNKNOWN") is None

    @patch("etf_brief.fallback.requests.get")
    def test_non_positive_price_rejected(self, mock_get):
        negative_csv = (
            "Symbol,Date,Time,Open,High,Low,Close,Volume\r\n"
            "^vix,2026-04-17,22:00:05,-1,-1,-1,-1,0\r\n"
        )
        mock_get.return_value = mock_response(negative_csv)
        assert fallback.stooq_quote("^VIX") is None


class TestStooqFallbackIntegration:
    """Fetcher macro scrapers must try stooq when Yahoo is unavailable."""

    @patch("fetcher.stooq_quote")
    @patch("fetcher.yahoo_chart_api")
    def test_vix_uses_stooq_when_yahoo_exhausted(self, mock_yahoo, mock_stooq):
        mock_yahoo.return_value = None
        mock_stooq.return_value = 19.55
        result = fetcher.scrape_vix()
        assert result["value"] == 19.55
        assert result["source"] == "stooq"
        mock_stooq.assert_called_once_with("^VIX")

    @patch("fetcher.stooq_quote")
    @patch("fetcher.yahoo_chart_api")
    def test_sp500_uses_stooq_when_yahoo_exhausted(
        self, mock_yahoo, mock_stooq
    ):
        mock_yahoo.return_value = None
        mock_stooq.return_value = 5115.33
        result = fetcher.scrape_sp500()
        assert result["price"] == 5115.33
        assert result["source"] == "stooq"

    @patch("fetcher.stooq_quote")
    @patch("fetcher.yahoo_chart_api")
    def test_gold_uses_stooq_when_yahoo_exhausted(self, mock_yahoo, mock_stooq):
        mock_yahoo.return_value = None
        mock_stooq.return_value = 2345.60
        result = fetcher.scrape_gold_price()
        assert result["price_usd"] == 2345.60
        assert result["source"] == "stooq"

    @patch("fetcher.stooq_quote")
    @patch("fetcher.yahoo_chart_api")
    def test_yahoo_success_bypasses_stooq(self, mock_yahoo, mock_stooq):
        """When Yahoo works, stooq must not be called."""
        mock_yahoo.return_value = {"price": 18.0}
        mock_stooq.return_value = 999.99  # would be wrong; must not be used
        result = fetcher.scrape_vix()
        assert result["value"] == 18.0
        assert result["source"] == "yahoo_api"
        mock_stooq.assert_not_called()
