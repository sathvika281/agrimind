"""Local demo provider.

This is NOT an AI model. It is a deterministic keyword-based rule set that
produces realistic structured output so the full application can be exercised
without any external service. A real provider (Gemini) replaces it behind the
same AIProvider interface.
"""
from . import demo_te
from .base import AnalysisContext

CHEMICAL_NOTE = (
    "Before using any chemical treatment, confirm the problem with your local agricultural "
    "officer or input dealer, and follow the product label exactly."
)

# (keywords, issue, explanation, actions, uncertainty-hint)
_RULES: list[tuple[tuple[str, ...], str, str, list[str], str]] = [
    (
        ("yellow", "yellowing", "pale"),
        "Possible nutrient deficiency or watering problem (leaf yellowing)",
        "Yellow leaves often point to too much or too little water, a lack of nitrogen or another "
        "nutrient, or root trouble. Where the yellowing starts (older or newer leaves) gives a clue.",
        [
            "Check whether older (lower) or newer (upper) leaves turn yellow first.",
            "Check soil moisture a hand-depth down; reduce watering if it is soggy, irrigate if bone dry.",
            "Look at the roots and stem base of a few plants for rot, browning or insects.",
            "Consider a soil test to see which nutrients are short before adding fertiliser.",
            "Remove badly affected leaves and watch whether new growth stays healthy.",
        ],
        "Yellowing has many causes. Photos, which leaves are affected and recent watering would help narrow it down.",
    ),
    (
        ("spot", "spots", "blight", "lesion", "brown patch", "black patch"),
        "Possible fungal or bacterial leaf spot",
        "Spots on leaves are commonly caused by fungi or bacteria, especially in humid or wet weather. "
        "Spread is often helped by water splashing between plants.",
        [
            "Remove and destroy the worst-affected leaves; do not leave them in the field.",
            "Avoid watering the leaves; water at the base, preferably in the morning.",
            "Improve spacing and airflow between plants where possible.",
            "Do not work in the field when plants are wet, to avoid spreading the problem.",
            "Take a clear leaf sample to an agricultural officer to identify the exact cause.",
        ],
        "Fungal and bacterial spots look similar and need different treatments, so the exact cause is not certain.",
    ),
    (
        ("wilt", "wilting", "drooping", "droop", "collapse"),
        "Possible water stress or root/stem disease (wilting)",
        "Wilting can come from lack of water, heat stress, damaged roots, or a soil-borne disease. "
        "If plants stay wilted even when the soil is moist, root or stem disease becomes more likely.",
        [
            "Check soil moisture and whether wilting recovers in the evening.",
            "Dig up one wilted plant and inspect roots and the base of the stem for rot or discolouration.",
            "Remove and destroy plants that are clearly dying so disease does not spread.",
            "Avoid waterlogging; make sure excess water can drain.",
            "Ask a local officer about soil-borne disease if several plants wilt in patches.",
        ],
        "Wilting due to drought and due to disease look alike at first. Checking the roots helps tell them apart.",
    ),
    (
        ("insect", "pest", "worm", "caterpillar", "hole", "holes", "aphid", "whitefly", "bug", "eaten", "chewed"),
        "Possible insect pest damage",
        "Holes, chewed edges, sticky leaves or visible insects usually indicate pests. "
        "The type of damage and when it happens help identify which pest is involved.",
        [
            "Inspect the underside of leaves and the growing tips, early morning or evening, for insects or eggs.",
            "Hand-pick and destroy visible caterpillars or egg clusters where the area is small.",
            "Consider traps (such as sticky traps) to monitor pest numbers.",
            "Encourage helpful insects and avoid unnecessary spraying that kills them.",
            "If damage keeps growing, get the pest identified before choosing any control method.",
        ],
        "The pest has not been identified. Describing or photographing the insect or damage would help.",
    ),
    (
        ("powder", "powdery", "white coating", "mildew", "white patch"),
        "Possible powdery or downy mildew",
        "A white or grey powdery coating on leaves is typical of mildew, which spreads in humid, "
        "crowded conditions with poor airflow.",
        [
            "Remove heavily coated leaves and dispose of them away from the field.",
            "Improve airflow by spacing or pruning, and avoid overhead watering.",
            "Water early in the day so leaves dry quickly.",
            "Watch nearby plants closely for the first signs of spread.",
        ],
        "Powdery and downy mildew are managed differently, so the exact type is uncertain without a closer look.",
    ),
    (
        ("stunted", "stunt", "slow growth", "not growing", "small plants", "curl", "curling"),
        "Possible nutrient shortage, poor soil conditions or a virus/pest issue (poor growth or curling)",
        "Slow or stunted growth and curling leaves can be caused by poor soil, lack of nutrients, "
        "compaction, water problems, or sap-sucking insects that can also spread viruses.",
        [
            "Check for tiny insects (whitefly, aphids, thrips) under the leaves.",
            "Check the soil: is it hard, waterlogged or very dry around the roots?",
            "Compare healthy and affected plants for differences in soil, water or sunlight.",
            "Consider a soil test before adding fertiliser.",
        ],
        "Several quite different causes fit these symptoms, so this is a broad suggestion rather than a diagnosis.",
    ),
]

