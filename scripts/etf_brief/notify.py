"""Optional Telegram notification helper.

Reads ``TELEGRAM_BOT_TOKEN`` and ``TELEGRAM_CHAT_ID`` from the process
environment. If either is missing, :func:`send_telegram` logs a single
INFO line explaining the skip and returns ``False`` — it never raises.

Safe to import without env vars set. Safe to call in tests (no live HTTP
until the caller actually sends a message; tests mock ``requests.post``
or leave env unset).

Design constraints:

* plain-text ``parse_mode=""`` (health-script convention — Markdown
    interpretation breaks on punctuation in prices / percentages)
* 10-second timeout (never hang a run on a slow Telegram edge)
* failures are warnings, not errors (observability, not fatal)
"""

from __future__ import annotations

import os

import requests
from loguru import logger

_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
_TIMEOUT_SECONDS = 10


def send_telegram(text: str) -> bool:
    """Send a plain-text message to a Telegram chat.

    Reads credentials from the environment at call time (not at import
    time), so env setup / teardown in tests works naturally.

    Args:
        text: Plain-text message body. Not HTML, not Markdown —
            arbitrary punctuation in prices is allowed.

    Returns:
        ``True`` on HTTP 200 from the Telegram API, ``False`` otherwise
        (missing env vars, non-200 response, or network error).
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        logger.info(
            "Telegram notification skipped "
            "(TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set)"
        )
        return False

    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "",
        "disable_web_page_preview": True,
    }
    url = _TELEGRAM_API.format(token=token)
    try:
        resp = requests.post(url, data=payload, timeout=_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        logger.warning(f"Telegram send failed (network): {exc}")
        return False

    if resp.status_code != 200:
        logger.warning(
            f"Telegram send failed: HTTP {resp.status_code} "
            f"body={resp.text[:120]!r}"
        )
        return False
    return True
