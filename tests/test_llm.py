"""Tests for the LLM provider chain (``etf_brief.llm``).

All HTTP, subprocess, and SDK calls are mocked. No live network
allowed — the autouse ``isolate_loguru`` fixture from conftest keeps
warnings from these mocked failures out of the production log.
"""

from __future__ import annotations

import importlib.util
import subprocess
from unittest.mock import MagicMock

import pytest
import requests

from etf_brief.llm import (
    AnthropicSDKProvider,
    ClaudeCLIProvider,
    OllamaProvider,
    build_provider_chain,
    generate_with_fallback,
)
from etf_brief.models import LLMConfig, OllamaConfig


# --- ClaudeCLIProvider --------------------------------------------------


def test_claude_cli_detects_unavailable(monkeypatch):
    """When `claude` is not on PATH, available is False — no raise."""
    monkeypatch.setattr("etf_brief.llm.shutil.which", lambda _: None)
    p = ClaudeCLIProvider()
    assert p.available is False
    assert p.name == "claude-cli"


def test_claude_cli_generate_success(monkeypatch):
    """Happy path: subprocess returns 0 with stdout — generate returns it."""
    monkeypatch.setattr(
        "etf_brief.llm.shutil.which", lambda _: "/usr/local/bin/claude"
    )
    fake = MagicMock(returncode=0, stdout="hello world\n", stderr="")
    monkeypatch.setattr("etf_brief.llm.subprocess.run", lambda *a, **k: fake)
    p = ClaudeCLIProvider()
    assert p.available is True
    assert p.generate("prompt") == "hello world"


def test_claude_cli_generate_nonzero_exit_raises(monkeypatch):
    """Non-zero exit becomes RuntimeError with stderr in the message."""
    monkeypatch.setattr(
        "etf_brief.llm.shutil.which", lambda _: "/usr/local/bin/claude"
    )
    fake = MagicMock(returncode=2, stdout="", stderr="boom: bad token")
    monkeypatch.setattr("etf_brief.llm.subprocess.run", lambda *a, **k: fake)
    p = ClaudeCLIProvider()
    with pytest.raises(RuntimeError, match="exited 2"):
        p.generate("prompt")


def test_claude_cli_generate_empty_stdout_raises(monkeypatch):
    """Empty stdout (rc=0) is still a failure — caller has nothing to use."""
    monkeypatch.setattr(
        "etf_brief.llm.shutil.which", lambda _: "/usr/local/bin/claude"
    )
    fake = MagicMock(returncode=0, stdout="", stderr="")
    monkeypatch.setattr("etf_brief.llm.subprocess.run", lambda *a, **k: fake)
    p = ClaudeCLIProvider()
    with pytest.raises(RuntimeError, match="empty stdout"):
        p.generate("prompt")


def test_claude_cli_generate_timeout_raises(monkeypatch):
    """subprocess.TimeoutExpired surfaces as RuntimeError."""
    monkeypatch.setattr(
        "etf_brief.llm.shutil.which", lambda _: "/usr/local/bin/claude"
    )

    def raise_timeout(*_a, **_k):
        raise subprocess.TimeoutExpired(cmd="claude", timeout=180)

    monkeypatch.setattr("etf_brief.llm.subprocess.run", raise_timeout)
    p = ClaudeCLIProvider()
    with pytest.raises(RuntimeError, match="timed out"):
        p.generate("prompt")


# --- OllamaProvider -----------------------------------------------------


def test_ollama_probe_unavailable(monkeypatch):
    """If GET /api/tags raises, probe returns False — no exception."""

    def raise_conn(*_a, **_k):
        raise requests.ConnectionError("nope")

    monkeypatch.setattr("etf_brief.llm.requests.get", raise_conn)
    p = OllamaProvider(
        endpoint="http://localhost:11434",
        model="m",
        temperature=0.3,
        num_predict=512,
    )
    assert p.available is False


