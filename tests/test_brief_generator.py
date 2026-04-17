"""Tests for ``etf_brief.brief_generator``.

The generator's job is to assemble a high-fidelity prompt and pass
it through the LLM chain. These tests assert the prompt contains
the right material — the LLM call itself is mocked.
"""

from __future__ import annotations

from typing import Any

import pytest

from etf_brief.brief_generator import (
    _build_config_summary,
    _summarize_previous_briefs,
    generate_brief,
)
from etf_brief.models import (
    AllocationRule,
    AnalysisConfig,
    AppConfig,
    BitcoinConfig,
    FundConfig,
    LLMConfig,
    OllamaConfig,
    OutputConfig,
    PortfolioConfig,
    RecessionSignal,
    RecessionSignalsConfig,
    RecommendationsConfig,
    SourcesConfig,
    ThresholdsConfig,
)


def _make_config(monthly_investment: int = 500) -> AppConfig:
    """Build a minimal valid AppConfig for tests."""
    return AppConfig(
        portfolio=PortfolioConfig(
            monthly_investment=monthly_investment,
            currency="EUR",
            broker="Test Broker",
            execution_day=4,
            funds=[
                FundConfig(
                    name="Acme Gold ETC",
                    ticker="GOLD",
                    isin="IE00TESTGOLD",
                    type="ETC",
                    category="gold",
                    monthly_contribution=165,
                ),
                FundConfig(
                    name="World Equity ETF",
                    ticker="WORLD",
                    isin="IE00TESTWORLD",
                    type="ETF",
                    category="global_equity",
                    monthly_contribution=170,
                ),
                FundConfig(
                    name="Europe Equity ETF",
                    ticker="EURO",
                    isin="IE00TESTEURO",
                    type="ETF",
                    category="europe_equity",
                    monthly_contribution=165,
                ),
            ],
        ),
        bitcoin=BitcoinConfig(status="watchlist"),
        sources=SourcesConfig(),
        recession_signals=RecessionSignalsConfig(
            indicators=[
                RecessionSignal(
                    name="VIX",
                    search_query="VIX index",
                    weight="high",
                ),
            ]
        ),
        thresholds=ThresholdsConfig(
            hold_max_signals=1,
            decrease_min_signals=2,
            decrease_max_signals=3,
            sell_min_signals=4,
            increase_gold_min_signals=2,
            drawdown_warn=-10.0,
            drawdown_sell=-20.0,
            rally_take_profit=15.0,
        ),
        output=OutputConfig(vault_dir="/tmp/etf-test"),
        analysis=AnalysisConfig(
            lookback_days=30, ma_period=200, sentiment_weight=0.3
        ),
        recommendations=RecommendationsConfig(
            allocation_rules=[
                AllocationRule(
                    level="GREEN",
                    splits={
                        "gold": 33,
                        "global_equity": 34,
                        "europe_equity": 33,
                        "cash": 0,
                    },
                ),
                AllocationRule(
                    level="RED",
                    splits={
                        "gold": 50,
                        "global_equity": 0,
                        "europe_equity": 0,
                        "cash": 50,
                    },
                ),
            ]
        ),
        llm=LLMConfig(
            primary="claude",
            fallback_order=["claude", "ollama"],
            ollama=OllamaConfig(enabled=False),
        ),
    )


class _CapturingProvider:
    """Fake provider that records the last (prompt, system) pair."""

    name = "capture"
    available = True

    def __init__(self, response: str = "## SIGNAL: GREEN\n\nBrief body."):
        self.captured_prompt: str | None = None
        self.captured_system: str | None = None
        self._response = response

    def generate(self, prompt: str, system: str | None = None) -> str:
        self.captured_prompt = prompt
        self.captured_system = system
        return self._response


# --- _summarize_previous_briefs ----------------------------------------


def test_summarize_previous_briefs_empty():
    """No prior briefs → placeholder string (not empty)."""
    out = _summarize_previous_briefs([])
    assert "no previous briefs" in out


def test_summarize_previous_briefs_keeps_three():
    """Only the first 3 are kept (most-recent-first by caller's contract)."""
    briefs = [f"brief {i}" for i in range(10)]
    out = _summarize_previous_briefs(briefs)
    assert "brief 0" in out
    assert "brief 1" in out
    assert "brief 2" in out
    assert "brief 3" not in out


