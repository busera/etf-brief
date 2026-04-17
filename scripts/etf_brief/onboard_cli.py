"""Standalone onboarding wizard — produces a valid ``config.yaml``.

This is the non-LLM fallback for the ``/etf-brief onboard`` flow. Same
Q&A, same validation, same output. Users who do not run the skill
inside Claude Code can run::

    PYTHONPATH=scripts python -m etf_brief.onboard_cli

from the repo root.

Interactive mode is the default. Non-interactive mode is supported via
``--defaults --yes`` (used by tests and documented as the "one-click"
path for power users who trust the example config).

Exit codes:

* ``0`` — success, ``config.yaml`` written
* ``1`` — user aborted (Ctrl-C or explicit "abort")
* ``2`` — validation failure (pydantic rejected the built dict)
* ``3`` — I/O error (file exists without ``--force``, unwritable path,
  broken ``config.example.yaml``, etc.)

Design notes:

* The default values for ``sources``, ``recession_signals``,
  ``thresholds``, ``analysis``, and the Bitcoin watch block are pulled
  verbatim from ``config.example.yaml`` so there is only one source of
  truth. The example file must ship with the repo.
* YAML is emitted via a hand-written template — not ``yaml.dump`` —
  so section-header comments survive.
* ISIN validation is delegated to
  :func:`etf_brief.isin_validator.validate_isin`. Tests mock that call;
  interactive runs hit JustETF live.
"""

from __future__ import annotations

import io
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import click
import yaml
from loguru import logger
from pydantic import ValidationError

from etf_brief.isin_validator import ISINInfo, validate_isin
from etf_brief.models import AppConfig

_EXIT_OK = 0
_EXIT_ABORT = 1
_EXIT_VALIDATION_ERROR = 2
_EXIT_IO_ERROR = 3

_SUPPORTED_CURRENCIES: tuple[str, ...] = ("EUR", "USD", "CHF", "GBP")
_DEFAULT_CATEGORIES: tuple[str, ...] = (
    "gold",
    "global_equity",
    "europe_equity",
    "us_equity",
    "emerging_markets",
    "bonds",
    "cash",
)
_SIGNAL_LEVELS: tuple[str, ...] = ("GREEN", "YELLOW", "ORANGE", "RED")


@dataclass
class FundEntry:
    """One fund the user added during the wizard loop."""

    name: str
    ticker: str
    isin: str
    type: str  # "ETF" | "ETC"
    category: str
    monthly_contribution: int


@dataclass
class OnboardState:
    """Accumulates wizard answers so each step can show a summary."""

    broker: str = "Scalable Capital"
    currency: str = "EUR"
    monthly_investment: int = 500
    funds: list[FundEntry] = field(default_factory=list)
    bitcoin_enabled: bool = True
    allocation_rules: list[dict[str, Any]] = field(default_factory=list)
    vault_dir: str = "./output/"
    telegram: bool = False
    execution_day: int = 4  # Scalable default


# --------------------------------------------------------------------------- #
# Defaults loader
# --------------------------------------------------------------------------- #


def _repo_root() -> Path:
    """Return the repo root (two levels up from this file)."""
    return Path(__file__).resolve().parent.parent.parent


def _load_example_defaults() -> dict[str, Any]:
    """Load ``config.example.yaml`` for default sub-sections.

    Returns:
        The parsed example config as a dict.

    Raises:
        FileNotFoundError: If the example file is missing (packaging bug).
    """
    example = _repo_root() / "config.example.yaml"
    if not example.exists():
        raise FileNotFoundError(
            f"config.example.yaml missing at {example}; cannot seed defaults."
        )
    with example.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(
            f"config.example.yaml is not a YAML mapping (got {type(data).__name__})"
        )
    return data


# --------------------------------------------------------------------------- #
# Q&A primitives (wrap click so unit-testing stays simple)
# --------------------------------------------------------------------------- #


def _ask_text(
    prompt: str, default: str, interactive: bool
) -> str:
    """Prompt for a free-text answer with a default.

    Args:
        prompt: Question shown to the user.
        default: Default value returned in non-interactive mode or when
            the user hits Enter.
        interactive: When ``False``, returns ``default`` without
            calling click.

    Returns:
        The answer string.
    """
    if not interactive:
        return default
    return click.prompt(prompt, default=default, type=str, show_default=True)


