from __future__ import annotations

import time
from datetime import UTC, datetime
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import or_, select

from ..audit import write_audit
from ..dependencies import DB, require_permissions
from ..mcp_analyzer import analyze_server, analyze_tool
from ..models import AgentTarget, MCPServer, MCPTool, ModelChannel, Project, User
from ..schemas import (
    AgentCreate,
    AgentResponse,
    AgentUpdate,
    ConnectionTestResponse,
    MCPAnalysisResponse,
    MCPImportRequest,
    MCPServerCreate,
    MCPServerResponse,
    MCPServerUpdate,
    MCPToolResponse,
    ModelChannelCreate,
    ModelChannelResponse,
    ModelChannelUpdate,
    Page,
)
from ..scope_guard import ScopeDenied, guarded_request
from ..security import (
    decrypt_json,
    decrypt_secret,
    encrypt_json,
    encrypt_secret,
    mask_secret,
    redact,
)
from .common import apply_updates, get_or_404, paginate

router = APIRouter(tags=["目标与 MCPShield"])


def _channel_response(channel: ModelChannel) -> ModelChannelResponse:
    api_key = decrypt_secret(channel.api_key_encrypted)
    headers = decrypt_json(channel.extra_headers_encrypted)
    return ModelChannelResponse(
        id=channel.id,
        created_at=channel.created_at,
        updated_at=channel.updated_at,
        project_id=channel.project_id,
        name=channel.name,
        provider=channel.provider,
        base_url=channel.base_url,
        api_key_masked=mask_secret(api_key),
        model=channel.model,
        timeout=channel.timeout,
        max_tokens=channel.max_tokens,
        temperature=channel.temperature,
        enabled=channel.enabled,
        extra_header_names=sorted(headers),
    )


@router.get("/model-channels", response_model=Page[ModelChannelResponse])
def list_channels(
    db: DB,
    _user: User = Depends(require_permissions("models.read")),
    project_id: UUID | None = None,
    search: str | None = None,
    enabled: bool | None = None,
    page: int = 1,
    page_size: int = 20,
) -> Page[ModelChannelResponse]:
    query = select(ModelChannel).order_by(ModelChannel.updated_at.desc())
    if project_id:
        query = query.where(ModelChannel.project_id == project_id)
    if search:
        pattern = f"%{search[:200]}%"
        query = query.where(
            or_(ModelChannel.name.ilike(pattern), ModelChannel.model.ilike(pattern))
        )
    if enabled is not None:
        query = query.where(ModelChannel.enabled.is_(enabled))
    page_result = paginate(db, query, page, page_size)
    page_result.items = [_channel_response(item) for item in page_result.items]
    return page_result


@router.post("/model-channels", response_model=ModelChannelResponse, status_code=201)
def create_channel(
    payload: ModelChannelCreate,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("models.write")),
) -> ModelChannelResponse:
    if payload.project_id:
        get_or_404(db, Project, payload.project_id, "项目不存在")
    values = payload.model_dump(exclude={"api_key", "extra_headers"})
    values["base_url"] = str(payload.base_url).rstrip("/")
    channel = ModelChannel(
        **values,
        api_key_encrypted=encrypt_secret(payload.api_key),
        extra_headers_encrypted=encrypt_json(payload.extra_headers),
    )
    db.add(channel)
    db.flush()
    write_audit(
        db,
        request,
        "model_channel.create",
        "model_channel",
        channel.id,
        user,
        details={"provider": channel.provider, "base_url": channel.base_url},
    )
    db.commit()
    db.refresh(channel)
    return _channel_response(channel)


@router.get("/model-channels/{channel_id}", response_model=ModelChannelResponse)
def get_channel(
    channel_id: UUID,
    db: DB,
    _user: User = Depends(require_permissions("models.read")),
) -> ModelChannelResponse:
    return _channel_response(get_or_404(db, ModelChannel, channel_id, "模型渠道不存在"))


