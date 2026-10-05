# AgriMind

AI-assisted crop decision support for farmers (English and Telugu). **It is decision support, not a professional diagnosis.**

A farmer describes a problem (typing or voice) and optionally adds a photo. AgriMind returns a clear verdict, what to do now, what to watch and when to get expert help. Tap-questions refine the answer, a follow-up compares with the earlier photo, a farm diary adds context, and weather hints are computed from real forecasts. Recurring problems and items needing attention are derived from the farmer's own checks.

## Stack
- Backend: FastAPI, SQLAlchemy, SQLite, JWT in an httpOnly cookie. AI provider is `demo` (offline, for development) or `gemini`.
- Frontend: Vite, React, TypeScript, Tailwind, React Router. All text lives in `frontend/src/i18n/{en,te}.ts`.

## Run locally
```
cd backend && py -3.13 -m venv .venv && .venv\Scripts\pip install -r requirements.txt
copy .env.example .env      # set JWT_SECRET
.venv\Scripts\uvicorn app.main:app --port 8000
cd frontend && npm install && npm run dev
```

## Test
```
cd backend && pytest
cd frontend && npm run build && npm run test:speech test:overview test:insights test:decision test:proactive test:round2
```
(run each `test:*` script). Browser suites live outside the repo in the development scratch area.

## Deploy
See **[DEPLOYMENT.md](DEPLOYMENT.md)**: Docker, Caddy HTTPS, production safety checks, migration and backup commands, pilot checklist and known limits. The production image has not yet been built or run on a server.

## History
The per-phase build notes are in [docs/PHASES.md](docs/PHASES.md).

## Agentic investigation (optional)
A LangGraph pipeline of specialist steps (planner, crop analysis, farm memory, environment, trusted-document retrieval, decision support, safety gate) is available behind `AGENTIC_ANALYSIS_ENABLED=false` (default off). See DEPLOYMENT.md section 11 and `python -m app.agentic_compare`.
