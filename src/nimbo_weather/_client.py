"""Sync and async clients. Both share the request building, the retry rule and the answer parsing below."""

from __future__ import annotations

import asyncio
import os
import random
import time
from collections.abc import Callable
from typing import Any, TypeVar
from urllib.parse import urlencode

import httpx

from nimbo_weather._version import __version__
from nimbo_weather.errors import NimboConnectionError, NimboError, error_from_response, parse_retry_after
from nimbo_weather.models import KeyUsage, Nowcast, Palettes, RateLimit, Status, TilesIndex

DEFAULT_BASE_URL = "https://nimboweather.com"
DEFAULT_TIMEOUT = 10.0
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
# 503s the API means as "come back in 10 min" and the monthly quota are not retried: waiting a few seconds won't help.
NO_RETRY_CODES = frozenset({"monthly_quota_exceeded", "forecast_unavailable", "frames_unavailable"})

T = TypeVar("T")


def _env_key() -> str | None:
    return os.environ.get("NIMBO_API_KEY") or os.environ.get("NIMBO_KEY") or None


class _Base:
    def __init__(
        self,
        api_key: str | None,
        base_url: str,
        max_retries: int,
        max_retry_wait: float,
        user_agent: str | None,
    ) -> None:
        self.api_key = api_key if api_key is not None else _env_key()
        self.base_url = base_url.rstrip("/")
        self.max_retries = max(0, max_retries)
        self.max_retry_wait = max_retry_wait
        ua = f"nimbo-weather-python/{__version__}"
        self._headers = {
            "User-Agent": f"{user_agent} {ua}" if user_agent else ua,
            "Accept": "application/json",
        }

    def _auth_headers(self, keyed: bool) -> dict[str, str]:
        if not keyed:
            return dict(self._headers)
        if not self.api_key:
            raise NimboError(
                "No API key: pass api_key= or set NIMBO_API_KEY (or NIMBO_KEY).", code="api_key_required"
            )
        return {**self._headers, "X-API-Key": self.api_key}

    def _retry_wait(self, attempt: int, response: httpx.Response | None) -> float | None:
        """Seconds to wait before retry ``attempt`` (1-based), or None when the answer should not be retried."""
        if attempt > self.max_retries:
            return None
        if response is not None:
            if response.status_code not in RETRY_STATUSES:
                return None
            code = _error_code(response)
            if code in NO_RETRY_CODES:
                return None
            retry_after = parse_retry_after(response.headers.get("retry-after"))
            if retry_after is not None:
                return retry_after if retry_after <= self.max_retry_wait else None
        backoff = min(self.max_retry_wait, 0.5 * 2 ** (attempt - 1))
        return float(backoff * (0.75 + random.random() * 0.5))

    def _parse(self, response: httpx.Response) -> tuple[dict[str, Any], RateLimit | None]:
        if response.status_code >= 400:
            raise error_from_response(
                response.status_code, _json_or_none(response), response.headers.get("retry-after")
            )
        body = _json_or_none(response)
        if not isinstance(body, dict):
            raise NimboError(
                f"Unexpected answer (HTTP {response.status_code}, not a JSON object).",
                status=response.status_code,
            )
        return body, RateLimit.from_headers(response.headers)

    def tile_url(
        self, z: int, x: int, y: int, *, offset_min: int = 5, layer: str = "rain", palette: str | None = None
    ) -> str:
        """URL of the current forecast's tile ``offset_min`` minutes after its issue time (a redirecting alias, good
        for a single current frame; animate with ``tiles_index()`` frames instead). It carries the key in the query,
        as tiles require: use it server-side or in an app you control, not in a public web page."""
        if not self.api_key:
            raise NimboError(
                "No API key: pass api_key= or set NIMBO_API_KEY (or NIMBO_KEY).", code="api_key_required"
            )
        query = {"key": self.api_key, **({"palette": palette} if palette else {})}
        return f"{self.base_url}/tiles/{layer}/latest/{offset_min}/{z}/{x}/{y}.webp?{urlencode(query)}"


