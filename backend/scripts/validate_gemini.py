"""Live Gemini validation: 4 real cases through the EXISTING provider + safety verifier.

Run from backend/ (needs GEMINI_API_KEY in backend/.env or the environment):

    .venv\\Scripts\\python.exe scripts\\validate_gemini.py --photo path\\to\\crop_photo.jpg [--json out.json]

- Refuses to run without a key (exit code 2). Never prints, logs or writes the key.
- Uses app.services.ai (GeminiProvider + analyze() + verifier). No second AI implementation.
- Case 3 needs a REAL crop photo via --photo; without one it is reported as NOT EXECUTED (nothing is fabricated).
- The automatic checks are structural/safety checks. Whether an answer is agriculturally *grounded* still needs a human
  to read the printed fields; this script says so rather than pretending to judge it.
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TELUGU = re.compile(r"[ఀ-౿]")
ENUMS = {
    "severity": {"low", "medium", "high", "unknown"},
    "uncertainty_level": {"low", "some", "high", "unknown"},
    "image_quality": {"good", "limited", "poor", "not_provided"},
}
# Words that are fine inside a disclaimer ("does not guarantee") but deserve a human look if present.
REVIEW_WORDS = re.compile(r"definitely|guarantee|100\s*%|certainly|laboratory|ఖచ్చితంగా|హామీ|తప్పకుండా", re.I)

CASES = [
    {"id": 1, "name": "English text", "language": "en", "crop": "Tomato", "photo": False,
     "symptoms": "Tomato leaves are turning yellow, especially the older leaves."},
    {"id": 2, "name": "Telugu text", "language": "te", "crop": "టమాటా", "photo": False,
     "symptoms": "నా టమాటా మొక్క ఆకులు పసుపు రంగులోకి మారుతున్నాయి. ముందుగా పాత ఆకులు పసుపుగా మారాయి."},
    {"id": 3, "name": "Telugu + real crop photo", "language": "te", "crop": "టమాటా", "photo": True,
     "symptoms": "నా టమాటా మొక్క ఆకులు పసుపు రంగులోకి మారుతున్నాయి. ఫోటో జత చేశాను."},
    {"id": 4, "name": "Mixed Telugu-English", "language": "te", "crop": "మిరప", "photo": False,
     "symptoms": "నా మిరప leaves మీద చిన్న చిన్న spots వస్తున్నాయి, కొన్ని leaves holes కూడా ఉన్నాయి."},
]


def _texts(r) -> list[str]:
    alt = [x for a in r.possible_alternatives for x in (a.possibility, a.how_to_tell)]
    return [r.likely_issue, r.explanation, r.uncertainty, r.when_to_seek_help, *r.recommended_actions, *r.immediate_actions,
            *r.monitoring_steps, *r.precautions, *r.observations, *r.evidence_for, *r.evidence_against, *r.unknowns,
            *r.follow_up_questions, *alt, r.image_guidance]


def check_result(r, language: str, had_image: bool, symptoms: str) -> list[tuple[str, bool, str]]:
    """Pure structural/safety checks on a validated AnalysisResult. Returns (name, passed, detail)."""
    out: list[tuple[str, bool, str]] = []
    out.append(("has recommended/immediate actions", bool(r.recommended_actions or r.immediate_actions), f"{len(r.recommended_actions)}/{len(r.immediate_actions)}"))
    out.append(("has monitoring steps", bool(r.monitoring_steps), str(len(r.monitoring_steps))))
    out.append(("has precautions", bool(r.precautions), str(len(r.precautions))))
    out.append(("uncertainty statement present", bool(r.uncertainty.strip()), r.uncertainty_level))
    out.append(("enum values valid (English, unchanged)", r.severity in ENUMS["severity"] and r.uncertainty_level in ENUMS["uncertainty_level"] and r.image_quality in ENUMS["image_quality"],
                f"{r.severity}/{r.uncertainty_level}/{r.image_quality}"))
    main = " ".join([r.likely_issue, r.explanation, *r.recommended_actions, *r.precautions])
    te_share = len(TELUGU.findall(main)) / max(1, len(re.findall(r"\S", main)))
    if language == "te":
        out.append(("Telugu output (meaningful Telugu script)", te_share >= 0.3, f"{te_share:.0%} of characters"))
    else:
        out.append(("English output (no Telugu script)", te_share == 0, f"{te_share:.0%}"))
    weak = len(symptoms.strip()) < 25 and not had_image
    if weak:
        out.append(("uncertainty not 'low' when evidence is thin", r.uncertainty_level != "low", r.uncertainty_level))
    if had_image:
        out.append(("image_quality was assessed (not 'not_provided')", r.image_quality != "not_provided", r.image_quality))
    else:
        out.append(("no image claimed when none sent", r.image_quality == "not_provided", r.image_quality))
    hits = sorted({m.group(0).lower() for t in _texts(r) for m in REVIEW_WORDS.finditer(t or "")})
    out.append(("certainty/lab wording for HUMAN REVIEW (informational)", True, ", ".join(hits) or "none found"))
    return out


def run_case(case: dict, provider, image) -> dict:
    from app.services.ai import AIServiceError, AnalysisContext, ImageInput, analyze

    ctx = AnalysisContext(
        crop=case["crop"], symptoms=case["symptoms"], farm_location="Guntur, Andhra Pradesh",
        language=case["language"], image=ImageInput(image.data, image.mime_type) if image else None,
    )
    rec = {"case": case["id"], "name": case["name"], "language": case["language"], "input_type": ctx.input_type,
           "image_used": image is not None}
    t0 = time.perf_counter()
    try:
        r = analyze(ctx, provider)  # existing pipeline: one Gemini call -> validation -> safety verifier
    except AIServiceError as e:
        rec.update(status="FAILED", error_code=e.code, error=str(e), latency_ms=round((time.perf_counter() - t0) * 1000))
        return rec
    rec["latency_ms"] = round((time.perf_counter() - t0) * 1000)
    checks = check_result(r, case["language"], image is not None, case["symptoms"])
    rec.update(
        status="PASSED" if all(ok for _, ok, _ in checks) else "CHECKS_FAILED",
        likely_issue=r.likely_issue, severity=r.severity, uncertainty_level=r.uncertainty_level, uncertainty=r.uncertainty,
        immediate_actions=r.immediate_actions or r.recommended_actions, monitoring_steps=r.monitoring_steps,
        precautions=r.precautions, when_to_seek_help=r.when_to_seek_help, image_quality=r.image_quality,
        image_guidance=r.image_guidance, follow_up_questions=r.follow_up_questions,
        checks=[{"check": n, "passed": ok, "detail": d} for n, ok, d in checks],
    )
    return rec


def _print(rec: dict) -> None:
    print(f"\n=== CASE {rec['case']}: {rec['name']} ===")
    print(f"language={rec['language']}  input_type={rec['input_type']}  image_used={rec['image_used']}  latency={rec.get('latency_ms')} ms  status={rec['status']}")
    if rec["status"] == "NOT_EXECUTED":
        print("reason:", rec["reason"])
        return
    if rec["status"] == "FAILED":
        print(f"error_code={rec['error_code']}  message={rec['error']}")
        return
    print("likely issue :", rec["likely_issue"])
    print(f"severity     : {rec['severity']}   uncertainty: {rec['uncertainty_level']} - {rec['uncertainty']}")
    for label, key in (("immediate", "immediate_actions"), ("monitoring", "monitoring_steps"), ("precautions", "precautions")):
        print(f"{label}:")
        for x in rec[key]:
            print("   -", x)
    print("escalation   :", rec["when_to_seek_help"] or "(none given)")
    print(f"image quality: {rec['image_quality']}  {rec['image_guidance']}")
    for c in rec["checks"]:
        print(f"   [{'PASS' if c['passed'] else 'FAIL'}] {c['check']}  ({c['detail']})")
    print("   [MANUAL] Is the answer grounded in what the farmer wrote / the photo, with no invented facts? -> read above.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--photo", help="path to a REAL crop photo (JPG/PNG/WebP) for case 3")
    ap.add_argument("--json", help="also write the results (never the key) to this JSON file")
    args = ap.parse_args(argv)

    from app.config import settings

    if not settings.gemini_api_key:
        print("REFUSING TO RUN: GEMINI_API_KEY is not configured.\n"
              "Put it in backend/.env (never paste it into chat or commit it), then re-run.\n"
              "No live Gemini validation was performed.")
        return 2

    from app.services import images
    from app.services.ai.gemini_provider import GeminiProvider

    image = None
    if args.photo:
        p = Path(args.photo)
        try:
            image = images.validate_image(p.read_bytes(), {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}.get(p.suffix.lower()), settings.max_image_bytes)
        except (OSError, images.ImageError) as e:
            print(f"Photo not usable ({type(e).__name__}); case 3 will not be executed.")

    provider = GeminiProvider()
    print(f"Model: {provider.model}   (key present: yes, value not shown)")
    results = []
    for case in CASES:
        if case["photo"] and image is None:
            rec = {"case": case["id"], "name": case["name"], "language": case["language"], "input_type": "text+image",
                   "image_used": False, "status": "NOT_EXECUTED",
                   "reason": "no real crop photo supplied (--photo). Nothing was fabricated or downloaded."}
        else:
            rec = run_case(case, provider, image if case["photo"] else None)
        _print(rec)
        results.append(rec)

    print("\n=== SUMMARY ===")
    for r in results:
        print(f"case {r['case']} ({r['name']}): {r['status']}  {r.get('latency_ms', '-')} ms")
    if args.json:
        Path(args.json).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print("results written to", args.json)
    ran = [r for r in results if r["status"] != "NOT_EXECUTED"]
    return 0 if ran and all(r["status"] == "PASSED" for r in ran) else 1


if __name__ == "__main__":
    sys.exit(main())
