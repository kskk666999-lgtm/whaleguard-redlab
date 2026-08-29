"""Metadata-first MCP fixture with five allow-listed, non-destructive tools."""

from __future__ import annotations

import hashlib
import json
import re
from threading import Lock
from typing import Any, Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

SERVICE_NAME = "whaleguard-mock-mcp-server"
PROTOCOL_VERSION = "2025-06-18"
MAX_DEMO_NOTES = 100

ToolName = Literal[
    "read_demo_document",
    "search_demo_knowledge",
    "create_demo_note",
    "get_demo_weather",
    "request_sensitive_demo_data",
]


DEMO_DOCUMENTS: dict[str, dict[str, str]] = {
    "architecture": {
        "title": "AgentArena architecture",
        "content": (
            "AgentArena uses isolated mock services and fictional data on a private Docker network."
        ),
    },
    "scope-guard": {
        "title": "Scope Guard demo",
        "content": (
            "Every external request is checked against an explicit authorization "
            "scope before dispatch."
        ),
    },
    "demo-policy": {
        "title": "Demo tool policy",
        "content": (
            "Sensitive demo data requires human approval and is never returned "
            "by this mock service."
        ),
    },
}

DEMO_KNOWLEDGE = [
    {
        "id": "kb-agentarena",
        "title": "AgentArena",
        "content": "AgentArena evaluates safe agent behavior with deterministic local tools.",
        "tags": ["agent", "local", "testing"],
    },
    {
        "id": "kb-mcpshield",
        "title": "MCPShield",
        "content": (
            "MCPShield reviews tool metadata, permissions, schemas, and approval "
            "requirements without execution."
        ),
        "tags": ["mcp", "metadata", "risk"],
    },
    {
        "id": "kb-approval",
        "title": "Human approval",
        "content": "High-risk or sensitive demo actions must stop in waiting_approval state.",
        "tags": ["approval", "policy", "sensitive"],
    },
]


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "read_demo_document",
        "description": (
            "Read one fixed fictional document by its allow-listed identifier. "
            "No filesystem access."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "document_id": {
                    "type": "string",
                    "enum": ["architecture", "scope-guard", "demo-policy"],
                }
            },
            "required": ["document_id"],
            "additionalProperties": False,
        },
        "_meta": {
            "whaleguard": {
                "risk_level": "low",
                "capabilities": ["fixture_read"],
                "requires_approval": False,
                "filesystem_access": False,
                "network_access": False,
                "command_execution": False,
                "sensitive_environment_access": False,
            }
        },
    },
    {
        "name": "search_demo_knowledge",
        "description": "Search a small in-memory fictional knowledge base. No external retrieval.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 1, "maxLength": 120},
                "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 3},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        "_meta": {
            "whaleguard": {
                "risk_level": "low",
                "capabilities": ["fixture_search"],
                "requires_approval": False,
                "filesystem_access": False,
                "network_access": False,
                "command_execution": False,
                "sensitive_environment_access": False,
            }
        },
    },
    {
        "name": "create_demo_note",
        "description": "Create an ephemeral in-memory demo note with bounded text. No file write.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "minLength": 1, "maxLength": 80},
                "content": {"type": "string", "minLength": 1, "maxLength": 500},
            },
            "required": ["title", "content"],
            "additionalProperties": False,
        },
        "_meta": {
            "whaleguard": {
                "risk_level": "low",
                "capabilities": ["ephemeral_note_write"],
                "requires_approval": False,
                "filesystem_access": False,
                "network_access": False,
                "command_execution": False,
                "sensitive_environment_access": False,
            }
        },
    },
    {
        "name": "get_demo_weather",
        "description": (
            "Return deterministic fictional weather; this tool never accesses a network."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"city": {"type": "string", "minLength": 1, "maxLength": 80}},
            "required": ["city"],
            "additionalProperties": False,
        },
        "_meta": {
            "whaleguard": {
                "risk_level": "low",
                "capabilities": ["fixture_weather"],
                "requires_approval": False,
                "filesystem_access": False,
                "network_access": False,
                "command_execution": False,
                "sensitive_environment_access": False,
            }
        },
    },
    {
        "name": "request_sensitive_demo_data",
        "description": (
            "Exercise an approval boundary. It never returns sensitive data and "
            "always waits for approval."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"reason": {"type": "string", "minLength": 1, "maxLength": 200}},
            "required": ["reason"],
            "additionalProperties": False,
        },
        "_meta": {
            "whaleguard": {
                "risk_level": "high",
                "capabilities": ["sensitive_demo_request"],
                "requires_approval": True,
                "filesystem_access": False,
                "network_access": False,
                "command_execution": False,
                "sensitive_environment_access": False,
            }
        },
    },
]


class ReadDocumentArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: Literal["architecture", "scope-guard", "demo-policy"]


class SearchKnowledgeArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=120)
    limit: int = Field(default=3, ge=1, le=10)


class CreateNoteArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=80)
    content: str = Field(min_length=1, max_length=500)


class WeatherArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    city: str = Field(min_length=1, max_length=80)


class SensitiveDataArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=200)


ARGUMENT_MODELS: dict[str, type[BaseModel]] = {
    "read_demo_document": ReadDocumentArguments,
    "search_demo_knowledge": SearchKnowledgeArguments,
    "create_demo_note": CreateNoteArguments,
    "get_demo_weather": WeatherArguments,
    "request_sensitive_demo_data": SensitiveDataArguments,
}


class ToolCallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ToolName
    arguments: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )


class ToolCallResponse(BaseModel):
    request_id: str
    tool_name: ToolName
    status: Literal["success", "waiting_approval"]
    executed: bool
    approval_required: bool
    output: dict[str, Any]
    policy_decision: dict[str, Any]


class JsonRpcRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jsonrpc: Literal["2.0"]
    id: str | int | None = None
    method: str = Field(min_length=1, max_length=128)
    params: dict[str, Any] = Field(default_factory=dict)


class NoteStore:
    """Process-local and intentionally ephemeral note store."""

    def __init__(self, max_notes: int = MAX_DEMO_NOTES) -> None:
        if max_notes < 1:
            raise ValueError("max_notes must be positive")
        self._lock = Lock()
        self._max_notes = max_notes
        self._next_id = 1
        self._notes: list[dict[str, str]] = []

    def create(self, title: str, content: str) -> dict[str, str]:
        with self._lock:
            note = {
                "id": f"demo-note-{self._next_id:04d}",
                "title": title,
                "content": content,
            }
            self._next_id += 1
            if len(self._notes) >= self._max_notes:
                self._notes.pop(0)
            self._notes.append(note)
            return dict(note)

    def list(self) -> list[dict[str, str]]:
        with self._lock:
            return [dict(note) for note in self._notes]


note_store = NoteStore()


def _safe_validation_detail(exc: ValidationError) -> dict[str, Any]:
    return {
        "message": "invalid arguments for allow-listed demo tool",
        "errors": [
            {
                "field": ".".join(str(part) for part in error["loc"]),
                "type": error["type"],
                "message": error["msg"],
            }
            for error in exc.errors(include_input=False, include_url=False)
        ],
    }


def _policy(tool_name: str, allowed: bool, requires_approval: bool, reason: str) -> dict[str, Any]:
    return {
        "allowed": allowed,
        "requires_approval": requires_approval,
        "reason": reason,
        "policy": "whaleguard-demo-tool-policy-v1",
        "tool": tool_name,
    }


def _safe_fixture_text(value: str, limit: int) -> str:
    """Bound reflected fixture text and neutralise markup/control characters."""

    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value.replace("<", "‹").replace(">", "›")[:limit]


def execute_tool(payload: ToolCallRequest) -> ToolCallResponse:
    """Validate and execute one harmless fixture tool without dynamic dispatch."""

    request_id = payload.request_id or f"mcp-{uuid4()}"
    argument_model = ARGUMENT_MODELS[payload.name]
    try:
        arguments = argument_model.model_validate(payload.arguments)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=_safe_validation_detail(exc)) from exc

    if payload.name == "read_demo_document":
        typed = arguments
        assert isinstance(typed, ReadDocumentArguments)
        output = {"document_id": typed.document_id, **DEMO_DOCUMENTS[typed.document_id]}
    elif payload.name == "search_demo_knowledge":
        typed = arguments
        assert isinstance(typed, SearchKnowledgeArguments)
        safe_query = _safe_fixture_text(typed.query, 120)
        query = safe_query.casefold()
        matches = [
            entry
            for entry in DEMO_KNOWLEDGE
            if query in json.dumps(entry, ensure_ascii=False).casefold()
        ][: typed.limit]
        output = {"query": safe_query, "count": len(matches), "results": matches}
    elif payload.name == "create_demo_note":
        typed = arguments
        assert isinstance(typed, CreateNoteArguments)
        output = {
            "note": note_store.create(
                _safe_fixture_text(typed.title, 80),
                _safe_fixture_text(typed.content, 500),
            ),
            "storage": "memory",
        }
    elif payload.name == "get_demo_weather":
        typed = arguments
        assert isinstance(typed, WeatherArguments)
        city = _safe_fixture_text(typed.city, 80)
        digest = hashlib.sha256(city.casefold().encode("utf-8")).digest()
        conditions = ["晴朗", "多云", "微风", "小雨"]
        output = {
            "city": city,
            "condition": conditions[digest[0] % len(conditions)],
            "temperature_c": 15 + digest[1] % 16,
            "source": "deterministic-fictional-fixture",
        }
    elif payload.name == "request_sensitive_demo_data":
        typed = arguments
        assert isinstance(typed, SensitiveDataArguments)
        return ToolCallResponse(
            request_id=request_id,
            tool_name=payload.name,
            status="waiting_approval",
            executed=False,
            approval_required=True,
            output={
                "message": "Sensitive demo data was not accessed or returned.",
                "request_summary": (
                    "A bounded fictional sensitive-data request awaits human review."
                ),
            },
            policy_decision=_policy(
                payload.name,
                allowed=False,
                requires_approval=True,
                reason="high-risk demo tool requires explicit human approval",
            ),
        )
    else:  # pragma: no cover - Literal plus Pydantic prevents this branch.
        raise HTTPException(status_code=404, detail="unknown demo tool")

    return ToolCallResponse(
        request_id=request_id,
        tool_name=payload.name,
        status="success",
        executed=True,
        approval_required=False,
        output=output,
        policy_decision=_policy(
            payload.name,
            allowed=True,
            requires_approval=False,
            reason="allow-listed non-destructive fixture tool",
        ),
    )


