"""ISIN validator for the onboarding wizard.

Looks up an ISIN against JustETF's public quote API to confirm the fund
exists and to pull enough metadata (name, currency, price) for the
wizard to show the user a confirmation prompt before accepting the
entry.

The quote API (``/api/etfs/{isin}/quote``) returns price + day-change
only — it has no ``name`` or ``ter`` fields. Human-readable name is
best-effort scraped from the profile page's HTML ``<title>`` tag.
TER is not available without running the profile page's JavaScript,
so :attr:`ISINInfo.ter` is always ``None`` today (kept in the model
shape so a future scraper upgrade can fill it without a schema bump).

Entry point::

    from etf_brief.isin_validator import validate_isin
    info = validate_isin("IE00B4ND3602")
    if info is None:
        # unknown ISIN or malformed input
        ...
    else:
        print(info.name, info.currency, info.price)

Network behaviour:

* Rejects inputs that do not match :data:`_ISIN_REGEX` before hitting
  the network (fails fast on typos).
* Returns ``None`` on 404 (unknown ISIN) or any non-recoverable JSON
  parse / HTTP error that is not a timeout.
* Raises :class:`TimeoutError` on genuine network timeouts so the
  wizard can prompt the user to retry rather than silently dropping
  the fund.
"""

from __future__ import annotations

import re
from typing import Any

import requests
from loguru import logger
from pydantic import BaseModel, ConfigDict

# ISO 6166: 2 alpha country code + 9 alphanumeric + 1 check digit.
# We do not verify the Luhn-style check digit — JustETF will do that
# by returning 404 on unknown ISINs.
_ISIN_REGEX = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}\d$")

_QUOTE_API_URL = (
    "https://www.justetf.com/api/etfs/{isin}/quote"
    "?locale=en&currency={currency}&isin={isin}"
)
_PROFILE_URL = "https://www.justetf.com/en/etf-profile.html?isin={isin}"
_TIMEOUT_SECONDS = 15

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class ISINInfo(BaseModel):
    """Public-facing metadata for an ISIN looked up via JustETF.

    Mirrors the fields the onboarding wizard actually needs to show
    the user before accepting the fund. ``name`` is optional because
    the HTML title parse is best-effort; ``ter`` is always ``None``
    today but kept on the model so a future scraper can fill it.
    """

    model_config = ConfigDict(extra="forbid")

    isin: str
    name: str | None
    currency: str
    price: float
    ter: float | None
    url: str


def _looks_like_isin(candidate: str) -> bool:
    """Return True if ``candidate`` matches the 12-char ISIN regex.

    Args:
        candidate: User-supplied string (already stripped / uppercased
            by the caller, but defensive against either).

    Returns:
        ``True`` for syntactically plausible ISINs, ``False`` otherwise.
    """
    return bool(_ISIN_REGEX.match(candidate.strip().upper()))


def _fetch_quote(isin: str, currency: str) -> dict[str, Any] | None:
    """Call the JustETF quote API and return the parsed JSON body.

    Args:
        isin: Normalised (upper-cased, stripped) ISIN.
        currency: Three-letter display currency (e.g. ``"EUR"``).

    Returns:
        Parsed JSON dict on success, ``None`` on 404 or any
        non-timeout error.

    Raises:
        TimeoutError: If the request times out (caller should prompt
            the user to retry rather than treating it as a validation
            failure).
    """
    url = _QUOTE_API_URL.format(isin=isin, currency=currency)
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
            timeout=_TIMEOUT_SECONDS,
        )
    except requests.Timeout as exc:
        raise TimeoutError(f"JustETF quote API timed out for {isin}") from exc
    except requests.RequestException as exc:
        logger.warning(f"isin_validator: HTTP error for {isin}: {exc}")
        return None

    if resp.status_code == 404:
        logger.info(f"isin_validator: {isin} unknown (HTTP 404)")
        return None
    if resp.status_code != 200:
        logger.warning(
            f"isin_validator: unexpected HTTP {resp.status_code} for {isin}"
        )
        return None

    try:
        return resp.json()
    except ValueError as exc:
        logger.warning(f"isin_validator: invalid JSON for {isin}: {exc}")
        return None


def _fetch_name_from_profile(isin: str) -> str | None:
    """Best-effort scrape of the fund name from the profile page title.

    The profile page renders its ``<title>`` server-side as
    ``"<fund name> | <WKN> | <ISIN>"``. We take the first
    pipe-separated chunk. If the network call fails or the title is
    missing / malformed, returns ``None`` — the caller treats ``name``
    as optional metadata.

    Args:
        isin: Normalised ISIN (caller already validated the regex).

    Returns:
        Fund name as a trimmed string, or ``None`` on any failure.
    """
    url = _PROFILE_URL.format(isin=isin)
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": _USER_AGENT, "Accept": "text/html"},
            timeout=_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
    except requests.Timeout:
        # Don't escalate — name is optional.
        logger.info(f"isin_validator: profile page timed out for {isin}")
        return None
    except requests.RequestException as exc:
        logger.info(f"isin_validator: profile page error for {isin}: {exc}")
        return None

    # Cheap regex is enough — avoid pulling BeautifulSoup just for the title.
    match = re.search(
        r"<title>([^<]+)</title>", resp.text, flags=re.IGNORECASE
    )
    if not match:
        return None
    raw = match.group(1).strip()
    # Format observed live: "<name> | <WKN> | <ISIN>". Take the leading chunk.
    first_chunk = raw.split("|", 1)[0].strip()
    return first_chunk or None


def validate_isin(isin: str, currency: str = "EUR") -> ISINInfo | None:
    """Look up an ISIN against JustETF and return its metadata.

    Runs a fast regex check first so typos never hit the network.
    On a valid-looking ISIN, calls the quote API and (best-effort)
    the profile page for the name.

    Args:
        isin: User-supplied ISIN (will be stripped + upper-cased).
        currency: Three-letter display currency passed to the quote
            API. Defaults to ``"EUR"``.

    Returns:
        An :class:`ISINInfo` on success; ``None`` if the ISIN is
        malformed, unknown (HTTP 404), or the response payload has no
        usable price.

    Raises:
        TimeoutError: Propagated from :func:`_fetch_quote` when the
            quote API request times out. The wizard should catch
            this and prompt for a retry.
    """
    if not isinstance(isin, str):
        logger.warning(
            f"isin_validator: non-string input {type(isin).__name__}"
        )
        return None

    normalised = isin.strip().upper()
    if not _looks_like_isin(normalised):
        logger.info(
            f"isin_validator: {isin!r} does not match ISIN regex; "
            f"skipping network call"
        )
        return None

    payload = _fetch_quote(normalised, currency)
    if payload is None:
        return None

    latest = payload.get("latestQuote") or {}
    raw_price = latest.get("raw")
    if not isinstance(raw_price, (int, float)) or raw_price <= 0:
        logger.info(
            f"isin_validator: {normalised} has no usable price "
            f"(got {raw_price!r})"
        )
        return None

    name = _fetch_name_from_profile(normalised)

    return ISINInfo(
        isin=normalised,
        name=name,
        currency=currency,
        price=float(raw_price),
        ter=None,
        url=_PROFILE_URL.format(isin=normalised),
    )