def test_ollama_generate_success(monkeypatch):
    """POST /api/chat returns content — generate returns it stripped."""
    monkeypatch.setattr(
        "etf_brief.llm.requests.get",
        lambda *a, **k: MagicMock(status_code=200),
    )
    monkeypatch.setattr(
        "etf_brief.llm.requests.post",
        lambda *a, **k: MagicMock(
            status_code=200,
            json=lambda: {"message": {"content": "  result text  "}},
        ),
    )
    p = OllamaProvider(
        endpoint="http://localhost:11434",
        model="m",
        temperature=0.3,
        num_predict=512,
    )
    assert p.available is True
    assert p.generate("prompt") == "result text"


def test_ollama_generate_thinking_fallback(monkeypatch):
    """MLX quirk: response under message.thinking when content empty."""
    monkeypatch.setattr(
        "etf_brief.llm.requests.get",
        lambda *a, **k: MagicMock(status_code=200),
    )
    monkeypatch.setattr(
        "etf_brief.llm.requests.post",
        lambda *a, **k: MagicMock(
            status_code=200,
            json=lambda: {
                "message": {"content": "", "thinking": "fallback content"}
            },
        ),
    )
    p = OllamaProvider(
        endpoint="http://localhost:11434",
        model="m",
        temperature=0.3,
        num_predict=512,
    )
    assert p.generate("prompt") == "fallback content"


def test_ollama_generate_empty_raises(monkeypatch):
    """No content + no thinking → RuntimeError."""
    monkeypatch.setattr(
        "etf_brief.llm.requests.get",
        lambda *a, **k: MagicMock(status_code=200),
    )
    monkeypatch.setattr(
        "etf_brief.llm.requests.post",
        lambda *a, **k: MagicMock(
            status_code=200,
            json=lambda: {"message": {"content": "", "thinking": ""}},
        ),
    )
    p = OllamaProvider(
        endpoint="http://localhost:11434",
        model="m",
        temperature=0.3,
        num_predict=512,
    )
    with pytest.raises(RuntimeError, match="empty message content"):
        p.generate("prompt")


def test_ollama_generate_non_200_raises(monkeypatch):
    """Non-200 HTTP body becomes RuntimeError with status in the message."""
    monkeypatch.setattr(
        "etf_brief.llm.requests.get",
        lambda *a, **k: MagicMock(status_code=200),
    )
    monkeypatch.setattr(
        "etf_brief.llm.requests.post",
        lambda *a, **k: MagicMock(status_code=500, text="server kaboom"),
    )
    p = OllamaProvider(
        endpoint="http://localhost:11434",
        model="m",
        temperature=0.3,
        num_predict=512,
    )
    with pytest.raises(RuntimeError, match="HTTP 500"):
        p.generate("prompt")


# --- AnthropicSDKProvider -----------------------------------------------


def test_anthropic_sdk_missing_package(monkeypatch):
    """When importlib can't find anthropic, available stays False."""
    real_find_spec = importlib.util.find_spec

    def fake_find_spec(name, *a, **k):
        if name == "anthropic":
            return None
        return real_find_spec(name, *a, **k)

    monkeypatch.setattr(
        "etf_brief.llm.importlib.util.find_spec", fake_find_spec
    )
    p = AnthropicSDKProvider(model="claude-sonnet-4-6")
    assert p.available is False


def test_anthropic_sdk_missing_key(monkeypatch):
    """SDK installed but no ANTHROPIC_API_KEY → available False."""
    monkeypatch.setattr(
        "etf_brief.llm.importlib.util.find_spec",
        lambda *a, **k: object(),
    )
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    p = AnthropicSDKProvider(model="claude-sonnet-4-6")
    assert p.available is False


# --- build_provider_chain -----------------------------------------------


def _claude_available(monkeypatch, available: bool) -> None:
    """Helper: pin shutil.which used by ClaudeCLIProvider."""
    monkeypatch.setattr(
        "etf_brief.llm.shutil.which",
        lambda _: ("/usr/local/bin/claude" if available else None),
    )


def _ollama_reachable(monkeypatch, reachable: bool) -> None:
    """Helper: pin requests.get to either succeed or raise."""
    if reachable:
        monkeypatch.setattr(
            "etf_brief.llm.requests.get",
            lambda *a, **k: MagicMock(status_code=200),
        )
    else:
        def boom(*_a, **_k):
            raise requests.ConnectionError("down")

        monkeypatch.setattr("etf_brief.llm.requests.get", boom)