def test_summarize_previous_briefs_trims_long_entries():
    """Long entries are truncated to ~500 chars + truncation marker."""
    big = "x" * 5000
    out = _summarize_previous_briefs([big])
    assert "[truncated for prompt budget]" in out
    assert len(out) < 5000


# --- _build_config_summary ---------------------------------------------


def test_build_config_summary_lists_funds_and_rules():
    cfg = _make_config()
    summary = _build_config_summary(cfg)
    assert "Acme Gold ETC" in summary
    assert "World Equity ETF" in summary
    assert "Europe Equity ETF" in summary
    assert "GREEN" in summary
    assert "RED" in summary
    # Threshold keys must surface so the LLM can derive the level rule
    assert "1" in summary  # hold_max_signals
    assert "4" in summary  # sell_min_signals


# --- generate_brief ----------------------------------------------------


@pytest.fixture
def fetcher_output() -> dict[str, Any]:
    """Minimal fetcher payload — shape doesn't matter for prompt assembly."""
    return {
        "funds": [{"isin": "IE00TESTGOLD", "price": 52.34}],
        "macro": {"vix": 17.5, "fear_greed": 35},
    }


def test_generate_brief_prompt_contains_fund_names(fetcher_output):
    cfg = _make_config()
    capture = _CapturingProvider()
    generate_brief(
        fetcher_output=fetcher_output,
        config=cfg,
        previous_briefs=None,
        chain=[capture],
    )
    assert capture.captured_prompt is not None
    for fund in cfg.portfolio.funds:
        assert fund.name in capture.captured_prompt


def test_generate_brief_prompt_contains_signal_thresholds(fetcher_output):
    cfg = _make_config()
    capture = _CapturingProvider()
    generate_brief(
        fetcher_output=fetcher_output, config=cfg, chain=[capture]
    )
    prompt = capture.captured_prompt or ""
    # Each threshold field has a non-zero value the LLM needs visible
    for key in ("hold_max_signals", "decrease_min_signals",
                "decrease_max_signals", "sell_min_signals"):
        assert key in prompt or key.replace("_", " ") in prompt


def test_generate_brief_prompt_contains_allocation_rules(fetcher_output):
    cfg = _make_config()
    capture = _CapturingProvider()
    generate_brief(
        fetcher_output=fetcher_output, config=cfg, chain=[capture]
    )
    prompt = capture.captured_prompt or ""
    assert "GREEN" in prompt
    assert "RED" in prompt
    # at least one numeric percentage from the splits
    assert "33%" in prompt
    assert "50%" in prompt


def test_generate_brief_prompt_contains_previous_briefs(fetcher_output):
    cfg = _make_config()
    capture = _CapturingProvider()
    generate_brief(
        fetcher_output=fetcher_output,
        config=cfg,
        previous_briefs=["snippet ALPHA from yesterday",
                         "snippet BRAVO from two days ago"],
        chain=[capture],
    )
    prompt = capture.captured_prompt or ""
    assert "ALPHA" in prompt
    assert "BRAVO" in prompt


def test_generate_brief_returns_llm_response(fetcher_output):
    cfg = _make_config()
    capture = _CapturingProvider(response="THE BRIEF MARKDOWN")
    text, name = generate_brief(
        fetcher_output=fetcher_output, config=cfg, chain=[capture]
    )
    assert text == "THE BRIEF MARKDOWN"
    assert name == "capture"


def test_generate_brief_no_previous_briefs_substitutes_placeholder(
    fetcher_output,
):
    """Empty/None previous_briefs must not leave ${previous_briefs_summary} unfilled."""
    cfg = _make_config()
    capture = _CapturingProvider()
    generate_brief(
        fetcher_output=fetcher_output,
        config=cfg,
        previous_briefs=None,
        chain=[capture],
    )
    prompt = capture.captured_prompt or ""
    # The placeholder syntax must have been substituted away
    assert "${previous_briefs_summary}" not in prompt
    # And the placeholder string we emit on empty must be present
    assert "no previous briefs" in prompt


def test_generate_brief_system_prompt_has_no_preamble_constraint(
    fetcher_output,
):
    cfg = _make_config()
    capture = _CapturingProvider()
    generate_brief(
        fetcher_output=fetcher_output, config=cfg, chain=[capture]
    )
    assert capture.captured_system is not None
    assert "no preamble" in capture.captured_system.lower()
