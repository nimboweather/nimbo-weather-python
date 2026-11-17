from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
import pytest
import respx

from nimbo_weather import (
    AsyncNimbo,
    AuthenticationError,
    InvalidParameterError,
    Nimbo,
    NimboConnectionError,
    NimboError,
    OutOfCoverageError,
    QuotaExceededError,
    RateLimitError,
    ServerError,
    ServiceUnavailableError,
)

BASE = "https://nimboweather.com"
KEY = "nimbo_test_key"

NOWCAST: dict[str, Any] = {
    "lat": 52.37,
    "lon": 4.9,
    "issue_time": "2026-11-12T17:10:00Z",
    "data_age_s": 420,
    "stale": False,
    "notice": None,
    "coverage": "radar",
    "radar_source": "opera",
    "summary": {
        "text": "Light rain starting in 23 min, for about 40 min",
        "rain_now": False,
        "rain_starts_at": "2026-11-12T17:40:00Z",
        "rain_ends_at": "2026-11-12T18:20:00Z",
        "minutes_until_rain": 23,
        "max_intensity": "light",
        "now_source": "radar",
    },
    "minutely": [
        {
            "time": "2026-11-12T17:15:00Z",
            "precip_mm_h": 0.0,
            "precip_probability": 0.05,
            "precip_probability_1mm_h": 0.0,
            "precip_probability_5mm_h": 0.0,
            "precip_type": "rain",
        },
        {
            "time": "2026-11-12T17:40:00Z",
            "precip_mm_h": 0.8,
            "precip_probability": 0.7,
            "precip_probability_1mm_h": 0.3,
            "precip_probability_5mm_h": 0.0,
            "precip_type": "rain",
        },
    ],
    "observed_now": {"time": "2026-11-12T17:15:00Z", "precip_mm_h": 0.0},
    "horizon_skill": [{"lead_min": 5, "csi_1mmh": 0.8}],
    "horizon_skill_label": "archive",
    "confidence_notes": [],
    "grid": "EUROPE_2K",
    "attribution": ["Radar credit line"],
    "future_field": 1,
}
RL_HEADERS = {
    "X-RateLimit-Limit": "20000",
    "X-RateLimit-Remaining": "19990",
    "X-RateLimit-Reset": "1764547200",
}


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    waits: list[float] = []
    monkeypatch.setattr("nimbo_weather._client.time.sleep", waits.append)
    return waits


@pytest.fixture(autouse=True)
def no_env_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NIMBO_API_KEY", raising=False)
    monkeypatch.delenv("NIMBO_KEY", raising=False)


@respx.mock
def test_nowcast_parses_and_sends_key() -> None:
    route = respx.get(f"{BASE}/v1/nowcast").mock(
        return_value=httpx.Response(200, json=NOWCAST, headers=RL_HEADERS)
    )
    with Nimbo(KEY) as nimbo:
        n = nimbo.nowcast(52.37, 4.9, horizon=60, step=5)
    req = route.calls.last.request
    assert req.headers["x-api-key"] == KEY
    assert req.headers["user-agent"].startswith("nimbo-weather-python/")
    assert dict(req.url.params) == {"lat": "52.37", "lon": "4.9", "horizon": "60", "step": "5"}
    assert n.issue_time == datetime(2026, 11, 12, 17, 10, tzinfo=timezone.utc)
    assert n.summary is not None and n.summary.minutes_until_rain == 23 and n.summary.rain_ends_at is not None
    assert n.minutely[1].precip_mm_h == 0.8 and n.minutely[1].precip_type == "rain"
    assert n.has_radar and n.attribution == ["Radar credit line"]
    assert n.raw["future_field"] == 1
    assert n.rate_limit is not None and n.rate_limit.remaining == 19990


@respx.mock
def test_no_radar_has_null_summary_and_values() -> None:
    body = {
        **NOWCAST,
        "coverage": "no_radar",
        "summary": None,
        "radar_source": None,
        "observed_now": None,
        "minutely": [
            {
                "time": "2026-11-12T17:15:00Z",
                "precip_mm_h": None,
                "precip_probability": None,
                "precip_probability_1mm_h": None,
                "precip_probability_5mm_h": None,
                "precip_type": "rain",
            }
        ],
    }
    respx.get(f"{BASE}/v1/nowcast").mock(return_value=httpx.Response(200, json=body))
    n = Nimbo(KEY).nowcast(36.0, 3.0)
    assert (
        not n.has_radar and n.summary is None and n.minutely[0].precip_mm_h is None and n.rate_limit is None
    )


