# AgriMind — Phase 7

AI-assisted agricultural decision support for farmers. **It is decision support, not a professional diagnosis.**

**Phase 7 (this version):** push-to-talk voice input, "Listen" for results, and a live-validation script for the real Gemini provider.

## Phase 7: voice + Gemini validation

**Voice is only an input/output layer. There is still ONE analysis pipeline** (same endpoint, same Gemini/demo provider, same safety verifier, same idempotency).

- **Speech-to-text:** the browser's `SpeechRecognition` (Web Speech API). No backend, no API key, no audio upload or storage; AgriMind's server never sees audio. In Chrome/Edge the *browser* sends audio to its own speech service (internet needed). Not available in every browser (e.g. Firefox); there the app shows a message and the farmer types. Language follows the UI: `te-IN` in Telugu, `en-IN` in English.
- **Flow:** tap "🎤 Speak your problem" → "⏹ Stop" while recording ("Listening…" only once the browser has really started; "Converting your voice to text…" only while it is genuinely finishing) → the transcript is **appended** to the problem box, editable, **never auto-submitted** → submit as usual (works together with crop, farm, photo, language). A 60-second UI guard stops the recording and keeps what was already recognised. Leaving the page or switching language cancels any live microphone.
- **Errors** (permission denied, no microphone, nothing heard, network, language not supported, unsupported browser) all show a short friendly message, and the text box is always usable.
- **Listen (text-to-speech):** the browser's `speechSynthesis`. The spoken text is built **deterministically** from the existing structured result (best guess, how sure, what to do now (max 3), what to watch (max 2), when to get help, first precaution), in the language the result was written in. No second AI call. **If the device has no Telugu voice, Telugu is NOT read with an English voice**; a message says playback isn't available and the written result stays. Speech stops when you leave the page.
- **Privacy:** no raw audio is logged or stored by AgriMind; transcripts are just ordinary problem text.

### Precision-agriculture redesign (Overview + app shell)
The app shell (compact header with farm selector and live chips, narrow dark-green sidebar that becomes a scrolling tab bar on phones) and the Overview (farm map, field-intelligence panel, AgriMind Copilot, microclimate, soil, alerts, activity feed) follow the reference style. Other pages keep their forms and sit inside the same shell.
- **Real data:** your farms (one organic polygon per farm), field colour from the severity of each farm's **latest check**, weather from Open-Meteo (`GET /farms/{id}/weather`, owner-checked, cached), the Copilot panel and "AgriMind Logic" from your latest real check (inputs used, evidence for/against, unknowns), alerts and the activity feed from your checks.
- **Sample data (clearly badged `SAMPLE DATA`, never called live):** NDVI, soil-moisture layer, N-P-K and other soil readings, root temperature, pathogen index, forecast yield. They live in one removable file, `frontend/src/sample/sampleTelemetry.ts`. Satellite, sensors, drone and irrigation are shown as **Not connected**. Sidebar pages that don't exist yet (Soil & Sensors, Insights, Analytics) are disabled with a "Soon" tag.
- No numeric AI confidence and no invented advice (e.g. irrigation scheduling) is shown. Tests: `npm run test:overview` (health levels, geometry, rain outlook).

### Result language follows the language switch (explicit, cached)
A check keeps the language it was written in. If you switch the app language, the result page offers **"Show this result in English / ఈ ఫలితాన్ని తెలుగులో చూడండి"**. It calls `POST /analyses/{id}/translate`, which writes the **same check again** in the other language from its original stored inputs (crop, symptoms, farm, saved weather, photo) through the same single pipeline and safety verifier (one model call, ~10–20 s with real Gemini). It is a re-generation, not a literal translation, so wording may differ a little (the UI says so). The new version is stored in `analyses.translations_json` (additive, nullable column added by the non-destructive migration; the original result and language are never changed), so switching back and forth afterwards is instant and survives reloads; history titles follow the UI language. It is never automatic (each new version costs one model call); failures show a friendly message with Try again.

