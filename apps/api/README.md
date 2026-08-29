# WhaleGuard AI RedLab API

FastAPI + SQLAlchemy 2 backend for the WhaleGuard AI security evaluation platform.

## Development

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\uvicorn.exe whaleguard_api.main:app --host 127.0.0.1 --port 8000
```

The first startup creates a random administrator password and atomically writes it to
`.local/first-run-credentials.txt` with restrictive permissions. The startup log only prints
`WHALEGUARD_INITIAL_CREDENTIALS_FILE=<path>`; it never prints the password. Existing credentials
files are never overwritten and the repository ignores `.local/`.

The API is served under `/api/v1`; OpenAPI is available at `/docs` in development.

## Model runs and evaluation

`POST /api/v1/runs` accepts either an Agent target or `target_type: "model"` with a
`model_channel_id`/`target_id`. Model runs use the configured OpenAI-Compatible
`base_url + /chat/completions` endpoint through Scope Guard. API keys are decrypted only for the
outbound request and are never returned by the API.

Deterministic rules are always the default (`evaluation_mode: "rules"`). Optional LLM Judge use
must be explicitly requested with `evaluation_mode: "rules_with_llm_judge"` and a
`judge_model_channel_id`; an unavailable or invalid Judge response falls back to the rule score.

The image remains non-root. On Linux, Compose can align bind-mount ownership by passing
`APP_UID`/`APP_GID` build arguments (both default to `1000`). Container startup first runs
`alembic upgrade head` and then starts Uvicorn.
