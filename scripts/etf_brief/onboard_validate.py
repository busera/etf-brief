"""One-shot validator invoked by the LLM onboarding path.

The LLM builds the config dict in working memory, writes a tempfile,
and calls::

    python -m etf_brief.onboard_validate <path-to-yaml>

Exit code ``0`` means :meth:`AppConfig.load_from_yaml` succeeded and the
file is ready to be promoted to ``config.yaml``. Exit code ``1`` means
the YAML failed validation; the serialized pydantic error is printed to
stderr so the LLM can read it and return to the relevant question.

Any other exit code indicates an unexpected crash and should bubble up
to the user.
"""

from __future__ import annotations

import sys
from pathlib import Path

from pydantic import ValidationError

from etf_brief.models import AppConfig

_EXIT_OK = 0
_EXIT_VALIDATION_FAIL = 1
_EXIT_USAGE = 2


def _validate(path: Path) -> int:
    """Validate a single YAML file as an :class:`AppConfig`.

    Args:
        path: Path to a YAML candidate.

    Returns:
        ``_EXIT_OK`` on success, ``_EXIT_VALIDATION_FAIL`` otherwise.
        Errors are written to stderr.
    """
    if not path.exists():
        print(f"onboard_validate: file not found: {path}", file=sys.stderr)
        return _EXIT_VALIDATION_FAIL
    try:
        AppConfig.load_from_yaml(path)
    except ValidationError as exc:
        print(exc, file=sys.stderr)
        return _EXIT_VALIDATION_FAIL
    except (OSError, ValueError) as exc:
        print(f"onboard_validate: {exc}", file=sys.stderr)
        return _EXIT_VALIDATION_FAIL
    return _EXIT_OK


def main(argv: list[str] | None = None) -> int:
    """CLI entry point — validate a single config file.

    Args:
        argv: Optional argument list (defaults to ``sys.argv[1:]``).
            Tests pass this explicitly.

    Returns:
        Process exit code.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print(
            "usage: python -m etf_brief.onboard_validate <path-to-yaml>",
            file=sys.stderr,
        )
        return _EXIT_USAGE
    return _validate(Path(args[0]))


if __name__ == "__main__":  # pragma: no cover - thin CLI wrapper
    raise SystemExit(main())
