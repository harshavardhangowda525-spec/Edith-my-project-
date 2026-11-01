# Single-container EDITH: builds the React app and serves it from the FastAPI backend.
# One URL for everything (no CORS setup). Used by render.yaml; works on any Docker host.

# ---- 1. build the frontend ----
FROM node:20-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# Empty VITE_API_URL = the app calls the same server it was loaded from.
ENV VITE_API_URL=""
RUN npm run build

# ---- 2. backend + built app ----
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    STATIC_DIR=/app/static ENVIRONMENT=production
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install -r requirements.txt
COPY backend/app ./app
COPY --from=web /web/dist ./static
RUN useradd --create-home --uid 10001 edith
USER edith
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import os,urllib.request,sys; sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/health').status==200 else 1)"
# Render (and most hosts) provide $PORT.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