def _ask_int(
    prompt: str, default: int, interactive: bool, minimum: int = 1
) -> int:
    """Prompt for an integer, enforcing a minimum.

    Args:
        prompt: Question shown to the user.
        default: Default integer used non-interactively.
        interactive: Skip prompting if ``False``.
        minimum: Reject values below this (re-prompts until valid).

    Returns:
        The accepted integer.
    """
    if not interactive:
        return default
    while True:
        value = click.prompt(
            prompt, default=default, type=int, show_default=True
        )
        if value >= minimum:
            return value
        click.echo(
            f"  Value must be >= {minimum}, got {value}. Try again.",
            err=True,
        )


def _ask_choice(
    prompt: str,
    choices: tuple[str, ...],
    default: str,
    interactive: bool,
) -> str:
    """Prompt for one-of-many choice (case-insensitive match).

    Args:
        prompt: Question shown to the user.
        choices: Legal values.
        default: Default used non-interactively.
        interactive: Skip prompting if ``False``.

    Returns:
        One of ``choices``.
    """
    if not interactive:
        return default
    upper_choices = tuple(c.upper() for c in choices)
    while True:
        raw = click.prompt(
            f"{prompt} ({'/'.join(choices)})",
            default=default,
            type=str,
            show_default=True,
        )
        value = raw.strip().upper()
        if value in upper_choices:
            idx = upper_choices.index(value)
            return choices[idx]
        click.echo(
            f"  Must be one of {', '.join(choices)}. Got {raw!r}.",
            err=True,
        )


def _ask_yes_no(prompt: str, default: bool, interactive: bool) -> bool:
    """Prompt for a yes/no answer.

    Args:
        prompt: Question shown to the user.
        default: Default used non-interactively.
        interactive: Skip prompting if ``False``.

    Returns:
        ``True`` for yes, ``False`` for no.
    """
    if not interactive:
        return default
    return click.confirm(prompt, default=default)


# --------------------------------------------------------------------------- #
# Wizard steps
# --------------------------------------------------------------------------- #


def _step_broker(state: OnboardState, interactive: bool) -> None:
    """Ask for broker name."""
    click.echo(
        "Saving-plan mechanics (4th-of-month execution, free changes) "
        "are Scalable-specific. Other brokers work — you may need to "
        "place orders manually."
    )
    state.broker = _ask_text("Broker name", state.broker, interactive)


def _step_currency(state: OnboardState, interactive: bool) -> None:
    """Ask for display currency."""
    state.currency = _ask_choice(
        "Display currency",
        _SUPPORTED_CURRENCIES,
        state.currency,
        interactive,
    )


def _step_monthly(state: OnboardState, interactive: bool) -> None:
    """Ask for total monthly investment."""
    state.monthly_investment = _ask_int(
        f"Total monthly investment ({state.currency})",
        state.monthly_investment,
        interactive,
    )


def _prompt_fund_from_isin(
    info: ISINInfo, interactive: bool, state: OnboardState
) -> FundEntry | None:
    """Collect category + monthly contribution for a confirmed ISIN.

    Args:
        info: Validator response (name may be ``None``).
        interactive: Whether to ask for user input.
        state: Current wizard state (for currency context).

    Returns:
        The built :class:`FundEntry`, or ``None`` if the user rejects it.
    """
    display_name = info.name or "(name unavailable)"
    click.echo(
        f"  -> {display_name} | {info.isin} | "
        f"price {info.price} {info.currency}"
    )
    if interactive and not click.confirm("  Confirm this fund?", default=True):
        return None

    suggested = ", ".join(_DEFAULT_CATEGORIES)
    if interactive:
        click.echo(f"  Suggested categories: {suggested}")
    category = _ask_text(
        "  Category slug",
        "global_equity",
        interactive,
    ).strip()

    fund_type = _ask_choice(
        "  Type", ("ETF", "ETC"), "ETF", interactive
    )

    ticker = _ask_text(
        "  Ticker (e.g. VWCE.DE, SGLN.L) — optional, Enter to skip",
        info.isin,  # fallback to ISIN if user has no ticker handy
        interactive,
    ).strip()

    contribution = _ask_int(
        f"  Monthly contribution ({state.currency})",
        1,
        interactive,
        minimum=0,
    )

    return FundEntry(
        name=info.name or info.isin,
        ticker=ticker or info.isin,
        isin=info.isin,
        type=fund_type,
        category=category,
        monthly_contribution=contribution,
    )