@router.patch("/model-channels/{channel_id}", response_model=ModelChannelResponse)
def update_channel(
    channel_id: UUID,
    payload: ModelChannelUpdate,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("models.write")),
) -> ModelChannelResponse:
    channel = get_or_404(db, ModelChannel, channel_id, "模型渠道不存在")
    values = payload.model_dump(exclude_unset=True, exclude={"api_key", "extra_headers"})
    if payload.base_url is not None:
        values["base_url"] = str(payload.base_url).rstrip("/")
    apply_updates(channel, values)
    if "api_key" in payload.model_fields_set:
        channel.api_key_encrypted = encrypt_secret(payload.api_key)
    if "extra_headers" in payload.model_fields_set:
        channel.extra_headers_encrypted = encrypt_json(payload.extra_headers or {})
    write_audit(db, request, "model_channel.update", "model_channel", channel.id, user)
    db.commit()
    db.refresh(channel)
    return _channel_response(channel)


@router.delete("/model-channels/{channel_id}", status_code=204)
def delete_channel(
    channel_id: UUID,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("models.write")),
) -> Response:
    channel = get_or_404(db, ModelChannel, channel_id, "模型渠道不存在")
    write_audit(db, request, "model_channel.delete", "model_channel", channel.id, user)
    db.delete(channel)
    db.commit()
    return Response(status_code=204)


@router.post("/model-channels/{channel_id}/test-connection", response_model=ConnectionTestResponse)
def test_channel_connection(
    channel_id: UUID,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("models.test")),
) -> ConnectionTestResponse:
    channel = get_or_404(db, ModelChannel, channel_id, "模型渠道不存在")
    headers = decrypt_json(channel.extra_headers_encrypted)
    api_key = decrypt_secret(channel.api_key_encrypted)
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    target_url = f"{channel.base_url.rstrip('/')}/models"
    started = time.perf_counter()
    try:
        response = guarded_request(
            db,
            "GET",
            target_url,
            channel.project_id,
            headers=headers,
            timeout=channel.timeout,
            request_id=getattr(request.state, "request_id", None),
        )
        latency_ms = round((time.perf_counter() - started) * 1000)
        success = response.status_code < 500
        result = ConnectionTestResponse(
            success=success,
            message="连接成功" if success else "目标服务返回错误",
            latency_ms=latency_ms,
            status_code=response.status_code,
        )
    except (ScopeDenied, httpx.HTTPError) as exc:
        result = ConnectionTestResponse(
            success=False,
            message=f"连接被拒绝或失败：{str(exc)[:300]}",
            latency_ms=round((time.perf_counter() - started) * 1000),
        )
    write_audit(
        db,
        request,
        "model_channel.test_connection",
        "model_channel",
        channel.id,
        user,
        outcome="success" if result.success else "failed",
        details={"status_code": result.status_code},
    )
    db.commit()
    return result


@router.get("/agents", response_model=Page[AgentResponse])
def list_agents(
    db: DB,
    _user: User = Depends(require_permissions("agents.read")),
    project_id: UUID | None = None,
    search: str | None = None,
    enabled: bool | None = None,
    page: int = 1,
    page_size: int = 20,
) -> Page[AgentResponse]:
    query = select(AgentTarget).order_by(AgentTarget.updated_at.desc())
    if project_id:
        query = query.where(AgentTarget.project_id == project_id)
    if search:
        query = query.where(AgentTarget.name.ilike(f"%{search[:200]}%"))
    if enabled is not None:
        query = query.where(AgentTarget.enabled.is_(enabled))
    return paginate(db, query, page, page_size)


@router.post("/agents", response_model=AgentResponse, status_code=201)
def create_agent(
    payload: AgentCreate,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("agents.write")),
) -> AgentTarget:
    get_or_404(db, Project, payload.project_id, "项目不存在")
    values = payload.model_dump()
    values["endpoint_url"] = str(payload.endpoint_url).rstrip("/")
    agent = AgentTarget(**values)
    db.add(agent)
    db.flush()
    write_audit(db, request, "agent.create", "agent_target", agent.id, user)
    db.commit()
    db.refresh(agent)
    return agent


