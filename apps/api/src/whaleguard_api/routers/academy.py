from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete, select

from ..academy_catalog import (
    ACADEMY_EVENT_TYPES,
    ACADEMY_VERSION,
    SCENARIOS,
    STARTER_PATH,
    correct_mitigation_id,
    get_scenario,
    public_scenario,
)
from ..academy_engine import (
    AcademyMode,
    detect_canary_flows,
    execute_scenario,
    public_fake_data_summary,
    seed_fake_data,
)
from ..academy_learning import (
    LEARNING_PATH,
    SKILLS,
    get_micro_course,
    get_scenario_learning,
    list_micro_courses,
    scenarios_for_skill,
)
from ..academy_schemas import (
    AcademyAttackStoryResponse,
    AcademyComparisonResponse,
    AcademyEvidenceResponse,
    AcademyEvidenceSubmission,
    AcademyExecuteRequest,
    AcademyHintResponse,
    AcademyMicroCourseListResponse,
    AcademyMicroCourseResponse,
    AcademyMitigationResponse,
    AcademyMitigationSubmission,
    AcademyProjectAction,
    AcademyReplayRequest,
    AcademyRoadmapResponse,
    AcademyScenarioResetResponse,
    AcademySessionResponse,
    AcademySkillProgressResponse,
    AcademyStandardsCatalogResponse,
    AcademyTutorRequest,
    AcademyTutorResponse,
)
from ..academy_standards import list_standards_mappings
from ..academy_tutor import (
    SUPPORTED_TUTOR_PROVIDERS,
    answer_with_optional_model,
    deterministic_tutor_answer,
    safe_session_context,
)
from ..audit import write_audit
from ..dependencies import DB, require_permissions, user_permissions
from ..models import (
    AcademyLabState,
    AcademyProgress,
    AcademySession,
    AuditLog,
    Evidence,
    Finding,
    ModelChannel,
    Project,
    User,
)
from ..security import redact
from .common import get_or_404

router = APIRouter(prefix="/academy", tags=["WhaleGuard Academy Range"])

_HINT_COSTS = {1: 5, 2: 5, 3: 10, 4: 20}
_MAX_SCORE = 125


def _project(db: DB, project_id: UUID) -> Project:
    return get_or_404(db, Project, project_id, "项目不存在")


def _state_query(project_id: UUID, user_id: UUID):
    return select(AcademyLabState).where(
        AcademyLabState.project_id == project_id,
        AcademyLabState.user_id == user_id,
    )


def _get_or_create_state(db: DB, project_id: UUID, user_id: UUID) -> AcademyLabState:
    state = db.scalar(_state_query(project_id, user_id))
    if state is None:
        state = AcademyLabState(
            project_id=project_id,
            user_id=user_id,
            seed_version=1,
            fake_data=seed_fake_data(),
            memory={},
        )
        db.add(state)
        db.flush()
    return state


def _progress_query(project_id: UUID, user_id: UUID, scenario_id: str):
    return select(AcademyProgress).where(
        AcademyProgress.project_id == project_id,
        AcademyProgress.user_id == user_id,
        AcademyProgress.scenario_id == scenario_id,
    )


def _get_or_create_progress(
    db: DB, project_id: UUID, user_id: UUID, scenario_id: str
) -> AcademyProgress:
    progress = db.scalar(_progress_query(project_id, user_id, scenario_id))
    if progress is None:
        progress = AcademyProgress(
            project_id=project_id,
            user_id=user_id,
            scenario_id=scenario_id,
        )
        db.add(progress)
        db.flush()
    return progress


def _score(progress: AcademyProgress) -> int:
    earned = (
        (60 if progress.exploit_complete else 0)
        + (20 if progress.evidence_complete else 0)
        + (20 if progress.mitigation_complete else 0)
        + (25 if progress.hardened_complete else 0)
    )
    deduction = sum(_HINT_COSTS.get(int(level), 0) for level in set(progress.hints_used))
    progress.score = max(0, earned - deduction)
    return progress.score


def _progress_payload(progress: AcademyProgress | None) -> dict[str, Any]:
    if progress is None:
        return {
            "exploit_complete": False,
            "evidence_complete": False,
            "mitigation_complete": False,
            "hardened_complete": False,
            "completed": False,
            "hints_used": [],
            "score": 0,
            "max_score": _MAX_SCORE,
            "last_session_id": None,
            "best_session_id": None,
        }
    return {
        "exploit_complete": progress.exploit_complete,
        "evidence_complete": progress.evidence_complete,
        "mitigation_complete": progress.mitigation_complete,
        "hardened_complete": progress.hardened_complete,
        "completed": all(
            (
                progress.exploit_complete,
                progress.evidence_complete,
                progress.mitigation_complete,
                progress.hardened_complete,
            )
        ),
        "hints_used": list(progress.hints_used),
        "score": progress.score,
        "max_score": _MAX_SCORE,
        "last_session_id": str(progress.last_session_id) if progress.last_session_id else None,
        "best_session_id": str(progress.best_session_id) if progress.best_session_id else None,
    }


def _progress_is_complete(progress: AcademyProgress | None) -> bool:
    return bool(progress and _progress_payload(progress)["completed"])


def _progress_is_touched(progress: AcademyProgress | None) -> bool:
    if progress is None:
        return False
    return bool(
        progress.last_session_id
        or progress.hints_used
        or progress.mitigation_choice
        or progress.exploit_complete
        or progress.evidence_complete
        or progress.mitigation_complete
        or progress.hardened_complete
    )


