"""Python client for the Nimbo Weather rain nowcast API (https://nimboweather.com/api)."""

from nimbo_weather._client import DEFAULT_BASE_URL, AsyncNimbo, Nimbo
from nimbo_weather._version import __version__
from nimbo_weather.errors import (
    AuthenticationError,
    InvalidParameterError,
    NimboConnectionError,
    NimboError,
    NotFoundError,
    OutOfCoverageError,
    QuotaExceededError,
    RateLimitError,
    ServerError,
    ServiceUnavailableError,
)
from nimbo_weather.models import (
    KeyUsage,
    MinutelyEntry,
    Nowcast,
    ObservedNow,
    Palettes,
    RateLimit,
    SkillAtLead,
    SourceState,
    Status,
    Summary,
    TileFrame,
    TilesIndex,
)

__all__ = [
    "DEFAULT_BASE_URL",
    "AsyncNimbo",
    "AuthenticationError",
    "InvalidParameterError",
    "KeyUsage",
    "MinutelyEntry",
    "Nimbo",
    "NimboConnectionError",
    "NimboError",
    "NotFoundError",
    "Nowcast",
    "ObservedNow",
    "OutOfCoverageError",
    "Palettes",
    "QuotaExceededError",
    "RateLimit",
    "RateLimitError",
    "ServerError",
    "ServiceUnavailableError",
    "SkillAtLead",
    "SourceState",
    "Status",
    "Summary",
    "TileFrame",
    "TilesIndex",
    "__version__",
]
