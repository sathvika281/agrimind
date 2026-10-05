import re
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _clean_email(v: str) -> str:
    v = v.strip().lower()
    if len(v) > 255 or not _EMAIL.match(v):
        raise ValueError("Please enter a valid email address.")
    return v


# ---------- auth ----------
class LoginRequest(BaseModel):
    email: str
    password: str = Field(max_length=200)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return _clean_email(v)


class RegisterRequest(LoginRequest):
    @field_validator("password")
    @classmethod
    def _pw(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters.")
        if len(v.encode()) > 72:
            raise ValueError("Password is too long (max 72 bytes).")
        return v


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    created_at: datetime


# ---------- farms ----------
IrrigationMethod = Literal["rainfed", "drip", "sprinkler", "flood", "other"]
Season = Literal["kharif", "rabi", "summer"]
EARLIEST_PLANTING = date(2000, 1, 1)


def _opt_text(v):
    """Optional text: trimmed; empty means 'not provided' (None)."""
    if v is None:
        return None
    v = v.strip() if isinstance(v, str) else v
    return v or None


def _check_planting(v: date | None) -> date | None:
    if v is None:
        return None
    if v < EARLIEST_PLANTING:
        raise ValueError("Planting date is too far in the past.")
    if v > datetime.now(timezone.utc).date() + timedelta(days=1):  # one day of timezone tolerance
        raise ValueError("Planting date cannot be in the future.")
    return v


class _FarmContext(BaseModel):
    """Optional farmer-provided context. Whatever is left out stays 'not provided'; nothing is inferred."""

    primary_crop: str | None = Field(default=None, max_length=100)
    irrigation_method: IrrigationMethod | None = None
    season: Season | None = None
    planting_date: date | None = None
    notes: str | None = Field(default=None, max_length=500)

    @field_validator("primary_crop", "notes", "irrigation_method", "season", mode="before")
    @classmethod
    def _text(cls, v):
        return _opt_text(v)

    @field_validator("planting_date", mode="before")
    @classmethod
    def _blank_date(cls, v):
        return None if isinstance(v, str) and not v.strip() else v

    @field_validator("planting_date")
    @classmethod
    def _planting(cls, v):
        return _check_planting(v)


class FarmCreate(_FarmContext):
    name: str = Field(max_length=120)
    location: str = Field(default="", max_length=200)
    soil_type: str = Field(default="", max_length=100)

    @field_validator("name", "location", "soil_type")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @field_validator("name")
    @classmethod
    def _name_required(cls, v: str) -> str:
        if not v:
            raise ValueError("Farm name is required.")
        return v


class FarmUpdate(_FarmContext):
    """PATCH body: a field that is OMITTED is left unchanged; null or empty CLEARS an optional one."""

    name: str | None = Field(default=None, max_length=120)
    location: str | None = Field(default=None, max_length=200)
    soil_type: str | None = Field(default=None, max_length=100)

    @field_validator("name", "location", "soil_type")
    @classmethod
    def _strip(cls, v):
        return v.strip() if isinstance(v, str) else v

    @field_validator("name")
    @classmethod
    def _name_required(cls, v):
        if not v:  # None or blank: a farm always keeps a name
            raise ValueError("Farm name is required.")
        return v


class FarmOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    location: str
    soil_type: str
    created_at: datetime
    primary_crop: str | None = None
    irrigation_method: str | None = None
    season: str | None = None
    planting_date: date | None = None
    notes: str | None = None
    context_updated_at: datetime | None = None

    @field_validator("created_at", "context_updated_at")
    @classmethod
    def _utc(cls, v):
        """SQLite hands back naive datetimes; everything stored is UTC, so every read says so explicitly."""
        return v.replace(tzinfo=timezone.utc) if v is not None and v.tzinfo is None else v


# ---------- analyses ----------
Severity = Literal["low", "medium", "high", "unknown"]
UncertaintyLevel = Literal["low", "some", "high", "unknown"]
ImageQuality = Literal["good", "limited", "poor", "not_provided"]

MAX_ALTERNATIVES = 3
MAX_EVIDENCE = 5
MAX_UNKNOWNS = 5
MAX_QUESTIONS = 4


class Alternative(BaseModel):
    """Another reasonable explanation, never a confirmed diagnosis."""

    possibility: str
    how_to_tell: str = ""

    @field_validator("possibility", "how_to_tell", mode="before")
    @classmethod
    def _text(cls, v):
        return "" if v is None else str(v).strip()


def _opt_list(v):
    """Optional list fields: None -> []; anything else must already be a list."""
    return [] if v is None else v


def _clean_strs(v: list[str]) -> list[str]:
    return [s.strip() for s in v if isinstance(s, str) and s.strip()]


MAX_QUICK_QUESTIONS = 3
MIN_OPTIONS, MAX_OPTIONS = 2, 4
ChangeStatus = Literal["better", "same", "worse", "unclear"]


class QuickQuestion(BaseModel):
    """A short multiple-choice question whose answer helps separate the leading possibilities."""

    question: str
    options: list[str]

    @field_validator("question", mode="before")
    @classmethod
    def _q(cls, v):
        return "" if v is None else str(v).strip()[:200]

    @field_validator("options", mode="before")
    @classmethod
    def _opts(cls, v):
        seen, out = set(), []
        for o in _opt_list(v):
            o = str(o).strip()[:60] if o is not None else ""
            if o and o.lower() not in seen:
                seen.add(o.lower())
                out.append(o)
        return out[:MAX_OPTIONS]


class Change(BaseModel):
    """Follow-up checks only: how this check compares with the earlier one. 'unclear' is always allowed."""

    status: ChangeStatus = "unclear"
    note: str = ""

    @field_validator("status", mode="before")
    @classmethod
    def _status(cls, v):
        v = str(v).strip().lower() if v is not None else "unclear"
        return v if v in ("better", "same", "worse") else "unclear"

    @field_validator("note", mode="before")
    @classmethod
    def _note(cls, v):
        return "" if v is None else str(v).strip()[:300]


class SourceRef(BaseModel):
    """A trusted document actually retrieved for this check (never written by the model)."""

    title: str
    institution: str
    url: str
    excerpt: str = ""


class AgentStepOut(BaseModel):
    """Audit trail of the agentic investigation: which step ran and how it ended. No reasoning text."""

    agent: str
    status: str
    note: str = ""


class Fact(BaseModel):
    """One language-neutral fact. The frontend turns `kind` (+count/detail) into a sentence; nothing here is prose."""

    kind: str
    count: int | None = None
    detail: str = ""
    used: bool | None = None  # only for 'evidence': was this input really used in the investigation?


class HypothesisOut(BaseModel):
    """A possible explanation (never a diagnosis). No scores: only coded support and gaps."""

    label: str
    rank: str  # better_supported | also_possible
    supporting: list[Fact] = Field(default_factory=list)
    against_or_unknown: list[Fact] = Field(default_factory=list)
    how_to_tell: str = ""


class Dossier(BaseModel):
    """What the investigation actually looked at and why. Built from the agents' real outputs, no model call."""

    evidence: list[Fact] = Field(default_factory=list)
    why: list[Fact] = Field(default_factory=list)
    unknown: list[Fact] = Field(default_factory=list)
    verify: list[Fact] = Field(default_factory=list)
    hypotheses: list[HypothesisOut] = Field(default_factory=list)


class AnalysisResult(BaseModel):
    """Validated structured AI output. Provider-independent response data.

    Phase 1 contract: likely_issue, explanation, recommended_actions, precautions, uncertainty.
    Everything after that is optional/defaulted so Phase 1 and Phase 2 stored results still validate.
    """

    likely_issue: str
    explanation: str
    recommended_actions: list[str]
    precautions: list[str]
    uncertainty: str
    severity: Severity = "unknown"
    observations: list[str] = Field(default_factory=list)
    when_to_seek_help: str = ""

    # Phase 3 reasoning fields
    possible_alternatives: list[Alternative] = Field(default_factory=list)
    evidence_for: list[str] = Field(default_factory=list)
    evidence_against: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    immediate_actions: list[str] = Field(default_factory=list)
    monitoring_steps: list[str] = Field(default_factory=list)
    follow_up_questions: list[str] = Field(default_factory=list)
    uncertainty_level: UncertaintyLevel = "unknown"
    image_quality: ImageQuality = "not_provided"
    image_guidance: str = ""

    # Phase 13 clarity fields (optional: every older stored result still validates)
    verdict: str = ""
    quick_questions: list[QuickQuestion] = Field(default_factory=list)
    change: Change | None = None

    # Agentic investigation (optional: absent on every legacy result)
    sources: list[SourceRef] = Field(default_factory=list)
    agent_steps: list[AgentStepOut] = Field(default_factory=list)
    dossier: Dossier | None = None

    @field_validator("dossier", mode="before")
    @classmethod
    def _dossier(cls, v):
        return v if isinstance(v, dict) else None

    @field_validator("sources", "agent_steps", mode="before")
    @classmethod
    def _lists(cls, v):
        return [x for x in _opt_list(v) if isinstance(x, dict)]

    @field_validator("verdict", mode="before")
    @classmethod
    def _verdict(cls, v):
        return "" if v is None else str(v).strip()[:300]

    @field_validator("quick_questions", mode="before")
    @classmethod
    def _qq_before(cls, v):
        return [x for x in _opt_list(v) if isinstance(x, dict)]

    @field_validator("quick_questions")
    @classmethod
    def _qq(cls, v: list[QuickQuestion]) -> list[QuickQuestion]:
        # a question is only useful with a real choice: keep those with a text and 2-4 distinct options
        return [q for q in v if q.question and len(q.options) >= MIN_OPTIONS][:MAX_QUICK_QUESTIONS]

    @field_validator("change", mode="before")
    @classmethod
    def _change(cls, v):
        return v if isinstance(v, dict) else None

    @field_validator("likely_issue", "explanation", "uncertainty")
    @classmethod
    def _nonempty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be empty")
        return v

    @field_validator(
        "observations", "evidence_for", "evidence_against", "unknowns",
        "immediate_actions", "monitoring_steps", "follow_up_questions", "possible_alternatives",
        mode="before",
    )
    @classmethod
    def _none_to_empty(cls, v):
        return _opt_list(v)

    @field_validator("possible_alternatives", mode="before")
    @classmethod
    def _alts(cls, v):
        out = []
        for item in _opt_list(v):
            out.append({"possibility": item} if isinstance(item, str) else item)
        return out

    @field_validator("possible_alternatives")
    @classmethod
    def _alts_trim(cls, v: list[Alternative]) -> list[Alternative]:
        return [a for a in v if a.possibility][:MAX_ALTERNATIVES]

    @field_validator("recommended_actions", "precautions", "observations", "immediate_actions", "monitoring_steps")
    @classmethod
    def _items(cls, v: list[str]) -> list[str]:
        return _clean_strs(v)

    @field_validator("evidence_for", "evidence_against")
    @classmethod
    def _evidence(cls, v: list[str]) -> list[str]:
        return _clean_strs(v)[:MAX_EVIDENCE]

    @field_validator("unknowns")
    @classmethod
    def _unknowns(cls, v: list[str]) -> list[str]:
        return _clean_strs(v)[:MAX_UNKNOWNS]

    @field_validator("follow_up_questions")
    @classmethod
    def _questions(cls, v: list[str]) -> list[str]:
        return _clean_strs(v)[:MAX_QUESTIONS]

    @field_validator("severity", mode="before")
    @classmethod
    def _severity(cls, v):
        v = str(v).strip().lower() if v is not None else "unknown"
        return v if v in ("low", "medium", "high") else "unknown"

    @field_validator("uncertainty_level", mode="before")
    @classmethod
    def _ulevel(cls, v):
        v = str(v).strip().lower() if v is not None else "unknown"
        return v if v in ("low", "some", "high") else "unknown"

    @field_validator("image_quality", mode="before")
    @classmethod
    def _iq(cls, v):
        v = str(v).strip().lower() if v is not None else "not_provided"
        return v if v in ("good", "limited", "poor") else "not_provided"

    @field_validator("when_to_seek_help", "image_guidance", mode="before")
    @classmethod
    def _opt_text(cls, v):
        return "" if v is None else str(v).strip()


class AnalysisCreate(BaseModel):
    """Request body. Symptoms may be empty only when an image is attached (checked in the router)."""

    farm_id: int
    crop: str = Field(max_length=100)
    symptoms: str = Field(default="", max_length=4000)
    # Language the farmer wants the analysis written in. Optional so older clients keep working (English).
    language: Literal["en", "te"] = "en"
    # Set when this check is a FOLLOW-UP of one of the farmer's earlier checks on the same farm.
    follow_up_of: int | None = None

    @field_validator("language", mode="before")
    @classmethod
    def _language(cls, v):
        return "en" if v is None or str(v).strip() == "" else str(v).strip().lower()

    @field_validator("follow_up_of", mode="before")
    @classmethod
    def _follow_up(cls, v):
        return None if v is None or str(v).strip() == "" else v

    @field_validator("crop")
    @classmethod
    def _crop(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Please enter the crop.")
        return v

    @field_validator("symptoms")
    @classmethod
    def _symptoms(cls, v: str) -> str:
        return v.strip()


class WeatherOut(BaseModel):
    location_name: str
    temperature_c: float | None = None
    humidity_pct: float | None = None
    precipitation_mm: float | None = None
    wind_kmh: float | None = None
    temp_min_c: float | None = None
    temp_max_c: float | None = None
    past_3d_rain_mm: float | None = None
    next_3d_rain_mm: float | None = None
    trend: str = ""
    fetched_at: str = ""


class FarmWeatherOut(BaseModel):
    """Current weather context for a farm's saved location, or why it is unavailable."""

    weather: WeatherOut | None = None
    note: str | None = None
    risks: list["WeatherRiskOut"] = Field(default_factory=list)  # deterministic hints from the real numbers; [] if unavailable


class WeatherConditionOut(BaseModel):
    kind: str
    value: float


class WeatherTipOut(BaseModel):
    kind: str
    group: str  # protect | water | watch


class WeatherTipsOut(BaseModel):
    """Coded, non-chemical coping tips for the weather forecast for a farm (Weather tab only)."""

    conditions: list[WeatherConditionOut] = Field(default_factory=list)
    tips: list[WeatherTipOut] = Field(default_factory=list)


class WeatherRiskOut(BaseModel):
    kind: Literal["extreme_heat", "heavy_rain", "humid_wet", "hot_dry"]
    action: Literal["check_heat_stress", "check_drainage", "check_leaves", "check_soil_moisture"]
    humidity_pct: float | None = None
    rain_mm: float | None = None
    temp_max_c: float | None = None


FarmWeatherOut.model_rebuild()


class TranslateRequest(BaseModel):
    language: Literal["en", "te"]


class AnalysisOut(BaseModel):
    id: int
    farm_id: int
    farm_name: str
    crop: str
    symptoms: str
    language: str
    input_type: str = "text"
    has_image: bool = False
    result: AnalysisResult
    weather: WeatherOut | None = None
    weather_note: str | None = None
    # Other-language versions of this same check (see POST /analyses/{id}/translate); {} when none exist.
    translations: dict[str, AnalysisResult] = Field(default_factory=dict)
    created_at: datetime
    # Set when this check refines or follows up an earlier one (see /analyses/{id}/refine and the follow-up form).
    parent_id: int | None = None
    link_kind: Literal["refine", "followup"] | None = None


class AnswerPair(BaseModel):
    question: str = Field(max_length=300)
    answer: str = Field(max_length=80)


class RefineRequest(BaseModel):
    """The farmer's taps on the quick questions. Each pair must be exactly one the stored check offered."""

    answers: list[AnswerPair] = Field(min_length=1, max_length=MAX_QUICK_QUESTIONS)
    language: Literal["en", "te"] | None = None


# ---------- farm insights (derived only from stored checks; see services/insights.py) ----------
class EvidenceOut(BaseModel):
    analysis_id: int
    at: datetime


class CheckBriefOut(EvidenceOut):
    crop: str
    issue: str
    severity: Severity


class IssueGroupOut(BaseModel):
    label: str
    count: int
    last_seen: datetime
    evidence: list[EvidenceOut]


class TrendOut(BaseModel):
    kind: Literal["recurring", "more_frequent", "less_frequent", "repeated_high", "stable"]
    issue: str
    count: int
    window: int
    earlier_count: int | None = None
    severity: Severity | None = None
    evidence: list[EvidenceOut]


class ComparisonOut(BaseModel):
    previous: CheckBriefOut
    latest: CheckBriefOut
    same_issue: bool
    comparable: bool
    same_crop: bool
    severity_changed: bool


class InsightsOut(BaseModel):
    farm_id: int
    level: Literal["none", "one", "limited", "enough"]
    total: int
    first_at: datetime | None
    last_at: datetime | None
    latest: CheckBriefOut | None
    severity_counts: dict[str, int]
    unclear_count: int
    issues: list[IssueGroupOut]
    recent: list[CheckBriefOut]
    trends: list[TrendOut]
    comparison: ComparisonOut | None


# ---------- decision support (rule-based, read-only; see services/decision_support.py) ----------
Action = Literal["inspect_plants", "compare_plants", "check_spread", "record_clearer_photo", "recheck_if_changes", "consult_expert", "add_detail"]
Limitation = Literal["no_treatment", "severity_not_recorded", "history_insufficient", "no_farm_context", "context_not_causal"]


class DecisionEvidenceOut(BaseModel):
    kind: Literal["this_check", "severity", "history_same_issue", "history_insufficient", "history_isolated", "trend"]
    value: str | None = None
    count: int | None = None
    window: int | None = None
    dates: list[EvidenceOut] = Field(default_factory=list)


class DecisionObservedOut(BaseModel):
    crop: str
    issue: str
    unclear: bool
    severity: Severity
    uncertainty: str
    image_quality: str
    input_type: str
    checked_at: datetime


class ContextItemOut(BaseModel):
    field: Literal["primary_crop", "irrigation_method", "season", "planting_date", "soil_type", "location"]
    value: str


class DecisionOut(BaseModel):
    farm_id: int
    analysis_id: int | None
    state: Literal["no_actionable_evidence", "seek_expert_help", "verify", "monitor"]
    level: Literal["none", "one", "limited", "enough"]
    history_total: int
    observed: DecisionObservedOut | None
    evidence: list[DecisionEvidenceOut]
    actions: list[Action]
    limitations: list[Limitation]
    expert_reason: Literal["severity_high", "repeated_high", "recurring", "more_frequent"] | None
    context: list[ContextItemOut]


# ---------- proactive intelligence (read-only; see services/proactive_intelligence.py) ----------
class ProactiveReasonOut(BaseModel):
    kind: Literal["latest_high", "repeated_high", "recurring", "more_frequent", "unresolved_verify"]
    count: int | None = None
    window: int | None = None
    earlier_count: int | None = None
    dates: list[EvidenceOut] = Field(default_factory=list)


class ProactiveItemOut(BaseModel):
    priority: Literal["attention", "important"]
    issue: str
    crop: str
    reasons: list[ProactiveReasonOut]
    actions: list[Action]
    expert_suggested: bool
    evidence_count: int
    latest_at: datetime
    analysis_id: int  # navigation reference to a check the signed-in farmer owns (the Result page re-checks ownership)


class ProactiveOut(BaseModel):
    farm_id: int
    level: Literal["none", "attention", "important"]
    total_checks: int
    items: list[ProactiveItemOut] = Field(default_factory=list, max_length=3)


# ---------- farm diary (what the farmer says they did) ----------
EventKind = Literal["sowed", "irrigated", "fertilised", "sprayed", "weeded", "harvested", "other"]
EVENT_KINDS = ("sowed", "irrigated", "fertilised", "sprayed", "weeded", "harvested", "other")


class EventCreate(BaseModel):
    kind: EventKind
    event_date: date | None = None  # today when omitted
    note: str | None = Field(default=None, max_length=300)

    @field_validator("note", mode="before")
    @classmethod
    def _note(cls, v):
        return _opt_text(v)

    @field_validator("event_date", mode="before")
    @classmethod
    def _blank(cls, v):
        return None if isinstance(v, str) and not v.strip() else v

    @field_validator("event_date")
    @classmethod
    def _when(cls, v):
        return _check_planting(v) if v is not None else None  # real date, not in the future, not before 2000


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kind: str
    event_date: date
    note: str | None = None
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _utc(cls, v):
        return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v


# ---- Crop Journey / Before vs Now (read-only views over stored checks; qualitative, no scores)
class JourneyItem(BaseModel):
    type: str  # check | diary
    at: datetime
    analysis_id: int | None = None
    crop: str = ""
    issue: str = ""
    unclear: bool = False
    severity: str = "unknown"
    uncertainty_level: str = "unknown"
    link: str | None = None  # refine | followup
    kind: str | None = None  # diary entry kind
    event_id: int | None = None


class JourneyOut(BaseModel):
    farm_id: int
    planting_date: date | None = None
    days_since_planting: int | None = None
    items: list[JourneyItem] = Field(default_factory=list)
    truncated: bool = False


class CheckBrief(BaseModel):
    analysis_id: int
    at: datetime
    crop: str
    issue: str
    severity: str = "unknown"
    uncertainty_level: str = "unknown"
    link: str | None = None


class SideCompare(BaseModel):
    previous: str
    now: str
    change: str  # up | down | same | unknown


class ObsCompare(BaseModel):
    still_present: list[str] = Field(default_factory=list)
    new: list[str] = Field(default_factory=list)
    not_mentioned_now: list[str] = Field(default_factory=list)


class CompareOut(BaseModel):
    issue: str  # same | different | unclear
    severity: SideCompare
    uncertainty: SideCompare
    observations: ObsCompare
    model_change: str | None = None
    direction: str  # improving | worsening | stable | mixed | unclear


class ComparisonOut(BaseModel):
    previous: CheckBrief
    now: CheckBrief
    compare: CompareOut


# ---- Farm Patterns (counts of real stored checks; no scores, no forecasts)
class PatternFact(BaseModel):
    kind: str
    count: int
    of: int


class PatternOut(BaseModel):
    issue: str
    count: int
    window: int
    label: str  # strong | possible | limited
    recurring: bool = False
    environment: list[PatternFact] = Field(default_factory=list)
    diary: list[PatternFact] = Field(default_factory=list)


class PatternsOut(BaseModel):
    farm_id: int
    enough: bool
    total: int
    patterns: list[PatternOut] = Field(default_factory=list)
