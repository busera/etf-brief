"""Tests for the ETF price sources in the etf-brief fetcher.

Covers:
- JustETF JSON API scraping (primary price source — the server-side
    HTML is skeleton-placeholder-only since the 2026 UI refactor).
- Yahoo Chart API (secondary, rate-limit hardened).
- TradingView scraping (tertiary fallback).
- Rate-limit hardening for Yahoo (retries, jitter, Retry-After).
- Edge cases specific to ETF price extraction.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

import fetcher
from conftest import (
    JUSTETF_API_JSON,
    JUSTETF_API_JSON_ZERO_PRICE,
    YAHOO_API_RESPONSE,
    mock_json_response,
    mock_response,
)


# --- JustETF tests ---


class TestJustETF:
    @patch("fetcher.requests.get")
    def test_extracts_price(self, mock_get):
        mock_get.return_value = mock_json_response(JUSTETF_API_JSON)
        result = fetcher.scrape_justetf("IE00BK5BQT80")
        assert result is not None
        assert result["price"] == 52.34

    @patch("fetcher.requests.get")
    def test_extracts_performance(self, mock_get):
        mock_get.return_value = mock_json_response(JUSTETF_API_JSON)
        result = fetcher.scrape_justetf("IE00BK5BQT80")
        # 1-day change pulled from dtdPrc.raw
        assert result["performance"]["1d"] == 0.46

    @patch("fetcher.requests.get")
    def test_handles_http_failure(self, mock_get):
        mock_get.side_effect = requests.ConnectionError("network down")
        assert fetcher.scrape_justetf("INVALID") is None

    @patch("fetcher.requests.get")
    def test_handles_404(self, mock_get):
        mock_get.return_value = mock_json_response({}, status_code=404)
        mock_get.return_value.raise_for_status.side_effect = (
            requests.HTTPError("404 Not Found")
        )
        assert fetcher.scrape_justetf("INVALID") is None

    @patch("fetcher.requests.get")
    def test_rejects_zero_price(self, mock_get):
        """etf-brief-002: JustETF returns zero → drop the price key."""
        mock_get.return_value = mock_json_response(JUSTETF_API_JSON_ZERO_PRICE)
        result = fetcher.scrape_justetf("IE00BK5BQT80")
        assert result is not None
        assert "price" not in result

    @patch("fetcher.requests.get")
    def test_rejects_malformed_payload(self, mock_get):
        """Missing latestQuote → drop price, still return dict."""
        mock_get.return_value = mock_json_response({"foo": "bar"})
        result = fetcher.scrape_justetf("IE00BK5BQT80")
        assert result is not None
        assert "price" not in result


# --- Yahoo Chart API tests ---


class TestYahooAPI:
    @patch("fetcher.requests.get")
    def test_extracts_price(self, mock_get):
        mock_get.return_value = mock_json_response(YAHOO_API_RESPONSE)
        result = fetcher.yahoo_chart_api("VWCE.DE")
        assert result["price"] == 105.23
        assert result["source"] == "yahoo_api"

    @patch("fetcher.requests.get")
    def test_calculates_change(self, mock_get):
        data = {
            "chart": {
                "result": [
                    {
                        "meta": {
                            "regularMarketPrice": 100.0,
                            "chartPreviousClose": 95.0,
                            "currency": "EUR",
                        },
                        "indicators": {
                            "quote": [{"close": [95.0, 100.0]}]
                        },
                    }
                ]
            }
        }
        mock_get.return_value = mock_json_response(data)
        result = fetcher.yahoo_chart_api("VWCE.DE")
        assert result["change_pct"] == 5.26

    @patch("fetcher.requests.get")
    def test_handles_failure(self, mock_get):
        mock_get.side_effect = requests.ConnectionError("429 Too Many Requests")
        assert fetcher.yahoo_chart_api("INVALID") is None

    @patch("fetcher.requests.get")
    def test_handles_empty_result(self, mock_get):
        mock_get.return_value = mock_json_response({"chart": {"result": []}})
        assert fetcher.yahoo_chart_api("VWCE.DE") is None


# --- Rate-limit hardening tests (etf-brief-001) ---


class TestRateLimitHardening:
    def test_user_agent_rotation_uses_pool(self):
        """_get_headers picks from USER_AGENTS pool."""
        assert len(fetcher.USER_AGENTS) >= 3
        for _ in range(10):
            headers = fetcher._get_headers()
            assert headers["User-Agent"] in fetcher.USER_AGENTS
            assert headers["Accept-Language"] == "en-US,en;q=0.9"

    def test_max_retries_bumped_to_five(self):
        assert fetcher.MAX_RETRIES == 5

    def test_backoff_cap_defined(self):
        assert fetcher.BACKOFF_CAP_SECONDS == 30.0

    @patch("fetcher.time.sleep")
    @patch("fetcher.requests.get")
    def test_yahoo_429_retries_with_jitter(self, mock_get, mock_sleep):
        """Two 429s followed by success — retries happen and backoff fires."""
        fetcher._yahoo_limiter.reset()

        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.headers = {}
        resp_429.raise_for_status = MagicMock()

        resp_ok = MagicMock()
        resp_ok.status_code = 200
        resp_ok.json.return_value = YAHOO_API_RESPONSE
        resp_ok.raise_for_status = MagicMock()

        mock_get.side_effect = [resp_429, resp_429, resp_ok]
        result = fetcher.yahoo_chart_api("VWCE.DE")
        assert result is not None
        assert result["price"] == 105.23

        backoff_waits = [
            c[0][0] for c in mock_sleep.call_args_list if c[0][0] >= 2.0
        ]
        assert len(backoff_waits) >= 2
        assert 2.0 <= backoff_waits[0] <= 3.0
        assert 4.0 <= backoff_waits[1] <= 5.0

    @patch("fetcher.time.sleep")
    @patch("fetcher.requests.get")
    def test_yahoo_exhausts_all_five_retries(self, mock_get, mock_sleep):
        """All MAX_RETRIES attempts return 429 → returns None."""
        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.headers = {}
        resp_429.raise_for_status = MagicMock()
        mock_get.return_value = resp_429

        result = fetcher.yahoo_chart_api("VWCE.DE")
        assert result is None
        assert mock_get.call_count == fetcher.MAX_RETRIES

    @patch("fetcher.time.sleep")
    @patch("fetcher.requests.get")
    def test_yahoo_429_respects_retry_after_header(self, mock_get, mock_sleep):
        """Retry-After header → wait time uses header value + jitter."""
        fetcher._yahoo_limiter.reset()

        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.headers = {"Retry-After": "10"}
        resp_429.raise_for_status = MagicMock()

        resp_ok = MagicMock()
        resp_ok.status_code = 200
        resp_ok.json.return_value = YAHOO_API_RESPONSE
        resp_ok.raise_for_status = MagicMock()

        mock_get.side_effect = [resp_429, resp_ok]
        result = fetcher.yahoo_chart_api("VWCE.DE")
        assert result is not None

        backoff_waits = [
            c[0][0] for c in mock_sleep.call_args_list if c[0][0] >= 2.0
        ]
        assert len(backoff_waits) >= 1
        assert 10.0 <= backoff_waits[0] <= 11.0


# --- ETF-price edge cases ---


class TestEtfPriceEdgeCases:
    """Edge cases for the Yahoo and TradingView price extractors."""

    @patch("fetcher.requests.get")
    def test_yahoo_api_price_zero_prev_close_zero(self, mock_get):
        data = {
            "chart": {
                "result": [
                    {
                        "meta": {
                            "regularMarketPrice": 0.0,
                            "chartPreviousClose": 0.0,
                            "currency": "EUR",
                        },
                        "indicators": {"quote": [{"close": []}]},
                    }
                ]
            }
        }
        mock_get.return_value = mock_json_response(data)
        result = fetcher.yahoo_chart_api("TEST")
        assert result is not None
        assert "change_pct" not in result

    @patch("fetcher.requests.get")
    def test_yahoo_api_all_none_closes(self, mock_get):
        data = {
            "chart": {
                "result": [
                    {
                        "meta": {
                            "regularMarketPrice": 100.0,
                            "chartPreviousClose": 99.0,
                            "currency": "EUR",
                        },
                        "indicators": {
                            "quote": [{"close": [None, None, None]}]
                        },
                    }
                ]
            }
        }
        mock_get.return_value = mock_json_response(data)
        result = fetcher.yahoo_chart_api("TEST")
        assert result is not None
        assert result["price"] == 100.0
        assert "performance" not in result or "1m" not in result.get(
            "performance", {}
        )

    @patch("fetcher.requests.post")
    def test_tradingview_empty_data(self, mock_post):
        mock_post.return_value = mock_json_response({"data": []})
        assert fetcher.scrape_tradingview("VWCE.DE") is None

    @patch("fetcher.requests.post")
    def test_tradingview_short_values(self, mock_post):
        mock_post.return_value = mock_json_response(
            {"data": [{"d": [100.0, 1.5]}]}
        )
        assert fetcher.scrape_tradingview("VWCE.DE") is None

    @patch("fetcher.requests.post")
    def test_tradingview_network_failure(self, mock_post):
        mock_post.side_effect = requests.ConnectionError("timeout")
        assert fetcher.scrape_tradingview("VWCE.DE") is None

    @patch("fetcher.requests.post")
    def test_tradingview_extracts_data(self, mock_post):
        vals = [105.0, 1.5, 1.58, -0.3, 2.1, 5.4, 8.2, 3.5, 12.1, 102.0, "EUR"]
        mock_post.return_value = mock_json_response({"data": [{"d": vals}]})
        result = fetcher.scrape_tradingview("VWCE.DE")
        assert result is not None
        assert result["price"] == 105.0
        assert result["change_pct"] == 1.5
        assert result["performance"]["1m"] == 2.1
        assert result["performance"]["ytd"] == 3.5
        assert result["sma200"] == 102.0
        assert result["currency"] == "EUR"
