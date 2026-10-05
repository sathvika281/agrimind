"""Deterministic verification of a model assessment. No AI, no extra calls.

Scope (by design): validate structure, safety signals, uncertainty behaviour and obvious
consistency problems. It NEVER diagnoses crops, diseases, pests or treatments and never
invents agricultural facts. Hard problems raise SafetyError (nothing is stored); a few
meta-fields (uncertainty level, severity cap, standard photo tips/questions) are repaired
from rules, using fixed generic text only.

Disclaimers vs prescriptions: a sentence that mentions a dosage pattern is allowed ONLY if it
both prohibits/conditions it (do not / never / avoid / unless / without ...) AND points to a
safeguard (label / officer / professional / guidance ...). If we cannot tell, we reject.
"""
import re
from dataclasses import dataclass

from ...schemas import AnalysisResult
from .base import AnalysisContext
from .evidence import build_evidence

IMAGE_GUIDANCE = (
    "For a clearer photo: use good daylight, focus on the affected leaf, include both healthy and "
    "affected parts, and avoid blurry or distant shots."
)
STANDARD_QUESTIONS = [
    "How many plants are affected, and is it only in some parts of the field?",
    "Are the older (lower) or younger (upper) leaves affected first?",
    "When did you first notice it, and is it getting worse?",
]


