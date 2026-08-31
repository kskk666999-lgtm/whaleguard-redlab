from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import ConfigDict, Field, field_validator

from .schemas import APIModel, ORMModel

_SUSPECTED_REAL_CREDENTIALS = (
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~-]{20,}\b", re.IGNORECASE),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)

_UNSAFE_TUTOR_QUESTION = (
    re.compile(
        r"(?:给我|生成|提供|写出|构造).{0,16}"
        r"(?:攻击载荷|payload|利用代码|绕过步骤|系统命令|shell|webshell|凭据)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:generate|give|provide|write|craft).{0,32}"
        r"(?:payload|exploit|bypass|shell command|credential)",
        re.IGNORECASE,
    ),
)


class AcademyProjectAction(APIModel):
    project_id: UUID


class AcademyExecuteRequest(AcademyProjectAction):
    mode: Literal["vulnerable", "hardened"] = "vulnerable"
    payload: str = Field(min_length=1, max_length=8000)

    @field_validator("payload")
    @classmethod
    def reject_suspected_real_credentials(cls, value: str) -> str:
        if "WHALE_LAB_FAKE_" not in value and any(
            pattern.search(value) for pattern in _SUSPECTED_REAL_CREDENTIALS
        ):
            raise ValueError("疑似真实凭证；Academy 仅允许 WHALE_LAB_FAKE_* 虚构训练数据")
        return value


class AcademyReplayRequest(APIModel):
    mode: Literal["vulnerable", "hardened"] = "hardened"


class AcademyEvidenceSubmission(APIModel):
    event_ids: list[str] = Field(min_length=1, max_length=20)


class AcademyMitigationSubmission(AcademyProjectAction):
    choice_id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_-]+$")


class AcademySessionResponse(ORMModel):
    project_id: UUID
    user_id: UUID
    scenario_id: str
    mode: str
    payload_sha256: str
    status: str
    attack_detected: bool
    exploit_success: bool
    defense_success: bool
    score_awarded: int
    events: list[dict[str, Any]]
    canary_flows: list[dict[str, Any]]
    replay_of_id: UUID | None
    finding_id: UUID | None
    evidence_id: UUID | None
    completed_at: datetime | None


class AcademyHintResponse(APIModel):
    scenario_id: str
    level: int
    kind: Literal["idea", "location", "near_solution", "solution"]
    text: str | None
    walkthrough: dict[str, Any] | None = None
    hints_used: list[int]
    score: int


class AcademyMitigationResponse(APIModel):
    scenario_id: str
    correct: bool
    selected_choice_id: str
    score: int
    mitigation_complete: bool


class AcademyEvidenceResponse(APIModel):
    scenario_id: str
    correct: bool
    matched_event_types: list[str]
    missing_event_types: list[str]
    score: int
    evidence_complete: bool


class AcademyStandardsMappingResponse(APIModel):
    scenario_id: str
    risk_family: str
    owasp_llm: list[str]
    owasp_agentic: list[str]
    mitre_atlas: list[str]
    cwe: list[str]
    framework_references: dict[str, str]


class AcademyStandardsCatalogResponse(APIModel):
    version: str
    items: list[AcademyStandardsMappingResponse]
    total: int


class AcademyMicroCourseResponse(APIModel):
    id: str
    order: int
    title: str
    minutes: int
    concepts: list[str]
    plain_explanation: str
    analogy: str
    diagram: dict[str, Any]
    interactive_example: dict[str, Any]


class AcademyMicroCourseListResponse(APIModel):
    items: list[AcademyMicroCourseResponse]
    total: int
    total_minutes: int


class AcademyNextLessonResponse(APIModel):
    scenario_id: str
    title: str
    action: Literal["start", "continue"]
    reason: str


class AcademyRoadmapLessonResponse(APIModel):
    scenario_id: str
    title: str
    difficulty: str
    estimated_time: int
    skills: list[str]
    layer: list[str]
    prerequisites: list[str]
    standards: dict[str, Any]
    status: Literal["available", "in_progress", "completed", "recommended_later"]
    progress: dict[str, Any]


class AcademyRoadmapResponse(APIModel):
    project_id: UUID
    items: list[AcademyRoadmapLessonResponse]
    levels: dict[str, dict[str, int]]
    completed_count: int
    total_count: int
    current_lesson: AcademyNextLessonResponse | None
    next_lesson: AcademyNextLessonResponse | None