def _next_lesson_payload(
    progress_map: dict[str, AcademyProgress],
) -> dict[str, str] | None:
    in_progress = [
        progress
        for progress in progress_map.values()
        if _progress_is_touched(progress) and not _progress_is_complete(progress)
    ]
    if in_progress:
        progress = max(in_progress, key=lambda item: item.updated_at)
        manifest = SCENARIOS[progress.scenario_id]
        return {
            "scenario_id": progress.scenario_id,
            "title": manifest["title"],
            "action": "continue",
            "reason": "继续最近尚未完成的课程",
        }
    completed_ids = {
        scenario_id
        for scenario_id, progress in progress_map.items()
        if _progress_is_complete(progress)
    }
    for scenario_id in LEARNING_PATH:
        if scenario_id in completed_ids:
            continue
        learning = get_scenario_learning(scenario_id)
        if all(item in completed_ids for item in learning["prerequisites"]):
            return {
                "scenario_id": scenario_id,
                "title": SCENARIOS[scenario_id]["title"],
                "action": "start",
                "reason": "这是学习路线中下一节已准备好的课程",
            }
    for scenario_id in LEARNING_PATH:
        if scenario_id not in completed_ids:
            return {
                "scenario_id": scenario_id,
                "title": SCENARIOS[scenario_id]["title"],
                "action": "start",
                "reason": "推荐按路线继续学习",
            }
    return None


_EVENT_EXPLANATIONS = {
    "academy.input.received": "系统接收了这次本地训练输入。",
    "academy.rag.retrieve": "RAG 检索把资料片段带进了当前上下文。",
    "academy.vector.match": "向量检索按相似度选择了内容。",
    "academy.context.injected": "外部内容进入了模型可见上下文。",
    "academy.agent.goal_changed": "Agent 接受了不可信内容并改变原目标。",
    "academy.tool.requested": "Agent 请求调用一个模拟工具。",
    "academy.tool.executed": "模拟工具在本地假数据上完成了动作。",
    "academy.authz.allowed": "权限策略允许了这次动作。",
    "academy.authz.denied": "权限策略拒绝了这次动作。",
    "academy.secret.read": "组件读取了动态生成的虚构训练机密。",
    "academy.secret.exposed": "虚构训练机密越过边界进入输出。",
    "academy.guard.blocked": "Hardened 安全控制在危险结果发生前阻断了路径。",
    "academy.output.rendered": "系统向用户呈现最终结果。",
}


def _event_component(event_type: str) -> str:
    if event_type == "academy.input.received":
        return "User Input"
    if any(token in event_type for token in ("rag.", "vector.", "context.", "memory.")):
        return "Context / RAG"
    if any(token in event_type for token in ("authz.", "guard.", "approval_")):
        return "Policy"
    if any(token in event_type for token in ("mcp.", "tool.")):
        return "Tool / MCP"
    if any(token in event_type for token in ("secret.", "output.", "egress.")):
        return "Data / Output"
    if any(token in event_type for token in ("agent.", "identity.", "human.")):
        return "LLM / Agent"
    if "resource." in event_type:
        return "Resource Guard"
    return "Academy Runtime"


def _attack_story_payload(session: AcademySession, manifest: dict[str, Any]) -> dict[str, Any]:
    timeline = [
        {
            "sequence": int(event.get("sequence", index + 1)),
            "event_id": str(event["id"]),
            "event_type": str(event["event_type"]),
            "component": _event_component(str(event["event_type"])),
            "source": str(event.get("source", "Academy Runtime")),
            "target": str(event.get("target", "Academy Runtime")),
            "title": str(event.get("summary", event["event_type"])),
            "explanation": _EVENT_EXPLANATIONS.get(
                str(event["event_type"]), "该事件记录了攻击路径中的一次可审计状态变化。"
            ),
            "status": str(event.get("status", "observed")),
            "risk": str(event.get("risk", "none")),
        }
        for index, event in enumerate(session.events)
    ]
    if session.defense_success:
        outcome = "blocked"
        headline = "同一条攻击路径已被 Hardened 控制阻断"
        explanation = "危险结果没有发生；时间线标出了真正生效的策略控制点。"
        preferred_events = ("academy.guard.blocked", "academy.authz.denied")
    elif session.exploit_success:
        outcome = "vulnerability_triggered"
        headline = "本地靶场中的漏洞路径已被确定性事件规则证明"
        explanation = "这不是依赖模型自述的判断；事件链证明了不可信输入如何到达危险结果。"
        preferred_events = ("academy.authz.allowed", manifest["primary_success_event"])
    else:
        outcome = "not_triggered"
        headline = "这次输入没有触发完整攻击路径"
        explanation = "可以查看事件时间线，再使用分级 Hint 调整本地训练输入。"
        preferred_events = ()
    control_event = next(
        (
            event
            for event_type in preferred_events
            for event in session.events
            if event["event_type"] == event_type
        ),
        None,
    )
    control_point = None
    if control_event:
        control_point = {
            "event_id": str(control_event["id"]),
            "event_type": control_event["event_type"],
            "component": _event_component(control_event["event_type"]),
            "explanation": _EVENT_EXPLANATIONS.get(
                control_event["event_type"], str(control_event.get("summary", ""))
            ),
        }
    return {
        "session_id": session.id,
        "scenario_id": session.scenario_id,
        "mode": session.mode,
        "outcome": outcome,
        "headline": headline,
        "explanation": explanation,
        "timeline": timeline,
        "control_point": control_point,
        "technical_details": {
            "evaluator": "deterministic_event_rules",
            "events": redact(session.events),
            "payload_sha256": session.payload_sha256,
            "public_network_access": False,
        },
    }


def _event_summaries(session: AcademySession, prefixes: tuple[str, ...]) -> list[str]:
    return [
        str(event.get("summary", event["event_type"]))
        for event in session.events
        if any(str(event["event_type"]).startswith(prefix) for prefix in prefixes)
    ]