# Short alternative name + how to tell it apart, parallel to _RULES.
_ALT: list[tuple[str, str]] = [
    ("Nutrient or watering problem", "Check which leaves turn yellow first and how wet the soil is."),
    ("Fungal or bacterial leaf spot", "Look for distinct spots or patches with darker edges, especially after wet weather."),
    ("Water stress or root disease", "Check whether plants recover in the evening and whether the roots look healthy."),
    ("Insect pest damage", "Look under leaves and at growing tips for insects, eggs or chewed edges."),
    ("Powdery or downy mildew", "Look for a white or grey coating on the leaf surface."),
    ("Poor growth from soil or virus", "Compare healthy and affected plants, and check for tiny sap-sucking insects."),
]

_GENERIC_ALT = [
    ("Water or nutrient problem", "Check soil moisture and whether older or younger leaves are affected first."),
    ("Insect pest damage", "Look under leaves and at growing tips for insects or chewed edges."),
    ("Fungal or bacterial disease", "Look for spots, patches or coatings on leaves, especially after wet weather."),
]

_GENERIC = (
    "Unable to pinpoint the problem from this description",
    "The information given is not enough to point to a specific cause. Crop problems can come from "
    "water, nutrients, pests, disease, weather or soil conditions, often in combination.",
    [
        "Walk through the field and note how many plants are affected and where (patches, edges, whole field).",
        "Look closely at leaves (both sides), stems and roots for spots, insects, rot or discolouration.",
        "Note recent changes: weather, irrigation, fertiliser, sprays, or a new crop variety.",
        "Take clear photos and show them to your local agricultural officer or extension service.",
    ],
    "Very uncertain. More detail (which part of the plant, how long, how widespread, recent weather) is needed.",
)

_MONITORING = [
    "Watch whether new leaves are affected over the next few days.",
    "Check nearby plants for the same signs and note how fast it spreads.",
    "Note any change after rain, irrigation or any treatment you try.",
]

_FOLLOW_UPS = [
    "How many plants are affected, and is it only some parts of the field?",
    "Are the older (lower) or younger (upper) leaves affected first?",
    "When did you first notice it, and is it getting worse?",
]

_UNKNOWNS = [
    "The exact cause, since nothing here is laboratory-confirmed.",
    "How widespread the problem is across the whole field.",
    "Soil nutrient and moisture levels (only a soil type was given, if anything).",
]


_BETTER = ("better", "improv", "fewer", "less", "తగ్గ", "మెరుగ")
_WORSE = ("worse", "spread", "more", "increas", "పెరిగ", "వ్యాపి", "ఎక్కువ")


def _demo_change(ctx, te: bool = False) -> dict:
    """The demo cannot compare photos: it only reads the farmer's own words, and says 'unclear' otherwise."""
    text = ctx.symptoms.lower()
    if any(k in text for k in _WORSE):
        return {"status": "worse", "note": "మీ వివరణ ప్రకారం సమస్య పెరిగినట్లు ఉంది." if te else "From your description, it sounds worse than before."}
    if any(k in text for k in _BETTER):
        return {"status": "better", "note": "మీ వివరణ ప్రకారం సమస్య తగ్గినట్లు ఉంది." if te else "From your description, it sounds better than before."}
    return {"status": "unclear", "note": "ఫోటోలను పోల్చలేము." if te else "The demo provider cannot compare photos."}