def _json_or_none(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


def _error_code(response: httpx.Response) -> str | None:
    body = _json_or_none(response)
    code = body.get("error") if isinstance(body, dict) else None
    return code if isinstance(code, str) else None


def _nowcast_params(lat: float, lon: float, horizon: int | None, step: int | None) -> dict[str, Any]:
    params: dict[str, Any] = {"lat": lat, "lon": lon}
    if horizon is not None:
        params["horizon"] = horizon
    if step is not None:
        params["step"] = step
    return params


class Nimbo(_Base):
    """Blocking client.

    >>> with Nimbo() as nimbo:  # reads NIMBO_API_KEY
    ...     print(nimbo.nowcast(52.37, 4.90).summary.text)
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = 2,
        max_retry_wait: float = 30.0,
        user_agent: str | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        super().__init__(api_key, base_url, max_retries, max_retry_wait, user_agent)
        self._own_client = http_client is None
        self._http = http_client or httpx.Client(timeout=timeout)

    def __enter__(self) -> Nimbo:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._own_client:
            self._http.close()

    def _get(
        self, path: str, params: dict[str, Any] | None = None, keyed: bool = True
    ) -> tuple[dict[str, Any], RateLimit | None]:
        headers = self._auth_headers(keyed)
        attempt = 0
        while True:
            attempt += 1
            try:
                response = self._http.get(self.base_url + path, params=params, headers=headers)
            except httpx.TransportError as e:
                wait = self._retry_wait(attempt, None)
                if wait is None:
                    raise NimboConnectionError(f"Request failed: {e}") from e
                time.sleep(wait)
                continue
            wait = self._retry_wait(attempt, response) if response.status_code >= 400 else None
            if wait is None:
                return self._parse(response)
            time.sleep(wait)

    def nowcast(
        self, lat: float, lon: float, *, horizon: int | None = None, step: int | None = None
    ) -> Nowcast:
        """Rain nowcast for a point. ``horizon``: 5-180 min (default 180); ``step``: 1, 5, 10 or 15 min (default 5)."""
        body, rl = self._get("/v1/nowcast", _nowcast_params(lat, lon, horizon, step))
        return Nowcast.from_dict(body, rl)

    def status(self) -> Status:
        """Health and freshness of the service (public, no key)."""
        return Status.from_dict(self._get("/v1/status", keyed=False)[0])

    def palettes(self) -> Palettes:
        """Colour tables of the rain tiles (public, no key)."""
        return Palettes.from_dict(self._get("/v1/palettes", keyed=False)[0])

    def tiles_index(self) -> TilesIndex:
        """The current forecast's map frames, each with a URL template per layer."""
        body, rl = self._get("/v1/tiles/index")
        return TilesIndex.from_dict(body, rl)

    def key_usage(self) -> KeyUsage:
        """The key's plan and this month's usage (not counted)."""
        return KeyUsage.from_dict(self._get("/v1/keys/me")[0])


class AsyncNimbo(_Base):
    """Asyncio client, same methods as :class:`Nimbo` (awaitable).

    >>> async with AsyncNimbo() as nimbo:
    ...     forecast = await nimbo.nowcast(52.37, 4.90)
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = 2,
        max_retry_wait: float = 30.0,
        user_agent: str | None = None,
        http_client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Any] | None = None,
    ) -> None:
        super().__init__(api_key, base_url, max_retries, max_retry_wait, user_agent)
        self._own_client = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=timeout)
        self._sleep = sleep or asyncio.sleep

    async def __aenter__(self) -> AsyncNimbo:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._own_client:
            await self._http.aclose()

    async def _get(
        self, path: str, params: dict[str, Any] | None = None, keyed: bool = True
    ) -> tuple[dict[str, Any], RateLimit | None]:
        headers = self._auth_headers(keyed)
        attempt = 0
        while True:
            attempt += 1
            try:
                response = await self._http.get(self.base_url + path, params=params, headers=headers)
            except httpx.TransportError as e:
                wait = self._retry_wait(attempt, None)
                if wait is None:
                    raise NimboConnectionError(f"Request failed: {e}") from e
                await self._sleep(wait)
                continue
            wait = self._retry_wait(attempt, response) if response.status_code >= 400 else None
            if wait is None:
                return self._parse(response)
            await self._sleep(wait)

    async def nowcast(
        self, lat: float, lon: float, *, horizon: int | None = None, step: int | None = None
    ) -> Nowcast:
        body, rl = await self._get("/v1/nowcast", _nowcast_params(lat, lon, horizon, step))
        return Nowcast.from_dict(body, rl)

    async def status(self) -> Status:
        return Status.from_dict((await self._get("/v1/status", keyed=False))[0])

    async def palettes(self) -> Palettes:
        return Palettes.from_dict((await self._get("/v1/palettes", keyed=False))[0])

    async def tiles_index(self) -> TilesIndex:
        body, rl = await self._get("/v1/tiles/index")
        return TilesIndex.from_dict(body, rl)

    async def key_usage(self) -> KeyUsage:
        return KeyUsage.from_dict((await self._get("/v1/keys/me"))[0])