def _comparison_side(db: DB, session: AcademySession) -> dict[str, Any]:
    finding = db.get(Finding, session.finding_id) if session.finding_id else None
    evidence = db.get(Evidence, session.evidence_id) if session.evidence_id else None
    return {
        "session_id": session.id,
        "mode": session.mode,
        "result": (
            "成功触发"
            if session.exploit_success
            else "已阻断"
            if session.defense_success
            else "未触发"
        ),
        "input": {
            "payload": redact(session.payload),
            "payload_sha256": session.payload_sha256,
        },
        "model_decision": _event_summaries(
            session, ("academy.agent.", "academy.context.", "academy.rag.", "academy.vector.")
        ),
        "tool_call": _event_summaries(session, ("academy.tool.", "academy.mcp.")),
        "policy_decision": _event_summaries(
            session, ("academy.authz.", "academy.guard.", "academy.human.approval_")
        ),
        "output": _event_summaries(
            session, ("academy.secret.exposed", "academy.output.", "academy.egress.")
        ),
        "evidence": {
            "created": evidence is not None,
            "id": str(evidence.id) if evidence else None,
            "sha256": evidence.sha256 if evidence else None,
        },
        "finding": {
            "created": finding is not None,
            "id": str(finding.id) if finding else None,
            "title": finding.title if finding else None,
            "severity": finding.severity if finding else None,
            "status": finding.status if finding else None,
        },
    }


