"""The tools the agents may use, and the ownership boundary around them.

One AgentToolbox is built per request, AFTER the farm was fetched with get_owned_farm(), and it only ever
queries with that user's id and that farm's id. The agents (and any model) cannot pass an id in, so a
foreign farm, history or diary cannot even be expressed through a tool. Authorization is therefore enforced
here in backend code, never by a prompt.

The tools wrap the existing deterministic services; no logic is duplicated.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import Analysis, Farm, User
from .. import decision_support as decision_service
from .. import insights as insights_service
from .. import proactive_intelligence as proactive_service
from ..ai.base import AnalysisContext, DiaryItem, PreviousCheck, WeatherContext

LIMIT = 100  # newest checks considered, same bound as the insights/decision routes
_CONTEXT_FIELDS = ("primary_crop", "irrigation_method", "season", "planting_date", "soil_type", "location")


class AgentToolbox:
    def __init__(self, db: Session, user: User, farm: Farm, ctx: AnalysisContext):
        self._db, self._user_id, self._farm, self._ctx = db, user.id, farm, ctx

    # ---- this farm's context -------------------------------------------------------------------
    def farm_context(self) -> dict:
        return {f: getattr(self._farm, f) for f in _CONTEXT_FIELDS}

    def diary(self) -> list[DiaryItem]:
        return list(self._ctx.diary)

    def previous_check(self) -> PreviousCheck | None:
        return self._ctx.previous

    def weather(self) -> WeatherContext | None:
        return self._ctx.weather

    # ---- this farm's stored checks (newest first; a refinement replaces the check it refined) -----
    def recent_checks(self) -> list[dict]:
        from ...routers.farms import _without_refined_parents  # lazy: routers import services

        found = self._db.execute(
            select(Analysis.id, Analysis.crop, Analysis.created_at, Analysis.input_type, Analysis.result_json,
                   Analysis.parent_id, Analysis.link_kind, Analysis.symptoms)
            .where(Analysis.user_id == self._user_id, Analysis.farm_id == self._farm.id)
            .order_by(Analysis.id.desc())
            .limit(LIMIT)
        ).all()
        rows = []
        for r in _without_refined_parents(found):
            res = r.result_json or {}
            rows.append({
                "id": r.id, "crop": r.crop, "created_at": r.created_at, "input_type": r.input_type,
                "likely_issue": res.get("likely_issue", ""), "severity": res.get("severity"),
                "uncertainty_level": res.get("uncertainty_level"), "image_quality": res.get("image_quality"),
                "symptoms": r.symptoms or "",
            })
        return rows

    # ---- the existing deterministic services, as tools -------------------------------------------
    def farm_insights(self) -> dict:
        return insights_service.build_insights(self.recent_checks())

    def decision_support(self) -> dict:
        return decision_service.decide(self.recent_checks(), self.farm_context())

    def proactive(self) -> dict:
        rows = self.recent_checks()
        return proactive_service.build_proactive_items(
            insights_service.build_insights(rows), decision_service.decide(rows, self.farm_context())
        )