### Real Gemini validation (needs your key)
No Gemini key is configured in this repository, so live Gemini has **not** been tested. To run it: put `AI_PROVIDER=gemini` and `GEMINI_API_KEY=...` in `backend/.env` (never in chat or git), then from `backend/`:

```
.\.venv\Scripts\python.exe scripts\validate_gemini.py --photo C:\path\to\real_crop_photo.jpg --json gemini_results.json
```
It runs 4 cases (English text, Telugu text, Telugu + a REAL photo, mixed Telugu/English) through the existing provider and safety verifier, prints issue/uncertainty/actions/monitoring/precautions/escalation/latency per case and structural checks (valid fields, Telugu script present, no dosage/guarantee/lab claims via the verifier, uncertainty kept). It **refuses to run without a key**, never prints or writes the key, and does not fabricate a photo (without `--photo`, case 3 is reported as not executed). Whether an answer is agriculturally *grounded* still needs a human to read it; the script says so.
Precautionary change (not from a live failure): Gemini's output-token cap was raised to 8192 (thinking tokens count against it and Telugu is token-heavy) and a truncated/blocked reply now logs its finish reason (never the text).

### Manual microphone checklist (not automated; do this on Chrome/Edge, desktop or Android)
English: open Check crop → English → tap 🎤 → say a crop problem → ⏹ Stop → transcript appears → edit → Check my crop → normal result → 🔊 Listen.
Telugu: switch to తెలుగు → 🎤 → speak Telugu → ⏹ → check the Telugu transcript → edit if needed → submit → result → 🔊 వినండి (needs a Telugu voice on the device).
Also try: permission denied, no microphone, voice + photo, long speech (>60 s), stopping early, retry after a failure, switching language while recording.

### Phase 7 limitations
Browser speech recognition quality (especially Telugu) and Telugu voices vary by browser/device and have not been tested on a real microphone here; Chrome/Edge process audio in the vendor's cloud; no real-time/streaming voice, wake word or voice chat (by design).

**Phase 6 (this version):** English and Telugu (తెలుగు). The whole farmer journey (login, dashboard, farms, check form, photo, loading, result, history, errors) is available in Telugu, and new analyses can be written in Telugu.

## Phase 6: Telugu

**UI translation.** Two typed dictionaries, `frontend/src/i18n/en.ts` and `te.ts` (Telugu must have exactly the same shape, so a missing translation is a build error), plus `LanguageContext` (`useLang()`). No i18n library. JSX never branches on language. Helpers in `src/copy.ts` (errors, dates, weather rows, photo tips) read the active dictionary.
- **Switcher:** "English | తెలుగు" in the header (`role="group"`, `aria-pressed`, ≥44 px, visible focus). Switching re-renders in place: no navigation; form text, photo and selected farm are kept. `<html lang>` follows the UI language.
- **Persistence:** `localStorage["agrimind_language"]`, read/written in try/catch; missing, corrupt or blocked storage falls back to English.
- **Never translated:** backend values (`low/medium/high/some/unknown/good/limited/poor/not_provided`), ids, `input_type`, error codes, and what the farmer typed (crop, farm name, location, soil type are stored exactly as entered). Only the text *shown* for them is translated. The crop suggestions are ~14 "వరి (Rice)" style options that fill the English name; free Telugu/English/mixed typing still works.
- **Dates** use `Intl` (`te-IN`) with translated Today/Yesterday. **Weather** rows are built from numbers, so they are translated too.

**Telugu AI output (one model call, no DB change).** `POST /analyses` accepts an optional `language` (`en` default, or `te`; anything else is a 422). It is passed into `AnalysisContext.language`, stored in the existing `analyses.language` column, and is part of the idempotency fingerprint. 
- **Gemini:** the same single call; the system prompt now asks for natural, conversational Telugu (familiar farm words like fungus/virus/pest/photo may stay in English; no forced formal Telugu), keeps JSON keys and enum values in English, and repeats that every safety rule applies unchanged.
- **Demo provider:** hand-written Telugu for its rules (not a model, not native-reviewed), matching English *or* Telugu keywords (e.g. "ఆకులు పసుపు", mixed "నా టమాటా leaves yellow"), enum values unchanged.
- **Each analysis keeps the language it was written in.** Changing the UI language never translates or regenerates an old result; a Telugu UI showing an English result (or the reverse) shows a small note saying which language it is in. If a Telugu request comes back with no Telugu text, the page treats it as English.

