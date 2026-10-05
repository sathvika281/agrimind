# AgriMind: one image = the built website + the API (same origin). Not built on the dev machine (no Docker there):
# build it on the server or in CI:  docker build -t agrimind .
# ---- 1. build the website ----
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- 2. the API + the built website ----
FROM python:3.13-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 APP_ENV=production \
    DATABASE_URL=sqlite:////data/agrimind.db UPLOADS_DIR=/data/uploads FRONTEND_DIST=/app/frontend-dist
WORKDIR /app
COPY backend/requirements.lock ./requirements.lock
RUN pip install --no-cache-dir -r requirements.lock
COPY backend/app ./app
COPY backend/knowledge ./knowledge
COPY --from=web /web/dist ./frontend-dist
RUN useradd --create-home --uid 10001 agrimind && mkdir -p /data/uploads && chown -R agrimind /data
USER agrimind
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"
# One worker: rate limits and idempotency locks are in-process (see DEPLOYMENT.md before scaling out).
CMD ["uvicorn", "app.asgi_prod:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]
