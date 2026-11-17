"""Opt-in smoke test against the real API: NIMBO_LIVE_KEY=nimbo_... pytest tests/test_live.py

NIMBO_LIVE_BASE_URL points it at another server. Uses 1 counted call (the nowcast); the rest is not counted."""

from __future__ import annotations

import os

import httpx
import pytest

from nimbo_weather import DEFAULT_BASE_URL, AuthenticationError, Nimbo

KEY = os.environ.get("NIMBO_LIVE_KEY")
BASE = os.environ.get("NIMBO_LIVE_BASE_URL", DEFAULT_BASE_URL)
LAT, LON = (float(v) for v in os.environ.get("NIMBO_LIVE_POINT", "52.37,4.90").split(","))

pytestmark = pytest.mark.skipif(not KEY, reason="set NIMBO_LIVE_KEY to run the live smoke test")


def test_live_smoke() -> None:
    with Nimbo(KEY, base_url=BASE) as nimbo:
        assert nimbo.status().status in ("ok", "degraded", "stale")
        assert nimbo.palettes().levels > 0
        usage = nimbo.key_usage()
        assert usage.monthly_quota > 0
        n = nimbo.nowcast(LAT, LON, horizon=60)
        assert n.minutely and n.attribution and n.coverage in ("radar", "no_radar")
        assert n.rate_limit is not None
        if n.has_radar:
            assert n.summary is not None and n.summary.text
        idx = nimbo.tiles_index()
        assert idx.forecast and "rain" in idx.forecast[0].tiles
        alias = httpx.get(nimbo.tile_url(6, 30, 24, offset_min=idx.forecast[0].offset_min))
        assert alias.status_code == 302
        tile = httpx.get(idx.forecast[0].url(6, 30, 24, api_key=KEY or ""))
        assert tile.status_code in (200, 204)
    with Nimbo("nimbo_not_a_real_key", base_url=BASE) as bad, pytest.raises(AuthenticationError):
        bad.key_usage()
