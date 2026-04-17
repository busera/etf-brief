"""Brief generator for the standalone Python execution path.

This module is *only* used by ``scripts/generate_brief.py`` (cron /
CI / any non-Claude-Code invocation). The Claude Code skill consumes
``SKILL.md`` directly and never reaches here.

The generator is pure I/O-free apart from reading the bundled prompt
template — file-system access (loading previous briefs, writing the
output file) is the responsibility of the CLI in
``scripts/generate_brief.py``. This split keeps the generator easy
to unit-test without monkeypatching paths, and keeps prompt
construction fully observable.

System / user prompt split:

* The **system** prompt is short and frames role + non-preamble
  constraint. Splices into the Claude CLI via
  ``--append-system-prompt`` and into the Anthropic SDK via the
  ``system`` field.
* The **user** prompt contains all data (fetcher JSON, config
  summary, previous briefs, today's date) and the full output
  template. Substitution uses :class:`string.Template` with
  ``${placeholder}`` syntax so the markdown body can use ``{`` and
  ``}`` freely.

The previous-brief summary cap (3 entries × ~500 chars each) is a
deliberate token-budget guardrail — too much history dilutes the
prompt and pushes the LLM toward over-fitting historical noise.
"""

from __future__ import annotations

import json
from pathlib import Path
from string import Template

from loguru import logger

from etf_brief.datetime_utils import today_berlin
from etf_brief.llm import (
    LLMProvider,
    build_provider_chain,
    generate_with_fallback,
)
from etf_brief.models import AppConfig

_SYSTEM_PROMPT = (
    "You are a disciplined, opinionated ETF investment analyst. "
    "Output the filled markdown brief only — no preamble, no "
    "meta-commentary, no apologies. Follow the output template "
    "structure exactly and write recommendations directly, without "
    "hedging."
)

_PREVIOUS_BRIEF_TRIM_CHARS = 500
_PREVIOUS_BRIEFS_KEEP = 3
_PROMPT_TEMPLATE_PATH = (
    Path(__file__).resolve().parent / "prompts" / "brief.md"
)


def _load_prompt_template() -> str:
    """Read the user-prompt template from the bundled ``prompts/`` dir.

    Raises:
        FileNotFoundError: If the template is missing — bug, not a
            user error.
    """
    if not _PROMPT_TEMPLATE_PATH.exists():
        raise FileNotFoundError(
            f"Brief prompt template missing at {_PROMPT_TEMPLATE_PATH} — "
            "package install is broken"
        )
    return _PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")


def _summarize_previous_briefs(previous_briefs: list[str]) -> str:
    """Trim and join the most recent prior briefs.

    Returns a placeholder string when no prior briefs are passed so
    the template never substitutes an empty value (prevents
    "previous briefs: " followed by nothing — LLMs hallucinate
    against silence).
    """
    if not previous_briefs:
        return "(no previous briefs found — this is the first brief)"
    chunks: list[str] = []
    for idx, brief in enumerate(
        previous_briefs[:_PREVIOUS_BRIEFS_KEEP], start=1
    ):
        trimmed = brief.strip()
        if len(trimmed) > _PREVIOUS_BRIEF_TRIM_CHARS:
            trimmed = (
                trimmed[:_PREVIOUS_BRIEF_TRIM_CHARS]
                + "\n... [truncated for prompt budget]"
            )
        chunks.append(f"=== Previous brief #{idx} ===\n{trimmed}")
    return "\n\n".join(chunks)


