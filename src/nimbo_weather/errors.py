"""Typed exceptions, one per kind of API error.

Every API error is JSON ``{"error": code, "message": text}``, sometimes with more fields (kept in ``body``).
"""

from __future__ import annotations

from typing import Any


class NimboError(Exception):
    """Base class of every error this package raises."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        code: str | None = None,
        body: dict[str, Any] | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.body: dict[str, Any] = body or {}
        self.retry_after = retry_after

    def __str__(self) -> str:
        if self.code:
            return f"{self.code}: {self.message}"
        return self.message


class NimboConnectionError(NimboError):
    """The request did not get an answer (network error or timeout), after the retries."""


class AuthenticationError(NimboError):
    """401: no key (``api_key_required``), a key that is not valid or revoked (``invalid_api_key``),
    two different keys (``conflicting_api_keys``), or a tile key sent in a header (``key_in_query_only``)."""


class InvalidParameterError(NimboError):
    """422 ``invalid_parameter``: fix the request. ``parameters`` lists each problem."""

    @property
    def parameters(self) -> list[dict[str, str]]:
        params = self.body.get("parameters")
        return params if isinstance(params, list) else []


class NotFoundError(NimboError):
    """404: no such layer, palette, tile or time."""


class OutOfCoverageError(NotFoundError):
    """404 ``out_of_coverage``: the point is outside the forecast area. Do not retry."""


class RateLimitError(NimboError):
    """429: too many requests at once (for example ``tile_rate_limited``). Wait ``retry_after`` seconds."""


class QuotaExceededError(RateLimitError):
    """429 ``monthly_quota_exceeded``: the month's allowance is used up. ``retry_after`` is the time to the reset."""


class ServiceUnavailableError(NimboError):
    """503 ``forecast_unavailable`` / ``frames_unavailable``: no recent forecast (a radar outage). Retry in 10 min."""


class ServerError(NimboError):
    """Any other 5xx answer."""


def error_from_response(status: int, body: Any, headers_retry_after: str | None) -> NimboError:
    """The typed exception for an error answer (``body`` is the decoded JSON, or None when it was not JSON)."""
    data: dict[str, Any] = body if isinstance(body, dict) else {}
    code = data.get("error") if isinstance(data.get("error"), str) else None
    message = data.get("message") if isinstance(data.get("message"), str) else f"HTTP {status}"
    retry_after = parse_retry_after(headers_retry_after)
    cls: type[NimboError]
    if status == 401:
        cls = AuthenticationError
    elif status == 422:
        cls = InvalidParameterError
    elif status == 404:
        cls = OutOfCoverageError if code == "out_of_coverage" else NotFoundError
    elif status == 429:
        cls = QuotaExceededError if code == "monthly_quota_exceeded" else RateLimitError
    elif status == 503 and code in ("forecast_unavailable", "frames_unavailable"):
        cls = ServiceUnavailableError
    elif status >= 500:
        cls = ServerError
    else:
        cls = NimboError
    return cls(str(message), status=status, code=code, body=data, retry_after=retry_after)


def parse_retry_after(value: str | None) -> float | None:
    """``Retry-After`` in seconds (the API sends a whole number of seconds; an HTTP date is not used)."""
    if value is None:
        return None
    try:
        seconds = float(value.strip())
    except ValueError:
        return None
    return max(0.0, seconds)
