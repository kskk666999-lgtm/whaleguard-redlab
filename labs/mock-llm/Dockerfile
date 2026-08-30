FROM python:3.11.16-alpine3.23@sha256:c8d52af7e2645b587d464082ab29ff4ddc9fc514f353b4ed491b3ae8105d4200 AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apk upgrade --no-cache

FROM base AS builder
COPY requirements.txt /build/requirements.txt
RUN python -m pip install --no-cache-dir --no-compile \
      --target /opt/python -r /build/requirements.txt

FROM base AS runtime
ENV PYTHONPATH=/opt/python
RUN python -m pip uninstall --yes pip setuptools wheel jaraco.context \
    && rm -rf /usr/local/lib/python3.11/ensurepip /root/.cache \
    && addgroup --system --gid 10001 appuser \
    && adduser --system --disabled-password --no-create-home \
      --uid 10001 --ingroup appuser --shell /sbin/nologin appuser
COPY --from=builder /opt/python /opt/python
WORKDIR /app
COPY --chown=appuser:appuser app ./app

USER appuser
EXPOSE 8101
HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8101/health', timeout=2)" || exit 1
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8101", "--no-server-header"]