**Telugu safety (conservative, additive).** The existing verifier still runs unchanged for every analysis. For Telugu there is an *extra* layer (`services/ai/safety.py`): Telugu units/digits and dosage/concentration patterns, Telugu certainty words, "lab-confirmed" claims, proven weather causation, unsafeguarded chemical instructions, and photo/weather claims with no photo/weather. Disclaimers such as "do not use X unless the label says…" pass only if they both prohibit/condition **and** point to a safeguard (label, officer, professional); otherwise the output is **rejected**, not repaired. Severity is never silently downgraded in Telugu.

**Limits (please read).** Telugu safety checking is pattern-based and **less thorough than English**; subtle unsafe wording, invented product names and unusual phrasing can slip through, and it can also reject harmless text. The prompt is the main guard. The Telugu UI text and the demo Telugu were written for this MVP and have **not** been reviewed by a native-speaking agronomist. Real Gemini Telugu quality has **not** been tested (no API key here); Gemini behaviour is covered with mocked HTTP only.

**Phase 4 (this version):** reliability and operations: bounded retries and deadlines for Gemini and weather, weather caching, idempotent retries, request IDs and structured logs, health endpoints, upload cleanup, lightweight rate limiting, and a farmer-friendly failure/retry experience.

## Phase 4: reliability & operations

> **Phase 4 remains synchronous because current analysis workloads do not justify background-job infrastructure.**
> One analysis is: validation → (optional) weather → one Gemini call → verification → one small DB write. Measured locally: DB write 6–17 ms, cold weather ≈ 2.2 s (live Open-Meteo), warm weather 0 ms, demo-provider AI ≈ 2 ms. The only unbounded-looking step (the model call) is now bounded by timeouts and a deadline, and the browser has its own timeout with a safe "Try again". No Redis, ARQ, Celery or worker was added. (Real Gemini latency has **not** been measured here; if it proves too slow in practice, that is the first thing to revisit.)

### Timeouts, retries (`services/http.py`)
- Every external call has split timeouts **and a hard wall-clock deadline per attempt** (httpx timeouts are per phase and DNS is unbounded, so the deadline is enforced by waiting on a worker thread).
- **Transient** failures (timeout, connection error, HTTP 408/429/5xx) are retried **at most once** with a short backoff, and not at all if the deadline is near. **Permanent** failures (bad key, bad request, unknown model, other 4xx, non-JSON, oversize response) are **never** retried.
- Gemini: connect 5 s / read 40 s, 55 s total including the single retry, 1 MB response cap. Weather: connect 1.5 s / read 2 s, **4 s total**.
- No silent fallback from Gemini to the demo provider: failures return a clean 503 (`ai_unavailable`).

### Weather resilience and caching (in memory, per process)
Coordinates are cached 24 h; "location not found" 10 min; weather per rounded lat/lon 10 min. Each weather result carries `fetched_at` (the real fetch time, also when served from cache) and the UI shows "updated HH:MM". After a *transient* weather failure, new weather fetches are skipped for 30 s (cache hits still work), so a dead weather service costs one slow analysis, not every analysis. AI results are never cached.

### Idempotent analysis submits
Send `Idempotency-Key` (8–64 chars `[A-Za-z0-9_-]`; invalid keys are ignored). Keys are **scoped to the authenticated user**. Same key + same input → the original analysis is returned (HTTP 200, `Idempotent-Replay: true`) with no new AI call. Same key + materially different input (farm, crop, symptoms or photo) → **409 `idempotency_conflict`**; the old result is never returned. Concurrent duplicates are serialised (one analysis). The web app reuses one key for "Try again", so a request that timed out in the browser but completed on the server is not duplicated. Limits: single process; a failed request does not consume its key.