def test_key_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NIMBO_API_KEY", "nimbo_env")
    assert Nimbo().api_key == "nimbo_env"


def test_missing_key_raises_before_any_request() -> None:
    with pytest.raises(NimboError) as e:
        Nimbo().nowcast(1, 2)
    assert e.value.code == "api_key_required"


@respx.mock
def test_public_endpoints_send_no_key() -> None:
    route = respx.get(f"{BASE}/v1/status").mock(
        return_value=httpx.Response(
            200,
            json={
                "time": "2026-11-16T23:07:51.149341+00:00",
                "status": "ok",
                "sources": {
                    "opera_dbzh": {
                        "status": "ok",
                        "last_nominal_time": "2026-11-16T23:00:00+00:00",
                        "age_s": 471,
                    }
                },
            },
        )
    )
    respx.get(f"{BASE}/v1/palettes").mock(
        return_value=httpx.Response(
            200,
            json={
                "levels": 63,
                "rate_min": 0.1,
                "rate_max": 100.0,
                "nodata": 255,
                "palettes": {"default": [[0, 0, 0, 0]]},
            },
        )
    )
    nimbo = Nimbo()  # no key needed
    s = nimbo.status()
    assert s.status == "ok" and s.sources["opera_dbzh"].age_s == 471
    assert "x-api-key" not in route.calls.last.request.headers
    assert nimbo.palettes().levels == 63


@respx.mock
def test_tiles_index_and_urls() -> None:
    respx.get(f"{BASE}/v1/tiles/index").mock(
        return_value=httpx.Response(
            200,
            json={
                "generated": "x",
                "issue_time": "2026-11-12T17:10:00Z",
                "data_age_s": 300,
                "stale": False,
                "notice": None,
                "layers": {"rain": "rain rate"},
                "palettes": ["default"],
                "past": [],
                "forecast": [
                    {
                        "time": "2026-11-12T17:15:00Z",
                        "offset_min": 5,
                        "tiles": {
                            "rain": f"{BASE}/tiles/rain/20261112T1710/20261112T1715/{{z}}/{{x}}/{{y}}.webp"
                        },
                    }
                ],
                "latest": f"{BASE}/tiles/{{layer}}/latest/{{offset_min}}/{{z}}/{{x}}/{{y}}.webp",
                "grid": "EUROPE_2K",
                "attribution": ["a"],
            },
            headers=RL_HEADERS,
        )
    )
    nimbo = Nimbo(KEY)
    idx = nimbo.tiles_index()
    assert idx.forecast[0].url(5, 16, 11, api_key=KEY, palette="default") == (
        f"{BASE}/tiles/rain/20261112T1710/20261112T1715/5/16/11.webp?key={KEY}&palette=default"
    )
    assert nimbo.tile_url(5, 16, 11, offset_min=30) == f"{BASE}/tiles/rain/latest/30/5/16/11.webp?key={KEY}"


@respx.mock
def test_key_usage() -> None:
    respx.get(f"{BASE}/v1/keys/me").mock(
        return_value=httpx.Response(
            200,
            json={
                "key_prefix": "nimbo_ab",
                "plan": "free",
                "monthly_quota": 20000,
                "created": "2026-11-13",
                "used_this_month": 5,
                "resets": 1764547200,
            },
        )
    )
    assert Nimbo(KEY).key_usage().monthly_quota == 20000


@pytest.mark.parametrize(
    ("status", "code", "cls"),
    [
        (401, "invalid_api_key", AuthenticationError),
        (404, "out_of_coverage", OutOfCoverageError),
        (422, "invalid_parameter", InvalidParameterError),
        (429, "monthly_quota_exceeded", QuotaExceededError),
        (503, "forecast_unavailable", ServiceUnavailableError),
    ],
)
@respx.mock
def test_errors_are_typed_and_not_retried(status: int, code: str, cls: type[NimboError]) -> None:
    route = respx.get(f"{BASE}/v1/nowcast").mock(
        return_value=httpx.Response(
            status,
            json={"error": code, "message": "m", "parameters": [{"name": "lat", "problem": "p"}]},
            headers={"Retry-After": "1209600"},
        )
    )
    with pytest.raises(cls) as e:
        Nimbo(KEY).nowcast(0, 0)
    assert e.value.code == code and e.value.status == status and e.value.message == "m"
    assert route.call_count == 1
    if cls is InvalidParameterError:
        assert e.value.parameters == [{"name": "lat", "problem": "p"}]  # type: ignore[attr-defined]
    if cls is QuotaExceededError:
        assert e.value.retry_after == 1209600


