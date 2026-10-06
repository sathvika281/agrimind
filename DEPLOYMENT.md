# AgriMind deployment runbook

This is the checklist for putting AgriMind in front of real farmers. Everything marked **YOU** needs a decision, an account or a human; the code, tools and tests for the rest are in this repository.

**Status of this release:** code, tooling and docs are complete and tested on a development machine. Not yet done: building the Docker image (Docker was not available where it was prepared), applying the database migration to your live database, judging answer quality on real photos, and any real-farmer use. Do the **Pilot checklist** before opening it publicly.

---

## 1. What you deploy

One container serves **both** the website and the API on the same origin (`app/asgi_prod.py`): `/api/*` is the API, everything else is the website. A small proxy (Caddy, included) adds HTTPS.

```
browser --HTTPS--> Caddy --> app container (uvicorn, 1 worker)
                                 |-- /data/agrimind.db   (SQLite, on a persistent volume)
                                 '-- /data/uploads/      (crop photos, on the same volume)
```

SQLite with backups is fine for a pilot of a few hundred farmers. Move to a hosted database before you need more than one server process (see *Known limits*).

## 2. Before the first deploy (YOU)

1. **Host:** any Linux server that runs Docker (a small VPS is enough). Point a **domain name** at its IP address.
2. **Gemini key:** create a **new** key in Google AI Studio. The key that was pasted in chat during development must be treated as exposed: revoke it.
3. **Secrets:** copy `.env.production.example` to `.env.production` on the server and fill it in (never commit it, never paste it in chat):
   - `JWT_SECRET`: 48+ random characters: `python -c "import secrets; print(secrets.token_urlsafe(48))"`
   - `GEMINI_API_KEY`: the new key
   - leave `COOKIE_SECURE=true`, `AI_PROVIDER=gemini`, `CORS_ORIGINS` empty (same origin)
4. Optional: set `VITE_CONTACT_EMAIL=you@example.com` when building the website, so the Privacy page shows a real contact address (until then it says the operator will add one).

The app **refuses to start** in production with a short secret, non-secure cookies, an http CORS origin, the demo AI provider, a missing Gemini key or rate limits turned off. That is deliberate.

## 3. First deploy of a NEW (empty) database

```
git clone <your repo> && cd agrimind
cp .env.production.example .env.production      # then edit it
echo "DOMAIN=agrimind.example.com" > .env
docker compose up -d --build
docker compose logs -f app                       # wait for: Application startup complete
curl https://agrimind.example.com/health         # {"status":"ok"}
```
Create the first account in the browser. Tables are created automatically on first start.

## 4. Moving your EXISTING database (the one from development) (YOU)

Your current `backend/agrimind.db` has the older structure. The migration only **adds** nullable columns and one new table; it never edits or deletes existing rows. Use the tool, which backs up first and verifies after:

```
# 1) Work on a COPY first, on any machine with the code:
cp backend/agrimind.db /tmp/try.db
cd backend && python -m app.cli migrate --db /tmp/try.db --backup-dir /tmp/backups
#    expect: "Migration finished and verified", rows unchanged, added columns listed

# 2) On the server, stop the app, then migrate the real file (it makes its own verified backup first):
docker compose stop app
docker compose run --rm --no-deps app python -m app.cli migrate --db /data/agrimind.db --backup-dir /data/backups
docker compose up -d app
```
If anything differs the tool **restores the backup itself** and exits with an error. To undo by hand: `python -m app.cli restore --backup <file> --db /data/agrimind.db --yes` (the current file is kept as `.before-restore`). Keep the pre-migration backup until you have checked the app.

Copy `backend/uploads/*` into the volume's `uploads/` folder so existing photos still show.

## 5. Backups (YOU: schedule it)

```
docker compose exec app python -m app.cli backup --db /data/agrimind.db --uploads /data/uploads --out /data/backups
```
Run it daily (cron on the server) and copy the archives **off the server**. Delete backups older than 30 days (the Privacy page says backups are kept only for a limited time). Test a restore once, on a copy, before you rely on it.

## 6. Monitoring

- Uptime: an external monitor on `https://<domain>/health` (expects `{"status":"ok"}`).
- Logs: `docker compose logs app`. Useful lines: `request method=... status=...`, `analysis_done`, `analysis_failed code=...`, `gemini_failed`. Logs contain request ids but never keys, passwords, cookies or photo bytes.
- Watch for a rise in `analysis_failed`, `429` rate-limit responses and `gemini_failed kind=permanent` (usually a bad or revoked key).
- Disk: the volume holds the database and photos; alert before it fills.

