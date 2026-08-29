FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MOCK_LLM_URL=http://mock-llm:8101 \
    MOCK_LLM_ALLOWED_HOSTS=mock-llm \
    MOCK_MCP_URL=http://mock-mcp-server:8103 \
    MOCK_MCP_ALLOWED_HOSTS=mock-mcp-server

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 appuser
COPY --chown=appuser:appuser app ./app

USER appuser
EXPOSE 8102
HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8102/health', timeout=2)" || exit 1
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8102", "--no-server-header"]
