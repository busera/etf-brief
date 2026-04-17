"""Integration + config tests for the etf-brief fetcher.

Covers:
- YAML config loading via pydantic models (AppConfig.load_from_yaml)
- fetch_all() end-to-end with every source mocked
- main() JSON output
- Honest per-source success accounting (etf-brief-001)
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

import fetcher
from etf_brief.models import AppConfig


# --- Helpers ---


@pytest.fixture
def example_config_in_place(tmp_path, monkeypatch):
    """Copy config.example.yaml → config.yaml in a tmp repo root and
    repoint the fetcher module-level path constant at it."""
    repo_root = Path(__file__).resolve().parent.parent
    src = repo_root / "config.example.yaml"
    assert src.exists(), "config.example.yaml is required for tests"

    fake_scripts_dir = tmp_path / "scripts"
    fake_scripts_dir.mkdir()
    cfg = tmp_path / "config.yaml"
    shutil.copy(src, cfg)

    monkeypatch.setattr(fetcher, "_SCRIPTS_DIR", fake_scripts_dir)
    return cfg


# --- Config tests ---


class TestConfig:
    def test_load_config_returns_appconfig(self, example_config_in_place):
        config = fetcher.load_config()
        assert isinstance(config, AppConfig)

    def test_config_has_three_funds(self, example_config_in_place):
        config = fetcher.load_config()
        assert len(config.portfolio.funds) == 3

    def test_config_has_sentiment_sources(self, example_config_in_place):
        config = fetcher.load_config()
        reddit = [
            s for s in config.sources.sentiment_sources if s.type == "reddit"
        ]
        assert len(reddit) >= 2

    def test_config_recession_indicators(self, example_config_in_place):
        config = fetcher.load_config()
        assert len(config.recession_signals.indicators) >= 6

    def test_config_allocation_rules_sum_to_100(self, example_config_in_place):
        """Each allocation rule's splits must sum to 100 (pydantic validates)."""
        config = fetcher.load_config()
        for rule in config.recommendations.allocation_rules:
            total = sum(rule.splits.values())
            assert abs(total - 100.0) < 0.01, (
                f"{rule.level} splits sum to {total}, not 100"
            )


# --- Integration tests ---


class TestFetchAll:
    @patch("fetcher.scrape_gold_price")
    @patch("fetcher.scrape_sp500")
    @patch("fetcher.scrape_treasury_yield")
    @patch("fetcher.scrape_fear_greed")
    @patch("fetcher.scrape_vix")
    @patch("fetcher.scrape_justetf")
    @patch("fetcher.yahoo_chart_api")
    def test_structure(
        self,
        mock_yapi,
        mock_je,
        mock_vix,
        mock_fg,
        mock_ty,
        mock_sp,
        mock_gold,
        example_config_in_place,
    ):
        mock_yapi.return_value = {
            "source": "yahoo_api",
            "price": 52.0,
            "change_pct": -0.5,
        }
        mock_je.return_value = {"source": "justetf", "performance": {"1d": 0.3}}
        mock_vix.return_value = {"name": "VIX", "value": 18.0}
        mock_fg.return_value = {"name": "Fear & Greed Index", "value": 40.0}
        mock_ty.return_value = {"name": "US Yield Curve", "spread": 0.4}
        mock_sp.return_value = {"name": "S&P 500", "price": 5200.0}
        mock_gold.return_value = {"name": "Gold Futures", "price_usd": 2300.0}

        result = fetcher.fetch_all()
        assert len(result["funds"]) == 3
        assert len(result["macro"]) == 5

    @patch("fetcher.scrape_gold_price")
    @patch("fetcher.scrape_sp500")
    @patch("fetcher.scrape_treasury_yield")
    @patch("fetcher.scrape_fear_greed")
    @patch("fetcher.scrape_vix")
    @patch("fetcher.scrape_justetf")
    @patch("fetcher.yahoo_chart_api")
    def test_handles_total_failure(
        self,
        mock_yapi,
        mock_je,
        mock_vix,
        mock_fg,
        mock_ty,
        mock_sp,
        mock_gold,
        example_config_in_place,
    ):
        mock_yapi.return_value = None
        mock_je.return_value = None
        mock_vix.return_value = {"name": "VIX", "value": None}
        mock_fg.return_value = {"name": "Fear & Greed Index", "value": None}
        mock_ty.return_value = {"name": "US Yield Curve", "spread": None}
        mock_sp.return_value = {"name": "S&P 500"}
        mock_gold.return_value = {"name": "Gold Futures"}

        result = fetcher.fetch_all()
        assert len(result["funds"]) == 3
        for fund in result["funds"]:
            assert "price" not in fund