def _get_manifest_or_404(scenario_id: str) -> dict[str, Any]:
    try:
        return get_scenario(scenario_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Academy 场景不存在") from exc


def _latest_model_connection_audit(db: DB, channel_id: UUID) -> AuditLog | None:
    return db.scalar(
        select(AuditLog)
        .where(
            AuditLog.action == "model_channel.test_connection",
            AuditLog.resource_type == "model_channel",
            AuditLog.resource_id == str(channel_id),
        )
        .order_by(AuditLog.created_at.desc())
        .limit(1)
    )


def _tutor_channel_is_connected(db: DB, channel: ModelChannel, project_id: UUID) -> bool:
    if (
        channel.project_id != project_id
        or not channel.enabled
        or not channel.api_key_encrypted
        or channel.provider.strip().lower() not in SUPPORTED_TUTOR_PROVIDERS
    ):
        return False
    latest = _latest_model_connection_audit(db, channel.id)
    return latest is not None and latest.outcome == "success"


def _latest_connected_tutor_channel(db: DB, project_id: UUID) -> ModelChannel | None:
    candidates = list(
        db.scalars(
            select(ModelChannel).where(
                ModelChannel.project_id == project_id,
                ModelChannel.enabled.is_(True),
                ModelChannel.api_key_encrypted.is_not(None),
            )
        )
    )
    connected: list[tuple[str, ModelChannel]] = []
    for channel in candidates:
        if channel.provider.strip().lower() not in SUPPORTED_TUTOR_PROVIDERS:
            continue
        latest = _latest_model_connection_audit(db, channel.id)
        if latest is not None and latest.outcome == "success":
            connected.append((latest.created_at.isoformat(), channel))
    if not connected:
        return None
    connected.sort(key=lambda item: item[0], reverse=True)
    return connected[0][1]


def _severity(stars: int) -> str:
    return {1: "medium", 2: "medium", 3: "high", 4: "critical"}[stars]


def _hash_json(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _create_finding_and_evidence(
    db: DB,
    request: Request,
    session: AcademySession,
    manifest: dict[str, Any],
) -> None:
    correct_id = correct_mitigation_id(manifest)
    remediation = next(
        item["label"] for item in manifest["mitigations"] if item["id"] == correct_id
    )
    finding = Finding(
        project_id=session.project_id,
        title=f"Academy {manifest['id']} · {manifest['title']}",
        category=f"Academy / {manifest['knowledge_tags'][0]}",
        severity=_severity(int(manifest["difficulty_stars"])),
        confidence="confirmed",
        affected_target=f"WhaleGuard Academy/{manifest['id']} (local fixture)",
        description=(
            "Deterministic Academy telemetry satisfied the vulnerable event conditions. "
            "This finding concerns generated fake training data and local mock components only."
        ),
        reproduction_summary=(
            f"Replay Academy session {session.id} in vulnerable mode and inspect its ordered "
            "event trace. No public target or real credential was accessed."
        ),
        impact=(
            "The lab demonstrated the modeled security property failure using disposable "
            "WHALE_LAB_FAKE_* data."
        ),
        remediation=remediation,
        status="open",
        tags=[
            "academy",
            str(manifest["id"]).lower(),
            "fake-training-data",
            *[str(item).split(" ", 1)[0].lower() for item in manifest["owasp_llm"]],
            *[str(item).split(" ", 1)[0].lower() for item in manifest["owasp_agentic"]],
        ],
    )
    db.add(finding)
    db.flush()
    content = redact(
        {
            "schema_version": "academy-events-1.0",
            "academy_version": ACADEMY_VERSION,
            "scenario_id": manifest["id"],
            "session_id": str(session.id),
            "mode": session.mode,
            "success_conditions": manifest["success_conditions"]["vulnerable"],
            "events": session.events,
            "canary_flows": session.canary_flows,
            "data_classification": "FAKE_TRAINING_DATA",
            "public_network_access": False,
        }
    )
    evidence = Evidence(
        project_id=session.project_id,
        finding_id=finding.id,
        evidence_type="policy_decision",
        title=f"Academy {manifest['id']} deterministic attack trace",
        content=content,
        request_id=getattr(request.state, "request_id", None),
        response_summary=(
            "Event-rule completion evidence from a local vulnerable Academy scenario."
        ),
        sha256=_hash_json(content),
    )
    db.add(evidence)
    db.flush()
    session.finding_id = finding.id
    session.evidence_id = evidence.id


def _run_execution(
    *,
    db: DB,
    request: Request,
    user: User,
    project_id: UUID,
    manifest: dict[str, Any],
    payload: str,
    mode: AcademyMode,
    replay_of: AcademySession | None = None,
) -> AcademySession:
    _project(db, project_id)
    state = _get_or_create_state(db, project_id, user.id)
    progress = _get_or_create_progress(db, project_id, user.id, manifest["id"])
    previous_score = _score(progress)
    execution = execute_scenario(
        manifest,
        payload=payload,
        mode=mode,
        fake_data=state.fake_data,
        memory=state.memory,
    )
    payload_sha256 = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    session = AcademySession(
        project_id=project_id,
        user_id=user.id,
        scenario_id=manifest["id"],
        mode=mode,
        payload=payload,
        payload_sha256=payload_sha256,
        status=execution.status,
        attack_detected=execution.attack_detected,
        exploit_success=execution.exploit_success,
        defense_success=execution.defense_success,
        events=execution.events,
        canary_flows=detect_canary_flows(execution.events),
        replay_of_id=replay_of.id if replay_of else None,
        completed_at=datetime.now(UTC),
    )
    state.fake_data = execution.fake_data_after
    state.memory = execution.memory_after
    db.add(session)
    db.flush()
    if session.exploit_success:
        _create_finding_and_evidence(db, request, session, manifest)
        progress.exploit_complete = True
        if progress.best_session_id is None:
            progress.best_session_id = session.id
    if (
        session.defense_success
        and replay_of is not None
        and replay_of.mode == "vulnerable"
        and replay_of.exploit_success
        and replay_of.scenario_id == session.scenario_id
        and replay_of.payload_sha256 == session.payload_sha256
    ):
        progress.hardened_complete = True
    progress.last_session_id = session.id
    current_score = _score(progress)
    session.score_awarded = max(0, current_score - previous_score)
    write_audit(
        db,
        request,
        "academy.execute",
        "academy_session",
        session.id,
        user,
        details={
            "scenario_id": manifest["id"],
            "mode": mode,
            "status": session.status,
            "attack_detected": session.attack_detected,
            "exploit_success": session.exploit_success,
            "defense_success": session.defense_success,
            "public_network_access": False,
        },
    )
    db.commit()
    db.refresh(session)
    return session


@router.get("")
def academy_summary(
    db: DB,
    project_id: UUID | None = None,
    user: User = Depends(require_permissions("academy.read")),
) -> dict[str, Any]:
    progress_items: list[AcademyProgress] = []
    if project_id is not None:
        _project(db, project_id)
        progress_items = list(
            db.scalars(
                select(AcademyProgress).where(
                    AcademyProgress.project_id == project_id,
                    AcademyProgress.user_id == user.id,
                )
            )
        )
    progress_map = {item.scenario_id: item for item in progress_items}
    completed = sum(1 for item in progress_items if _progress_payload(item)["completed"])
    next_lesson = _next_lesson_payload(progress_map)
    return {
        "name": "WhaleGuard Academy Range",
        "version": ACADEMY_VERSION,
        "scenario_count": len(SCENARIOS),
        "completed_count": completed,
        "total_score": sum(item.score for item in progress_items),
        "max_score": len(SCENARIOS) * _MAX_SCORE,
        "starter_path": STARTER_PATH,
        "learning_path": LEARNING_PATH,
        "next_lesson": next_lesson,
        "event_types": list(ACADEMY_EVENT_TYPES),
        "frameworks": [
            "OWASP GenAI LLM Top 10 2026",
            "OWASP Top 10 for Agentic Applications 2026",
            "MITRE ATLAS",
            "CWE",
            "MCP 2026-07-28",
        ],
        "isolation": {
            "targets": "local mocks only",
            "public_listener": False,
            "public_egress": False,
            "data": "dynamic WHALE_LAB_FAKE_* training fixtures",
            "success_evaluator": "deterministic event rules",
        },
        "progress": {
            scenario_id: _progress_payload(progress_map.get(scenario_id))
            for scenario_id in SCENARIOS
        },
    }


@router.get("/standards", response_model=AcademyStandardsCatalogResponse)
def academy_standards(
    user: User = Depends(require_permissions("academy.read")),
) -> dict[str, Any]:
    del user
    items = list_standards_mappings()
    return {"version": ACADEMY_VERSION, "items": items, "total": len(items)}


@router.get("/micro-courses", response_model=AcademyMicroCourseListResponse)
def academy_micro_courses(
    user: User = Depends(require_permissions("academy.read")),
) -> dict[str, Any]:
    del user
    items = list_micro_courses()
    return {
        "items": items,
        "total": len(items),
        "total_minutes": sum(int(item["minutes"]) for item in items),
    }


@router.get("/micro-courses/{course_id}", response_model=AcademyMicroCourseResponse)
def academy_micro_course_detail(
    course_id: str,
    user: User = Depends(require_permissions("academy.read")),
) -> dict[str, Any]:
    del user
    try:
        return get_micro_course(course_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Academy 微课程不存在") from exc


@router.get("/roadmap", response_model=AcademyRoadmapResponse)
def academy_roadmap(
    project_id: UUID,
    db: DB,
    user: User = Depends(require_permissions("academy.read")),
) -> dict[str, Any]:
    _project(db, project_id)
    progress_map = {
        item.scenario_id: item
        for item in db.scalars(
            select(AcademyProgress).where(
                AcademyProgress.project_id == project_id,
                AcademyProgress.user_id == user.id,
            )
        )
    }
    completed_ids = {
        scenario_id
        for scenario_id, progress in progress_map.items()
        if _progress_is_complete(progress)
    }
    items = []
    levels = {
        level: {"completed": 0, "total": 0} for level in ("Beginner", "Intermediate", "Advanced")
    }
    for scenario_id in LEARNING_PATH:
        manifest = SCENARIOS[scenario_id]
        progress = progress_map.get(scenario_id)
        learning = get_scenario_learning(scenario_id)
        if _progress_is_complete(progress):
            status = "completed"
        elif _progress_is_touched(progress):
            status = "in_progress"
        elif all(item in completed_ids for item in learning["prerequisites"]):
            status = "available"
        else:
            status = "recommended_later"
        levels[manifest["difficulty"]]["total"] += 1
        if status == "completed":
            levels[manifest["difficulty"]]["completed"] += 1
        items.append(
            {
                "scenario_id": scenario_id,
                "title": manifest["title"],
                "difficulty": manifest["difficulty"],
                "estimated_time": manifest["estimated_time"],
                "skills": learning["skills"],
                "layer": learning["layer"],
                "prerequisites": learning["prerequisites"],
                "standards": manifest["standards"],
                "status": status,
                "progress": _progress_payload(progress),
            }
        )
    next_lesson = _next_lesson_payload(progress_map)
    current_lesson = next_lesson if next_lesson and next_lesson["action"] == "continue" else None
    return {
        "project_id": project_id,
        "items": items,
        "levels": levels,
        "completed_count": len(completed_ids),
        "total_count": len(LEARNING_PATH),
        "current_lesson": current_lesson,
        "next_lesson": next_lesson,
    }


@router.get("/skills", response_model=AcademySkillProgressResponse)
def academy_skill_progress(
    project_id: UUID,
    db: DB,
    user: User = Depends(require_permissions("academy.read")),
) -> dict[str, Any]:
    _project(db, project_id)
    progress_map = {
        item.scenario_id: item
        for item in db.scalars(
            select(AcademyProgress).where(
                AcademyProgress.project_id == project_id,
                AcademyProgress.user_id == user.id,
            )
        )
    }
    status_labels = {
        "not_started": "未接触",
        "introduced": "入门",
        "practicing": "练习中",
        "foundation": "掌握基础",
    }
    items = []
    for skill_id, metadata in SKILLS.items():
        scenario_ids = scenarios_for_skill(skill_id)
        relevant = [progress_map.get(scenario_id) for scenario_id in scenario_ids]
        touched_count = sum(1 for progress in relevant if _progress_is_touched(progress))
        if skill_id == "evidence_analysis":
            completed_count = sum(
                1 for progress in relevant if progress and progress.evidence_complete
            )
        else:
            completed_count = sum(1 for progress in relevant if _progress_is_complete(progress))
        foundation_threshold = min(2, len(scenario_ids))
        if touched_count == 0:
            status = "not_started"
        elif completed_count == 0:
            status = "introduced"
        elif completed_count < foundation_threshold:
            status = "practicing"
        else:
            status = "foundation"
        items.append(
            {
                "skill_id": skill_id,
                "name": metadata["name"],
                "description": metadata["description"],
                "status": status,
                "status_label": status_labels[status],
                "scenario_ids": scenario_ids,
                "touched_count": touched_count,
                "completed_count": completed_count,
                "total_count": len(scenario_ids),
                "progress_percent": round(completed_count * 100 / len(scenario_ids)),
            }
        )
    return {
        "project_id": project_id,
        "items": items,
        "status_order": ["not_started", "introduced", "practicing", "foundation"],
    }


@router.get("/scenarios")
def list_scenarios(
    db: DB,
    project_id: UUID | None = None,
    difficulty: str | None = None,
    user: User = Depends(require_permissions("academy.read")),
) -> dict[str, Any]:
    progress_map: dict[str, AcademyProgress] = {}
    if project_id is not None:
        _project(db, project_id)
        progress_map = {
            item.scenario_id: item
            for item in db.scalars(
                select(AcademyProgress).where(
                    AcademyProgress.project_id == project_id,
                    AcademyProgress.user_id == user.id,
                )
            )
        }
    normalized_difficulty = difficulty.casefold() if difficulty else None
    items = []
    for manifest in SCENARIOS.values():
        if normalized_difficulty and manifest["difficulty"].casefold() != normalized_difficulty:
            continue
        progress = progress_map.get(manifest["id"])
        items.append(
            {
                "id": manifest["id"],
                "title": manifest["title"],
                "difficulty": manifest["difficulty"],
                "difficulty_stars": manifest["difficulty_stars"],
                "estimated_time": manifest["estimated_time"],
                "story": manifest["story"],
                "knowledge_tags": manifest["knowledge_tags"],
                "skills": manifest["skills"],
                "layer": manifest["layer"],
                "prerequisites": manifest["prerequisites"],
                "risk_family": manifest["risk_family"],
                "standards": manifest["standards"],
                "owasp_llm": manifest["owasp_llm"],
                "owasp_agentic": manifest["owasp_agentic"],
                "progress": _progress_payload(progress),
                "starter_path_index": (
                    STARTER_PATH.index(manifest["id"]) + 1
                    if manifest["id"] in STARTER_PATH
                    else None
                ),
            }
        )
    return {"items": items, "total": len(items), "starter_path": STARTER_PATH}


@router.get("/scenarios/{scenario_id}")
def get_scenario_detail(
    scenario_id: str,
    db: DB,
    project_id: UUID | None = None,
    user: User = Depends(require_permissions("academy.read")),
) -> dict[str, Any]:
    manifest = _get_manifest_or_404(scenario_id)
    progress = None
    if project_id is not None:
        _project(db, project_id)
        progress = db.scalar(_progress_query(project_id, user.id, manifest["id"]))
    visible = public_scenario(
        manifest, unlocked_hints=list(progress.hints_used) if progress else []
    )
    visible["progress"] = _progress_payload(progress)
    return visible


@router.post(
    "/scenarios/{scenario_id}/tutor",
    response_model=AcademyTutorResponse,
)
def ask_academy_tutor(
    scenario_id: str,
    payload: AcademyTutorRequest,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("academy.read")),
) -> AcademyTutorResponse:
    manifest = _get_manifest_or_404(scenario_id)
    _project(db, payload.project_id)

    session_context = None
    if payload.session_id is not None:
        session = db.get(AcademySession, payload.session_id)
        if (
            session is None
            or session.project_id != payload.project_id
            or session.scenario_id != manifest["id"]
            or (session.user_id != user.id and not user.is_superuser)
        ):
            raise HTTPException(status_code=404, detail="Academy 执行记录不存在")
        session_context = safe_session_context(session)

    permissions = user_permissions(user)
    can_use_models = user.is_superuser or "models.test" in permissions
    selected_channel: ModelChannel | None = None
    selected_channel_id: UUID | None = None
    unavailable_requested_channel = False
    selection = "none"
    if payload.model_channel_id is not None:
        if not can_use_models:
            raise HTTPException(status_code=403, detail="使用真实模型导师需要模型测试权限")
        candidate = db.get(ModelChannel, payload.model_channel_id)
        if candidate is None or candidate.project_id != payload.project_id:
            raise HTTPException(status_code=404, detail="模型渠道不存在")
        selected_channel_id = candidate.id
        selection = "explicit"
        if _tutor_channel_is_connected(db, candidate, payload.project_id):
            selected_channel = candidate
        else:
            unavailable_requested_channel = True
    elif can_use_models:
        selected_channel = _latest_connected_tutor_channel(db, payload.project_id)
        if selected_channel is not None:
            selected_channel_id = selected_channel.id
            selection = "automatic"

    if unavailable_requested_channel:
        content = deterministic_tutor_answer(manifest, payload.intent, session_context)
        used_ai = False
        fallback_reason = "channel_unavailable"
    else:
        content, used_ai, fallback_reason = answer_with_optional_model(
            db,
            channel=selected_channel,
            project_id=payload.project_id,
            manifest=manifest,
            intent=payload.intent,
            question=payload.question,
            session_context=session_context,
            request_id=getattr(request.state, "request_id", None),
        )

    response = AcademyTutorResponse(
        project_id=payload.project_id,
        scenario_id=manifest["id"],
        intent=payload.intent,
        answer=content.answer,
        key_points=content.key_points,
        suggested_next_step=content.suggested_next_step,
        used_ai=used_ai,
        fallback_reason=fallback_reason,
        session_context_used=session_context is not None,
        model_channel_id=selected_channel_id,
        safety_boundary=content.safety_boundary,
    )
    write_audit(
        db,
        request,
        "academy.tutor.ask",
        "academy_scenario",
        manifest["id"],
        user,
        details={
            "project_id": str(payload.project_id),
            "intent": payload.intent,
            "session_context_used": session_context is not None,
            "model_selection": selection,
            "model_channel_id": str(selected_channel_id) if selected_channel_id else None,
            "used_ai": used_ai,
            "fallback_reason": fallback_reason,
            "safety_boundary": content.safety_boundary,
        },
    )
    db.commit()
    return response


@router.get("/state")
def get_academy_state(
    project_id: UUID,
    db: DB,
    user: User = Depends(require_permissions("academy.read")),
) -> dict[str, Any]:
    _project(db, project_id)
    state = db.scalar(_state_query(project_id, user.id))
    if state is None:
        return {
            "seeded": False,
            "memory_entries": 0,
            "public_network_access": False,
            "prefix": "WHALE_LAB_FAKE_*",
        }
    return {
        "seeded": True,
        "fake_data": public_fake_data_summary(state.fake_data, state.seed_version),
        "memory_entries": len(state.memory),
        "public_network_access": False,
    }


@router.post("/fake-data/seed")
def seed_academy_fake_data(
    payload: AcademyProjectAction,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("academy.execute")),
) -> dict[str, Any]:
    _project(db, payload.project_id)
    state = _get_or_create_state(db, payload.project_id, user.id)
    state.seed_version += 1
    state.fake_data = seed_fake_data()
    write_audit(
        db,
        request,
        "academy.fake_data.seed",
        "academy_lab_state",
        state.id,
        user,
        details={"seed_version": state.seed_version, "classification": "FAKE_TRAINING_DATA"},
    )
    db.commit()
    return {
        "seeded": True,
        "fake_data": public_fake_data_summary(state.fake_data, state.seed_version),
    }


@router.post("/memory/clear")
def clear_academy_memory(
    payload: AcademyProjectAction,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("academy.reset")),
) -> dict[str, Any]:
    _project(db, payload.project_id)
    state = db.scalar(_state_query(payload.project_id, user.id))
    cleared = len(state.memory) if state else 0
    if state:
        state.memory = {}
    write_audit(
        db,
        request,
        "academy.memory.clear",
        "academy_lab_state",
        state.id if state else None,
        user,
        details={"cleared_entries": cleared},
    )
    db.commit()
    return {"cleared": True, "cleared_entries": cleared}


