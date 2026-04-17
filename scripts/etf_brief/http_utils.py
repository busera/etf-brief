"""Shared HTTP helpers for fetcher / fallback modules.

Centralises the rotating User-Agent pool so we do not drift two copies
across ``fetcher.py`` and ``fallback.py``. Both modules import
:data:`USER_AGENTS` and :func:`get_rotating_headers` from here.

The pool is deliberately short (five UAs). More variety does not help —
the point is to avoid being classified as a single client by UA alone.
"""

from __future__ import annotations

import random

USER_AGENTS: list[str] = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]


def get_rotating_headers() -> dict[str, str]:
    """Return request headers with a randomly rotated ``User-Agent``.

    Returns:
        Dict suitable for ``requests.get(..., headers=...)``. Includes
        a generic ``Accept-Language`` so servers that content-negotiate
        on locale do not fall through to an error page.
    """
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept-Language": "en-US,en;q=0.9",
    }