class SafetyError(Exception):
    """Output failed verification. `code` is for server logs only, never shown to users."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _rx(p: str) -> re.Pattern:
    return re.compile(p, re.I)


# ---------- shared language cues ----------
PROHIB = _rx(r"\b(?:do not|don't|dont|never|avoid|should not|shouldn't|must not|not recommended|no specific|cannot|can't|unless|without)\b")
SAFEGUARD = _rx(r"\b(?:label|officer|professional|extension|agronomist|dealer|guidance|instructions|advice|confirm\w*|local expert)\b")
NEG = _rx(r"\b(?:not|no|never|cannot|can't|without|nor|neither|unless|until|rather than)\b|n't\b")
HEDGE = _rx(
    r"\b(?:may|might|could|can|possibly|possible|likely|probably|perhaps|associated|consistent|increase\w*|"
    r"raise\w*|favou?r\w*|often|sometimes|typically|commonly)\b"
)

# ---------- dosage / concentration ----------
_UNIT = r"(?:ml|mls|millilit(?:re|er)s?|l|lit(?:re|er)s?|g|gm|gms|grams?|kg|kgs|kilograms?|mg|milligrams?|cc|tsp|tbsp|teaspoons?|tablespoons?|oz|ounces?|lbs?)"
AMOUNT = _rx(rf"\b\d+(?:[.,]\d+)?\s*{_UNIT}\b")
RATE_FIELD = _rx(rf"\b\d+(?:[.,]\d+)?\s*{_UNIT}\s*(?:/|per)\s*(?:acre|ac|hectare|ha|bigha|guntha|tank|pump|knapsack)\b")
PPM = _rx(r"\b\d+(?:[.,]\d+)?\s*ppm\b")
PCT = _rx(r"\b\d+(?:[.,]\d+)?\s*%")
RATIO = _rx(r"\b\d+\s*:\s*\d+\b")
STRENGTH = _rx(r"\b(?:solution|concentrat\w*|dilut\w*|strength|emulsi\w*|spray\w*|mixture)\b")
CHEM_CTX = _rx(
    r"\b(?:pesticid\w*|fungicid\w*|insecticid\w*|herbicid\w*|bactericid\w*|miticid\w*|nematicid\w*|chemical\w*|"
    r"spray\w*|dos(?:e|es|age|ing)|dilut\w*|mix(?:ed|ing|ture)?|solution|concentrat\w*|fertili[sz]er\w*|urea|"
    r"npk|dap|potash|emulsi\w*|wettable|formulation|drench\w*|sulph\w*|sulf\w*|copper|neem|mancozeb|"
    r"carbendazim|imidacloprid)\b"
)


RATE_CONC = _rx(rf"\b\d+(?:[.,]\d+)?\s*{_UNIT}\s*(?:/|per)\s*(?:l|lit(?:re|er)s?|gallon)\b")


def _is_dosage(s: str) -> bool:
    if RATE_FIELD.search(s) or RATE_CONC.search(s):
        return True
    chem = CHEM_CTX.search(s)
    if chem and (AMOUNT.search(s) or PPM.search(s) or RATIO.search(s)):
        return True
    if chem and PCT.search(s) and STRENGTH.search(s):
        return True
    return False


def _is_disclaimer(s: str) -> bool:
    return bool(PROHIB.search(s) and SAFEGUARD.search(s))


# ---------- guaranteed diagnosis / outcome ----------
_GUARANTEE = [
    r"\bguarantee[sd]?\b|\bguaranteeing\b",
    r"\b(?:definitely|certainly|undoubtedly|unquestionably|absolutely certain|without (?:a )?doubt|no doubt|beyond doubt)\b",
    r"\b100\s*%",
    r"\bwill (?:definitely |certainly |fully |completely |surely )?(?:cure|fix|solve|eliminate|kill|save|recover|stop|prevent|restore)\b",
    r"\b(?:sure|certain) to (?:work|cure|fix|help)\b|\bcannot fail\b|\bwon't fail\b|\bproven (?:cure|treatment|remedy)\b",
    r"\b(?:is|are|was|were) (?:diagnosed as|confirmed (?:as|to be))\b|\bconfirmed (?:as|to be)\b",
]
GUARANTEE = [_rx(p) for p in _GUARANTEE]

# ---------- lab-confirmed claims ----------
LAB = _rx(
    r"\b(?:laboratory|lab)[- ](?:confirmed|tested|verified|proven)\b|\bconfirmed by (?:a |the )?(?:lab|laboratory|tests?)\b|"
    r"\b(?:lab|laboratory|tests?|analysis) (?:results? )?(?:show|shows|showed|confirm|confirms|confirmed|prove|proves|proved|indicates?|indicated)\b"
)

# ---------- weather causality stated as fact ----------
WEATHER_CAUSE_A = _rx(
    r"\b(?:rain\w*|weather|humidity|heat|temperature\w*|moisture|wind|drought|conditions)\b[^.;]{0,40}?"
    r"\b(?:caused|causes|causing|led to|leads to|resulted in|is responsible for|are responsible for)\b"
)
WEATHER_CAUSE_B = _rx(
    r"\b(?:caused|due|owing|thanks) (?:by|to) (?:the |this |these )?(?:recent |heavy |high |current )?"
    r"(?:rain\w*|weather|humidity|heat|drought|conditions|temperature\w*)\b"
)

# ---------- chemical application directive (actions only) ----------
CHEM_DIRECTIVE = _rx(
    r"\b(?:spray|apply|use|treat(?:ing)? with|drench|dust|add)\b[^.;]{0,80}?"
    r"\b(?:fungicid\w*|pesticid\w*|insecticid\w*|herbicid\w*|bactericid\w*|miticid\w*|chemical\w*|copper|"
    r"sulph\w*|sulf\w*|mancozeb|carbendazim|imidacloprid)\b"
)

# ---------- consistency with provided inputs ----------
IMAGE_CLAIM = _rx(
    r"\b(?:in|from|on|of) (?:the |your |this )?(?:photo|photograph|image|picture)\b|"
    r"\b(?:photo|photograph|image|picture) (?:shows?|showed|reveals?|indicates?)\b"
)
WEATHER_NUMBER = _rx(r"\b\d+(?:[.,]\d+)?\s*(?:mm|°\s?c|°|km/h|degrees)\b")

ESCALATION = _rx(
    r"\b(?:dying|dead|collaps\w*|spread\w*|rapid\w*|quick\w*|fast|widespread|whole field|entire|all (?:the )?plants|"
    r"most (?:of )?(?:the )?plants|many plants|severe\w*|serious\w*|large area|destroy\w*|rott\w*)\b"
)


# =====================================================================================
# Telugu layer (ADDITIONAL to the English checks above, never a replacement).
# Pattern-based and deliberately conservative: Telugu is not checked as thoroughly as English,
# and anything that looks like a dose/concentration, certainty claim, lab claim, proven weather
# cause or unsafeguarded chemical instruction is REJECTED rather than repaired. Telugu word
# order is verb-final, so negation/disclaimer cues are looked for anywhere in the sentence.
# =====================================================================================
IMAGE_GUIDANCE_TE = (
    "మెరుగైన ఫోటో కోసం: మంచి పగటి వెలుతురులో తీయండి, దెబ్బతిన్న ఆకుపై ఫోకస్ చేయండి, ఆరోగ్యంగా ఉన్న భాగం, "
    "దెబ్బతిన్న భాగం రెండూ కనిపించేలా తీయండి, మసకగా లేదా చాలా దూరం నుండి తీయకండి."
)
STANDARD_QUESTIONS_TE = [
    "ఎన్ని మొక్కలు ప్రభావితమయ్యాయి? పొలంలో కొన్ని చోట్ల మాత్రమేనా?",
    "పాత (కింది) ఆకులా, కొత్త (పై) ఆకులా ముందు ప్రభావితమయ్యాయి?",
    "మీరు మొదట ఎప్పుడు గమనించారు? ఇది ఎక్కువవుతోందా?",
]

_TE_DIGITS = str.maketrans("౦౧౨౩౪౫౬౭౮౯", "0123456789")


def _norm_te(s: str) -> str:
    """Telugu digits -> ASCII; drop zero-width joiners typed inside words (e.g. లేబుల్‌)."""
    return s.translate(_TE_DIGITS).replace("‌", "").replace("‍", "")


_UNIT_TE = (
    r"(?:మి\.?\s?లీ\.?|మిల్లీ\s?లీటర్(?:లు|ల్)?|లీటర్(?:లు|ల్)?|లీటరు(?:లు)?|లీ\.|గ్రా\.?|గ్రాము(?:లు)?|గ్రాం(?:లు)?|"
    r"కిలో(?:లు)?|కేజీ|కి\.గ్రా\.?|మి\.గ్రా\.?|టేబుల్\s?స్పూన్(?:లు)?|టీ\s?స్పూన్(?:లు)?|స్పూన్(?:లు)?|మూత(?:లు)?|పీపీఎం|ppm)"
)
AMOUNT_TE = _rx(rf"\d+(?:[.,]\d+)?\s*{_UNIT_TE}")
RATE_TE = _rx(r"\d+(?:[.,]\d+)?\s*[^\s.;]{0,12}\s*(?:ఎకరాకు|ఎకరం|హెక్టారుకు|లీటరుకు|లీటర్‌కు|లీటరు నీటికి|నీటికి|ట్యాంకుకు|పంపుకు|డబ్బాకు)")
PCT_TE = _rx(r"\d+(?:[.,]\d+)?\s*(?:%|శాతం)")
STRENGTH_TE = _rx(r"ద్రావణ|గాఢత|కలిపి|కలపండి|కలుపు|పిచికారీ|స్ప్రే|డోసు|మోతాదు")
CHEM_TE = _rx(
    r"మందు|పురుగుమందు|శిలీంద్ర|రసాయన|ఎరువు|యూరియా|పొటాష్|డీఏపీ|పిచికారీ|స్ప్రే|కలిపి|కలపండి|ద్రావణ|గాఢత|డోసు|మోతాదు|"
    r"కాపర్|సల్ఫర్|గంధకం|వేప నూనె|ఇమిడాక్లోప్రిడ్|మాంకోజెబ్|కార్బెండజిమ్"
)
PROHIB_TE = _rx(r"వద్దు|వద్దని|కాదు|లేకుండా|తప్ప|చేయకండి|వాడకండి|వేయకండి|కొట్టకండి|పోయకండి|ముందు")
SAFEGUARD_TE = _rx(r"లేబుల్|సూచనల|అధికారి|నిపుణ|సలహా|డీలర్|వ్యవసాయ శాఖ|విస్తరణ|ప్యాకెట్")
NEG_TE = _rx(
    r"కాదు|లేదు|లేవు|లేము|లేరు|చెప్పలేము|తెలియదు|తెలియవు|ఇవ్వదు|ఇవ్వలేదు|కాకపోవచ్చు|వద్దు|వద్దని|లేకుండా|"
    r"చేయకండి|వాడకండి|బడలేదు|నిర్ధారణ కాలేదు|కాలేదు"
)
HEDGE_TE = _rx(r"వచ్చు|అవకాశం|సాధారణంగా|తరచుగా|సంబంధం|అయ్యే|ఉండొచ్చు|బహుశా")
ALWAYS_TE = _rx(r"సందేహం\s?(?:లేదు|లేకుండా)|సందేహమే లేదు|నిస్సందేహంగా")  # certainty phrases that contain a negation word
GUARANTEE_TE = _rx(
    r"ఖచ్చితంగా|ఖచ్చితమైన హామీ|తప్పకుండా|తప్పక\s?(?:నయం|తగ్గు|పని)|హామీ|100\s*%|పూర్తిగా\s?(?:నయం|తగ్గిపోతుంది|పోతుంది)|"
    r"కచ్చితంగా|నిస్సందేహంగా|అసలు సందేహం"
)
LAB_TE = _rx(r"(?:ప్రయోగశాల|ల్యాబ్|పరీక్ష)[^.;]{0,30}(?:నిర్ధారణ|నిర్ధారించ|ధృవీక|రుజువు)|నిర్ధారణ అయింది|నిర్ధారించబడింది")
WEATHER_CAUSE_TE = _rx(r"(?:వర్షం|వాతావరణం|తేమ|ఎండ|వేడి|చలి|గాలి)[^.;]{0,20}(?:వల్ల|కారణంగా)")
CHEM_DIRECTIVE_TE = _rx(r"(?:పిచికారీ|స్ప్రే|కలపండి|వేయండి|వాడండి|కొట్టండి|చల్లండి)")
IMAGE_CLAIM_TE = _rx(r"ఫోటోలో|చిత్రంలో|ఫొటోలో|ఫోటో చూపిస్తోంది")
WEATHER_NUMBER_TE = _rx(r"\d+(?:[.,]\d+)?\s*(?:మి\.?\s?మీ|డిగ్రీ|°|కి\.?\s?మీ)")


def _is_dosage_te(s: str) -> bool:
    chem = CHEM_TE.search(s) or CHEM_CTX.search(s)
    if RATE_TE.search(s) and chem:
        return True
    if chem and (AMOUNT_TE.search(s) or AMOUNT.search(s) or PPM.search(s) or RATIO.search(s)):
        return True
    if chem and PCT_TE.search(s) and STRENGTH_TE.search(s):
        return True
    return False


def _scan_te(r: AnalysisResult, ctx: AnalysisContext) -> None:
    """Extra checks for Telugu analyses. Raises SafetyError on the first violation."""
    evidence_fields = {"observations", "evidence_for", "evidence_against", "likely_issue", "explanation"}
    for name, items in _fields(r).items():
        for item in items:
            for raw in _sentences(item or ""):
                s = _norm_te(raw)
                if _is_dosage_te(s) and not (PROHIB_TE.search(s) and SAFEGUARD_TE.search(s)):
                    raise SafetyError("te_dosage_or_concentration")
                if ALWAYS_TE.search(s):
                    raise SafetyError("te_guaranteed_claim")
                if GUARANTEE_TE.search(s) and not NEG_TE.search(s):
                    raise SafetyError("te_guaranteed_claim")
                if name in evidence_fields and LAB_TE.search(s) and not NEG_TE.search(s):
                    raise SafetyError("te_lab_confirmed_claim")
                if WEATHER_CAUSE_TE.search(s) and not HEDGE_TE.search(s) and not NEG_TE.search(s):
                    raise SafetyError("te_weather_causality")
                if name in {"recommended_actions", "immediate_actions", "monitoring_steps"}:
                    if CHEM_DIRECTIVE_TE.search(s) and CHEM_TE.search(s) and not PROHIB_TE.search(s) and not SAFEGUARD_TE.search(s):
                        raise SafetyError("te_unsafeguarded_chemical_directive")
                if name in evidence_fields:
                    if ctx.image is None and IMAGE_CLAIM_TE.search(s) and not NEG_TE.search(s):
                        raise SafetyError("te_image_claim_without_image")
                    if ctx.weather is None and WEATHER_NUMBER_TE.search(s):
                        raise SafetyError("te_weather_claim_without_weather")


def _sentences(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"(?<=[.!?;])\s+|\n+", text) if p.strip()]


def _fields(r: AnalysisResult) -> dict[str, list[str]]:
    alt = []
    for a in r.possible_alternatives:
        alt += [a.possibility, a.how_to_tell]
    qq = []
    for q in r.quick_questions:
        qq += [q.question, *q.options]
    return {
        "verdict": [r.verdict],
        "quick_questions": qq,
        "change_note": [r.change.note] if r.change else [],
        "likely_issue": [r.likely_issue],
        "explanation": [r.explanation],
        "recommended_actions": r.recommended_actions,
        "immediate_actions": r.immediate_actions,
        "monitoring_steps": r.monitoring_steps,
        "precautions": r.precautions,
        "observations": r.observations,
        "evidence_for": r.evidence_for,
        "evidence_against": r.evidence_against,
        "unknowns": r.unknowns,
        "alternatives": alt,
        "follow_up_questions": r.follow_up_questions,
        "when_to_seek_help": [r.when_to_seek_help],
        "uncertainty": [r.uncertainty],
        "image_guidance": [r.image_guidance],
    }


def _prefix(sentence: str, m: re.Match) -> str:
    return sentence[: m.start()]


def _scan(r: AnalysisResult, ctx: AnalysisContext) -> None:
    """Hard checks. Raises SafetyError on the first violation."""
    action_fields = {"recommended_actions", "immediate_actions", "monitoring_steps"}
    evidence_fields = {"observations", "evidence_for", "evidence_against"}
    for name, items in _fields(r).items():
        for item in items:
            for s in _sentences(item or ""):
                # dosage / concentration
                if _is_dosage(s) and not _is_disclaimer(s):
                    raise SafetyError("dosage_or_concentration")
                # guaranteed diagnosis / outcome (negated disclaimers like "does not guarantee" are fine)
                for rx in GUARANTEE:
                    for m in rx.finditer(s):
                        if not NEG.search(_prefix(s, m)):
                            raise SafetyError("guaranteed_claim")
                # lab-confirmed claims
                if name in evidence_fields | {"likely_issue", "explanation"}:
                    for m in LAB.finditer(s):
                        if not NEG.search(_prefix(s, m)):
                            raise SafetyError("lab_confirmed_claim")
                # weather causation stated as fact
                for rx in (WEATHER_CAUSE_A, WEATHER_CAUSE_B):
                    if rx.search(s) and not HEDGE.search(s) and not NEG.search(s):
                        raise SafetyError("weather_causality")
                # claims about inputs that were not provided
                if name in evidence_fields:
                    if ctx.image is None:
                        for m in IMAGE_CLAIM.finditer(s):
                            if not NEG.search(_prefix(s, m)):
                                raise SafetyError("image_claim_without_image")
                    if ctx.weather is None and WEATHER_NUMBER.search(s):
                        raise SafetyError("weather_claim_without_weather")
    return None


def verify(result: AnalysisResult, ctx: AnalysisContext) -> AnalysisResult:
    """Return the verified (possibly repaired) result, or raise SafetyError."""
    if not result.recommended_actions:
        raise SafetyError("no_actions")

    _scan(result, ctx)  # existing English/numeric checks remain authoritative for every language
    te = ctx.language == "te"
    if te:
        _scan_te(result, ctx)  # additional, conservative Telugu layer

    ev = build_evidence(ctx)
    update: dict = {}
    if ctx.previous is None:
        update["change"] = None  # a comparison is only meaningful (and only kept) for a follow-up check

    # image fields must agree with whether an image was actually provided
    quality = result.image_quality
    if ctx.image is None:
        quality = "not_provided"
        update["image_quality"] = "not_provided"
        update["image_guidance"] = ""
    poor_image = quality == "poor"
    weak = ev.weak or poor_image

    # qualitative uncertainty must reflect weak evidence
    level = result.uncertainty_level
    if level == "unknown":
        level = "high" if weak else "some"
    elif level == "low" and weak:
        level = "high" if poor_image else "some"
    update["uncertainty_level"] = level

    # severity must not be extreme without any escalation signal in the inputs
    # (Not done for Telugu: escalation words can't be detected reliably there, and silently downgrading
    # a possibly urgent case is the wrong direction to be wrong in.)
    if result.severity == "high" and not te:
        basis = " ".join([ctx.symptoms, *result.observations, *result.evidence_for])
        if not ESCALATION.search(basis):
            update["severity"] = "medium"

    # standard photo tips when the photo is hard to interpret
    if ctx.image is not None and quality in ("poor", "limited") and not result.image_guidance:
        update["image_guidance"] = IMAGE_GUIDANCE_TE if te else IMAGE_GUIDANCE

    # a few standard questions when evidence is thin and none were asked
    if weak and not result.follow_up_questions:
        update["follow_up_questions"] = (STANDARD_QUESTIONS_TE if te else STANDARD_QUESTIONS)[:3]

    repaired = result.model_copy(update=update)

    # consistency: do not direct chemical application while uncertain, unless safeguarded
    if repaired.uncertainty_level != "low":
        for item in repaired.immediate_actions + repaired.recommended_actions + repaired.monitoring_steps:
            for s in _sentences(item):
                if CHEM_DIRECTIVE.search(s) and not PROHIB.search(s) and not SAFEGUARD.search(s):
                    raise SafetyError("unsafeguarded_chemical_directive")
    return repaired
