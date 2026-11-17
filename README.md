# nimbo-weather

Python client for the [Nimbo Weather](https://nimboweather.com) rain nowcast API: minute-by-minute rain for the next
3 hours anywhere in the European radar coverage, at 2 km.

- Sync and asyncio clients, typed (`py.typed`), one dependency (`httpx`)
- Typed exceptions for every API error code
- Retries on rate limits and server errors, honouring `Retry-After`
- Map tile URL helpers

## Install

```sh
pip install nimbo-weather
```

## Quickstart

Get a free key (no card) at [nimboweather.com](https://nimboweather.com), then:

```python
from nimbo_weather import Nimbo

nimbo = Nimbo("nimbo_...")  # or set NIMBO_API_KEY and call Nimbo()
forecast = nimbo.nowcast(52.37, 4.90)  # Amsterdam

if forecast.summary:
    print(forecast.summary.text)  # "Light rain starting in 25 min, for about 40 min"
for step in forecast.minutely[:6]:
    print(step.time, step.precip_mm_h, step.precip_probability)
print(forecast.attribution)  # show this with the data (Free plan)
```

Async:

```python
from nimbo_weather import AsyncNimbo

async with AsyncNimbo() as nimbo:
    forecast = await nimbo.nowcast(48.86, 2.35, horizon=60, step=1)
```

## Methods

| Method | Endpoint | Key |
|---|---|---|
| `nowcast(lat, lon, horizon=None, step=None)` | `/v1/nowcast` | yes |
| `tiles_index()` | `/v1/tiles/index` | yes |
| `key_usage()` | `/v1/keys/me` (not counted) | yes |
| `status()` | `/v1/status` | no |
| `palettes()` | `/v1/palettes` | no |
| `tile_url(z, x, y, offset_min=5, layer="rain", palette=None)` | builds a tile URL | in the URL |

`horizon` is 5 to 180 minutes (default 180), `step` is 1, 5, 10 or 15 minutes (default 5).
Answers are dataclasses; the full JSON is in `.raw`. `Nowcast.rate_limit` carries your monthly allowance.

## Things to check in every answer

- `coverage == "no_radar"`: the point is in the forecast area but no radar sees it. `summary` and every value are `None`.
- `stale`: the forecast is late (more than 25 min old). `notice` explains an outage.
- `attribution`: on the Free plan, show it with the data ("Rain forecast: Nimbo Weather" and its link). Optional on
  paid plans. `data_credits` links to the credits of the data the forecast is made from.

## Errors

All errors derive from `NimboError` (`.status`, `.code`, `.message`, `.body`, `.retry_after`).

| Exception | When |
|---|---|
| `AuthenticationError` | 401: missing, invalid or revoked key |
| `OutOfCoverageError` | 404 `out_of_coverage`: outside the forecast area, do not retry |
| `NotFoundError` | 404: unknown layer, palette, tile or time |
| `InvalidParameterError` | 422: see `.parameters` |
| `QuotaExceededError` | 429 `monthly_quota_exceeded`: wait for the reset or upgrade |
| `RateLimitError` | 429: too many requests at once |
| `ServiceUnavailableError` | 503: no recent forecast, retry in about 10 minutes |
| `ServerError` | other 5xx |
| `NimboConnectionError` | network error or timeout |

Rate limits (429) and server errors are retried `max_retries` times (default 2) with exponential backoff, waiting
`Retry-After` when the API sends it and it is at most `max_retry_wait` seconds (default 30). The monthly quota and
503 `forecast_unavailable` are not retried.

## Map tiles

Tiles take the key in the query string only, so a tile URL contains your key. Build them on your server or in an app
you control; do not put your key in a public web page.

```python
index = nimbo.tiles_index()
for frame in index.forecast:
    print(frame.offset_min, frame.url(6, 33, 21, api_key=nimbo.api_key))
```

## Links

- API docs: https://nimboweather.com/api
- OpenAPI: https://nimboweather.com/openapi.json
- Questions: hello@nimboweather.com

MIT licence.