@router.get("/agents/{agent_id}", response_model=AgentResponse)
def get_agent(
    agent_id: UUID,
    db: DB,
    _user: User = Depends(require_permissions("agents.read")),
) -> AgentTarget:
    return get_or_404(db, AgentTarget, agent_id, "Agent 不存在")


@router.patch("/agents/{agent_id}", response_model=AgentResponse)
def update_agent(
    agent_id: UUID,
    payload: AgentUpdate,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("agents.write")),
) -> AgentTarget:
    agent = get_or_404(db, AgentTarget, agent_id, "Agent 不存在")
    values = payload.model_dump(exclude_unset=True)
    if payload.endpoint_url is not None:
        values["endpoint_url"] = str(payload.endpoint_url).rstrip("/")
    apply_updates(agent, values)
    write_audit(db, request, "agent.update", "agent_target", agent.id, user)
    db.commit()
    db.refresh(agent)
    return agent


@router.delete("/agents/{agent_id}", status_code=204)
def delete_agent(
    agent_id: UUID,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("agents.write")),
) -> Response:
    agent = get_or_404(db, AgentTarget, agent_id, "Agent 不存在")
    write_audit(db, request, "agent.delete", "agent_target", agent.id, user)
    db.delete(agent)
    db.commit()
    return Response(status_code=204)


def _tool_from_input(server_id: UUID, value) -> MCPTool:
    data = value.model_dump()
    return MCPTool(server_id=server_id, **data)


@router.get("/mcp/servers", response_model=Page[MCPServerResponse])
def list_mcp_servers(
    db: DB,
    _user: User = Depends(require_permissions("mcp.read")),
    project_id: UUID | None = None,
    search: str | None = None,
    risk_level: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> Page[MCPServerResponse]:
    query = select(MCPServer).order_by(MCPServer.updated_at.desc())
    if project_id:
        query = query.where(MCPServer.project_id == project_id)
    if search:
        query = query.where(MCPServer.name.ilike(f"%{search[:200]}%"))
    if risk_level:
        query = query.where(MCPServer.risk_level == risk_level)
    return paginate(db, query, page, page_size)


@router.post("/mcp/servers", response_model=MCPServerResponse, status_code=201)
def create_mcp_server(
    payload: MCPServerCreate,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("mcp.write")),
) -> MCPServer:
    get_or_404(db, Project, payload.project_id, "项目不存在")
    values = payload.model_dump(exclude={"tools"})
    values["endpoint_url"] = str(payload.endpoint_url).rstrip("/") if payload.endpoint_url else None
    values["config"] = redact(payload.config)
    server = MCPServer(**values)
    db.add(server)
    db.flush()
    for item in payload.tools:
        db.add(_tool_from_input(server.id, item))
    write_audit(db, request, "mcp_server.create", "mcp_server", server.id, user)
    db.commit()
    db.refresh(server)
    return server


@router.get("/mcp/servers/{server_id}", response_model=MCPServerResponse)
def get_mcp_server(
    server_id: UUID,
    db: DB,
    _user: User = Depends(require_permissions("mcp.read")),
) -> MCPServer:
    return get_or_404(db, MCPServer, server_id, "MCP Server 不存在")