### Request IDs, logging, errors
`X-Request-ID` is accepted if it matches `[A-Za-z0-9._-]{8,64}`, otherwise generated; it is returned on every response and included in logs and in 5xx error bodies. Log lines are `time level logger rid=… message`; one access line per request (method, path, status, duration, **no query string**), plus an `analysis_done` line with `provider`, `weather_ms`, `ai_ms`, `db_ms`, `total_ms`. Never logged: keys, passwords, cookies, prompts, image bytes. Every error body has `detail` (unchanged) and a stable `code`; 5xx also carry `request_id`.

### Health
- `GET /health`: liveness only, always 200 while the process is up.
- `GET /health/dependencies`: database (live), uploads dir, AI provider configured yes/no (no network call), weather reachability (cached 60 s). Gemini/weather problems report `degraded` and never fail the endpoint; only a database failure returns 503. No secrets or provider error text.

### Uploads and persistence
- Oversized bodies are rejected early (before spooling): image limit + 256 KB for `/analyses`, 64 KB elsewhere; the upload form is closed in `finally`.
- The image file is written **only after** a verified result exists and is removed if the DB write fails; storage failure → clean 503 and nothing stored. A startup sweep deletes upload files that no analysis references **and** that are older than 1 h (covers a crash between file write and commit).
- The browser shrinks large photos once (max 1600 px JPEG) so normal phone photos fit the 5 MB cap; a retry sends identical bytes.
- Server-side, images are never decoded (magic bytes + declared type only), so malformed images cannot crash image code; a provider rejection is a permanent error and nothing is stored.

### Rate limiting (in-process, no Redis)
Sliding windows with `429` + `Retry-After`: login per IP+email (15 / 5 min, cleared by a successful login) and per IP (100 / 5 min); register per IP (50 / h); analysis creation per user (40 / 10 min, checked before parsing or any AI/storage work). Defaults are generous for normal use. Tune/disable with `RATE_LIMIT_ENABLED`, `RL_LOGIN_PER_EMAIL`, `RL_LOGIN_PER_IP`, `RL_REGISTER_PER_IP`, `RL_ANALYSIS_PER_USER`. Per-process memory only (resets on restart, not shared); `X-Forwarded-For` is not trusted.

### Security review (specific protections and remaining limits)
Protections: owner-filtered queries on every farm/analysis/image access with identical 404s for foreign vs missing; images only via the authenticated endpoint (no public directory; random server-side names; path-traversal-safe refs; `nosniff`); bcrypt hashing, HttpOnly SameSite=Lax cookie; CORS limited to configured origins (verified: unknown origin gets no CORS headers); JSON errors never include traces; security headers (`nosniff`, `X-Frame-Options: DENY`, `no-referrer`, `no-store`); validated request IDs; secrets never logged.
Remaining limits: JWTs are stateless (logout clears the cookie but does not revoke a copied token; 12 h lifetime); registration reveals whether an email exists (409); `Secure` cookies are off for local HTTP; no email verification or password reset; EXIF/GPS metadata is kept in uploaded photos that are not resized (browser-shrunk photos lose it); `/docs` is exposed; rate limits are per-process; SQLite and local disk are single-node. This is an MVP, not a claim of production security.

### Phase 4 limitations
Real Gemini latency/behaviour is untested (no key). Cached weather can be up to 10 min old (it is labelled). The cooldown and caches are per process. A request abandoned by the browser keeps running on the server until it finishes (the idempotency key makes a retry safe).

**Phase 1:** register, login, farms, analysis, history, strict ownership.
**Phase 2:** a real AI provider (Gemini) behind the provider-agnostic interface, optional crop-photo analysis, weather context (Open-Meteo), richer structured results, and matching UI.
**Phase 3 (this version):** more deliberate reasoning: explicit observed/inferred/unknown evidence, alternative possibilities, immediate vs. monitoring steps, follow-up questions, qualitative uncertainty, and a deterministic safety-verification layer.