def _step_funds(state: OnboardState, interactive: bool) -> None:
    """Loop: ask for funds until user says done. Enforces invariants.

    Raises:
        click.Abort: If the user cancels out mid-loop.
    """
    if not interactive:
        # Seed with two synthetic funds so non-interactive runs produce
        # a valid config without hitting the network. Tests bypass this
        # path by passing --isin / --fund flags (see ``main``).
        if not state.funds:
            state.funds = [
                FundEntry(
                    name="Example Global Equity ETF",
                    ticker="VWCE.DE",
                    isin="IE00BK5BQT80",
                    type="ETF",
                    category="global_equity",
                    monthly_contribution=max(state.monthly_investment - 100, 1),
                ),
                FundEntry(
                    name="Example Gold ETC",
                    ticker="SGLN.L",
                    isin="IE00B4ND3602",
                    type="ETC",
                    category="gold",
                    monthly_contribution=min(100, state.monthly_investment),
                ),
            ]
        return

    click.echo(
        "\nAdd funds. Enter an ISIN; the wizard validates against "
        "JustETF and asks for category + contribution. At least one "
        "non-cash fund required."
    )
    while True:
        raw = click.prompt(
            "ISIN (or 'done' to finish)", type=str, default="done"
        )
        if raw.strip().lower() in {"done", ""}:
            if not _funds_valid(state):
                click.echo(
                    "  At least one non-cash fund required. Add one.",
                    err=True,
                )
                continue
            break

        info = _resolve_isin(raw)
        if info is None:
            click.echo(
                f"  {raw.strip().upper()} did not validate. Skipped.",
                err=True,
            )
            continue

        fund = _prompt_fund_from_isin(info, interactive=True, state=state)
        if fund is not None:
            state.funds.append(fund)
            click.echo(
                f"  Added. Total funds so far: {len(state.funds)} "
                f"(contributions sum to "
                f"{sum(f.monthly_contribution for f in state.funds)})"
            )

    _reconcile_contributions(state, interactive)


def _resolve_isin(raw: str) -> ISINInfo | None:
    """Thin wrapper around :func:`validate_isin` that swallows timeouts.

    Args:
        raw: User-typed ISIN.

    Returns:
        ``ISINInfo`` on success, ``None`` otherwise (includes timeout —
        we log + skip rather than abort the whole wizard).
    """
    try:
        return validate_isin(raw)
    except TimeoutError as exc:
        logger.warning(f"onboard_cli: ISIN timeout for {raw}: {exc}")
        return None


def _funds_valid(state: OnboardState) -> bool:
    """At least one fund with a non-``cash`` category."""
    return any(f.category.strip().lower() != "cash" for f in state.funds)


def _reconcile_contributions(
    state: OnboardState, interactive: bool
) -> None:
    """Warn if ``sum(monthly_contribution) != monthly_investment``.

    Offers the user a chance to auto-adjust (scale proportionally) or
    override the monthly total. Non-interactive runs silently accept
    the mismatch — pydantic does not enforce the relationship.
    """
    total = sum(f.monthly_contribution for f in state.funds)
    if total == state.monthly_investment:
        return
    if not interactive:
        return
    click.echo(
        f"\nContributions sum to {total}, but monthly_investment is "
        f"{state.monthly_investment}."
    )
    choice = _ask_choice(
        "Reconcile by",
        ("keep", "match-total", "match-funds"),
        "keep",
        interactive,
    )
    if choice == "match-total" and total > 0:
        # Scale fund contributions to match the total.
        scale = state.monthly_investment / total
        for fund in state.funds:
            fund.monthly_contribution = max(
                1, round(fund.monthly_contribution * scale)
            )
    elif choice == "match-funds":
        state.monthly_investment = total


def _step_bitcoin(state: OnboardState, interactive: bool) -> None:
    """Ask whether to keep the Bitcoin watchlist."""
    state.bitcoin_enabled = _ask_yes_no(
        "Enable Bitcoin watchlist section?", state.bitcoin_enabled, interactive
    )


