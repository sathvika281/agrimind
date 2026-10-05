"""Agent 1: Investigation. Decides WHICH specialists this request needs and whether to ask the farmer first.

Deterministic on purpose (a pure, unit-tested function): routing and "is there enough to go on" are rules, not
reasoning that needs a model. It never reaches an agricultural conclusion; it only plans the investigation.
"""
from ...schemas import AnalysisResult
from ..ai.base import AnalysisContext
from ..ai.demo_provider import _RULES
from ..ai.demo_te import KEYWORDS_TE
from ..graph.state import Clarification, Plan

MAX_CLARIFICATIONS = 2  # the farmer is never asked more than this many times in a row

_SIGNALS = tuple(k for r in _RULES for k in r[0]) + tuple(k for ks in KEYWORDS_TE for k in ks)

_TEXT = {
    "en": {
        "too_vague": ("What changes are you seeing on the crop?",
                      ["Spots on leaves", "Yellowing", "Wilting or drooping", "Holes or insects", "Leaves curling", "Something else"]),
        "poor_image": ("The photo isn't clear enough to judge the affected part. Can you add a closer photo of an affected leaf in good light?",
                       ["I'll add a closer photo", "I can't take another photo"]),
        "issue": "Unable to pinpoint the problem from this description",
        "explanation": "There isn't enough information yet to say what is affecting the crop.",
        "uncertainty": "AgriMind needs a little more detail before it can say anything useful about this.",
        "verdict": "Not enough to tell yet. Answering the question below will help.",
        "actions": ["Walk through the field and note how many plants are affected and where (patches, edges, whole field).",
                    "Look closely at leaves (both sides), stems and roots for spots, insects, rot or discolouration.",
                    "Note any recent changes: weather, irrigation, fertiliser, sprays, or a new crop variety."],
        "help": "If the problem spreads quickly or affects a large area, contact your local agricultural officer.",
    },
    "te": {
        "too_vague": ("పంటలో మీకు ఏ మార్పులు కనిపిస్తున్నాయి?",
                      ["ఆకులపై మచ్చలు", "ఆకులు పసుపు రంగులోకి మారడం", "వాడిపోవడం లేదా వంగిపోవడం", "రంధ్రాలు లేదా పురుగులు", "ఆకులు ముడుచుకోవడం", "మరేదైనా"]),
        "poor_image": ("ప్రభావిత భాగాన్ని అంచనా వేయడానికి ఫోటో సరిపడా స్పష్టంగా లేదు. మంచి వెలుతురులో ప్రభావిత ఆకును దగ్గరగా తీసిన ఫోటో జోడించగలరా?",
                       ["దగ్గరగా ఫోటో జోడిస్తాను", "మరో ఫోటో తీయలేను"]),
        "issue": "ఈ వివరణతో సమస్యను స్పష్టంగా చెప్పలేము",
        "explanation": "పంటకు ఏమి జరుగుతోందో చెప్పడానికి ఇంకా తగినంత సమాచారం లేదు.",
        "uncertainty": "దీని గురించి ఉపయోగపడేది చెప్పడానికి AgriMindకు మరికొంత వివరం కావాలి.",
        "verdict": "ఇంకా చెప్పడానికి సరిపోదు. కింది ప్రశ్నకు సమాధానం ఇస్తే సహాయపడుతుంది.",
        "actions": ["పొలంలో తిరిగి, ఎన్ని మొక్కలు ప్రభావితమయ్యాయో, ఎక్కడ (పాచెస్, అంచులు, మొత్తం పొలం) గమనించండి.",
                    "ఆకులను (రెండు వైపులా), కాండాలు, వేర్లను మచ్చలు, పురుగులు, కుళ్ళు లేదా రంగు మార్పుల కోసం జాగ్రత్తగా చూడండి.",
                    "ఇటీవలి మార్పులను గమనించండి: వాతావరణం, నీటి తడులు లేదా కొత్త రకం."],
        "help": "సమస్య వేగంగా వ్యాపిస్తే లేదా పెద్ద విస్తీర్ణంలో ఉంటే, మీ స్థానిక వ్యవసాయ అధికారిని సంప్రదించండి.",
    },
}


def has_symptom_signal(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in _SIGNALS)


def plan(ctx: AnalysisContext, *, has_history: bool, knowledge_available: bool, clarification_round: int = 0) -> Plan:
    """Choose the specialists. A follow-up check is a continuation (it has the earlier check), so it is never
    sent back with a question; and the farmer is never asked more than MAX_CLARIFICATIONS times."""
    p = Plan()
    can_ask = ctx.previous is None and clarification_round < MAX_CLARIFICATIONS
    if ctx.image is None and not has_symptom_signal(ctx.symptoms) and can_ask:
        p.clarify = Clarification(reason="no_evidence" if not ctx.symptoms.strip() else "too_vague", question=_TEXT[_lang(ctx)]["too_vague"][0],
                                  options=_TEXT[_lang(ctx)]["too_vague"][1])
        return p
    p.nodes.append("crop_analysis")
    if has_history or ctx.previous is not None or ctx.diary:
        p.nodes.append("farm_memory")
    else:
        p.skipped["farm_memory"] = "no_history"
    if ctx.weather is not None:
        p.nodes.append("environment")
    else:
        p.skipped["environment"] = "no_weather"
    if knowledge_available:
        p.nodes.append("knowledge")
    else:
        p.skipped["knowledge"] = "no_knowledge_base"
    return p


def image_needs_replacing(ctx: AnalysisContext, image_quality: str, clarification_round: int = 0) -> Clarification | None:
    """After crop analysis: a photo too poor to use, with nothing written that helps, is a reason to ask for a better one."""
    if ctx.image is None or image_quality != "poor" or has_symptom_signal(ctx.symptoms):
        return None
    if ctx.previous is not None or clarification_round >= MAX_CLARIFICATIONS:
        return None
    q, opts = _TEXT[_lang(ctx)]["poor_image"]
    return Clarification(reason="poor_image", question=q, options=opts)


def clarification_result(ctx: AnalysisContext, c: Clarification) -> AnalysisResult:
    """The 'need a bit more' answer, in the existing result shape (verdict + quick question), so the existing
    UI and the existing refine endpoint handle the farmer's reply. It names no cause and gives no treatment."""
    t = _TEXT[_lang(ctx)]
    return AnalysisResult(
        likely_issue=t["issue"], explanation=t["explanation"], recommended_actions=t["actions"], immediate_actions=t["actions"],
        precautions=[], uncertainty=t["uncertainty"], severity="unknown", uncertainty_level="high",
        image_quality="poor" if c.reason == "poor_image" else "not_provided", verdict=t["verdict"], when_to_seek_help=t["help"],
        quick_questions=[{"question": c.question, "options": c.options}],
    )


def _lang(ctx: AnalysisContext) -> str:
    return "te" if ctx.language == "te" else "en"