def test_build_chain_primary_first(monkeypatch):
    """Primary provider appears first; fallback_order order preserved."""
    _claude_available(monkeypatch, True)
    _ollama_reachable(monkeypatch, True)
    cfg = LLMConfig(
        primary="ollama",
        fallback_order=["claude", "ollama"],
        ollama=OllamaConfig(enabled=True),
    )
    chain = build_provider_chain(cfg)
    assert [p.name for p in chain] == ["ollama", "claude-cli"]


def test_build_chain_disabled_ollama_excluded(monkeypatch):
    """ollama.enabled=False → Ollama dropped even if primary."""
    _claude_available(monkeypatch, True)
    _ollama_reachable(monkeypatch, True)
    cfg = LLMConfig(
        primary="claude",
        fallback_order=["claude", "ollama"],
        ollama=OllamaConfig(enabled=False),
    )
    chain = build_provider_chain(cfg)
    assert [p.name for p in chain] == ["claude-cli"]


def test_build_chain_unavailable_claude_excluded(monkeypatch):
    """Claude CLI not on PATH → dropped from chain."""
    _claude_available(monkeypatch, False)
    _ollama_reachable(monkeypatch, True)
    cfg = LLMConfig(
        primary="claude",
        fallback_order=["claude", "ollama"],
        ollama=OllamaConfig(enabled=True),
    )
    chain = build_provider_chain(cfg)
    assert [p.name for p in chain] == ["ollama"]


def test_build_chain_no_duplicates(monkeypatch):
    """Same provider listed twice across primary+fallback collapses to one."""
    _claude_available(monkeypatch, True)
    cfg = LLMConfig(
        primary="claude",
        fallback_order=["claude", "claude"],
        ollama=OllamaConfig(enabled=False),
    )
    chain = build_provider_chain(cfg)
    assert [p.name for p in chain] == ["claude-cli"]


def test_build_chain_unknown_keys_ignored(monkeypatch):
    """Stray keys in fallback_order are silently dropped."""
    _claude_available(monkeypatch, True)
    cfg = LLMConfig(
        primary="claude",
        fallback_order=["claude", "bogus", "made_up"],
        ollama=OllamaConfig(enabled=False),
    )
    chain = build_provider_chain(cfg)
    assert [p.name for p in chain] == ["claude-cli"]


# --- generate_with_fallback ---------------------------------------------


class _FakeProvider:
    def __init__(self, name: str, response: str | None = None,
                 raises: Exception | None = None):
        self.name = name
        self.available = True
        self._response = response
        self._raises = raises

    def generate(self, prompt: str, system: str | None = None) -> str:
        if self._raises is not None:
            raise self._raises
        return self._response or ""


def test_generate_with_fallback_first_succeeds():
    chain = [
        _FakeProvider("a", response="ok-a"),
        _FakeProvider("b", raises=RuntimeError("never reached")),
    ]
    text, name = generate_with_fallback("prompt", None, chain)
    assert text == "ok-a"
    assert name == "a"


def test_generate_with_fallback_falls_through():
    """First provider raises; second succeeds; second's name is returned."""
    chain = [
        _FakeProvider("a", raises=RuntimeError("transient")),
        _FakeProvider("b", response="ok-b"),
    ]
    text, name = generate_with_fallback("prompt", "sys", chain)
    assert text == "ok-b"
    assert name == "b"


def test_generate_with_fallback_all_exhausted():
    """Every provider raises → RuntimeError naming both errors."""
    chain = [
        _FakeProvider("a", raises=RuntimeError("first-err")),
        _FakeProvider("b", raises=RuntimeError("second-err")),
    ]
    with pytest.raises(RuntimeError) as excinfo:
        generate_with_fallback("prompt", None, chain)
    msg = str(excinfo.value)
    assert "first-err" in msg
    assert "second-err" in msg


def test_generate_with_fallback_empty_chain():
    """Empty chain raises immediately — no providers to try."""
    with pytest.raises(RuntimeError, match="chain is empty"):
        generate_with_fallback("prompt", None, [])