def _build_config_summary(config: AppConfig) -> str:
    """Render a compact plain-text summary of the validated config.

    Includes the fields the LLM actually needs to make decisions:
    portfolio funds, thresholds, allocation rules. Skips opaque
    sections (sources URLs, sentiment search terms) that would
    bloat the prompt without informing the recommendation.
    """
    lines: list[str] = []
    p = config.portfolio
    lines.append(
        f"Portfolio: {p.broker}, {p.monthly_investment} {p.currency}/month, "
        f"execution day {p.execution_day}"
    )
    lines.append("")
    lines.append("Funds:")
    for f in p.funds:
        contrib_pct = (
            (f.monthly_contribution / p.monthly_investment * 100)
            if p.monthly_investment
            else 0.0
        )
        lines.append(
            f"  - {f.name} ({f.ticker} / {f.isin}) — category={f.category}, "
            f"current contribution {f.monthly_contribution} {p.currency}/mo "
            f"({contrib_pct:.0f}%)"
        )
    lines.append("")
    t = config.thresholds
    lines.append("Signal thresholds (active-signal counts):")
    lines.append(
        f"  - HOLD when count <= {t.hold_max_signals}; "
        f"DECREASE when {t.decrease_min_signals}-{t.decrease_max_signals}; "
        f"SELL when count >= {t.sell_min_signals}; "
        f"INCREASE_GOLD when count >= {t.increase_gold_min_signals}"
    )
    lines.append(
        f"  - Drawdown warn = {t.drawdown_warn:.1f}%, "
        f"sell = {t.drawdown_sell:.1f}%, "
        f"rally take-profit = {t.rally_take_profit:.1f}%"
    )
    lines.append("")
    lines.append("Allocation rules (signal level → category split %):")
    for rule in config.recommendations.allocation_rules:
        split_str = ", ".join(
            f"{cat}={pct:g}%" for cat, pct in rule.splits.items()
        )
        lines.append(f"  - {rule.level}: {split_str}")
    lines.append("")
    lines.append(
        f"Bitcoin status: {config.bitcoin.status}"
        + (
            f" (monthly_budget={config.bitcoin.monthly_budget})"
            if config.bitcoin.monthly_budget is not None
            else ""
        )
    )
    lines.append("")
    lines.append(
        f"Recession indicators tracked ({len(config.recession_signals.indicators)}): "
        + ", ".join(
            f"{ind.name}[{ind.weight}]"
            for ind in config.recession_signals.indicators
        )
    )
    return "\n".join(lines)


def _build_user_prompt(
    fetcher_output: dict,
    config: AppConfig,
    previous_briefs: list[str] | None,
) -> str:
    """Assemble the full user prompt by substituting into the template."""
    template_str = _load_prompt_template()
    template = Template(template_str)
    return template.safe_substitute(
        fetcher_json=json.dumps(fetcher_output, indent=2, sort_keys=True),
        config_summary=_build_config_summary(config),
        previous_briefs_summary=_summarize_previous_briefs(
            previous_briefs or []
        ),
        today_iso=today_berlin().isoformat(),
    )


def generate_brief(
    fetcher_output: dict,
    config: AppConfig,
    previous_briefs: list[str] | None = None,
    chain: list[LLMProvider] | None = None,
) -> tuple[str, str]:
    """Generate today's brief using the configured LLM provider chain.

    Args:
        fetcher_output: Parsed JSON output of ``scripts/fetcher.py``.
        config: Validated app config (provides funds, thresholds,
            allocation rules, and the LLM chain spec).
        previous_briefs: Most-recent-first list of prior brief
            markdown strings. Pass an empty list or ``None`` for the
            first run.
        chain: Optional pre-built provider chain. When ``None`` (the
            normal case), :func:`build_provider_chain` is called on
            ``config.llm``. Tests and the CLI's ``--provider``
            override path inject custom chains here.

    Returns:
        ``(markdown_brief, provider_name)`` — the second element is
        the ``name`` of the provider that produced the result; the
        CLI writes it into the brief frontmatter.

    Raises:
        RuntimeError: If the provider chain is empty or every
            provider failed (re-raised from
            :func:`generate_with_fallback`).
        FileNotFoundError: If the bundled prompt template is missing.
    """
    user_prompt = _build_user_prompt(
        fetcher_output, config, previous_briefs
    )
    active_chain = (
        chain if chain is not None else build_provider_chain(config.llm)
    )
    logger.debug(
        f"LLM chain: {[p.name for p in active_chain]} "
        f"({len(active_chain)} providers)"
    )
    response, provider_name = generate_with_fallback(
        user_prompt, _SYSTEM_PROMPT, active_chain
    )
    logger.info(
        f"Brief generated by {provider_name} "
        f"({len(response)} chars)"
    )
    return response, provider_name