@router.post("/mcp/servers/import", response_model=list[MCPServerResponse], status_code=201)
def import_mcp_config(
    payload: MCPImportRequest,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("mcp.write")),
) -> list[MCPServer]:
    get_or_404(db, Project, payload.project_id, "项目不存在")
    raw_servers = payload.config.get("mcpServers", payload.config)
    if not isinstance(raw_servers, dict) or not raw_servers or len(raw_servers) > 100:
        raise HTTPException(status_code=422, detail="MCP 配置必须包含非空 mcpServers 对象")
    created: list[MCPServer] = []
    for name, raw in raw_servers.items():
        if not isinstance(raw, dict):
            raise HTTPException(status_code=422, detail=f"MCP Server {name} 配置无效")
        url = raw.get("url") or raw.get("endpoint_url")
        transport = raw.get("transport") or ("streamable-http" if url else "stdio")
        tools = raw.get("tools", [])
        if not isinstance(tools, list) or len(tools) > 500:
            raise HTTPException(status_code=422, detail=f"MCP Server {name} tools 无效")
        server = MCPServer(
            project_id=payload.project_id,
            name=str(name)[:200],
            description=str(raw.get("description", ""))[:5000] or None,
            transport=transport if transport in {"stdio", "sse", "streamable-http"} else "stdio",
            endpoint_url=str(url)[:1024] if url else None,
            config=redact({key: value for key, value in raw.items() if key != "tools"}),
        )
        db.add(server)
        db.flush()
        for raw_tool in tools:
            if not isinstance(raw_tool, dict) or not raw_tool.get("name"):
                continue
            db.add(
                MCPTool(
                    server_id=server.id,
                    name=str(raw_tool["name"])[:200],
                    description=str(raw_tool.get("description", ""))[:20000],
                    input_schema=raw_tool.get("inputSchema", raw_tool.get("input_schema", {})),
                    permissions=raw_tool.get("permissions", []),
                    requires_approval=bool(raw_tool.get("requires_approval", False)),
                )
            )
        created.append(server)
    for server in created:
        write_audit(db, request, "mcp_server.import", "mcp_server", server.id, user)
    db.commit()
    for server in created:
        db.refresh(server)
    return created


@router.patch("/mcp/servers/{server_id}", response_model=MCPServerResponse)
def update_mcp_server(
    server_id: UUID,
    payload: MCPServerUpdate,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("mcp.write")),
) -> MCPServer:
    server = get_or_404(db, MCPServer, server_id, "MCP Server 不存在")
    values = payload.model_dump(exclude_unset=True)
    if payload.endpoint_url is not None:
        values["endpoint_url"] = str(payload.endpoint_url).rstrip("/")
    if payload.config is not None:
        values["config"] = redact(payload.config)
    apply_updates(server, values)
    write_audit(db, request, "mcp_server.update", "mcp_server", server.id, user)
    db.commit()
    db.refresh(server)
    return server


@router.delete("/mcp/servers/{server_id}", status_code=204)
def delete_mcp_server(
    server_id: UUID,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("mcp.write")),
) -> Response:
    server = get_or_404(db, MCPServer, server_id, "MCP Server 不存在")
    write_audit(db, request, "mcp_server.delete", "mcp_server", server.id, user)
    db.delete(server)
    db.commit()
    return Response(status_code=204)


@router.get("/mcp/servers/{server_id}/tools", response_model=list[MCPToolResponse])
def list_mcp_tools(
    server_id: UUID,
    db: DB,
    _user: User = Depends(require_permissions("mcp.read")),
) -> list[MCPTool]:
    get_or_404(db, MCPServer, server_id, "MCP Server 不存在")
    return list(
        db.scalars(select(MCPTool).where(MCPTool.server_id == server_id).order_by(MCPTool.name))
    )


@router.post("/mcp/servers/{server_id}/analyze", response_model=MCPAnalysisResponse)
def analyze_mcp_server(
    server_id: UUID,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("mcp.analyze")),
) -> MCPAnalysisResponse:
    server = get_or_404(db, MCPServer, server_id, "MCP Server 不存在")
    tools = list(db.scalars(select(MCPTool).where(MCPTool.server_id == server.id)))
    for tool in tools:
        result = analyze_tool(tool)
        tool.risk_score = result.score
        tool.risk_level = result.level
        tool.risk_flags = result.flags
    score, level, findings, recommendations = analyze_server(tools)
    server.risk_score = score
    server.risk_level = level
    server.last_analyzed_at = datetime.now(UTC)
    write_audit(
        db,
        request,
        "mcp_server.analyze",
        "mcp_server",
        server.id,
        user,
        details={"execution_performed": False, "risk_score": score, "tool_count": len(tools)},
    )
    db.commit()
    for tool in tools:
        db.refresh(tool)
    return MCPAnalysisResponse(
        server_id=server.id,
        risk_score=score,
        risk_level=level,
        findings=findings,
        recommendations=recommendations,
        tools=tools,
        execution_performed=False,
    )