@router.post(
    "/scenarios/{scenario_id}/execute",
    response_model=AcademySessionResponse,
    status_code=201,
)
def execute_academy_scenario(
    scenario_id: str,
    payload: AcademyExecuteRequest,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("academy.execute")),
) -> AcademySession:
    manifest = _get_manifest_or_404(scenario_id)
    return _run_execution(
        db=db,
        request=request,
        user=user,
        project_id=payload.project_id,
        manifest=manifest,
        payload=payload.payload,
        mode=payload.mode,
    )


@router.get("/sessions/{session_id}", response_model=AcademySessionResponse)
def get_academy_session(
    session_id: UUID,
    db: DB,
    user: User = Depends(require_permissions("academy.read")),
) -> AcademySession:
    session = get_or_404(db, AcademySession, session_id, "Academy 执行记录不存在")
    if session.user_id != user.id and not user.is_superuser:
        raise HTTPException(status_code=404, detail="Academy 执行记录不存在")
    return session


@router.get(
    "/sessions/{session_id}/attack-story",
    response_model=AcademyAttackStoryResponse,
)
def get_academy_attack_story(
    session_id: UUID,
    db: DB,
    user: User = Depends(require_permissions("academy.read")),
) -> dict[str, Any]:
    session = get_or_404(db, AcademySession, session_id, "Academy 执行记录不存在")
    if session.user_id != user.id and not user.is_superuser:
        raise HTTPException(status_code=404, detail="Academy 执行记录不存在")
    manifest = _get_manifest_or_404(session.scenario_id)
    return _attack_story_payload(session, manifest)


