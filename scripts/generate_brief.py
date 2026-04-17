"""Standalone CLI for generating an ETF brief without Claude Code.

Use this when running from cron, CI, or any environment that does
not have an interactive Claude Code session. The default chain is
read from ``config.yaml -> llm`` (Claude CLI primary, optional
Ollama / Anthropic SDK fallback).

Usage::

    # Use the chain configured in config.yaml (auto):
    PYTHONPATH=scripts python scripts/generate_brief.py

    # Force a specific provider — useful for testing:
    python scripts/generate_brief.py --provider=ollama
    python scripts/generate_brief.py --provider=claude

    # Skip the live fetcher and use a saved JSON snapshot:
    python scripts/generate_brief.py --from-json /tmp/snap.json --dry-run

The ``--provider`` override force-enables the chosen provider as the
sole chain entry — bypassing the ``llm.ollama.enabled`` flag and
``primary`` / ``fallback_order`` in the config. ``auto`` (the
default) honours the config faithfully.

Exit codes:

* ``0`` — brief generated successfully.
* ``1`` — provider chain exhausted; no provider produced a brief.
* ``2`` — config file missing or invalid (pydantic ValidationError).
* ``3`` — I/O error (vault dir missing, write permission denied,
  ``--from-json`` file not found).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import click
import yaml
from loguru import logger

# Make the sibling ``etf_brief`` package importable without pip install.
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from etf_brief.brief_generator import generate_brief  # noqa: E402
from etf_brief.datetime_utils import today_berlin  # noqa: E402
from etf_brief.llm import (  # noqa: E402
    AnthropicSDKProvider,
    ClaudeCLIProvider,
    LLMProvider,
    OllamaProvider,
    build_provider_chain,
)
from etf_brief.logging_config import setup_logger  # noqa: E402
from etf_brief.models import AppConfig  # noqa: E402
from etf_brief.notify import send_telegram  # noqa: E402

logger = setup_logger(  # noqa: F811 — replace module-level loguru proxy
    "generate_brief",
    log_dir=_SCRIPTS_DIR.parent / "logs",
)

_PREVIOUS_BRIEF_PATTERN = re.compile(
    r"^(\d{4}-\d{2}-\d{2}) ETF Brief\.md$"
)
_PREVIOUS_BRIEFS_TO_LOAD = 3
_TELEGRAM_PREVIEW_LINES = 18


def _build_override_chain(
    provider: str, config: AppConfig
) -> list[LLMProvider]:
    """Construct a single-provider chain when ``--provider`` is given.

    Force-enables the chosen provider regardless of
    ``config.llm.ollama.enabled`` etc. The chain is *not* filtered
    by ``available`` here — if the user explicitly asks for Ollama
    and Ollama is down, they should see the failure rather than a
    silent no-op. The provider's own :meth:`generate` will raise.
    """
    if provider == "claude":
        return [ClaudeCLIProvider()]
    if provider == "ollama":
        return [
            OllamaProvider(
                endpoint=config.llm.ollama.endpoint,
                model=config.llm.ollama.model,
                temperature=config.llm.ollama.temperature,
                num_predict=config.llm.ollama.num_predict,
                timeout_seconds=config.llm.ollama.timeout_seconds,
            )
        ]
    if provider == "anthropic_sdk":
        return [AnthropicSDKProvider(model=config.llm.anthropic_sdk_model)]
    raise click.UsageError(f"Unknown provider key {provider!r}")


def _load_previous_briefs(vault_dir: Path) -> list[str]:
    """Glob the vault for prior briefs, return last N most-recent first.

    Uses filename-date sorting (filenames start with ISO date), which
    is robust to filesystem mtime drift.
    """
    if not vault_dir.exists():
        logger.warning(
            f"Vault dir {vault_dir} does not exist — skipping previous-brief load"
        )
        return []
    candidates: list[tuple[str, Path]] = []
    for path in vault_dir.iterdir():
        if not path.is_file():
            continue
        match = _PREVIOUS_BRIEF_PATTERN.match(path.name)
        if match:
            candidates.append((match.group(1), path))
    candidates.sort(reverse=True)
    return [
        path.read_text(encoding="utf-8")
        for _, path in candidates[:_PREVIOUS_BRIEFS_TO_LOAD]
    ]


def _condense_for_telegram(brief: str) -> str:
    """Take the first ~N lines of the brief for a quick Telegram ping.

    The full markdown is always written to the vault — Telegram is a
    nudge, not a replacement.
    """
    lines = brief.splitlines()
    head = "\n".join(lines[:_TELEGRAM_PREVIEW_LINES])
    return head + "\n\n[full brief in vault]"


def _stamp_provider_in_frontmatter(brief: str, provider_name: str) -> str:
    """Replace the ``llm_provider: TBD`` frontmatter placeholder.

    The LLM is told to leave ``llm_provider`` and ``llm_model`` as
    ``TBD``; the runner stamps the actual provider here so the file
    on disk is self-describing.
    """
    return brief.replace(
        "llm_provider: <will be filled by the runner — leave as TBD>",
        f"llm_provider: {provider_name}",
    )


@click.command()
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=False, path_type=Path),
    default=Path("config.yaml"),
    show_default=True,
    help="Path to config.yaml.",
)
@click.option(
    "--from-json",
    "from_json",
    type=click.Path(exists=False, path_type=Path),
    default=None,
    help=(
        "Read fetcher output from this JSON file instead of running "
        "the live fetcher. Useful for offline testing."
    ),
)
@click.option(
    "--provider",
    type=click.Choice(["auto", "claude", "ollama", "anthropic_sdk"]),
    default="auto",
    show_default=True,
    help=(
        "Force a single provider. 'auto' uses config.llm. Any "
        "explicit value force-enables that provider as the only "
        "chain entry."
    ),
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Print brief to stdout; skip file write and Telegram.",
)
def main(
    config_path: Path,
    from_json: Path | None,
    provider: str,
    dry_run: bool,
) -> None:
    """Generate an ETF brief and optionally write it / send Telegram."""
    if not config_path.exists():
        click.echo(
            f"ERROR: config file not found at {config_path}",
            err=True,
        )
        sys.exit(2)
    try:
        config = AppConfig.load_from_yaml(config_path)
    except (yaml.YAMLError, ValueError) as exc:
        click.echo(f"ERROR: invalid config at {config_path}: {exc}", err=True)
        sys.exit(2)

    if from_json is not None:
        if not from_json.exists():
            click.echo(f"ERROR: --from-json file not found: {from_json}", err=True)
            sys.exit(3)
        try:
            fetcher_output = json.loads(from_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            click.echo(
                f"ERROR: --from-json file is not valid JSON: {exc}", err=True
            )
            sys.exit(3)
    else:
        # Lazy import — avoids paying network/env cost when only --from-json
        # is used (cron, tests).
        import fetcher  # noqa: PLC0415

        fetcher_output = fetcher.fetch_all()

    vault_dir = Path(config.output.vault_dir).expanduser()
    previous_briefs = _load_previous_briefs(vault_dir)

    chain = (
        build_provider_chain(config.llm)
        if provider == "auto"
        else _build_override_chain(provider, config)
    )

    try:
        brief, provider_name = generate_brief(
            fetcher_output=fetcher_output,
            config=config,
            previous_briefs=previous_briefs,
            chain=chain,
        )
    except RuntimeError as exc:
        click.echo(f"ERROR: brief generation failed: {exc}", err=True)
        sys.exit(1)

    brief = _stamp_provider_in_frontmatter(brief, provider_name)

    if dry_run:
        click.echo(brief)
        return

    today = today_berlin().isoformat()
    out_path = vault_dir / f"{today} ETF Brief.md"
    try:
        vault_dir.mkdir(parents=True, exist_ok=True)
        out_path.write_text(brief, encoding="utf-8")
    except OSError as exc:
        click.echo(
            f"ERROR: failed to write brief to {out_path}: {exc}", err=True
        )
        sys.exit(3)
    click.echo(f"Wrote brief to {out_path} (provider={provider_name})")

    if config.output.telegram:
        sent = send_telegram(_condense_for_telegram(brief))
        if sent:
            click.echo("Telegram notification sent.")
        else:
            click.echo("Telegram notification skipped or failed (see logs).")


if __name__ == "__main__":
    main()