def _step_allocation(state: OnboardState, interactive: bool) -> None:
    """Propose default allocation rules per signal level; let user override.

    Defaults:

    * GREEN  — even split across non-cash funds
    * YELLOW — same, with a small gold tilt if present
    * ORANGE — half cash, rest skewed to gold when present
    * RED    — 100% cash
    """
    categories = _categories_in_use(state)
    state.allocation_rules = _propose_rules(categories)

    if not interactive:
        return

    click.echo("\nProposed allocation rules (edit any level to override):")
    for rule in state.allocation_rules:
        click.echo(f"  {rule['level']}: {rule['splits']}")

    if not click.confirm("Accept these defaults?", default=True):
        for rule in state.allocation_rules:
            _prompt_allocation_override(rule, categories)


def _categories_in_use(state: OnboardState) -> list[str]:
    """Return the sorted distinct categories across configured funds.

    Always includes the synthetic ``cash`` category so allocation
    rules can reference it even if no fund has that category.
    """
    seen: dict[str, None] = {}
    for fund in state.funds:
        seen[fund.category.strip()] = None
    seen["cash"] = None
    return list(seen)


def _propose_rules(categories: list[str]) -> list[dict[str, Any]]:
    """Build default allocation rules for the given categories.

    Args:
        categories: All categories in use (including synthetic cash).

    Returns:
        List of four rule dicts — one per signal level — with weights
        that sum to exactly 100.
    """
    non_cash = [c for c in categories if c != "cash"]
    has_gold = "gold" in categories
    rules: list[dict[str, Any]] = []
    for level in _SIGNAL_LEVELS:
        rules.append(
            {"level": level, "splits": _weights_for_level(level, non_cash, has_gold)}
        )
    return rules


def _weights_for_level(
    level: str, non_cash: list[str], has_gold: bool
) -> dict[str, float]:
    """Produce a weights dict (summing to 100) for one signal level."""
    splits: dict[str, float] = {}
    if level == "GREEN":
        splits = _even_split(non_cash)
        splits["cash"] = 0.0
    elif level == "YELLOW":
        if has_gold and len(non_cash) > 1:
            # 10-point gold tilt; balance across the rest.
            rest = [c for c in non_cash if c != "gold"]
            splits["gold"] = round(100 / len(non_cash) + 10, 2)
            remainder = 100 - splits["gold"]
            for cat in rest:
                splits[cat] = round(remainder / len(rest), 2)
            splits = _force_sum_100(splits)
        else:
            splits = _even_split(non_cash)
        splits["cash"] = splits.get("cash", 0.0)
    elif level == "ORANGE":
        if has_gold:
            splits["cash"] = 50.0
            splits["gold"] = 30.0
            rest = [c for c in non_cash if c != "gold"]
            if rest:
                per = round(20 / len(rest), 2)
                for cat in rest:
                    splits[cat] = per
            else:
                splits["gold"] = 50.0  # no other non-cash → all to gold
        else:
            splits["cash"] = 50.0
            for cat in non_cash:
                splits[cat] = round(50 / len(non_cash), 2)
        splits = _force_sum_100(splits)
    elif level == "RED":
        for cat in non_cash:
            splits[cat] = 0.0
        splits["cash"] = 100.0
    return _force_sum_100(splits)


def _even_split(categories: list[str]) -> dict[str, float]:
    """Evenly distribute 100 across ``categories`` (plus cash=0)."""
    if not categories:
        return {"cash": 100.0}
    per = 100 / len(categories)
    return {cat: round(per, 2) for cat in categories}


def _force_sum_100(splits: dict[str, float]) -> dict[str, float]:
    """Nudge the last non-zero weight so the dict sums to exactly 100.

    Rounding 100/3 twice gives 33.33 + 33.33 + 33.33 = 99.99 which the
    pydantic validator rejects (tolerance 0.01, 100.0 - 99.99 = 0.01 is
    on the edge). Adjust the largest weight by the residual.
    """
    total = sum(splits.values())
    residual = round(100.0 - total, 4)
    if abs(residual) < 0.001:
        return splits
    # Add the residual to the largest current weight so no bucket goes
    # negative and the human-readable split stays close to original.
    largest = max(splits, key=lambda k: splits[k])
    splits[largest] = round(splits[largest] + residual, 2)
    return splits