@router.get(
    "/sessions/{session_id}/comparison",
    response_model=AcademyComparisonResponse,
)
def get_academy_session_comparison(
    session_id: UUID,
    db: DB,
    user: User = Depends(require_permissions("academy.read")),
) -> dict[str, Any]:
    selected = get_or_404(db, AcademySession, session_id, "Academy 执行记录不存在")
    if selected.user_id != user.id and not user.is_superuser:
        raise HTTPException(status_code=404, detail="Academy 执行记录不存在")
    vulnerable: AcademySession | None = None
    hardened: AcademySession | None = None
    if selected.mode == "vulnerable":
        vulnerable = selected
        hardened = db.scalar(
            select(AcademySession)
            .where(
                AcademySession.replay_of_id == selected.id,
                AcademySession.mode == "hardened",
            )
            .order_by(AcademySession.created_at.desc())
        )
    else:
        hardened = selected
        if selected.replay_of_id:
            vulnerable = db.get(AcademySession, selected.replay_of_id)
    if vulnerable and vulnerable.user_id != selected.user_id:
        vulnerable = None
    if hardened and hardened.user_id != selected.user_id:
        hardened = None
    manifest = _get_manifest_or_404(selected.scenario_id)
    ready = vulnerable is not None and hardened is not None
    missing_mode = None if ready else "vulnerable" if vulnerable is None else "hardened"
    control_changes = []
    if ready:
        vulnerable_config = manifest["vulnerable_config"]
        hardened_config = manifest["hardened_config"]
        for control in sorted(set(vulnerable_config) | set(hardened_config)):
            before = vulnerable_config.get(control)
            after = hardened_config.get(control)
            if before == after:
                continue
            control_changes.append(
                {
                    "control": control,
                    "vulnerable": before,
                    "hardened": after,
                    "explanation": (
                        f"Hardened 模式把 {control} 从 {before!s} 调整为 {after!s}，"
                        "并由确定性策略事件证明控制已生效。"
                    ),
                }
            )
    return {
        "scenario_id": selected.scenario_id,
        "ready": ready,
        "missing_mode": missing_mode,
        "vulnerable": _comparison_side(db, vulnerable) if vulnerable else None,
        "hardened": _comparison_side(db, hardened) if hardened else None,
        "control_changes": control_changes,
        "conclusion": (
            "相同输入在漏洞版触发危险结果，在修复版被策略控制阻断。"
            if ready
            else f"还需要完成 {missing_mode} 模式，才能生成左右对照。"
        ),
    }


