# LoreOS: one image for the api, the worker and the migration. Build: docker compose build.

# The UI, built once and copied into the Python image; Node never ships.
FROM node:22-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.14-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.3 /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/backend/.venv \
    TIKTOKEN_CACHE_DIR=/app/tiktoken \
    FASTEMBED_CACHE_PATH=/app/fastembed \
    PATH=/app/backend/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --locked --no-dev
COPY backend/ ./
# main.DIST is the repo root's frontend/dist, two directories above loreos/main.py.
COPY --from=frontend /app/frontend/dist /app/frontend/dist
# The chunker's encoding, fetched now so a container never downloads it at runtime.
RUN python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"
# The reranker model (decision 0010), for the same reason: the api loads it at startup since the default mode reranks.
RUN python -c "from loreos import rerank; rerank.model()"
RUN useradd --create-home --uid 10001 loreos && chown -R loreos:loreos /app/fastembed
USER loreos
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "loreos.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
