"""Pluggable LLM provider chain for the standalone Python brief generator.

The canonical brief path is the Claude Code skill (the LLM that loads
``SKILL.md``); this module exists for the *Python* path —
``scripts/generate_brief.py`` invoked from cron, CI, or any context
without Claude Code. It tries Claude CLI first, falls through to
Ollama (local LLM) or the Anthropic SDK if configured.

Three providers ship today:

* :class:`ClaudeCLIProvider` — shells out to ``claude --print``;
  available when the Claude Code CLI binary is on ``PATH``.
* :class:`OllamaProvider` — POSTs to a local Ollama HTTP server
  (``/api/chat``); available when ``GET /api/tags`` succeeds.
* :class:`AnthropicSDKProvider` — uses the official ``anthropic``
  Python SDK; available when the SDK is importable and
  ``ANTHROPIC_API_KEY`` is in the environment.

All providers expose the same shape (``name``, ``available``,
``generate``). :func:`build_provider_chain` reads
:class:`etf_brief.models.LLMConfig`, honours ``primary`` +
``fallback_order``, drops unavailable / disabled providers, and
returns the chain ready to feed :func:`generate_with_fallback`.

Provider failures during a generate call (timeout, non-200 HTTP,
empty body) are caught at :func:`generate_with_fallback` and the
next provider is tried; the entire chain failing raises
:class:`RuntimeError` with all per-provider error strings joined.

Environment variables consulted:

* ``ANTHROPIC_API_KEY`` — required for :class:`AnthropicSDKProvider`.

Everything else flows through the validated :class:`LLMConfig` —
no module-level state.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import time
from typing import Protocol

import requests
from loguru import logger

from etf_brief.models import LLMConfig


_PROBE_TIMEOUT_SECONDS = 5
_OLLAMA_GENERATE_TIMEOUT_DEFAULT = 120
_CLAUDE_GENERATE_TIMEOUT_DEFAULT = 180
_ANTHROPIC_GENERATE_TIMEOUT_DEFAULT = 180
_ANTHROPIC_MAX_TOKENS = 4096


class LLMProvider(Protocol):
    """Common shape every provider implements.

    Attributes:
        name: Short stable identifier ("claude-cli", "ollama",
            "anthropic-sdk"); written into the brief frontmatter.
        available: ``True`` iff the provider was successfully probed
            at construct time. Providers that fail to construct never
            raise — they set ``available = False`` instead so the
            chain builder can filter them out cleanly.
    """

    name: str
    available: bool

    def generate(self, prompt: str, system: str | None = None) -> str:
        """Run the provider against a user prompt + optional system prompt.

        Returns the raw response text. Raises :class:`RuntimeError` on
        any provider-side failure (timeout, non-200, empty body,
        network error, etc.).
        """
        ...


class ClaudeCLIProvider:
    """Provider that shells out to the ``claude`` CLI binary.

    Availability is determined by ``shutil.which("claude")``. The
    ``--append-system-prompt`` flag is only added when ``system`` is
    non-empty so the CLI's own behaviour for prompts without a system
    component is preserved.
    """

    name = "claude-cli"

    def __init__(
        self,
        timeout_seconds: int = _CLAUDE_GENERATE_TIMEOUT_DEFAULT,
        bypass_permissions: bool = False,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.bypass_permissions = bypass_permissions
        self.available = shutil.which("claude") is not None

    def generate(self, prompt: str, system: str | None = None) -> str:
        cmd: list[str] = ["claude", "--print", prompt]
        if system:
            cmd.extend(["--append-system-prompt", system])
        if self.bypass_permissions:
            cmd.extend(["--permission-mode", "bypassPermissions"])
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"Claude CLI timed out after {self.timeout_seconds}s"
            ) from exc
        except OSError as exc:
            raise RuntimeError(f"Claude CLI invocation failed: {exc}") from exc
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()[:200]
            raise RuntimeError(
                f"Claude CLI exited {result.returncode}: {stderr!r}"
            )
        out = (result.stdout or "").strip()
        if not out:
            raise RuntimeError("Claude CLI produced empty stdout")
        return out


class OllamaProvider:
    """Provider for a local Ollama HTTP server.

    Probes ``GET /api/tags`` once at construct time (5s timeout).
    Calls ``POST /api/chat`` with ``stream=False, think=False`` for
    each generate call.

    The MLX backend occasionally returns the response under
    ``message.thinking`` instead of ``message.content``; we read both
    and prefer ``content`` when present.
    """

    name = "ollama"

    def __init__(
        self,
        endpoint: str,
        model: str,
        temperature: float,
        num_predict: int,
        timeout_seconds: int = _OLLAMA_GENERATE_TIMEOUT_DEFAULT,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.num_predict = num_predict
        self.timeout_seconds = timeout_seconds
        self.available = self._probe()

    def _probe(self) -> bool:
        try:
            resp = requests.get(
                f"{self.endpoint}/api/tags",
                timeout=_PROBE_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            logger.debug(f"Ollama probe failed at {self.endpoint}: {exc}")
            return False
        return resp.status_code == 200

    def generate(self, prompt: str, system: str | None = None) -> str:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        body = {
            "model": self.model,
            "messages": messages,
            "options": {
                "num_predict": self.num_predict,
                "temperature": self.temperature,
            },
            "stream": False,
            "think": False,
        }
        try:
            resp = requests.post(
                f"{self.endpoint}/api/chat",
                json=body,
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise RuntimeError(f"Ollama HTTP error: {exc}") from exc
        if resp.status_code != 200:
            body_preview = (resp.text or "")[:200]
            raise RuntimeError(
                f"Ollama returned HTTP {resp.status_code}: {body_preview!r}"
            )
        try:
            data = resp.json()
        except ValueError as exc:
            raise RuntimeError(f"Ollama returned non-JSON body: {exc}") from exc
        msg = data.get("message") or {}
        content = (msg.get("content") or msg.get("thinking") or "").strip()
        if not content:
            raise RuntimeError("Ollama returned empty message content")
        return content


class AnthropicSDKProvider:
    """Provider that uses the ``anthropic`` Python SDK directly.

    Availability requires both:

    * the ``anthropic`` package to be importable, AND
    * ``ANTHROPIC_API_KEY`` to be present in the process environment.

    The SDK is imported at construct time via :func:`importlib.util.find_spec`
    so a missing package does not raise; ``available`` is set to
    ``False`` instead.
    """

    name = "anthropic-sdk"

    def __init__(
        self,
        model: str,
        timeout_seconds: int = _ANTHROPIC_GENERATE_TIMEOUT_DEFAULT,
    ) -> None:
        self.model = model
        self.timeout_seconds = timeout_seconds
        self._client: object | None = None
        if importlib.util.find_spec("anthropic") is None:
            self.available = False
            return
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            self.available = False
            return
        import anthropic  # noqa: PLC0415 — deferred to avoid hard dep

        self._client = anthropic.Anthropic(
            api_key=api_key, timeout=timeout_seconds
        )
        self.available = True

    def generate(self, prompt: str, system: str | None = None) -> str:
        if self._client is None:
            raise RuntimeError(
                "Anthropic SDK provider is not available "
                "(missing package or ANTHROPIC_API_KEY)"
            )
        kwargs: dict[str, object] = {
            "model": self.model,
            "max_tokens": _ANTHROPIC_MAX_TOKENS,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system
        message = self._client.messages.create(**kwargs)  # type: ignore[attr-defined]
        chunks: list[str] = []
        for block in getattr(message, "content", []) or []:
            text = getattr(block, "text", None)
            if text:
                chunks.append(text)
        out = "\n".join(chunks).strip()
        if not out:
            raise RuntimeError("Anthropic SDK returned empty response")
        return out


_PROVIDER_KEYS: tuple[str, ...] = ("claude", "ollama", "anthropic_sdk")


def _construct_provider(
    key: str, config: LLMConfig
) -> LLMProvider | None:
    """Build one provider from a config key.

    Returns ``None`` if the key is unknown OR if the key is
    ``"ollama"`` and ``config.ollama.enabled`` is ``False`` — disabled
    providers are deliberately filtered before chain assembly so the
    chain accurately reflects intent.
    """
    if key == "claude":
        return ClaudeCLIProvider()
    if key == "ollama":
        if not config.ollama.enabled:
            return None
        return OllamaProvider(
            endpoint=config.ollama.endpoint,
            model=config.ollama.model,
            temperature=config.ollama.temperature,
            num_predict=config.ollama.num_predict,
            timeout_seconds=config.ollama.timeout_seconds,
        )
    if key == "anthropic_sdk":
        return AnthropicSDKProvider(model=config.anthropic_sdk_model)
    return None


def build_provider_chain(config: LLMConfig) -> list[LLMProvider]:
    """Assemble the ordered provider chain from ``LLMConfig``.

    Order: ``primary`` first, then each ``fallback_order`` entry, with
    duplicates dropped (preserving first occurrence). Unknown keys
    are silently skipped. Disabled / unavailable providers are
    filtered out so the chain only contains providers that can be
    invoked right now.

    Returns an empty list if no provider is available — callers must
    handle this (typically by raising).
    """
    seen: set[str] = set()
    ordered_keys: list[str] = []
    for key in [config.primary, *config.fallback_order]:
        if key not in _PROVIDER_KEYS:
            continue
        if key in seen:
            continue
        seen.add(key)
        ordered_keys.append(key)

    chain: list[LLMProvider] = []
    for key in ordered_keys:
        provider = _construct_provider(key, config)
        if provider is None:
            continue
        if not provider.available:
            logger.debug(
                f"LLM provider {provider.name} not available — skipping"
            )
            continue
        chain.append(provider)
    return chain


def generate_with_fallback(
    prompt: str,
    system: str | None,
    chain: list[LLMProvider],
) -> tuple[str, str]:
    """Try each provider in order; return the first success.

    Catches any ``Exception`` per provider so one provider's failure
    cannot abort the chain. Empty chain raises immediately.

    Returns:
        ``(response_text, provider_name)`` on success.

    Raises:
        RuntimeError: If the chain is empty, or if every provider
            raises. The error message lists every per-provider failure
            so the operator can diagnose without re-running.
    """
    if not chain:
        raise RuntimeError(
            "LLM provider chain is empty — no provider available"
        )
    errors: list[str] = []
    for provider in chain:
        start = time.perf_counter()
        try:
            response = provider.generate(prompt, system=system)
        except Exception as exc:  # noqa: BLE001 — fallback boundary
            elapsed = time.perf_counter() - start
            logger.warning(
                f"LLM provider {provider.name} failed after "
                f"{elapsed:.1f}s: {exc}"
            )
            errors.append(f"{provider.name}: {exc}")
            continue
        elapsed = time.perf_counter() - start
        logger.info(
            f"LLM provider {provider.name} succeeded in {elapsed:.1f}s"
        )
        return response, provider.name
    raise RuntimeError(
        "All LLM providers exhausted: " + "; ".join(errors)
    )