def _prompt_allocation_override(
    rule: dict[str, Any], categories: list[str]
) -> None:
    """Ask the user to override one allocation rule's weights.

    Loops until weights sum to 100 +/- 0.01.
    """
    click.echo(f"\nOverride {rule['level']} weights (must sum to 100):")
    new_splits: dict[str, float] = {}
    for cat in categories:
        current = rule["splits"].get(cat, 0.0)
        new_splits[cat] = click.prompt(
            f"  {cat} %", default=current, type=float
        )
    while abs(sum(new_splits.values()) - 100) > 0.01:
        click.echo(
            f"  Sum is {sum(new_splits.values())}, not 100. Retry.",
            err=True,
        )
        for cat in categories:
            new_splits[cat] = click.prompt(
                f"  {cat} %", default=new_splits[cat], type=float
            )
    rule["splits"] = new_splits


def _step_output(state: OnboardState, interactive: bool) -> None:
    """Ask for the vault directory and Telegram preference.

    The path is resolved to an absolute form before storage — a relative
    ``./output/`` otherwise ends up interpreted against whatever CWD
    the cron job / launchd job happened to run with.
    """
    while True:
        raw = _ask_text(
            "Vault directory (absolute path recommended; "
            "will be created if missing)",
            state.vault_dir,
            interactive,
        )
        expanded = Path(raw).expanduser().resolve()
        if not interactive:
            state.vault_dir = str(expanded)
            break
        try:
            expanded.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            click.echo(f"  Could not create {expanded}: {exc}", err=True)
            continue
        state.vault_dir = str(expanded)
        break

    state.telegram = _ask_yes_no(
        "Enable Telegram notifications?", state.telegram, interactive
    )
    if state.telegram and interactive:
        click.echo(
            "  Reminder: set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID "
            "env vars. See README for details."
        )


# --------------------------------------------------------------------------- #
# YAML emission
# --------------------------------------------------------------------------- #


def build_config_dict(
    state: OnboardState, defaults: dict[str, Any]
) -> dict[str, Any]:
    """Assemble the complete AppConfig-shaped dict.

    Copies ``sources``, ``recession_signals``, ``thresholds``, and
    ``analysis`` from the example defaults so the generated YAML has
    every required section.

    Args:
        state: Accumulated wizard answers.
        defaults: Parsed ``config.example.yaml``.

    Returns:
        A dict ready to serialise (and to validate via pydantic).

    Raises:
        ValueError: If the accumulated state violates a cross-field
            invariant (e.g. no non-cash fund). Caller handles this as
            exit code 2 (validation error).
    """
    if not state.funds:
        raise ValueError(
            "onboard_cli: at least one fund is required; "
            "state.funds is empty."
        )
    if not _funds_valid(state):
        raise ValueError(
            "onboard_cli: at least one non-cash fund is required; "
            "all configured funds have category='cash'."
        )
    cfg: dict[str, Any] = {}
    cfg["portfolio"] = {
        "monthly_investment": state.monthly_investment,
        "currency": state.currency,
        "broker": state.broker,
        "execution_day": state.execution_day,
        "funds": [
            {
                "name": f.name,
                "ticker": f.ticker,
                "isin": f.isin,
                "type": f.type,
                "category": f.category,
                "monthly_contribution": f.monthly_contribution,
            }
            for f in state.funds
        ],
    }
    cfg["bitcoin"] = _build_bitcoin_block(state, defaults)
    cfg["sources"] = defaults["sources"]
    cfg["recession_signals"] = defaults["recession_signals"]
    cfg["thresholds"] = defaults["thresholds"]
    cfg["output"] = {"vault_dir": state.vault_dir, "telegram": state.telegram}
    cfg["analysis"] = defaults["analysis"]
    cfg["recommendations"] = {"allocation_rules": state.allocation_rules}
    return cfg


def _build_bitcoin_block(
    state: OnboardState, defaults: dict[str, Any]
) -> dict[str, Any]:
    """Either copy the full example block or emit a minimal disabled stub.

    When disabled, we strip the ETP / exchange / indicator options per
    the spec — only the ``status`` field is required.
    """
    if state.bitcoin_enabled:
        block = dict(defaults["bitcoin"])
        # Respect user choice when watchlist was default; expose as-is.
        block["status"] = "watchlist"
        return block
    return {"status": "disabled", "monthly_budget": None}


