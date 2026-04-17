"""Tests for the optional Telegram notifier.

Zero live HTTP: every test either leaves env vars unset (no-op path) or
mocks ``requests.post``.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from etf_brief import notify


class TestSendTelegram:
    def test_both_env_vars_unset_returns_false(self, monkeypatch):
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

        captured: list[str] = []
        sink_id = notify.logger.add(
            lambda m: captured.append(str(m)), level="INFO"
        )
        try:
            result = notify.send_telegram("hi")
        finally:
            notify.logger.remove(sink_id)

        assert result is False
        assert any("Telegram notification skipped" in m for m in captured)

    def test_only_token_set_returns_false(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "abc")
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

        captured: list[str] = []
        sink_id = notify.logger.add(
            lambda m: captured.append(str(m)), level="INFO"
        )
        try:
            result = notify.send_telegram("hi")
        finally:
            notify.logger.remove(sink_id)

        assert result is False
        assert any("Telegram notification skipped" in m for m in captured)

    @patch("etf_brief.notify.requests.post")
    def test_success_returns_true(self, mock_post, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "abc")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "123456")

        resp = MagicMock()
        resp.status_code = 200
        mock_post.return_value = resp

        assert notify.send_telegram("hi") is True
        # Confirm plain-text parse_mode was honoured
        args, kwargs = mock_post.call_args
        assert kwargs["data"]["parse_mode"] == ""
        assert kwargs["data"]["text"] == "hi"
        assert kwargs["data"]["chat_id"] == "123456"
        assert "bot" in args[0] or "bot" in kwargs.get("url", "")

    @patch("etf_brief.notify.requests.post")
    def test_network_error_returns_false(self, mock_post, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "abc")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "123456")
        mock_post.side_effect = requests.ConnectionError("boom")

        assert notify.send_telegram("hi") is False

    @patch("etf_brief.notify.requests.post")
    def test_non_200_returns_false(self, mock_post, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "abc")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "123456")
        resp = MagicMock()
        resp.status_code = 400
        resp.text = "bad request"
        mock_post.return_value = resp

        assert notify.send_telegram("hi") is False