class DemoAIProvider:
    name = "demo"

    def analyze(self, ctx: AnalysisContext) -> dict:
        if ctx.language == "te":
            return self._analyze_te(ctx)
        text = f"{ctx.symptoms} {ctx.crop}".lower()
        idx = [i for i, r in enumerate(_RULES) if any(k in text for k in r[0])]

        if not idx:
            issue, explanation, actions, uncertainty = _GENERIC
            alternatives = _GENERIC_ALT
            level = "high"
        else:
            _, issue, explanation, actions, uncertainty = _RULES[idx[0]]
            level = "some"
            others = [_ALT[i] for i in idx[1:]]
            fillers = [a for i, a in enumerate(_ALT) if i not in idx]
            alternatives = (others + fillers)[:2]
            if len(idx) > 1:
                names = "; ".join(a[0].lower() for a in others)
                explanation += f" Other possibilities given your description: {names}."
                uncertainty += " More than one cause fits what you described."
                level = "high"

        crop = ctx.crop.strip() or "your crop"
        where = f" on your {ctx.soil_type} soil" if ctx.soil_type else ""
        explanation = f"For {crop}{where}: {explanation}"

        observations = []
        evidence_for = []
        if ctx.symptoms.strip():
            excerpt = ctx.symptoms.strip()[:160]
            observations.append(f"You reported: {excerpt}")
            if idx:
                evidence_for.append(f"Your description mentions signs that fit this: {excerpt}")
        image_quality, image_guidance = "not_provided", ""
        if ctx.image:
            uncertainty += " A photo was attached, but the demo provider cannot analyze images."
            observations.append("A photo was received but not analyzed (demo provider).")
            image_quality = "limited"
            image_guidance = "The demo provider cannot analyze photos. Use the Gemini provider for photo analysis."
        if ctx.weather and ctx.weather.trend:
            observations.append(f"Weather context: {ctx.weather.trend}.")
            explanation += " Recent weather conditions can be associated with some crop problems, but that is not confirmed here."
        if ctx.history:
            observations.append(f"You have {len(ctx.history)} earlier analysis for this crop on this farm (not a verified diagnosis).")
        if ctx.diary:
            observations.append("You reported in your diary: " + "; ".join(f"{d.kind} on {d.date}" for d in ctx.diary[:3]) + ".")

        immediate = list(actions[:3])
        monitoring = list(_MONITORING)
        precautions = [
            CHEMICAL_NOTE,
            "Wear gloves and cover your face if you handle any sprays or fertilisers, and keep them away from children and food.",
        ]
        asked = len(ctx.symptoms.strip()) < 25 or not idx
        change = _demo_change(ctx) if ctx.previous else None
        return {
            "change": change,
            "verdict": f"Most likely: {issue}." if idx else "Not enough to tell yet. Answering the questions below will help.",
            "quick_questions": [
                {"question": "Which leaves are affected first?", "options": ["Older (lower) leaves", "Newer (upper) leaves", "Fruit or stems", "Not sure"]},
                {"question": "Is it spreading?", "options": ["Yes, quickly", "Slowly", "No", "Not sure"]},
            ],
            "likely_issue": issue,
            "explanation": explanation,
            "observations": observations,
            "possible_alternatives": [{"possibility": n, "how_to_tell": h} for n, h in alternatives],
            "evidence_for": evidence_for,
            "evidence_against": [],
            "unknowns": list(_UNKNOWNS),
            "immediate_actions": immediate,
            "recommended_actions": list(actions),
            "monitoring_steps": monitoring,
            "precautions": precautions,
            "follow_up_questions": list(_FOLLOW_UPS) if asked else [],
            "severity": "unknown",
            "when_to_seek_help": "Contact your local agricultural officer if the problem spreads quickly, "
            "affects a large area, or the cause stays unclear.",
            "uncertainty_level": level,
            "image_quality": image_quality,
            "image_guidance": image_guidance,
            "uncertainty": uncertainty
            + " AgriMind gives decision-support information, not a guaranteed diagnosis.",
        }

    def _analyze_te(self, ctx: AnalysisContext) -> dict:
        """Same rule matching as English (English OR Telugu keywords), Telugu text, English enum values."""
        te = demo_te
        text = f"{ctx.symptoms} {ctx.crop}".lower()
        idx = [i for i, r in enumerate(_RULES) if any(k in text for k in r[0] + te.KEYWORDS_TE[i])]

        if not idx:
            issue, explanation, actions, uncertainty = te.GENERIC_TE
            alternatives = te.GENERIC_ALT_TE
            level = "high"
        else:
            issue, explanation, actions, uncertainty = te.RULES_TE[idx[0]]
            level = "some"
            others = [te.ALT_TE[i] for i in idx[1:]]
            fillers = [a for i, a in enumerate(te.ALT_TE) if i not in idx]
            alternatives = (others + fillers)[:2]
            if len(idx) > 1:
                explanation += te.OTHERS.format(names="; ".join(a[0] for a in others))
                uncertainty += te.MORE_THAN_ONE
                level = "high"

        crop = ctx.crop.strip() or "మీ"
        soil = f" ({ctx.soil_type})" if ctx.soil_type else ""
        explanation = te.CROP_PREFIX.format(crop=crop, soil=soil) + explanation

        observations, evidence_for = [], []
        if ctx.symptoms.strip():
            excerpt = ctx.symptoms.strip()[:160]
            observations.append(te.YOU_REPORTED.format(x=excerpt))
            if idx:
                evidence_for.append(te.FITS.format(x=excerpt))
        image_quality, image_guidance = "not_provided", ""
        if ctx.image:
            uncertainty += te.PHOTO_UNCERTAINTY
            observations.append(te.PHOTO_OBS)
            image_quality = "limited"
            image_guidance = te.PHOTO_GUIDANCE
        if ctx.weather:
            wo = te.weather_obs(ctx.weather.past_3d_rain_mm, ctx.weather.next_3d_rain_mm)
            if wo:
                observations.append(wo)
                explanation += te.WEATHER_EXPL
        if ctx.history:
            observations.append(te.HISTORY_OBS.format(n=len(ctx.history)))

        asked = len(ctx.symptoms.strip()) < 25 or not idx
        change = _demo_change(ctx, te=True) if ctx.previous else None
        return {
            "change": change,
            "verdict": f"బహుశా: {issue}." if idx else "ఇంకా చెప్పడానికి సరిపోదు. కింది ప్రశ్నలకు జవాబిస్తే సహాయపడుతుంది.",
            "quick_questions": [
                {"question": "మొదట ఏ ఆకులు ప్రభావితమయ్యాయి?", "options": ["పాత (కింది) ఆకులు", "కొత్త (పై) ఆకులు", "కాయలు లేదా కాండం", "తెలియదు"]},
                {"question": "ఇది వ్యాపిస్తోందా?", "options": ["అవును, త్వరగా", "నెమ్మదిగా", "లేదు", "తెలియదు"]},
            ],
            "likely_issue": issue,
            "explanation": explanation,
            "observations": observations,
            "possible_alternatives": [{"possibility": n, "how_to_tell": h} for n, h in alternatives],
            "evidence_for": evidence_for,
            "evidence_against": [],
            "unknowns": list(te.UNKNOWNS_TE),
            "immediate_actions": list(actions[:3]),
            "recommended_actions": list(actions),
            "monitoring_steps": list(te.MONITORING_TE),
            "precautions": [te.CHEMICAL_NOTE, te.HANDLING_NOTE],
            "follow_up_questions": list(te.FOLLOW_UPS_TE) if asked else [],
            "severity": "unknown",
            "when_to_seek_help": te.WHEN_HELP,
            "uncertainty_level": level,
            "image_quality": image_quality,
            "image_guidance": image_guidance,
            "uncertainty": uncertainty + te.DISCLAIMER,
        }
