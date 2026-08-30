FROM python:3.11.16-alpine3.23@sha256:c8d52af7e2645b587d464082ab29ff4ddc9fc514f353b4ed491b3ae8105d4200 AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apk upgrade --no-cache

FROM base AS builder
WORKDIR /build
COPY pyproject.toml /build/pyproject.toml
COPY src /build/src
RUN python -m pip install --no-cache-dir --no-compile --target /opt/python /build

FROM base AS runtime
ENV PYTHONPATH=/opt/python
RUN python -m pip uninstall --yes pip setuptools wheel jaraco.context \
    && rm -rf /usr/local/lib/python3.11/ensurepip /root/.cache \
    && addgroup --system whaleguard \
    && adduser --system --disabled-password --no-create-home \
      --ingroup whaleguard --shell /sbin/nologin whaleguard
COPY --from=builder /opt/python /opt/python
WORKDIR /app

USER whaleguard
HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=10 \
  CMD ["python", "-m", "whaleguard_worker.healthcheck"]
CMD ["python", "-m", "whaleguard_worker.main"]