@respx.mock
def test_429_retried_after_retry_after(no_sleep: list[float]) -> None:
    route = respx.get(f"{BASE}/v1/tiles/index").mock(
        side_effect=[
            httpx.Response(
                429, json={"error": "tile_rate_limited", "message": "slow"}, headers={"Retry-After": "2"}
            ),
            httpx.Response(
                429, json={"error": "tile_rate_limited", "message": "slow"}, headers={"Retry-After": "3"}
            ),
            httpx.Response(
                429, json={"error": "tile_rate_limited", "message": "slow"}, headers={"Retry-After": "1"}
            ),
        ]
    )
    with pytest.raises(RateLimitError) as e:
        Nimbo(KEY, max_retries=2).tiles_index()
    assert route.call_count == 3 and no_sleep == [2.0, 3.0] and e.value.retry_after == 1


@respx.mock
def test_retry_after_longer_than_cap_is_not_waited(no_sleep: list[float]) -> None:
    route = respx.get(f"{BASE}/v1/nowcast").mock(
        return_value=httpx.Response(
            429, json={"error": "rate_limited", "message": "x"}, headers={"Retry-After": "120"}
        )
    )
    with pytest.raises(RateLimitError):
        Nimbo(KEY, max_retry_wait=30).nowcast(0, 0)
    assert route.call_count == 1 and no_sleep == []


@respx.mock
def test_5xx_and_network_errors_retried_with_backoff(no_sleep: list[float]) -> None:
    route = respx.get(f"{BASE}/v1/nowcast").mock(
        side_effect=[
            httpx.ConnectError("boom"),
            httpx.Response(502, text="bad gateway"),
            httpx.Response(200, json=NOWCAST),
        ]
    )
    assert Nimbo(KEY).nowcast(0, 0).grid == "EUROPE_2K"
    assert (
        route.call_count == 3
        and len(no_sleep) == 2
        and 0.3 <= no_sleep[0] <= 0.7
        and 0.7 <= no_sleep[1] <= 1.3
    )


@respx.mock
def test_retries_exhausted() -> None:
    respx.get(f"{BASE}/v1/nowcast").mock(side_effect=httpx.ConnectTimeout("slow"))
    with pytest.raises(NimboConnectionError):
        Nimbo(KEY, max_retries=1).nowcast(0, 0)
    respx.get(f"{BASE}/v1/status").mock(return_value=httpx.Response(500, text="oops"))
    with pytest.raises(ServerError) as e:
        Nimbo(max_retries=0).status()
    assert e.value.status == 500 and e.value.code is None


@respx.mock
async def test_async_client_retries_and_parses() -> None:
    waits: list[float] = []

    async def sleep(s: float) -> None:
        waits.append(s)

    route = respx.get(f"{BASE}/v1/nowcast").mock(
        side_effect=[
            httpx.Response(
                429, json={"error": "tile_rate_limited", "message": "x"}, headers={"Retry-After": "1"}
            ),
            httpx.Response(200, json=NOWCAST, headers=RL_HEADERS),
        ]
    )
    async with AsyncNimbo(KEY, sleep=sleep) as nimbo:
        n = await nimbo.nowcast(52.37, 4.9, step=1)
    assert n.summary is not None and n.summary.text.startswith("Light rain")
    assert route.call_count == 2 and waits == [1.0]
    assert route.calls.last.request.headers["x-api-key"] == KEY


@respx.mock
async def test_async_error() -> None:
    respx.get(f"{BASE}/v1/keys/me").mock(
        return_value=httpx.Response(
            401, json={"error": "api_key_required", "message": "An API key is required"}
        )
    )
    async with AsyncNimbo("nimbo_x") as nimbo:
        with pytest.raises(AuthenticationError):
            await nimbo.key_usage()
