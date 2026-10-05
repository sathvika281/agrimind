"""Compare the legacy pipeline with the agentic one on the SAME input. Development tool; never writes anywhere.

    python -m app.agentic_compare                          # the built-in scenarios, configured AI provider
    python -m app.agentic_compare --crop Tomato --symptoms "brown spots on lower leaves" --history 4

Everything runs on a throw-away in-memory database with a synthetic farm: the real database is never opened.
With AI_PROVIDER=demo the answers are keyword-level (shape check only); use AI_PROVIDER=gemini for real quality.
"""
import argparse
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from .database import Base
from .models import Analysis, Farm, User
from .services import ai
from .services.agentic import agentic_analyze_check
from .services.agents.toolbox import AgentToolbox
from .services.ai.base import HistoryItem, WeatherContext

SCENARIOS = [
    ("A clear symptoms", "Tomato", "brown spots on the lower leaves with rings", 0, True),
    ("B vague question", "Tomato", "my crop is not good", 0, True),
    ("C recurring problem", "Tomato", "brown spots on the leaves again", 5, True),
    ("D new problem, no history", "Chilli", "leaves curling upward and small insects underneath", 0, False),
]


def _world():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    db = sessionmaker(bind=eng, expire_on_commit=False)()
    u = User(email="compare@example.invalid", password_hash="x")
    db.add(u)
    db.flush()
    f = Farm(user_id=u.id, name="Compare farm", location="Guntur", soil_type="Red soil", primary_crop="Tomato")
    db.add(f)
    db.commit()
    return db, u, f


def _history(db, u, f, crop: str, n: int) -> list[HistoryItem]:
    for i in range(n):
        r = {"likely_issue": "Possible fungal or bacterial leaf spot", "explanation": "x", "recommended_actions": ["a"], "precautions": ["p"],
             "uncertainty": "u", "severity": "medium", "uncertainty_level": "some", "image_quality": "good"}
        db.add(Analysis(user_id=u.id, farm_id=f.id, crop=crop, symptoms="spots", language="en", input_type="text", result_json=r,
                        created_at=datetime.now(timezone.utc) - timedelta(days=3 + 4 * i)))
    db.commit()
    return [HistoryItem(date="", crop=crop, likely_issue="Possible fungal or bacterial leaf spot", severity="medium")] * min(n, 3)


def _summary(r) -> dict:
    return {
        "likely_issue": r.likely_issue, "verdict": r.verdict[:90], "uncertainty_level": r.uncertainty_level, "severity": r.severity,
        "evidence_for": len(r.evidence_for), "evidence_against": len(r.evidence_against), "unknowns": len(r.unknowns),
        "asks_a_question": bool(r.quick_questions), "sources": len(r.sources),
        "agents": [f"{s.agent}:{s.status}" + (f"({s.note})" if s.note else "") for s in r.agent_steps],
    }


def compare(name: str, crop: str, symptoms: str, history: int, weather: bool) -> dict:
    db, u, f = _world()
    hist = _history(db, u, f, crop, history)
    wx = WeatherContext(location_name="Guntur", humidity_pct=88, temp_max_c=31, past_3d_rain_mm=14, next_3d_rain_mm=9) if weather else None

    def ctx():
        return ai.AnalysisContext(crop=crop, symptoms=symptoms, farm_location=f.location, soil_type=f.soil_type, weather=wx, history=list(hist))

    out: dict = {"scenario": name, "input": {"crop": crop, "symptoms": symptoms, "history_checks": history, "weather": bool(wx)}}
    try:
        out["legacy"] = _summary(ai.analyze(ctx()))
    except ai.AIServiceError as e:
        out["legacy"] = {"error": str(e)}
    c = ctx()
    try:
        out["agentic"] = _summary(agentic_analyze_check(c, AgentToolbox(db, u, f, c), farm_id=f.id))
    except ai.AIServiceError as e:
        out["agentic"] = {"error": str(e)}
    db.close()
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.agentic_compare", description=__doc__.split("\n")[0])
    ap.add_argument("--crop")
    ap.add_argument("--symptoms")
    ap.add_argument("--history", type=int, default=0, help="number of earlier checks with the same issue to seed")
    ap.add_argument("--no-weather", action="store_true")
    args = ap.parse_args(argv)
    cases = [("custom", args.crop, args.symptoms or "", args.history, not args.no_weather)] if args.crop else SCENARIOS
    print(json.dumps([compare(*c) for c in cases], indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