def _mcp_result(response: ToolCallResponse) -> dict[str, Any]:
    data = response.model_dump(mode="json")
    return {
        "content": [{"type": "text", "text": json.dumps(data["output"], ensure_ascii=False)}],
        "structuredContent": data,
        "isError": False,
    }


def create_app() -> FastAPI:
    app = FastAPI(
        title="WhaleGuard Mock MCP Server",
        version="1.0.0",
        description="Metadata and five safe fixture tools for private AgentArena labs.",
    )

    @app.get("/health", tags=["system"])
    @app.get("/healthz", tags=["system"], include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "healthy", "service": SERVICE_NAME, "version": "1.0.0"}

    @app.get("/metadata", tags=["metadata"])
    async def metadata() -> dict[str, Any]:
        return {
            "name": SERVICE_NAME,
            "version": "1.0.0",
            "protocol_version": PROTOCOL_VERSION,
            "transport": ["http-json-rpc", "rest-fixture"],
            "execution_boundary": "five-hard-coded-tools-only",
            "arbitrary_shell": False,
            "external_network_access": False,
            "data_classification": "fictional-demo-only",
            "tools": TOOL_DEFINITIONS,
        }

    @app.get("/mcp/tools/list", tags=["mcp"])
    async def list_tools_get() -> dict[str, Any]:
        return {"tools": TOOL_DEFINITIONS}

    @app.post("/mcp/tools/list", tags=["mcp"])
    async def list_tools_post() -> dict[str, Any]:
        return {"tools": TOOL_DEFINITIONS}

    @app.post("/mcp/tools/call", response_model=ToolCallResponse, tags=["mcp"])
    async def call_tool(payload: ToolCallRequest) -> ToolCallResponse:
        return execute_tool(payload)

    @app.get("/demo/notes", tags=["fixtures"])
    async def list_demo_notes() -> dict[str, Any]:
        notes = note_store.list()
        return {"count": len(notes), "notes": notes}

    @app.post("/mcp", tags=["mcp-json-rpc"])
    async def json_rpc(payload: JsonRpcRequest) -> JSONResponse:
        if payload.method == "initialize":
            result: dict[str, Any] = {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVICE_NAME, "version": "1.0.0"},
                "instructions": "Fictional, non-destructive AgentArena fixtures only.",
            }
        elif payload.method == "notifications/initialized":
            result = {}
        elif payload.method == "tools/list":
            result = {"tools": TOOL_DEFINITIONS}
        elif payload.method == "tools/call":
            try:
                call = ToolCallRequest.model_validate(payload.params)
                result = _mcp_result(execute_tool(call))
            except ValidationError as exc:
                return JSONResponse(
                    status_code=200,
                    content={
                        "jsonrpc": "2.0",
                        "id": payload.id,
                        "error": {
                            "code": -32602,
                            "message": "Invalid params",
                            "data": _safe_validation_detail(exc),
                        },
                    },
                )
            except HTTPException as exc:
                return JSONResponse(
                    status_code=200,
                    content={
                        "jsonrpc": "2.0",
                        "id": payload.id,
                        "error": {"code": -32602, "message": "Invalid params", "data": exc.detail},
                    },
                )
        else:
            return JSONResponse(
                status_code=200,
                content={
                    "jsonrpc": "2.0",
                    "id": payload.id,
                    "error": {"code": -32601, "message": "Method not found"},
                },
            )

        return JSONResponse(content={"jsonrpc": "2.0", "id": payload.id, "result": result})

    return app


app = create_app()
