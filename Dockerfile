# syntax=docker/dockerfile:1

# --------------------------------------------------------------------------- #
# Stage 1 — build the React/Vite frontend.
# Vite emits the bundle into ../app/static (see vite.config.ts), so after the
# build the assets live at /src/app/static, ready to be copied into the runtime.
# --------------------------------------------------------------------------- #
FROM node:24-slim AS web
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --------------------------------------------------------------------------- #
# Stage 2 — Python runtime with ffmpeg, deps installed by uv.
# --------------------------------------------------------------------------- #
FROM python:3.12-slim AS runtime

# ffmpeg is required for muxing/extraction; ca-certificates for HTTPS to YouTube.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# uv binary, copied from the official image.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PATH="/app/.venv/bin:$PATH"

# Install dependencies first (cached unless the lockfile changes).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# Application code and the built frontend.
COPY app/ ./app/
COPY --from=web /src/app/static ./app/static

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health').status==200 else 1)"

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
