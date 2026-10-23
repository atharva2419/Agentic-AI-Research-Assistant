# One image: the built React UI is served by the FastAPI app.
#   docker compose up --build        then open http://localhost:8000

# --- Stage 1: build the UI ---------------------------------------------------------------------
FROM node:24-alpine AS ui
WORKDIR /ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci
COPY ui/ ./
RUN npm run build

# --- Stage 2: the Python app -------------------------------------------------------------------
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.4 /uv /uvx /bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

# Dependencies first, so code changes don't reinstall them (Docker layer caching).
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

COPY alembic.ini ./
COPY app ./app
COPY blueprints ./blueprints
COPY prompts ./prompts
COPY migrations ./migrations
COPY --from=ui /ui/dist ./ui/dist

# Run as a non-root user; sessions, memory and exported reports live on the /data volume.
RUN useradd --create-home appuser && mkdir /data && chown appuser /data
USER appuser
ENV DATA_DIR=/data \
    DATABASE_URL=sqlite:////data/research.db

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