class AcademySkillProgressItemResponse(APIModel):
    skill_id: str
    name: str
    description: str
    status: Literal["not_started", "introduced", "practicing", "foundation"]
    status_label: str
    scenario_ids: list[str]
    touched_count: int
    completed_count: int
    total_count: int
    progress_percent: int


class AcademySkillProgressResponse(APIModel):
    project_id: UUID
    items: list[AcademySkillProgressItemResponse]
    status_order: list[str]


class AcademyAttackStoryStepResponse(APIModel):
    sequence: int
    event_id: str
    event_type: str
    component: str
    source: str
    target: str
    title: str
    explanation: str
    status: str
    risk: str


class AcademyAttackStoryResponse(APIModel):
    session_id: UUID
    scenario_id: str
    mode: str
    outcome: Literal["vulnerability_triggered", "blocked", "not_triggered"]
    headline: str
    explanation: str
    timeline: list[AcademyAttackStoryStepResponse]
    control_point: dict[str, Any] | None
    technical_details: dict[str, Any]


class AcademyComparisonSideResponse(APIModel):
    session_id: UUID
    mode: str
    result: str
    input: dict[str, Any]
    model_decision: list[str]
    tool_call: list[str]
    policy_decision: list[str]
    output: list[str]
    evidence: dict[str, Any]
    finding: dict[str, Any]


class AcademyControlChangeResponse(APIModel):
    control: str
    vulnerable: Any
    hardened: Any
    explanation: str


class AcademyComparisonResponse(APIModel):
    scenario_id: str
    ready: bool
    missing_mode: Literal["vulnerable", "hardened"] | None
    vulnerable: AcademyComparisonSideResponse | None
    hardened: AcademyComparisonSideResponse | None
    control_changes: list[AcademyControlChangeResponse]
    conclusion: str


class AcademyScenarioResetResponse(APIModel):
    reset: bool
    scenario_id: str
    cleared_ephemeral_state: dict[str, int]
    preserved: dict[str, int | bool]


AcademyTutorIntent = Literal[
    "meaning",
    "why_vulnerable",
    "why_hardened",
    "evidence",
    "simplify",
]

AcademyTutorFallbackReason = Literal[
    "no_model",
    "channel_unavailable",
    "provider_error",
    "timeout",
    "scope_denied",
    "transport_error",
    "structured_output",
    "unsafe_output",
]


class AcademyTutorRequest(AcademyProjectAction):
    intent: AcademyTutorIntent
    question: str | None = Field(default=None, min_length=1, max_length=300)
    session_id: UUID | None = None
    model_channel_id: UUID | None = None

    @field_validator("question")
    @classmethod
    def validate_defensive_question(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("question must not be blank")
        if any(pattern.search(normalized) for pattern in _SUSPECTED_REAL_CREDENTIALS):
            raise ValueError("疑似真实凭证；鲸鱼导师不接收凭据或敏感证据")
        if any(pattern.search(normalized) for pattern in _UNSAFE_TUTOR_QUESTION):
            raise ValueError("鲸鱼导师只回答课程解释、防御与证据判断问题")
        return normalized


class AcademyTutorAIOutput(APIModel):
    """Strict provider-independent output for the optional Academy tutor."""

    model_config = ConfigDict(from_attributes=True, extra="forbid", strict=True)

    answer: str = Field(min_length=1, max_length=1600)
    key_points: list[str] = Field(min_length=1, max_length=5)
    suggested_next_step: str = Field(min_length=1, max_length=300)
    safety_boundary: Literal["defensive_explanation_only"]

    @field_validator("answer", "suggested_next_step")
    @classmethod
    def strip_non_empty_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("text must not be blank")
        return normalized

    @field_validator("key_points")
    @classmethod
    def validate_key_points(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item or len(item) > 300 for item in normalized):
            raise ValueError("key points must be non-empty and at most 300 characters")
        return normalized


class AcademyTutorResponse(APIModel):
    project_id: UUID
    scenario_id: str
    intent: AcademyTutorIntent
    answer: str
    key_points: list[str] = Field(min_length=1, max_length=5)
    suggested_next_step: str
    used_ai: bool
    fallback_reason: AcademyTutorFallbackReason | None = None
    session_context_used: bool
    model_channel_id: UUID | None = None
    safety_boundary: Literal["defensive_explanation_only"] = "defensive_explanation_only"