## 7. Rotating the Gemini key

Edit `GEMINI_API_KEY` in `.env.production` on the server, then `docker compose up -d app`. Revoke the old key in Google AI Studio. The key lives only in that file and the container environment, never in the website or the logs.

## 8. Updating the app

`git pull && docker compose up -d --build`. Database changes ship as additive migrations applied at start; take a backup first (section 5). Roll back by checking out the previous version and restoring the backup if the database was changed.

## 9. Pilot checklist (do this before a public launch) (YOU)

- [ ] Run **15-20 real crop photos** (several crops, several symptoms, some bad photos) through the live app. Does the verdict match what an agronomist would say? Note wrong, vague or overconfident answers.
- [ ] Ask a **Telugu-speaking agronomist** to read the Telugu screens, results and the privacy text.
- [ ] Have **2-5 farmers** use it on their phones (Chrome/Android) on poor signal; watch where they get stuck.
- [ ] Check voice input and Listen on a real phone (needs a Telugu voice for Telugu).
- [ ] Read the Privacy page; confirm it matches what you actually do; add your contact email; get legal review if you operate commercially.
- [ ] Do one **restore test** from a backup.
- [ ] Confirm `robots.txt` still blocks search engines until you decide to go public.

## 10. Known limits (be honest with users and yourself)

- **Not a diagnosis.** Decision support only; answers can be wrong. The app says so and tells users when to ask an expert.
- **One server process.** Rate limits, idempotency locks and the weather cache live in memory. Do not run several workers/replicas until these move to a shared store (Redis) and the database to PostgreSQL.
- **No notifications** (SMS/WhatsApp/push), no background jobs, no satellite or sensor data. "Needs your attention" appears only when the app is opened.
- **Logins last 12 hours and can't be revoked early** (stateless tokens). Deleting an account stops it working immediately (the user no longer exists).
- **Weather** comes from Open-Meteo's free tier (non-commercial use). A commercial service needs their paid plan or another provider.
- **Recurrence/trend counts** group checks by the AI's wording; the same problem described differently counts separately.
- Weather hint thresholds (humidity 80%, rain 5/40 mm, 35/40 °C) are general rules of thumb and should be reviewed by an agronomist for your region.
- The Docker image has not been built on the author's machine; the first build on your server is the first test of it.

## 11. Agentic investigation (optional, OFF by default)

`AGENTIC_ANALYSIS_ENABLED=true` switches new checks from the single-call pipeline to a LangGraph investigation: Investigation (planner) -> Crop Analysis (model) -> Farm Memory -> Environment -> Knowledge (retrieval from `backend/knowledge`) -> Decision Support (model) -> Safety gate (existing verifier + policy checks, bounded retries, fails closed). It makes **two** model calls per check instead of one (roughly double the time and cost), and it may answer a vague description with a question instead of a guess.

- **Do not turn it on** until you have compared answers on real photos with the real model: `python -m app.agentic_compare` (runs both pipelines on the same input against a throw-away in-memory database; it never opens your real database).
- **No database change.** New optional fields (`sources`, `agent_steps`) live inside the stored result JSON.
- **Knowledge base:** `backend/knowledge/sources.json` lists every source considered (included or excluded, with the reason) and `documents.jsonl` holds the text chunks. Refresh with `python -m app.rag.discover candidates.json` (validates and records candidate URLs) then `python -m app.rag.ingest`. Pages are fetched over verified HTTPS only; sentences about chemicals, doses or spraying are removed at ingestion. A page that changed upstream is flagged `update_available` and is not applied until you run `ingest --accept-updates` (the old chunks are archived).
- **Limits:** retrieval is lexical (BM25), so wording matters; the current corpus is TNAU (Tamil Nadu) pages only (see the manifest for what could not be reached); sources are shown only when the model actually relied on a retrieved passage.

## 12. GitHub + Render (one service for website and backend)