## Phase 3: reasoning pipeline
One synchronous request, **one model call**, no agents or queues:
```
AnalysisContext (+ up to 3 past analyses for the same farm & crop)
  -> evidence.py   build_evidence(): app-built OBSERVED / UNKNOWN ledger (no AI)
  -> provider      ONE call (Gemini or demo): the assessment, including the model's INFERRED reasoning
  -> service.py    validate (Pydantic) -> normalize
  -> safety.py     verify(): deterministic hard checks + a few rule-based repairs
  -> stored + shown
```
`services/ai/service.py::analyze()` keeps the same signature as before, so routers and Phase 1/2 code are unchanged.

### Result fields
Kept from earlier phases: `likely_issue, explanation, recommended_actions, precautions, uncertainty, severity, observations, when_to_seek_help`.
New, all optional (old stored results still load): `possible_alternatives` (max 3, each with `how_to_tell`), `evidence_for`, `evidence_against` (max 5), `unknowns` (max 5), `immediate_actions` ("what to do now"), `monitoring_steps` ("what to watch"), `follow_up_questions` (max 4), `uncertainty_level` (`low`/`some`/`high`, qualitative; no numeric confidence), `image_quality` and `image_guidance`.

### Safety verification (`services/ai/safety.py`, no extra AI call)
It validates structure, safety signals, uncertainty behaviour and obvious consistency. It **never diagnoses** and never invents agronomy.

*Rejected (nothing stored, nothing saved to disk, generic error shown, reason code logged only):*
dosage / concentration / dilution patterns; guaranteed diagnosis or outcome wording; "laboratory confirmed" claims; weather causation stated as fact; directing a chemical application while uncertain without a safeguard (label / officer / professional); claims about a photo or weather figures that were not provided; no usable actions.

*Disclaimers vs. prescriptions:* a sentence containing a dosage pattern is allowed only if it both prohibits/conditions it (do not, never, avoid, unless, without) **and** points to a safeguard (label, officer, professional, guidance). Example allowed: "Do not use a 10 ml/L dosage unless that exact amount is on the product label." Example rejected: "Never use more than 10 ml per litre." If it cannot tell, it rejects. Negated phrases like "does not guarantee a diagnosis" are allowed.

*Repaired from fixed rules (generic text only):* raise `uncertainty_level` when evidence is thin (very short description with no photo, or a poor photo); cap `severity: high` to `medium` when nothing in the input signals serious or spreading damage; add standard photo tips for a poor/limited photo; add up to 3 standard questions (how widespread, which leaves first, when it started) when evidence is thin and none were asked; clear image fields when no photo was provided.

### History as context
At most 3 recent analyses for the **same user, same farm and same crop** are added to the prompt, labelled as historical observations, not verified diagnoses. Other users' analyses can never be included. This context object is also what a future follow-up question can reuse (no chat is implemented).

### Phase 3 limitations
- Pattern-based safety checks catch obvious violations, not every subtle one. Invented product names and nuanced unsafe advice are handled by the prompt only; they cannot be reliably detected deterministically. It can also reject legitimate output that happens to match a pattern (the user sees a clean "couldn't produce a safe analysis" message).
- The repairs and checks do not judge agricultural correctness. Reasoning quality depends on the model; unit tests only prove the structured contract.
- The live Gemini prompt/schema has not been exercised against the real API (no key in this environment).

## AI providers
Selected with `AI_PROVIDER` in `backend/.env`:

| Value | What it is |
|---|---|
| `demo` (default) | `DemoAIProvider`: a deterministic keyword rule set. **Not an AI model**, cannot read images. Used for development, tests and offline demos. |
| `gemini` | `GeminiProvider`: Google Gemini over REST. Reads text, the photo and weather context, and returns schema-constrained JSON. |