def render_yaml(cfg: dict[str, Any]) -> str:
    """Serialize the config dict as well-commented YAML.

    Rather than fighting ``yaml.dump`` to emit comments, we emit each
    section with an explanatory header directly. Values inside each
    section are rendered via ``yaml.safe_dump`` so edge-case escaping
    (quotes, percent signs) stays correct.

    Args:
        cfg: The dict produced by :func:`build_config_dict`.

    Returns:
        A YAML document as a single string (trailing newline included).
    """
    buf = io.StringIO()
    buf.write(_FILE_HEADER)

    buf.write("# --- portfolio -----------------------------------------------\n")
    buf.write(
        "# Your funds, monthly budget, and broker mechanics. `funds[].category`\n"
        "# must match a key in `recommendations.allocation_rules.*.splits`.\n"
    )
    buf.write(_dump_block({"portfolio": cfg["portfolio"]}))
    buf.write("\n")

    buf.write("# --- bitcoin -------------------------------------------------\n")
    buf.write(
        "# Watchlist / active position configuration. Set status: disabled\n"
        "# to skip the Bitcoin section entirely.\n"
    )
    buf.write(_dump_block({"bitcoin": cfg["bitcoin"]}))
    buf.write("\n")

    buf.write("# --- sources -------------------------------------------------\n")
    buf.write(
        "# Web sources hinted to the LLM during brief generation. Not hit\n"
        "# directly by the scraper.\n"
    )
    buf.write(_dump_block({"sources": cfg["sources"]}))
    buf.write("\n")

    buf.write("# --- recession_signals --------------------------------------\n")
    buf.write(
        "# Each indicator is one row in the Recession Dashboard.\n"
    )
    buf.write(_dump_block({"recession_signals": cfg["recession_signals"]}))
    buf.write("\n")

    buf.write("# --- thresholds ---------------------------------------------\n")
    buf.write(
        "# Signal-count and price-move thresholds used by the decision logic.\n"
    )
    buf.write(_dump_block({"thresholds": cfg["thresholds"]}))
    buf.write("\n")

    buf.write("# --- output -------------------------------------------------\n")
    buf.write(
        "# Where to write briefs + whether to emit Telegram messages\n"
        "# (requires TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID env vars).\n"
    )
    buf.write(_dump_block({"output": cfg["output"]}))
    buf.write("\n")

    buf.write("# --- analysis -----------------------------------------------\n")
    buf.write("# Lookback + moving-average windows for trend analysis.\n")
    buf.write(_dump_block({"analysis": cfg["analysis"]}))
    buf.write("\n")

    buf.write("# --- recommendations ----------------------------------------\n")
    buf.write(
        "# Config-driven allocation rules. Each rule maps a signal level to\n"
        "# category weights (percentages summing to 100). pydantic validates\n"
        "# the sum on load — a 95-or-105 total will fail fast.\n"
    )
    buf.write(_dump_block({"recommendations": cfg["recommendations"]}))

    return buf.getvalue()


_FILE_HEADER = (
    "# -----------------------------------------------------------------------------\n"
    "# Generated by `etf_brief.onboard_cli`. Edit freely — this file is a plain\n"
    "# YAML config validated by pydantic on every run. Unknown fields fail fast\n"
    "# so typos surface at startup rather than as silent mis-analysis.\n"
    "#\n"
    "# Not financial advice. Decision support only.\n"
    "# -----------------------------------------------------------------------------\n\n"
)


def _dump_block(block: dict[str, Any]) -> str:
    """Serialise one top-level section via ``yaml.safe_dump``.

    We always emit ``default_flow_style=False`` (block style) and allow
    Unicode so strings like ``"Vanguard FTSE All-World"`` don't pick up
    escape sequences.
    """
    return yaml.safe_dump(
        block,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    )


# --------------------------------------------------------------------------- #
# Validation + write
# --------------------------------------------------------------------------- #