# --- JSON output test ---


class TestOutput:
    @patch("fetcher.fetch_all")
    def test_main_outputs_json(self, mock_fetch, capsys):
        mock_fetch.return_value = {
            "timestamp": "2026-04-17T08:00:00",
            "funds": [{"name": "Test", "price": 100.0}],
            "macro": [{"name": "VIX", "value": 18.0}],
        }
        fetcher.main()
        data = json.loads(capsys.readouterr().out)
        assert data["funds"][0]["price"] == 100.0


# --- Honest per-source accounting (etf-brief-001) ---


class TestSuccessCountAccounting:
    @patch("fetcher.scrape_gold_price")
    @patch("fetcher.scrape_sp500")
    @patch("fetcher.scrape_treasury_yield")
    @patch("fetcher.scrape_fear_greed")
    @patch("fetcher.scrape_vix")
    @patch("fetcher.scrape_justetf")
    @patch("fetcher.yahoo_chart_api")
    def test_yahoo_fails_justetf_succeeds_fund_still_has_price(
        self,
        mock_yapi,
        mock_je,
        mock_vix,
        mock_fg,
        mock_ty,
        mock_sp,
        mock_gold,
        example_config_in_place,
    ):
        """Yahoo rate-limited → JustETF (now primary) still fills price."""
        mock_yapi.return_value = None
        mock_je.return_value = {
            "source": "justetf",
            "price": 52.34,
            "performance": {"1d": 0.3},
        }
        mock_vix.return_value = {"name": "VIX", "value": 18.0}
        mock_fg.return_value = {"name": "Fear & Greed Index", "value": 40.0}
        mock_ty.return_value = {"name": "US Yield Curve", "spread": 0.4}
        mock_sp.return_value = {"name": "S&P 500", "price": 5200.0}
        mock_gold.return_value = {"name": "Gold Futures", "price_usd": 2300.0}

        result = fetcher.fetch_all()
        for fund in result["funds"]:
            assert fund["price"] == 52.34
            assert fund["price_source"] == "justetf"

    @patch("fetcher.fetch_all")
    def test_main_logs_per_source_counts(self, mock_fetch):
        """Completion log splits any-price from JustETF / Yahoo sub-counts."""
        mock_fetch.return_value = {
            "timestamp": "2026-04-17T08:00:00",
            "funds": [
                {
                    "name": "Example gold",
                    "price": 52.0,
                    "sources": [{"source": "justetf", "price": 52.0}],
                },
                {
                    "name": "Example global",
                    "price": 105.0,
                    "sources": [
                        {"source": "justetf", "price": 105.0},
                        {"source": "yahoo_api", "price": 105.2},
                    ],
                },
                {"name": "Example europe", "sources": []},
            ],
            "macro": [{"name": "VIX", "value": 18.0}],
        }

        captured: list[str] = []
        sink_id = fetcher.logger.add(
            lambda msg: captured.append(str(msg)), level="INFO"
        )
        try:
            fetcher.main()
        finally:
            fetcher.logger.remove(sink_id)

        joined = " ".join(captured)
        assert "2/3 with any price" in joined
        assert "JustETF 2/3" in joined
        assert "Yahoo 1/3" in joined
