# --- frontend build ---
FROM node:22-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- backend runtime ---
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.9.10 /uv /bin/uv
# yt-dlp needs a JavaScript runtime to unlock YouTube's audio streams.
COPY --from=denoland/deno:bin-2.9.7 /deno /usr/local/bin/deno
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --frozen --no-dev
# YouTube changes often and yt-dlp follows quickly: always ship its latest release.
# `docker compose build --no-cache` picks up a newer one.
RUN uv pip install --upgrade "yt-dlp[default]"
COPY backend/app ./app
COPY --from=frontend /app/frontend/dist /app/frontend/dist

ENV JAM_DATA_DIR=/data
VOLUME /data
EXPOSE 8000
# One worker only: the queue lives in memory.
CMD [".venv/bin/uvicorn", "--factory", "app.main:create_app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
