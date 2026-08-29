FROM python:3.11-slim AS runtime

ARG APP_UID=1000
ARG APP_GID=1000

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    WHALEGUARD_UPLOAD_DIR=/app/data/uploads \
    WHALEGUARD_CREDENTIALS_FILE=/app/.local/first-run-credentials.txt

RUN groupadd --gid "$APP_GID" whaleguard \
    && useradd --uid "$APP_UID" --gid "$APP_GID" --create-home \
      --shell /usr/sbin/nologin whaleguard
WORKDIR /app

COPY apps/api /app/apps/api
COPY packages/policy-engine /app/packages/policy-engine
COPY apps/worker /app/apps/worker
RUN python -m pip install --upgrade pip \
    && python -m pip install /app/packages/policy-engine /app/apps/worker /app/apps/api

WORKDIR /app/apps/api
RUN mkdir -p /app/data/uploads /app/.local && chown -R whaleguard:whaleguard /app
USER whaleguard

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

CMD ["sh", "-ec", "alembic upgrade head && exec uvicorn whaleguard_api.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips 127.0.0.1"]
