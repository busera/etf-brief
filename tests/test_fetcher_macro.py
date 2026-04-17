"""Tests for the macro indicator sources in the etf-brief fetcher.

Covers:
- VIX (volatility index) via Yahoo with stooq fallback
- CNN Fear & Greed index
- US Treasury yield curve (inversion signal)
- S&P 500
- Gold futures
"""

from __future__ import annotations

from unittest.mock import patch

import requests

import fetcher
from conftest import FEAR_GREED_JSON, mock_json_response


# --- Macro indicator tests ---


class TestMacro:
    @patch("fetcher.yahoo_chart_api")
    def test_vix(self, mock_api):
        mock_api.return_value = {"price": 18.45}
        result = fetcher.scrape_vix()
        assert result["name"] == "VIX"
        assert result["value"] == 18.45
        assert result["source"] == "yahoo_api"

    @patch("fetcher.stooq_quote")
    @patch("fetcher.yahoo_chart_api")
    def test_vix_total_failure(self, mock_api, mock_stooq):
        mock_api.return_value = None
        mock_stooq.return_value = None
        result = fetcher.scrape_vix()
        assert result["value"] is None
        assert "error" in result

    @patch("fetcher.requests.get")
    def test_fear_greed(self, mock_get):
        mock_get.return_value = mock_json_response(FEAR_GREED_JSON)
        result = fetcher.scrape_fear_greed()
        assert result["value"] == 35.5
        assert result["rating"] == "fear"

    @patch("fetcher.yahoo_chart_api")
    def test_treasury_yield_normal(self, mock_api):
        mock_api.side_effect = (
            lambda t: {"price": 4.25} if "TNX" in t else {"price": 3.85}
        )
        result = fetcher.scrape_treasury_yield()
        assert result["spread"] == 0.4
        assert result["inverted"] is False

    @patch("fetcher.yahoo_chart_api")
    def test_treasury_yield_inverted(self, mock_api):
        mock_api.side_effect = (
            lambda t: {"price": 3.50} if "TNX" in t else {"price": 4.25}
        )
        result = fetcher.scrape_treasury_yield()
        assert result["spread"] < 0
        assert result["inverted"] is True

    @patch("fetcher.yahoo_chart_api")
    def test_sp500(self, mock_api):
        mock_api.return_value = {"price": 5234.18, "change_pct": -0.5}
        result = fetcher.scrape_sp500()
        assert result["price"] == 5234.18

    @patch("fetcher.yahoo_chart_api")
    def test_gold(self, mock_api):
        mock_api.return_value = {"price": 2345.60, "change_pct": 1.23}
        result = fetcher.scrape_gold_price()
        assert result["price_usd"] == 2345.60


# --- Macro edge cases ---


class TestMacroEdgeCases:
    @patch("fetcher.requests.get")
    def test_fear_greed_network_failure(self, mock_get):
        mock_get.side_effect = requests.ConnectionError("network down")
        result = fetcher.scrape_fear_greed()
        assert result["value"] is None
        assert "error" in result

    @patch("fetcher.stooq_quote")
    @patch("fetcher.yahoo_chart_api")
    def test_treasury_yield_one_side_missing(self, mock_api, mock_stooq):
        """One yield fails at both Yahoo and stooq — spread is None."""
        mock_api.side_effect = (
            lambda t: {"price": 4.25} if "TNX" in t else None
        )
        mock_stooq.return_value = None
        result = fetcher.scrape_treasury_yield()
        assert result["spread"] is None
        assert result["inverted"] is False

    @patch("fetcher.stooq_quote")
    @patch("fetcher.yahoo_chart_api")
    def test_sp500_no_data(self, mock_api, mock_stooq):
        mock_api.return_value = None
        mock_stooq.return_value = None
        result = fetcher.scrape_sp500()
        assert result["name"] == "S&P 500"
        assert "price" not in result

    @patch("fetcher.stooq_quote")
    @patch("fetcher.yahoo_chart_api")
    def test_gold_no_data(self, mock_api, mock_stooq):
        mock_api.return_value = None
        mock_stooq.return_value = None
        result = fetcher.scrape_gold_price()
        assert result["name"] == "Gold Futures"
        assert "price_usd" not in result
