"""Provider-agnostic AI contract.

AnalysisContext is independent of any form, language or input modality. The same
context serves text-only, image-only, text+image and weather-enhanced analyses.
Later phases can add fields (retrieved knowledge, voice transcript, conversation)
without touching the analysis API.
"""
from dataclasses import asdict, dataclass, field
from typing import Protocol


class AIServiceError(Exception):
    """Raised when the AI layer cannot produce a valid result. Message is user-safe.

    `code` is a stable machine-readable category surfaced in API error bodies."""

    def __init__(self, message: str = "", code: str = "ai_unavailable"):
        super().__init__(message)
        self.code = code


@dataclass
class ImageInput:
    data: bytes
    mime_type: str


@dataclass
class WeatherContext:
    """Server-built weather evidence. Never supplied by the client."""

    location_name: str
    temperature_c: float | None = None
    humidity_pct: float | None = None
    precipitation_mm: float | None = None  # current hour
    wind_kmh: float | None = None
    temp_min_c: float | None = None  # today
    temp_max_c: float | None = None  # today
    past_3d_rain_mm: float | None = None
    next_3d_rain_mm: float | None = None
    trend: str = ""
    fetched_at: str = ""  # UTC ISO time the data was actually fetched (may be a cached copy)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class HistoryItem:
    """A past analysis for the same farm and crop: a historical observation, NOT a verified diagnosis."""

    date: str
    crop: str
    likely_issue: str
    severity: str = "unknown"
    symptoms: str = ""


@dataclass
class DiaryItem:
    """Something the farmer SAYS they did (kind + date only; free-text notes are never sent to the model)."""

    date: str
    kind: str


@dataclass
class PreviousCheck:
    """The earlier check this one follows up (the farmer's own, same farm). Used only to judge change over time."""

    date: str
    likely_issue: str
    severity: str = "unknown"
    verdict: str = ""
    symptoms: str = ""
    image: ImageInput | None = None


@dataclass
class AnalysisContext:
    crop: str
    symptoms: str = ""
    farm_location: str = ""
    soil_type: str = ""
    language: str = "en"
    image: ImageInput | None = None
    weather: WeatherContext | None = None
    history: list[HistoryItem] = field(default_factory=list)  # small, same user/farm/crop only
    previous: PreviousCheck | None = None  # set only for a follow-up check
    diary: list[DiaryItem] = field(default_factory=list)  # farmer-reported activities, last 30 days, at most 5

    @property
    def input_type(self) -> str:
        if self.image and self.symptoms.strip():
            return "text+image"
        if self.image:
            return "image"
        return "text"


class AIProvider(Protocol):
    name: str

    def analyze(self, ctx: AnalysisContext) -> dict:
        """Return a dict matching the AnalysisResult schema (validated by the service)."""
        ...