def _validate_dict(cfg: dict[str, Any]) -> AppConfig:
    """Run pydantic validation on the built dict.

    Args:
        cfg: Candidate config dict.

    Returns:
        Validated :class:`AppConfig`.

    Raises:
        pydantic.ValidationError: Propagated to caller.
    """
    return AppConfig.model_validate(cfg)


def _write_yaml(path: Path, body: str) -> None:
    """Write ``body`` to ``path`` atomically.

    Args:
        path: Target file path.
        body: YAML document.

    Raises:
        OSError: On filesystem failure.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(path)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.option(
    "--defaults",
    "use_defaults",
    is_flag=True,
    help="Skip the Q&A and use sensible defaults for everything.",
)
@click.option(
    "--yes",
    "assume_yes",
    is_flag=True,
    help="Assume yes to every confirmation (required with --defaults "
    "for a fully non-interactive run).",
)
@click.option(
    "--force",
    is_flag=True,
    help="Overwrite config.yaml if it already exists.",
)
@click.option(
    "--config-path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Target path for the generated config (defaults to "
    "<repo-root>/config.yaml).",
)
def cli(
    use_defaults: bool,
    assume_yes: bool,
    force: bool,
    config_path: Path | None,
) -> None:
    """Run the onboarding wizard and write a validated ``config.yaml``.

    Args:
        use_defaults: Bypass interactive prompts.
        assume_yes: Skip confirmation prompts.
        force: Overwrite an existing config.
        config_path: Optional override for the output path.
    """
    try:
        exit_code = run(
            interactive=not (use_defaults and assume_yes),
            force=force,
            config_path=config_path,
        )
    except click.Abort:
        click.echo("Aborted by user.", err=True)
        sys.exit(_EXIT_ABORT)
    sys.exit(exit_code)


def run(
    interactive: bool,
    force: bool,
    config_path: Path | None,
) -> int:
    """Core wizard entry point, returns an exit code.

    Split out from ``cli`` so unit tests can drive it directly.

    Args:
        interactive: Whether to prompt for input.
        force: Overwrite an existing config.
        config_path: Target path (defaults to ``<repo>/config.yaml``).

    Returns:
        One of ``_EXIT_OK`` / ``_EXIT_VALIDATION_ERROR`` / ``_EXIT_IO_ERROR``.
    """
    target = config_path or (_repo_root() / "config.yaml")
    if target.exists() and not force:
        click.echo(
            f"Refusing to overwrite existing {target}. "
            f"Re-run with --force if you mean it.",
            err=True,
        )
        return _EXIT_IO_ERROR

    try:
        defaults = _load_example_defaults()
    except (FileNotFoundError, ValueError) as exc:
        click.echo(f"Cannot seed defaults: {exc}", err=True)
        return _EXIT_IO_ERROR

    state = OnboardState()

    _step_broker(state, interactive)
    _step_currency(state, interactive)
    _step_monthly(state, interactive)
    _step_funds(state, interactive)
    _step_bitcoin(state, interactive)
    _step_allocation(state, interactive)
    _step_output(state, interactive)

    try:
        cfg = build_config_dict(state, defaults)
    except ValueError as exc:
        click.echo(f"Validation failed: {exc}", err=True)
        return _EXIT_VALIDATION_ERROR
    try:
        _validate_dict(cfg)
    except ValidationError as exc:
        click.echo(f"Validation failed:\n{exc}", err=True)
        return _EXIT_VALIDATION_ERROR

    body = render_yaml(cfg)
    # Belt-and-braces: validate the rendered YAML round-trips cleanly.
    try:
        round_trip = yaml.safe_load(body)
        _validate_dict(round_trip)
    except (yaml.YAMLError, ValidationError) as exc:
        click.echo(
            f"Rendered YAML did not round-trip through the validator: {exc}",
            err=True,
        )
        return _EXIT_VALIDATION_ERROR

    try:
        _write_yaml(target, body)
    except OSError as exc:
        click.echo(f"Failed to write {target}: {exc}", err=True)
        return _EXIT_IO_ERROR

    click.echo(f"Wrote {target}.")
    click.echo(
        "Next steps: run `/etf-brief` in Claude Code or schedule "
        "scripts/run.sh via cron. See README for details."
    )
    return _EXIT_OK


if __name__ == "__main__":  # pragma: no cover - thin CLI wrapper
    cli()
