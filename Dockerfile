# Build the React/Vite portals into static assets.
FROM node:22.16.0-alpine AS frontend-build
WORKDIR /build/frontend
COPY frontend/package.json frontend/.npmrc ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# Production FastAPI service.
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 libgl1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system app && useradd --system --gid app --home-dir /app app
COPY requirements-prod.txt .
RUN python -m pip install --upgrade pip && python -m pip install -r requirements-prod.txt
COPY --chown=app:app app ./app
COPY --chown=app:app alembic ./alembic
COPY --chown=app:app alembic.ini pyproject.toml README.md ./
COPY --from=frontend-build --chown=app:app /build/frontend/dist ./frontend/dist
USER app
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
