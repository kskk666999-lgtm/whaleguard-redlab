FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

RUN addgroup --system whaleguard && adduser --system --ingroup whaleguard whaleguard
WORKDIR /app
COPY pyproject.toml /app/pyproject.toml
COPY src /app/src
RUN pip install --no-cache-dir .

USER whaleguard
HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=10 \
  CMD ["python", "-m", "whaleguard_worker.healthcheck"]
CMD ["python", "-m", "whaleguard_worker.main"]