- Only `services/ai/gemini_provider.py` knows Gemini's API. The router, DB and frontend only use `AnalysisContext` → `analyze()` → validated `AnalysisResult`.
- **No silent fallback.** If `gemini` is selected but the key is missing or the call fails, the API returns a clear 503 and stores nothing. It never substitutes demo output.
- The model output is always validated with Pydantic before it is stored or returned. Malformed output is rejected.
- The system prompt lives in the provider and separates OBSERVATION / LIKELY INTERPRETATION / RECOMMENDED NEXT STEP / UNCERTAINTY, forbids pesticide dosages and guaranteed diagnoses, and treats weather as context only.

### Enable Gemini locally
1. Create a key in Google AI Studio.
2. Edit `backend/.env` (never commit it, never paste it into chat):
   ```
   AI_PROVIDER=gemini
   GEMINI_API_KEY=your-key
   GEMINI_MODEL=            # optional; default gemini-2.5-flash
   ```
3. Restart the backend. The key stays on the backend only; the frontend never sees it.

> A live Gemini call has **not** been verified in this repository's test runs (no key was available). The provider is covered by mocked-HTTP tests only. Test it with your own key.

## Images
- Optional on the Analyze page: JPG, PNG or WebP, up to `MAX_IMAGE_MB` (default 5).
- Validated server-side by magic bytes **and** declared MIME (they must agree); the original filename is ignored; stored under a random UUID name in `backend/uploads/` (git-ignored, outside any static directory).
- Served **only** through `GET /analyses/{id}/image` (authenticated, owner-only, `nosniff`). Other users get the same 404 as a missing image.
- Storage sits behind `services/storage.py`, so cloud storage can replace it later.
- A photo is treated as supporting evidence, not a diagnosis.

## Weather
- Source: Open-Meteo (no API key). The farm's location text is geocoded (cached in memory) and current conditions, the last 3 days of rain and the next few days' forecast are fetched server-side.
- Weather is optional: if it is slow, unavailable or the location can't be found, the analysis still runs and the result says weather was unavailable.
- Weather is passed to the AI as context and is never accepted from the client.

## Database
SQLite with `create_all`, plus a tiny non-destructive `migrate()` that adds the new Phase 2 columns (`image_path`, `input_type`, `weather_json`, `weather_note`) to an existing database on startup. Phase 1 data is preserved and renders unchanged.

## Setup (Windows)
```powershell
cd backend
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env     # then set JWT_SECRET (32+ random chars):
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000

cd ..\frontend
npm install
npm run dev
```
- App: http://localhost:5173 (proxies `/api` → `http://localhost:8000`)
- API docs: http://localhost:8000/docs

## Environment variables (`backend/.env`)
`JWT_SECRET` (required), `DATABASE_URL`, `CORS_ORIGINS`, `COOKIE_SECURE`, `AI_PROVIDER`, `GEMINI_API_KEY`, `GEMINI_MODEL`, `MAX_IMAGE_MB`, `UPLOADS_DIR`, `LOG_LEVEL`, `RATE_LIMIT_ENABLED` and `RL_*` (all optional). See `backend/.env.example`. Frontend dev-only knobs: `VITE_PROXY_TARGET`, `VITE_ANALYSIS_TIMEOUT_MS`, `VITE_SLOW_AFTER_MS` (for testing the failure UI).

## Tests
```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
cd ..\frontend
npm run build      # type-check + production build
```
Tests use the demo provider, mock Gemini's HTTP, mock weather, and need no key or network.

## Security notes
bcrypt passwords; JWT in an HttpOnly SameSite=Lax cookie; every farm, analysis and image query is owner-filtered server-side; upload validation as above; CORS limited to configured origins; secrets only in `backend/.env`.

## Known limitations
- Gemini not verified live without a key (see above), including the Phase 3 prompt and response schema.
- Gemini is asked for English only; Telugu comes in a later phase.
- Weather is limited to what Open-Meteo returns for the geocoded location text; ambiguous place names may resolve to the wrong place.
- Demo provider ignores images.
- No rate limiting, email verification, password reset, or cloud storage yet.
- Image uploads are held in memory during the request (5 MB cap).
