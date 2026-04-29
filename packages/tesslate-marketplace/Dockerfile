# syntax=docker/dockerfile:1.7
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY app ./app
COPY scripts ./scripts
COPY alembic.ini ./
COPY alembic ./alembic
COPY spec ./spec

RUN pip install --no-cache-dir --upgrade pip wheel \
 && pip install --no-cache-dir .

# ---------------------------------------------------------------------------
# Final image
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BUNDLE_STORAGE_DIR=/data/bundles \
    HUB_ID_FILE=/data/.hub_id \
    ATTESTATION_KEY_PATH=/data/.attestation_key

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 marketplace \
    && mkdir -p /data/bundles \
    && chown -R marketplace:marketplace /data

COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /build/app /app/app
COPY --from=builder /build/scripts /app/scripts
COPY --from=builder /build/alembic /app/alembic
COPY --from=builder /build/alembic.ini /app/alembic.ini
COPY --from=builder /build/spec /app/spec

USER marketplace

EXPOSE 8800

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://localhost:8800/v1/manifest > /dev/null || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8800"]
