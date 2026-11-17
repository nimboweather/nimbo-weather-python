"""Response models. Times are timezone-aware ``datetime`` (UTC). Every model keeps the decoded JSON in ``raw``,
so fields added to the API later are readable before this package knows them."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import urlencode


def parse_time(value: Any) -> datetime | None:
    """An ISO 8601 time from the API (``...Z`` or ``...+00:00``), or None."""
    if not isinstance(value, str) or not value:
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(text)


def _req_time(value: Any) -> datetime:
    t = parse_time(value)
    if t is None:
        raise ValueError(f"expected an ISO time, got {value!r}")
    return t


def _opt_float(value: Any) -> float | None:
    return None if value is None else float(value)


@dataclass(frozen=True)
class RateLimit:
    """The key's monthly allowance, from the ``X-RateLimit-*`` headers of a data answer."""

    limit: int
    remaining: int
    reset: int  # Unix time (s) of the monthly reset, UTC

    @classmethod
    def from_headers(cls, headers: Any) -> RateLimit | None:
        try:
            return cls(
                int(headers["x-ratelimit-limit"]),
                int(headers["x-ratelimit-remaining"]),
                int(headers["x-ratelimit-reset"]),
            )
        except (KeyError, TypeError, ValueError):
            return None


@dataclass(frozen=True)
class Summary:
    """The next hours in a sentence (``text``, in English) and a few fields. Rain means 0.2 mm/h or more."""

    text: str
    rain_now: bool | None
    rain_starts_at: datetime | None
    rain_ends_at: datetime | None  # None when the rain lasts past the horizon
    minutes_until_rain: int | None  # from the request time; 0 when it rains now
    max_intensity: str | None  # light | moderate | heavy | violent
    now_source: str | None  # radar | forecast

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Summary:
        return cls(
            text=d["text"],
            rain_now=d.get("rain_now"),
            rain_starts_at=parse_time(d.get("rain_starts_at")),
            rain_ends_at=parse_time(d.get("rain_ends_at")),
            minutes_until_rain=d.get("minutes_until_rain"),
            max_intensity=d.get("max_intensity"),
            now_source=d.get("now_source"),
        )


@dataclass(frozen=True)
class MinutelyEntry:
    """One step of the forecast. Values are None where there is no radar."""

    time: datetime
    precip_mm_h: float | None
    precip_probability: float | None  # P(rate >= 0.2 mm/h), 0-1
    precip_probability_1mm_h: float | None
    precip_probability_5mm_h: float | None
    precip_type: str = "rain"

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> MinutelyEntry:
        return cls(
            time=_req_time(d["time"]),
            precip_mm_h=_opt_float(d.get("precip_mm_h")),
            precip_probability=_opt_float(d.get("precip_probability")),
            precip_probability_1mm_h=_opt_float(d.get("precip_probability_1mm_h")),
            precip_probability_5mm_h=_opt_float(d.get("precip_probability_5mm_h")),
            precip_type=d.get("precip_type") or "rain",
        )


@dataclass(frozen=True)
class ObservedNow:
    time: datetime
    precip_mm_h: float


@dataclass(frozen=True)
class SkillAtLead:
    lead_min: int
    csi_1mmh: float


@dataclass(frozen=True)
class Nowcast:
    """The answer of ``/v1/nowcast``. Check ``coverage`` (``radar`` / ``no_radar``) and ``stale`` before use, and
    show ``attribution`` with the data."""

    lat: float
    lon: float
    issue_time: datetime
    data_age_s: int
    stale: bool
    notice: str | None
    coverage: str
    radar_source: str | None
    summary: Summary | None
    minutely: list[MinutelyEntry]
    observed_now: ObservedNow | None
    horizon_skill: list[SkillAtLead]
    grid: str
    attribution: list[str]
    raw: dict[str, Any] = field(repr=False, compare=False)
    rate_limit: RateLimit | None = field(default=None, compare=False)

    @property
    def has_radar(self) -> bool:
        return self.coverage == "radar"

    @classmethod
    def from_dict(cls, d: dict[str, Any], rate_limit: RateLimit | None = None) -> Nowcast:
        obs = d.get("observed_now")
        return cls(
            lat=float(d["lat"]),
            lon=float(d["lon"]),
            issue_time=_req_time(d["issue_time"]),
            data_age_s=int(d["data_age_s"]),
            stale=bool(d["stale"]),
            notice=d.get("notice"),
            coverage=d.get("coverage", "radar"),
            radar_source=d.get("radar_source"),
            summary=Summary.from_dict(d["summary"]) if d.get("summary") else None,
            minutely=[MinutelyEntry.from_dict(m) for m in d.get("minutely") or []],
            observed_now=ObservedNow(_req_time(obs["time"]), float(obs["precip_mm_h"])) if obs else None,
            horizon_skill=[
                SkillAtLead(int(s["lead_min"]), float(s["csi_1mmh"])) for s in d.get("horizon_skill") or []
            ],
            grid=d.get("grid", ""),
            attribution=list(d.get("attribution") or []),
            raw=d,
            rate_limit=rate_limit,
        )


