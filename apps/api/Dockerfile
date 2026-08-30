FROM python:3.11.16-alpine3.23@sha256:c8d52af7e2645b587d464082ab29ff4ddc9fc514f353b4ed491b3ae8105d4200 AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apk upgrade --no-cache

FROM base AS builder
WORKDIR /build

COPY apps/api/pyproject.toml apps/api/README.md /build/apps/api/
COPY apps/api/src /build/apps/api/src
COPY packages/policy-engine/pyproject.toml /build/packages/policy-engine/pyproject.toml
COPY packages/policy-engine/src /build/packages/policy-engine/src
COPY apps/worker/pyproject.toml /build/apps/worker/pyproject.toml
COPY apps/worker/src /build/apps/worker/src
RUN python -m pip install --no-cache-dir --no-compile --target /opt/python \
      /build/packages/policy-engine /build/apps/worker /build/apps/api

FROM base AS runtime

ARG APP_UID=1000
ARG APP_GID=1000

ENV PYTHONPATH=/opt/python \
    WHALEGUARD_UPLOAD_DIR=/app/data/uploads \
    WHALEGUARD_CREDENTIALS_FILE=/app/.local/first-run-credentials.txt

RUN python -m pip uninstall --yes pip setuptools wheel jaraco.context \
    && rm -rf /usr/local/lib/python3.11/ensurepip /root/.cache \
    && addgroup --system --gid "$APP_GID" whaleguard \
    && adduser --system --disabled-password --no-create-home \
      --uid "$APP_UID" --ingroup whaleguard --shell /sbin/nologin whaleguard

COPY --from=builder /opt/python /opt/python
COPY apps/api/alembic.ini /app/apps/api/alembic.ini
COPY apps/api/alembic /app/apps/api/alembic
WORKDIR /app/apps/api
RUN mkdir -p /app/data/uploads /app/data/reports /app/.local \
    && chown -R whaleguard:whaleguard /app
USER whaleguard

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

CMD ["sh", "-ec", "python -m alembic upgrade head && exec python -m uvicorn whaleguard_api.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips 127.0.0.1"]