@router.post(
    "/sessions/{session_id}/replay",
    response_model=AcademySessionResponse,
    status_code=201,
)
def replay_academy_session(
    session_id: UUID,
    payload: AcademyReplayRequest,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("academy.execute")),
) -> AcademySession:
    source = get_or_404(db, AcademySession, session_id, "Academy 执行记录不存在")
    if source.user_id != user.id:
        raise HTTPException(status_code=404, detail="Academy 执行记录不存在")
    manifest = _get_manifest_or_404(source.scenario_id)
    return _run_execution(
        db=db,
        request=request,
        user=user,
        project_id=source.project_id,
        manifest=manifest,
        payload=source.payload,
        mode=payload.mode,
        replay_of=source,
    )


@router.post(
    "/sessions/{session_id}/evidence",
    response_model=AcademyEvidenceResponse,
)
def submit_academy_evidence(
    session_id: UUID,
    payload: AcademyEvidenceSubmission,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("academy.execute")),
) -> AcademyEvidenceResponse:
    session = get_or_404(db, AcademySession, session_id, "Academy 执行记录不存在")
    if session.user_id != user.id or not session.exploit_success:
        raise HTTPException(status_code=409, detail="请先完成该场景的 Vulnerable 利用")
    manifest = _get_manifest_or_404(session.scenario_id)
    selected_ids = set(payload.event_ids)
    selected_types = {
        str(event["event_type"]) for event in session.events if event["id"] in selected_ids
    }
    expected = set(manifest["expected_evidence"]["event_types"])
    missing = sorted(expected - selected_types)
    correct = not missing
    progress = _get_or_create_progress(db, session.project_id, user.id, session.scenario_id)
    if correct:
        progress.evidence_complete = True
    _score(progress)
    write_audit(
        db,
        request,
        "academy.evidence.submit",
        "academy_session",
        session.id,
        user,
        details={
            "scenario_id": session.scenario_id,
            "correct": correct,
            "selected_event_count": len(selected_ids),
            "missing_event_types": missing,
        },
    )
    db.commit()
    return AcademyEvidenceResponse(
        scenario_id=session.scenario_id,
        correct=correct,
        matched_event_types=sorted(expected & selected_types),
        missing_event_types=missing,
        score=progress.score,
        evidence_complete=progress.evidence_complete,
    )


@router.post(
    "/scenarios/{scenario_id}/mitigation",
    response_model=AcademyMitigationResponse,
)
def submit_academy_mitigation(
    scenario_id: str,
    payload: AcademyMitigationSubmission,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("academy.execute")),
) -> AcademyMitigationResponse:
    manifest = _get_manifest_or_404(scenario_id)
    _project(db, payload.project_id)
    choices = {item["id"] for item in manifest["mitigations"]}
    if payload.choice_id not in choices:
        raise HTTPException(status_code=422, detail="修复选项无效")
    correct = payload.choice_id == correct_mitigation_id(manifest)
    progress = _get_or_create_progress(db, payload.project_id, user.id, manifest["id"])
    progress.mitigation_choice = payload.choice_id
    if correct:
        progress.mitigation_complete = True
    _score(progress)
    write_audit(
        db,
        request,
        "academy.mitigation.submit",
        "academy_progress",
        progress.id,
        user,
        details={"scenario_id": manifest["id"], "choice_id": payload.choice_id, "correct": correct},
    )
    db.commit()
    return AcademyMitigationResponse(
        scenario_id=manifest["id"],
        correct=correct,
        selected_choice_id=payload.choice_id,
        score=progress.score,
        mitigation_complete=progress.mitigation_complete,
    )


def _unlock_academy_hint(
    scenario_id: str,
    level: int,
    payload: AcademyProjectAction,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("academy.execute")),
) -> AcademyHintResponse:
    manifest = _get_manifest_or_404(scenario_id)
    _project(db, payload.project_id)
    if level not in _HINT_COSTS:
        raise HTTPException(status_code=422, detail="Hint 等级必须为 1、2、3 或 Walkthrough 4")
    progress = _get_or_create_progress(db, payload.project_id, user.id, manifest["id"])
    required_prior = set(range(1, level))
    if not required_prior.issubset(set(progress.hints_used)):
        raise HTTPException(status_code=409, detail="请按顺序解锁 Hint")
    progress.hints_used = sorted(set(progress.hints_used) | {level})
    _score(progress)
    hint_text = manifest["hints"][level - 1]["text"] if level <= 3 else None
    walkthrough = manifest["walkthrough"] if level == 4 else None
    write_audit(
        db,
        request,
        "academy.hint.unlock",
        "academy_progress",
        progress.id,
        user,
        details={"scenario_id": manifest["id"], "level": level, "score": progress.score},
    )
    db.commit()
    return AcademyHintResponse(
        scenario_id=manifest["id"],
        level=level,
        kind=(manifest["hints"][level - 1]["kind"] if level <= 3 else "solution"),
        text=hint_text,
        walkthrough=walkthrough,
        hints_used=list(progress.hints_used),
        score=progress.score,
    )


