# WhaleGuard AgentArena local labs

This directory contains three deliberately constrained FastAPI services used by
AgentArena. They use fictional data only, expose no shell or arbitrary network
primitive, and are intended to be attached to a Docker private network without
published host ports.

| Service | Purpose | Suggested local-only port |
| --- | --- | --- |
| `mock-llm` | Deterministic OpenAI-compatible chat responses | `8101` |
| `mock-agent` | Knowledge lookup, allow-listed MCP calls, execution traces | `8102` |
| `mock-mcp-server` | Five harmless demo tools and MCP metadata | `8103` |

## Run locally

From a service directory, install its development requirements and bind only to
loopback:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8101
```

Use ports `8102` and `8103` for the agent and MCP service. When running the
agent outside Docker, set `MOCK_MCP_URL=http://127.0.0.1:8103` and optionally
`MOCK_LLM_URL=http://127.0.0.1:8101`.
The agent accepts MCP hosts only from `MOCK_MCP_ALLOWED_HOSTS` (default:
`mock-mcp-server,localhost,127.0.0.1,::1`). It never accepts a target URL in an
API request and never follows redirects.

Run all lab tests from this directory:

```powershell
py -m pytest mock-llm/tests mock-mcp-server/tests mock-agent/tests
```

The Docker images listen on container ports `8101`, `8102`, and `8103` in table
order. Compose should use these internal ports, an `internal: true` network, `read_only: true`,
`security_opt: ["no-new-privileges:true"]`, and must not publish these services
to a host interface.

The API run engine can call `POST /tasks` on `mock-agent` with
`{"task":"...","context":{},"test_case_id":"..."}`. The response includes
`status`, `output`, a full `trace`, summarized `tool_calls`, and
`policy_decisions`. `/v1/tasks` is an equivalent versioned route.
When `MOCK_LLM_URL` is configured, a completed safe tool run is summarized by
the local mock LLM; the URL is deployment-owned, allow-listed, and never read
from task input.
