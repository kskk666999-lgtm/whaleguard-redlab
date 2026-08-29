from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, HttpUrl, field_validator


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True, extra="forbid")


class ORMModel(APIModel):
    id: UUID
    created_at: datetime
    updated_at: datetime


T = TypeVar("T")


class Page(APIModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
    pages: int


class Message(APIModel):
    message: str


class HealthResponse(APIModel):
    status: str
    service: str
    version: str
    database: str | None = None


class LoginRequest(APIModel):
    username: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=512)


class RoleSummary(APIModel):
    name: str
    permissions: list[str] = []


class UserResponse(ORMModel):
    username: str
    email: str
    display_name: str | None
    is_active: bool
    is_superuser: bool
    roles: list[RoleSummary] = []


class UserCreate(APIModel):
    username: str = Field(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=12, max_length=512)
    display_name: str | None = Field(default=None, max_length=160)
    role_names: list[str] = Field(default_factory=lambda: ["Viewer"], max_length=10)


class UserUpdate(APIModel):
    display_name: str | None = Field(default=None, max_length=160)
    is_active: bool | None = None
    role_names: list[str] | None = Field(default=None, max_length=10)


class RoleResponse(ORMModel):
    name: str
    description: str | None
    permissions: list[str]


class TokenResponse(APIModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    csrf_token: str
    user: UserResponse


class ProjectCreate(APIModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    tags: list[str] = Field(default_factory=list, max_length=30)


class ProjectUpdate(APIModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    status: Literal["active", "archived"] | None = None
    tags: list[str] | None = Field(default=None, max_length=30)


class ProjectResponse(ORMModel):
    name: str
    description: str | None
    status: str
    owner_id: UUID
    tags: list[str]


class ScopeCreate(APIModel):
    name: str = Field(min_length=1, max_length=200)
    target_type: Literal["domain", "ip", "cidr", "url"]
    target_value: str = Field(min_length=1, max_length=512)
    allowed_request_types: list[Literal["http", "https"]] = ["http", "https"]
    is_authorized: bool = False
    expires_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=5000)

    @field_validator("expires_at")
    @classmethod
    def timezone_required(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("expires_at must include a timezone")
        return value


class ScopeUpdate(APIModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    target_value: str | None = Field(default=None, min_length=1, max_length=512)
    allowed_request_types: list[Literal["http", "https"]] | None = None
    is_authorized: bool | None = None
    expires_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=5000)


class ScopeResponse(ORMModel):
    project_id: UUID
    name: str
    target_type: str
    target_value: str
    allowed_request_types: list[str]
    is_authorized: bool
    confirmed_by_id: UUID | None
    authorized_at: datetime | None
    expires_at: datetime | None
    notes: str | None


Provider = Literal[
    "openai-compatible",
    "deepseek-compatible",
    "glm-compatible",
    "qwen-compatible",
    "ollama-compatible",
]


class ModelChannelCreate(APIModel):
    project_id: UUID | None = None
    name: str = Field(min_length=1, max_length=200)
    provider: Provider
    base_url: HttpUrl
    api_key: str | None = Field(default=None, max_length=4096)
    model: str = Field(min_length=1, max_length=200)
    timeout: int = Field(default=30, ge=1, le=300)
    max_tokens: int = Field(default=1024, ge=1, le=131072)
    temperature: float = Field(default=0.2, ge=0, le=2)
    enabled: bool = True
    extra_headers: dict[str, str] = Field(default_factory=dict)

    @field_validator("extra_headers")
    @classmethod
    def validate_headers(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > 30:
            raise ValueError("Too many extra headers")
        forbidden = {"host", "content-length", "transfer-encoding", "connection"}
        for key, item in value.items():
            if key.lower() in forbidden or "\r" in key or "\n" in key:
                raise ValueError(f"Forbidden header: {key}")
            if "\r" in item or "\n" in item:
                raise ValueError("Header values may not contain CR/LF")
        return value


class ModelChannelUpdate(APIModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    provider: Provider | None = None
    base_url: HttpUrl | None = None
    api_key: str | None = Field(default=None, max_length=4096)
    model: str | None = Field(default=None, min_length=1, max_length=200)
    timeout: int | None = Field(default=None, ge=1, le=300)
    max_tokens: int | None = Field(default=None, ge=1, le=131072)
    temperature: float | None = Field(default=None, ge=0, le=2)
    enabled: bool | None = None
    extra_headers: dict[str, str] | None = None


class ModelChannelResponse(ORMModel):
    project_id: UUID | None
    name: str
    provider: str
    base_url: str
    api_key_masked: str | None
    model: str
    timeout: int
    max_tokens: int
    temperature: float
    enabled: bool
    extra_header_names: list[str]


class ConnectionTestResponse(APIModel):
    success: bool
    message: str
    latency_ms: int
    status_code: int | None = None


class AgentCreate(APIModel):
    project_id: UUID
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    endpoint_url: HttpUrl
    agent_type: str = Field(default="openai-compatible", max_length=80)
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)
    risk_level: Literal["low", "medium", "high", "critical"] = "medium"


class AgentUpdate(APIModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    endpoint_url: HttpUrl | None = None
    enabled: bool | None = None
    config: dict[str, Any] | None = None
    risk_level: Literal["low", "medium", "high", "critical"] | None = None


class AgentResponse(ORMModel):
    project_id: UUID
    name: str
    description: str | None
    endpoint_url: str
    agent_type: str
    enabled: bool
    config: dict[str, Any]
    risk_level: str


class MCPToolInput(APIModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=20000)
    input_schema: dict[str, Any] = Field(default_factory=dict, alias="inputSchema")
    permissions: list[str] = Field(default_factory=list)
    requires_approval: bool = False


class MCPServerCreate(APIModel):
    project_id: UUID
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    transport: Literal["stdio", "sse", "streamable-http"] = "stdio"
    endpoint_url: HttpUrl | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    tools: list[MCPToolInput] = Field(default_factory=list, max_length=500)


class MCPImportRequest(APIModel):
    project_id: UUID
    config: dict[str, Any]


class MCPServerUpdate(APIModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    endpoint_url: HttpUrl | None = None
    enabled: bool | None = None
    config: dict[str, Any] | None = None


class MCPToolResponse(ORMModel):
    server_id: UUID
    name: str
    description: str
    input_schema: dict[str, Any]
    permissions: list[str]
    requires_approval: bool
    risk_score: float
    risk_level: str
    risk_flags: list[str]


class MCPServerResponse(ORMModel):
    project_id: UUID
    name: str
    description: str | None
    transport: str
    endpoint_url: str | None
    config: dict[str, Any]
    enabled: bool
    risk_score: float
    risk_level: str
    last_analyzed_at: datetime | None
    tool_count: int


class MCPAnalysisResponse(APIModel):
    server_id: UUID
    risk_score: float
    risk_level: str
    findings: list[dict[str, Any]]
    recommendations: list[str]
    tools: list[MCPToolResponse]
    execution_performed: Literal[False] = False


class TestSuiteCreate(APIModel):
    project_id: UUID
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    version: str = Field(default="1.0.0", max_length=40)
    enabled: bool = True
    tags: list[str] = Field(default_factory=list)


class TestSuiteUpdate(APIModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    version: str | None = Field(default=None, max_length=40)
    enabled: bool | None = None
    tags: list[str] | None = None


class TestSuiteResponse(ORMModel):
    project_id: UUID
    name: str
    description: str | None
    version: str
    enabled: bool
    tags: list[str]


class TestCaseCreate(APIModel):
    case_key: str = Field(alias="id", min_length=1, max_length=160)
    name: str = Field(min_length=1, max_length=240)
    category: str = Field(min_length=1, max_length=120)
    severity: Literal["info", "low", "medium", "high", "critical"]
    description: str = Field(min_length=1, max_length=20000)
    input_data: dict[str, Any] = Field(default_factory=dict, alias="input")
    context: dict[str, Any] = Field(default_factory=dict)
    expected_behavior: str = Field(min_length=1, max_length=20000)
    forbidden_behavior: str = Field(min_length=1, max_length=20000)
    evaluator: dict[str, Any] = Field(default_factory=lambda: {"type": "rules"})
    tags: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
    enabled: bool = True


class TestCaseResponse(ORMModel):
    suite_id: UUID
    case_key: str
    name: str
    category: str
    severity: str
    description: str
    input_data: dict[str, Any] = Field(alias="input")
    context: dict[str, Any]
    expected_behavior: str
    forbidden_behavior: str
    evaluator: dict[str, Any]
    tags: list[str]
    references: list[str]
    enabled: bool


RunStatus = Literal[
    "pending",
    "queued",
    "running",
    "waiting_approval",
    "completed",
    "failed",
    "cancelled",
]


class TestRunCreate(APIModel):
    project_id: UUID
    suite_id: UUID = Field(validation_alias=AliasChoices("suite_id", "test_suite_id"))
    agent_target_id: UUID | None = None
    model_channel_id: UUID | None = None
    evaluation_mode: Literal["rules", "rules_with_llm_judge"] = "rules"
    judge_model_channel_id: UUID | None = None
    target_type: Literal["agent", "model"] | None = None
    target_id: UUID | None = None
    name: str = Field(default="安全评估运行", min_length=1, max_length=240)
    max_concurrency: int = Field(default=1, ge=1, le=20)
    timeout_seconds: int = Field(default=120, ge=1, le=3600)
    max_retries: int = Field(default=1, ge=0, le=5)


class TestRunResponse(ORMModel):
    project_id: UUID
    suite_id: UUID
    agent_target_id: UUID | None
    model_channel_id: UUID | None
    evaluation_mode: str
    judge_model_channel_id: UUID | None
    name: str
    status: str
    progress: int
    max_concurrency: int
    timeout_seconds: int
    attempt: int
    max_retries: int
    pause_requested: bool
    cancellation_requested: bool
    security_score: float | None
    score_explanation: dict[str, Any]
    event_log: list[dict[str, Any]]
    started_at: datetime | None
    finished_at: datetime | None
    error_summary: str | None
    requested_by_id: UUID


class TestResultResponse(ORMModel):
    run_id: UUID
    test_case_id: UUID
    outcome: str
    metrics: dict[str, Any]
    score: float
    explanation: str
    raw_input: dict[str, Any]
    raw_output: dict[str, Any]
    latency_ms: int


FindingStatus = Literal[
    "open",
    "confirmed",
    "false_positive",
    "accepted_risk",
    "fixed",
    "retest_required",
    "closed",
]


class FindingCreate(APIModel):
    project_id: UUID
    run_id: UUID | None = None
    title: str = Field(min_length=1, max_length=300)
    category: str = Field(min_length=1, max_length=120)
    severity: Literal["info", "low", "medium", "high", "critical"]
    confidence: Literal["low", "medium", "high", "confirmed"]
    affected_target: str = Field(min_length=1, max_length=300)
    description: str = Field(min_length=1, max_length=30000)
    reproduction_summary: str = Field(min_length=1, max_length=30000)
    impact: str = Field(min_length=1, max_length=30000)
    remediation: str = Field(min_length=1, max_length=30000)
    status: FindingStatus = "open"
    owner_id: UUID | None = None
    tags: list[str] = Field(default_factory=list)


class FindingUpdate(APIModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    severity: Literal["info", "low", "medium", "high", "critical"] | None = None
    confidence: Literal["low", "medium", "high", "confirmed"] | None = None
    description: str | None = Field(default=None, min_length=1, max_length=30000)
    impact: str | None = Field(default=None, min_length=1, max_length=30000)
    remediation: str | None = Field(default=None, min_length=1, max_length=30000)
    status: FindingStatus | None = None
    owner_id: UUID | None = None
    tags: list[str] | None = None


class FindingResponse(ORMModel):
    project_id: UUID
    run_id: UUID | None
    title: str
    category: str
    severity: str
    confidence: str
    affected_target: str
    description: str
    reproduction_summary: str
    impact: str
    remediation: str
    status: str
    owner_id: UUID | None
    tags: list[str]


class EvidenceCreate(APIModel):
    project_id: UUID
    finding_id: UUID | None = None
    run_id: UUID | None = None
    evidence_type: Literal[
        "raw_input", "model_output", "tool_call", "policy_decision", "screenshot", "attachment"
    ]
    title: str = Field(min_length=1, max_length=240)
    content: dict[str, Any]
    request_id: str | None = Field(default=None, max_length=120)
    response_summary: str | None = Field(default=None, max_length=10000)


class EvidenceResponse(ORMModel):
    project_id: UUID
    finding_id: UUID | None
    run_id: UUID | None
    evidence_type: str
    title: str
    content: dict[str, Any]
    request_id: str | None
    response_summary: str | None
    attachment_path: str | None
    media_type: str | None
    sha256: str
    captured_at: datetime


class ReportCreate(APIModel):
    project_id: UUID
    run_id: UUID | None = None
    name: str = Field(min_length=1, max_length=240)
    formats: list[Literal["html", "markdown", "json"]] = ["html", "markdown", "json"]


class ReportResponse(ORMModel):
    project_id: UUID
    run_id: UUID | None
    name: str
    status: str
    formats: list[str]
    content_json: dict[str, Any]
    content_markdown: str | None
    content_html: str | None
    generated_by_id: UUID
    generated_at: datetime | None


class ApprovalCreate(APIModel):
    project_id: UUID
    run_id: UUID | None = None
    action_type: str = Field(min_length=1, max_length=120)
    risk_level: Literal["low", "medium", "high", "critical"]
    reason: str = Field(min_length=1, max_length=10000)
    expires_at: datetime | None = None


class ApprovalDecision(APIModel):
    status: Literal["approved", "rejected"]
    decision_reason: str = Field(min_length=1, max_length=10000)


class ApprovalResponse(ORMModel):
    project_id: UUID
    run_id: UUID | None
    action_type: str
    risk_level: str
    reason: str
    status: str
    requested_by_id: UUID
    decided_by_id: UUID | None
    decision_reason: str | None
    decided_at: datetime | None
    expires_at: datetime | None


class AuditLogResponse(ORMModel):
    actor_id: UUID | None
    action: str
    resource_type: str
    resource_id: str | None
    outcome: str
    ip_address: str | None
    user_agent: str | None
    request_id: str | None
    details: dict[str, Any]


class KnowledgeCreate(APIModel):
    project_id: UUID
    title: str = Field(min_length=1, max_length=300)
    source_type: str = Field(default="manual", max_length=60)
    content: str = Field(min_length=1, max_length=1_000_000)
    tags: list[str] = Field(default_factory=list)


class KnowledgeResponse(ORMModel):
    project_id: UUID
    title: str
    source_type: str
    content: str
    status: str
    tags: list[str]
    sha256: str
    created_by_id: UUID


class SettingUpsert(APIModel):
    value: dict[str, Any]
    description: str | None = Field(default=None, max_length=5000)
    is_secret: bool = False


class SettingResponse(ORMModel):
    key: str
    value: dict[str, Any]
    description: str | None
    is_secret: bool
    updated_by_id: UUID | None


class DashboardSummary(APIModel):
    projects: int
    active_runs: int
    open_findings: int
    critical_findings: int
    mcp_servers: int
    evidence: int
    recent_runs: list[TestRunResponse]
    severity_distribution: dict[str, int]


class WorkerEvaluationResult(APIModel):
    attack_success: bool = False
    refusal_correct: bool | None = None
    over_refusal: bool = False
    sensitive_data_leak: bool = False
    tool_policy_violation: bool = False
    task_deviation: bool = False
    latency_ms: int = Field(default=0, ge=0)
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    estimated_cost: float = Field(default=0, ge=0)
    passed: bool
    reasons: list[str]
    security_score: float = Field(ge=0, le=100)
    score_explanation: list[str]
    worker_elapsed_ms: float = Field(default=0, ge=0)