@router.post(
    "/scenarios/{scenario_id}/hints/{level}",
    response_model=AcademyHintResponse,
)
def unlock_academy_hint(
    scenario_id: str,
    level: int,
    payload: AcademyProjectAction,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("academy.execute")),
) -> AcademyHintResponse:
    return _unlock_academy_hint(scenario_id, level, payload, request, db, user)


@router.post(
    "/scenarios/{scenario_id}/solution",
    response_model=AcademyHintResponse,
)
def unlock_academy_solution(
    scenario_id: str,
    payload: AcademyProjectAction,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("academy.execute")),
) -> AcademyHintResponse:
    return _unlock_academy_hint(scenario_id, 4, payload, request, db, user)


def _academy_artifact_ids(
    db: DB, project_id: UUID, user_id: UUID, scenario_id: str | None = None
) -> tuple[list[UUID], list[UUID], list[UUID]]:
    query = select(AcademySession).where(
        AcademySession.project_id == project_id,
        AcademySession.user_id == user_id,
    )
    if scenario_id:
        query = query.where(AcademySession.scenario_id == scenario_id)
    sessions = list(db.scalars(query))
    return (
        [item.id for item in sessions],
        [item.finding_id for item in sessions if item.finding_id],
        [item.evidence_id for item in sessions if item.evidence_id],
    )


def _delete_academy_records(
    db: DB, project_id: UUID, user_id: UUID, scenario_id: str | None = None
) -> dict[str, int]:
    session_ids, finding_ids, evidence_ids = _academy_artifact_ids(
        db, project_id, user_id, scenario_id
    )
    progress_filter = [
        AcademyProgress.project_id == project_id,
        AcademyProgress.user_id == user_id,
    ]
    session_filter = [
        AcademySession.project_id == project_id,
        AcademySession.user_id == user_id,
    ]
    if scenario_id:
        progress_filter.append(AcademyProgress.scenario_id == scenario_id)
        session_filter.append(AcademySession.scenario_id == scenario_id)
    progress_result = db.execute(delete(AcademyProgress).where(*progress_filter))
    session_result = db.execute(delete(AcademySession).where(*session_filter))
    if evidence_ids:
        db.execute(delete(Evidence).where(Evidence.id.in_(evidence_ids)))
    if finding_ids:
        db.execute(delete(Finding).where(Finding.id.in_(finding_ids)))
    return {
        "sessions": int(session_result.rowcount or len(session_ids)),
        "progress": int(progress_result.rowcount or 0),
        "findings": len(finding_ids),
        "evidence": len(evidence_ids),
    }


@router.post(
    "/scenarios/{scenario_id}/reset",
    response_model=AcademyScenarioResetResponse,
)
def reset_academy_scenario(
    scenario_id: str,
    payload: AcademyProjectAction,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("academy.reset")),
) -> dict[str, Any]:
    manifest = _get_manifest_or_404(scenario_id)
    _project(db, payload.project_id)
    session_ids, finding_ids, evidence_ids = _academy_artifact_ids(
        db, payload.project_id, user.id, manifest["id"]
    )
    progress = db.scalar(_progress_query(payload.project_id, user.id, manifest["id"]))
    memory_entries_cleared = 0
    collector_entries_cleared = 0
    state = db.scalar(_state_query(payload.project_id, user.id))
    if state:
        if manifest["id"] == "I09":
            memory = deepcopy(state.memory)
            if memory.pop("poisoned_instruction", None) is not None:
                memory_entries_cleared = 1
            state.memory = memory
        fake_data = deepcopy(state.fake_data)
        collector_before = list(fake_data.get("collector", []))
        collector_after = [
            item for item in collector_before if item.get("scenario_id") != manifest["id"]
        ]
        collector_entries_cleared = len(collector_before) - len(collector_after)
        fake_data["collector"] = collector_after
        state.fake_data = fake_data
    preserved = {
        "sessions": len(session_ids),
        "progress": progress is not None,
        "score": progress.score if progress else 0,
        "findings": len(finding_ids),
        "evidence": len(evidence_ids),
        "reports": True,
        "project": True,
    }
    cleared_ephemeral_state = {
        "memory_entries": memory_entries_cleared,
        "collector_entries": collector_entries_cleared,
    }
    write_audit(
        db,
        request,
        "academy.scenario.reset",
        "academy_scenario",
        manifest["id"],
        user,
        details={
            "scenario_id": manifest["id"],
            "cleared_ephemeral_state": cleared_ephemeral_state,
            "preserved": preserved,
        },
    )
    db.commit()
    return {
        "reset": True,
        "scenario_id": manifest["id"],
        "cleared_ephemeral_state": cleared_ephemeral_state,
        "preserved": preserved,
    }


@router.post("/reset-all")
def reset_all_academy_scenarios(
    payload: AcademyProjectAction,
    request: Request,
    db: DB,
    user: User = Depends(require_permissions("academy.reset")),
) -> dict[str, Any]:
    _project(db, payload.project_id)
    removed = _delete_academy_records(db, payload.project_id, user.id)
    state = db.scalar(_state_query(payload.project_id, user.id))
    if state:
        state.seed_version += 1
        state.fake_data = seed_fake_data()
        state.memory = {}
    write_audit(
        db,
        request,
        "academy.reset_all",
        "project",
        payload.project_id,
        user,
        details={"removed": removed, "fake_data_reseeded": bool(state)},
    )
    db.commit()
    return {"reset": True, "removed": removed, "fake_data_reseeded": bool(state)}