@dataclass(frozen=True)
class SourceState:
    status: str  # ok | stale | missing
    last_nominal_time: datetime | None
    age_s: int | None


@dataclass(frozen=True)
class Status:
    """The answer of ``/v1/status``: ``status`` is ``ok``, ``degraded`` or ``stale``."""

    time: datetime
    status: str
    sources: dict[str, SourceState]
    raw: dict[str, Any] = field(repr=False, compare=False)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Status:
        sources = {
            name: SourceState(
                s.get("status", "missing"), parse_time(s.get("last_nominal_time")), s.get("age_s")
            )
            for name, s in (d.get("sources") or {}).items()
        }
        return cls(time=_req_time(d["time"]), status=d["status"], sources=sources, raw=d)


@dataclass(frozen=True)
class Palettes:
    """The colour tables of the rain tiles: RGBA per level, levels spaced logarithmically in rate."""

    levels: int
    rate_min: float
    rate_max: float
    nodata: int
    palettes: dict[str, list[list[int]]]
    raw: dict[str, Any] = field(repr=False, compare=False)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Palettes:
        return cls(
            levels=int(d["levels"]),
            rate_min=float(d["rate_min"]),
            rate_max=float(d["rate_max"]),
            nodata=int(d["nodata"]),
            palettes=d["palettes"],
            raw=d,
        )


@dataclass(frozen=True)
class TileFrame:
    """One forecast frame of the map: ``tiles`` maps a layer to its URL template."""

    time: datetime
    offset_min: int
    tiles: dict[str, str]

    def url(
        self, z: int, x: int, y: int, *, api_key: str, layer: str = "rain", palette: str | None = None
    ) -> str:
        """The tile URL, with the key in the query (tiles only take ``?key=``). Do not put it in a public page."""
        template = self.tiles[layer]
        return fill_template(template, z, x, y, api_key=api_key, palette=palette)


def fill_template(template: str, z: int, x: int, y: int, *, api_key: str, palette: str | None = None) -> str:
    query = {"key": api_key}
    if palette:
        query["palette"] = palette
    return (
        template.replace("{z}", str(z)).replace("{x}", str(x)).replace("{y}", str(y)) + "?" + urlencode(query)
    )


@dataclass(frozen=True)
class TilesIndex:
    """The answer of ``/v1/tiles/index``. Animate ``forecast`` frames with their immutable URLs."""

    issue_time: datetime
    data_age_s: int
    stale: bool
    notice: str | None
    tile_size: int
    min_zoom: int
    max_zoom: int
    layers: dict[str, str]
    palettes: list[str]
    forecast: list[TileFrame]
    latest: str
    grid: str
    attribution: list[str]
    raw: dict[str, Any] = field(repr=False, compare=False)
    rate_limit: RateLimit | None = field(default=None, compare=False)

    @classmethod
    def from_dict(cls, d: dict[str, Any], rate_limit: RateLimit | None = None) -> TilesIndex:
        frames = [
            TileFrame(_req_time(f["time"]), int(f["offset_min"]), dict(f["tiles"]))
            for f in d.get("forecast") or []
        ]
        return cls(
            issue_time=_req_time(d["issue_time"]),
            data_age_s=int(d["data_age_s"]),
            stale=bool(d["stale"]),
            notice=d.get("notice"),
            tile_size=int(d.get("tile_size", 256)),
            min_zoom=int(d.get("min_zoom", 0)),
            max_zoom=int(d.get("max_zoom", 8)),
            layers=dict(d.get("layers") or {}),
            palettes=list(d.get("palettes") or []),
            forecast=frames,
            latest=d.get("latest", ""),
            grid=d.get("grid", ""),
            attribution=list(d.get("attribution") or []),
            raw=d,
            rate_limit=rate_limit,
        )


@dataclass(frozen=True)
class KeyUsage:
    """The answer of ``/v1/keys/me`` (not counted against the quota)."""

    key_prefix: str
    plan: str
    monthly_quota: int
    created: str
    used_this_month: int
    resets: int  # Unix time (s)
    raw: dict[str, Any] = field(repr=False, compare=False)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> KeyUsage:
        return cls(
            key_prefix=d["key_prefix"],
            plan=d["plan"],
            monthly_quota=int(d["monthly_quota"]),
            created=str(d["created"]),
            used_this_month=int(d["used_this_month"]),
            resets=int(d["resets"]),
            raw=d,
        )