- The repo is public, so it holds **no secrets and no third-party page text**: `.env`, databases and uploads are git-ignored, and `backend/knowledge/documents.jsonl` is rebuilt on the server with `python -m app.rag.ingest` (the audited `sources.json` is committed). Without it the app simply says "no knowledge base".
- **One service does everything.** The Docker image builds the website and serves it together with the API (`app/asgi_prod.py`), so a single Render service is enough: one URL, and the login cookie stays first-party. No Vercel needed.
- **Deploy:** Render -> New -> Blueprint -> pick this repo (it reads `render.yaml`). Set `GEMINI_API_KEY` (a NEW key) in the Render dashboard. Keep `AGENTIC_ANALYSIS_ENABLED=false` for the first deploy. Check `https://<service>.onrender.com/health`.
- **Paid disk required:** SQLite and photos live on the persistent disk mounted at `/data`; without a disk they are lost on every deploy.
- The Docker image has not been built on the author's machine, so Render's first build is its first test.
- Vercel can host only the website, not this backend (no persistent disk, SQLite and photos would be lost), so it is not used.

## 13. Weather (OpenWeather + Open-Meteo backup)

- **Key:** create a free account at openweathermap.org, copy the API key (a new key can take up to about 2 hours to start working) and set `OPENWEATHER_API_KEY` in Render's Environment tab. The key lives only there (and in your local git-ignored `.env`), never in git or the website. Without a key the app uses Open-Meteo only.
- **Order:** `WEATHER_PROVIDER=auto` (default) tries OpenWeather first and falls back to Open-Meteo on any failure; `openweather` or `openmeteo` force one provider.
- **Free plan limit:** OpenWeather's free plan has no rain history, so "rain in the last 3 days" shows "Not available" when OpenWeather answered. Everything else (temperature, humidity, wind, rain ahead) comes from it.
- **Timeouts:** weather for an analysis keeps a short 4 s budget (it must never slow a check); the Weather page waits up to 10 s, which is what slow cloud networks need.
- **Weather tab tips:** `GET /farms/{id}/weather/tips` returns coded, non-chemical coping tips and the real measured conditions behind them (thresholds: `services/weather_risk.py` plus wind >= 30 km/h and cold night <= 10 C in `services/weather_tips.py`). They are general rules of thumb: have an agronomist review them for your region.
- **If weather still fails on Render:** the log line `weather request failed category=...` (or `weather provider failed ...`) says why. Share only that line, never the key.

## 14. Farm plan (Adaptive Farm Planning)

- **What it is:** its own page (`/plan`, sidebar "Farm plan"), separate from Overview and Insights. One deterministic planning agent (`backend/app/services/planning/agent.py`) builds a plan from the real daily forecast, the farm's crop facts, the latest stored crop check and the farmer's own planned activities, and re-plans when something material changes. No model call, no soil or market data, nothing simulated.
- **When it re-plans:** on opening the page, on "Check for changes", after the farmer edits their planned activities or field condition, and after a new crop check. A new version is stored only if the forecast changed materially (rain crossing 10 mm or moving by 10 mm, max temperature crossing 35 C or moving by 5 C), a new check exists, or the inputs changed. There are no background jobs or notifications.
- **Weather:** uses the same OpenWeather-first/Open-Meteo-backup chain; the daily forecast reaches about 5 days. If the forecast can't be fetched the last real snapshot is kept (and said so); with no forecast at all, weather steps are left out.
- **Database:** one new additive table, `farm_plans` (plan versions, kept per farm, newest 100). `create_all` adds it automatically when a server starts on a database; `python -m app.cli migrate` lists it under new tables. It is included in "Download my data" and deleted with the account.
- **Review before real use:** the thresholds (`SIGNIFICANT_RAIN_MM`, `HOT_C`, ...) are general rules of thumb for an agronomist to review, and the Telugu text for a Telugu speaker.

## 15. Crop Economics & Selling Intelligence

A separate top-level page (`/economics`, sidebar item **Economics** under DECIDE). It never needs a model call and never touches the network.

- **What it uses:** the farm profile (crop, planting date), the latest crop check and the diary through the shared farm context, plus the farmer's own numbers: area, yield range, marketable share, costs and market quotes (market, date, price, distance, transport). Assumptions are stored in one table, `farm_economics` (one row per farm, owner-scoped, included in `/auth/me/export`, removed on account delete). The farm profile itself is never changed.
- **What is real / not:** all figures are deterministic arithmetic over the farmer's inputs. Missing inputs show as "Not available" or "Needs your estimate" and are never defaulted or counted as zero. **No live mandi price feed is connected, and there is no price forecast or export-price source**: the page says so.
- **Agent:** one Economics agent (deterministic, structured output, no LLM) run by a LangGraph workflow whose executed steps are recorded and shown on the page.
- **`ECONOMICS_DEMO_MARKET=true`** (default off) adds clearly labelled **DEMO DATA** example prices so the screen can be tried without typing quotes. Never enable it for farmers' real use.
