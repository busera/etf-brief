"""Pydantic v2 config models for the etf-brief skill.

The YAML user-config is validated at the program boundary so malformed
configs fail loudly with a precise error message rather than silently
producing wrong analysis downstream.

Cross-field invariants enforced here:

* Each :class:`AllocationRule` weight-dict must sum to 100 (+/-0.01).
* Every model uses ``extra="forbid"`` so typos in user YAML surface
  immediately.

Import example::

    from pathlib import Path
    from etf_brief.models import AppConfig
    config = AppConfig.load_from_yaml(Path("config.yaml"))
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


_FORBID = ConfigDict(extra="forbid")
_ALLOCATION_TOLERANCE = 0.01


class FundConfig(BaseModel):
    """Configuration for a single ETF / ETC saving plan.

    ``current_value``, ``total_return_pct`` and ``allocation_pct`` are
    optional so users who want to track live portfolio totals can do so
    without hard-coding them into the public skill.
    """

    model_config = _FORBID

    name: str
    ticker: str
    isin: str
    type: Literal["ETF", "ETC"]
    category: str
    monthly_contribution: int = 0
    current_value: float | None = None
    total_return_pct: float | None = None
    allocation_pct: float | None = None


class BitcoinOption(BaseModel):
    """One Bitcoin investment vehicle (ETP, exchange, or app)."""

    model_config = _FORBID

    name: str
    ticker: str | None = None
    isin: str | None = None
    ter: float | None = None
    fees: str | None = None
    note: str | None = None
    type: Literal["etp", "exchange", "app"] | None = None


class BitcoinIndicator(BaseModel):
    """One BTC-specific indicator to watch (e.g. 200-day MA, F&G)."""

    model_config = _FORBID

    name: str
    search_query: str
    note: str | None = None


class BitcoinConfig(BaseModel):
    """Bitcoin watch / active-position configuration."""

    model_config = _FORBID

    status: Literal["watchlist", "active", "disabled"]
    monthly_budget: float | None = None
    current_value: float | None = None
    scalable_options: list[BitcoinOption] = Field(default_factory=list)
    direct_options: list[BitcoinOption] = Field(default_factory=list)
    indicators: list[BitcoinIndicator] = Field(default_factory=list)


class RecessionSignal(BaseModel):
    """One recession-indicator entry.

    Threshold fields are signal-specific — ``threshold_warn`` /
    ``threshold_critical`` for ordinal signals (e.g. VIX), and
    ``threshold_contraction`` for level-crossing signals (e.g. PMI).
    """

    model_config = _FORBID

    name: str
    search_query: str
    weight: Literal["low", "medium", "high"]
    signal: str | None = None
    threshold_warn: float | None = None
    threshold_critical: float | None = None
    threshold_contraction: float | None = None
    note: str | None = None


class AllocationRule(BaseModel):
    """Category-weighted split for a single signal level.

    ``splits`` keys must match the ``category`` values of the configured
    funds (plus the synthetic ``cash`` category). Values are percentages
    that sum to 100 within :data:`_ALLOCATION_TOLERANCE`.

    ``level`` is free-form so users can model custom signal regimes
    (e.g. ``"EXTREME"``). The canonical four — ``GREEN``, ``YELLOW``,
    ``ORANGE``, ``RED`` — remain valid; the field validator only
    normalises to upper case and rejects empty strings. Uniqueness
    across the configured rule set is enforced at
    :class:`AppConfig` level.
    """

    model_config = _FORBID

    level: str
    splits: dict[str, float]

    @field_validator("level", mode="after")
    @classmethod
    def _normalise_level(cls, value: str) -> str:
        """Upper-case the level and reject empty strings.

        Args:
            value: Raw level as parsed from YAML.

        Returns:
            The upper-cased level.

        Raises:
            ValueError: If the level is empty or whitespace-only.
        """
        stripped = value.strip()
        if not stripped:
            raise ValueError(
                "AllocationRule.level must be a non-empty string"
            )
        return stripped.upper()

    @model_validator(mode="after")
    def _splits_sum_to_100(self) -> "AllocationRule":
        """Reject rules whose weights do not sum to 100%."""
        total = sum(self.splits.values())
        if abs(total - 100.0) > _ALLOCATION_TOLERANCE:
            raise ValueError(
                f"AllocationRule[{self.level}] splits sum to {total:.2f}, "
                f"expected 100.0 +/- {_ALLOCATION_TOLERANCE}"
            )
        return self


class RecommendationsConfig(BaseModel):
    """Top-level container for the ``recommendations.allocation_rules`` block."""

    model_config = _FORBID

    allocation_rules: list[AllocationRule]


class RecessionSignalsConfig(BaseModel):
    """Container for the ``recession_signals.indicators`` block."""

    model_config = _FORBID

    indicators: list[RecessionSignal]


class SentimentSource(BaseModel):
    """One community / social sentiment source (Reddit, X, etc.)."""

    model_config = _FORBID

    source: str
    type: Literal["reddit", "x", "forum", "other"]
    note: str | None = None
    search_terms: list[str] = Field(default_factory=list)


class SourcesConfig(BaseModel):
    """Web sources used for data gathering (grouped by purpose)."""

    model_config = _FORBID

    price_sources: list[str] = Field(default_factory=list)
    macro_sources: list[str] = Field(default_factory=list)
    analysis_sources: list[str] = Field(default_factory=list)
    etf_sources: list[str] = Field(default_factory=list)
    gold_sources: list[str] = Field(default_factory=list)
    sentiment_sources: list[SentimentSource] = Field(default_factory=list)


class PortfolioConfig(BaseModel):
    """Portfolio-level settings: budget, broker, and funds."""

    model_config = _FORBID

    monthly_investment: int
    currency: str
    broker: str
    execution_day: int
    funds: list[FundConfig]
    total_value: float | None = None
    total_monthly: int | None = None


class ThresholdsConfig(BaseModel):
    """Signal-count and price-move thresholds used in decision logic."""

    model_config = _FORBID

    hold_max_signals: int
    decrease_min_signals: int
    decrease_max_signals: int
    sell_min_signals: int
    increase_gold_min_signals: int
    drawdown_warn: float
    drawdown_sell: float
    rally_take_profit: float


class OutputConfig(BaseModel):
    """Where to write briefs and whether to emit a Telegram message."""

    model_config = _FORBID

    vault_dir: str
    telegram: bool = False


class AnalysisConfig(BaseModel):
    """Lookback windows and weighting for trend analysis."""

    model_config = _FORBID

    lookback_days: int
    ma_period: int
    sentiment_weight: float


class AppConfig(BaseModel):
    """Top-level application configuration.

    Load with :meth:`AppConfig.load_from_yaml`. Missing sections raise a
    :class:`pydantic.ValidationError` — do not paper over by adding
    defaults at this layer.
    """

    model_config = _FORBID

    portfolio: PortfolioConfig
    bitcoin: BitcoinConfig
    sources: SourcesConfig
    recession_signals: RecessionSignalsConfig
    thresholds: ThresholdsConfig
    output: OutputConfig
    analysis: AnalysisConfig
    recommendations: RecommendationsConfig

    @model_validator(mode="after")
    def _allocation_levels_unique(self) -> "AppConfig":
        """Reject duplicate signal-level keys across allocation rules.

        A single rule for a given level is the contract — two rules
        with ``level: GREEN`` would make the downstream selection
        non-deterministic.
        """
        levels = [
            rule.level for rule in self.recommendations.allocation_rules
        ]
        if len(levels) != len(set(levels)):
            seen: set[str] = set()
            dupes: list[str] = []
            for lvl in levels:
                if lvl in seen and lvl not in dupes:
                    dupes.append(lvl)
                seen.add(lvl)
            raise ValueError(
                "allocation_rules contains duplicate level(s): "
                f"{', '.join(dupes)}. Each level must appear at most once."
            )
        return self

    @model_validator(mode="after")
    def _allocation_splits_reference_known_categories(self) -> "AppConfig":
        """Every ``splits`` key must match a fund category or ``cash``.

        The synthetic ``cash`` category is held outside the saving plan
        and is always valid. Any other key must be present in at least
        one ``portfolio.funds[].category``.
        """
        known_categories: set[str] = {
            fund.category for fund in self.portfolio.funds
        } | {"cash"}
        for rule in self.recommendations.allocation_rules:
            for category in rule.splits:
                if category not in known_categories:
                    raise ValueError(
                        "allocation_rules.splits references unknown "
                        f"category {category!r} — not in funds[].category "
                        "or 'cash'"
                    )
        return self

    @classmethod
    def load_from_yaml(cls, path: Path) -> "AppConfig":
        """Parse and validate a YAML config file.

        Args:
            path: Path to the YAML config (typically ``config.yaml`` in
                the repo root).

        Returns:
            A validated :class:`AppConfig`.

        Raises:
            FileNotFoundError: If ``path`` does not exist.
            yaml.YAMLError: If the file is not valid YAML.
            pydantic.ValidationError: If the file is valid YAML but does
                not match the schema.
        """
        with path.open("r", encoding="utf-8") as fh:
            raw: Any = yaml.safe_load(fh)
        if not isinstance(raw, dict):
            raise ValueError(
                f"Config at {path} must be a YAML mapping, got "
                f"{type(raw).__name__}"
            )
        return cls.model_validate(raw)
