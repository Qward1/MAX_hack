# syntax=docker/dockerfile:1.7

FROM node:24.21.0-bookworm-slim AS frontend-build
WORKDIR /build/miniapp
COPY miniapp/package.json miniapp/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci
COPY miniapp/ ./
RUN npm run build

FROM python:3.12.11-slim-bookworm AS python-build
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
WORKDIR /app
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir uv==0.12.6
COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

FROM python:3.12.11-slim-bookworm AS runtime
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    STATIC_DIR=/app/miniapp/dist
WORKDIR /app
COPY deploy/ca/russian_trusted_root_ca.crt /usr/local/share/ca-certificates/russian-trusted-root-ca.crt
RUN apt-get update \
    && apt-get install --no-install-recommends --yes ca-certificates \
    && update-ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && addgroup --system --gid 10001 domsignal \
    && adduser --system --uid 10001 --ingroup domsignal --home /nonexistent domsignal     && mkdir -p /app/output/max-record     && chown -R 10001:10001 /app/output
COPY --from=python-build --chown=domsignal:domsignal /app/.venv /app/.venv
COPY --chown=domsignal:domsignal alembic.ini ./
COPY --chown=domsignal:domsignal migrations/ ./migrations/
COPY --chown=domsignal:domsignal regions/ ./regions/
# F1 §3.2: эмулятор MAX для локального стенда (`MAX_TRANSPORT=record`):
# docker compose exec api python scripts/max_emulator.py …
COPY --chown=domsignal:domsignal scripts/max_emulator.py ./scripts/max_emulator.py
COPY --from=frontend-build --chown=domsignal:domsignal /build/miniapp/dist ./miniapp/dist/
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]
# Журнал доступа пишет приложение (`http_request`, без полного IP), не uvicorn.
CMD ["uvicorn", "domsignal.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
