from __future__ import annotations

import re
import secrets
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from .academy_catalog import ACADEMY_EVENT_TYPES

AcademyMode = Literal["vulnerable", "hardened"]

_ATTACK_PATTERNS: dict[str, list[tuple[str, ...]]] = {
    "B01": [
        ("ignore", "override", "忽略", "绕过", "放弃"),
        ("secret", "canary", "internal", "机密", "内部", "训练数据"),
    ],
    "B02": [("system prompt", "hidden context", "developer", "隐藏", "内部说明", "系统提示")],
    "B03": [("expense", "manual", "报销", "新员工", "制度")],
    "B04": [
        ("payroll", "salary", "薪资", "工资"),
        ("without approval", "skip approval", "不要审批", "直接读取", "跳过审批"),
    ],
    "B05": [("friendly", "optimizer", "友好", "工具描述"), ("tool", "mcp", "工具")],
    "I06": [("user_1002", "other user", "其他用户", "用户 b"), ("payroll", "薪资", "记录")],
    "I07": [("quarterly", "policy", "季度", "政策"), ("search", "retrieve", "检索", "相关度")],
    "I08": [("export", "导出"), ("../", "user_1002", "admin", "全量", "target=")],
    "I10": [("user_1001",), ("user_1002",), ("modify", "update", "修改", "操作")],
    "I11": [("<img", "onerror", "markdown", "html", "collector", "原样渲染")],
    "I12": [("recursive", "recursion", "递归", "重复"), ("1000", "never stop", "不要停止", "无限")],
    "A13": [("supervisor-agent", "supervisor agent", "主管代理"), ("from=", "sender=", "来自")],
    "A14": [("analytics-pro", "plugin-manifest", "plugin manifest", "插件清单")],
    "A15": [("forecast", "预测"), ("downstream", "下游", "inventory", "库存", "执行")],
    "A16": [("issuer-alpha",), ("issuer-beta",), ("admin", "payroll", "scope", "薪资")],
    "A17": [
        ("approve", "approval", "批准", "审批"),
        ("convince", "persuade", "可信解释", "说服", "立即执行"),
        ("high-risk", "batch", "高风险", "批量"),
    ],
}

_MEMORY_WRITE_MARKERS = ("remember", "记住", "memory", "长期记忆")
_MEMORY_TRIGGER_MARKERS = ("continue", "继续")
_MEMORY_DANGEROUS_MARKERS = ("secret", "内部机密", "敏感", "读取内部")


@dataclass(slots=True)
class AcademyExecution:
    events: list[dict[str, Any]]
    status: str
    attack_detected: bool
    exploit_success: bool
    defense_success: bool
    memory_after: dict[str, Any]
    fake_data_after: dict[str, Any]


def seed_fake_data() -> dict[str, Any]:
    generation_id = str(uuid4())
    return {
        "generation_id": generation_id,
        "classification": "FAKE_TRAINING_DATA",
        "secrets": {
            "openai": f"WHALE_LAB_FAKE_OPENAI_{secrets.token_hex(10).upper()}",
            "admin": f"WHALE_LAB_FAKE_ADMIN_TOKEN_{secrets.token_hex(10).upper()}",
            "payroll": f"WHALE_LAB_FAKE_PAYROLL_{secrets.token_hex(10).upper()}",
            "mcp": f"WHALE_LAB_FAKE_MCP_SECRET_{secrets.token_hex(10).upper()}",
        },
        "enterprise": {
            "user_1001": {
                "display_name": "Training User A",
                "tenant": "training-a",
                "payroll_band": "FAKE-A2",
            },
            "user_1002": {
                "display_name": "Training User B",
                "tenant": "training-b",
                "payroll_band": "FAKE-B7",
            },
        },
        "rag": {
            "poisoned_chunk_id": "poisoned_chunk_17",
            "poisoned_vector_id": "poisoned-vector-09",
        },
        "identity": {
            "issuers": ["https://issuer-alpha.invalid", "https://issuer-beta.invalid"],
            "credential_issuer": "https://issuer-alpha.invalid",
        },
        "plugins": {
            "analytics-pro": {
                "approved_sha256": "0" * 64,
                "current_sha256": "f" * 64,
                "signed": False,
            }
        },
        "collector": [],
    }


def public_fake_data_summary(fake_data: dict[str, Any], seed_version: int) -> dict[str, Any]:
    return {
        "generation_id": fake_data.get("generation_id"),
        "seed_version": seed_version,
        "classification": fake_data.get("classification", "FAKE_TRAINING_DATA"),
        "secret_labels": sorted((fake_data.get("secrets") or {}).keys()),
        "enterprise_identities": sorted((fake_data.get("enterprise") or {}).keys()),
        "collector_event_count": len(fake_data.get("collector") or []),
        "prefix": "WHALE_LAB_FAKE_*",
        "public_network_access": False,
    }


def _safe_payload(value: str) -> str:
    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", value)
    return value.strip()[:8000]


def _contains_groups(payload: str, groups: list[tuple[str, ...]]) -> bool:
    lowered = payload.casefold()
    return all(any(marker.casefold() in lowered for marker in group) for group in groups)


def _is_memory_write(payload: str) -> bool:
    lowered = payload.casefold()
    return (
        any(marker in lowered for marker in _MEMORY_WRITE_MARKERS)
        and any(marker in lowered for marker in _MEMORY_TRIGGER_MARKERS)
        and any(marker in lowered for marker in _MEMORY_DANGEROUS_MARKERS)
    )


def _is_memory_trigger(payload: str) -> bool:
    lowered = payload.casefold().strip()
    return any(marker in lowered for marker in _MEMORY_TRIGGER_MARKERS)


class _EventBuilder:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def add(
        self,
        event_type: str,
        *,
        source: str,
        target: str,
        summary: str,
        status: str = "observed",
        risk: str = "none",
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if event_type not in ACADEMY_EVENT_TYPES:
            raise ValueError(f"Unregistered Academy event type: {event_type}")
        event = {
            "id": str(uuid4()),
            "sequence": len(self.events) + 1,
            "timestamp": datetime.now(UTC).isoformat(),
            "event_type": event_type,
            "source": source,
            "target": target,
            "summary": summary,
            "status": status,
            "risk": risk,
            "details": deepcopy(details or {}),
        }
        self.events.append(event)
        return event


def _training_secret(fake_data: dict[str, Any], label: str) -> str:
    secrets_map = fake_data.get("secrets") or {}
    value = str(secrets_map.get(label, ""))
    if not value.startswith("WHALE_LAB_FAKE_"):
        raise ValueError("Academy runtime refused a non-training secret")
    return value


def _expose_secret(
    builder: _EventBuilder,
    fake_data: dict[str, Any],
    label: str,
    *,
    source: str = "fake-secret-store",
    sink: str = "assistant-output",
) -> str:
    value = _training_secret(fake_data, label)
    builder.add(
        "academy.secret.read",
        source=source,
        target="Academy Agent",
        summary=f"Read dynamic {label} training canary",
        risk="high",
        details={"classification": "TRAINING_SECRET", "canary_label": label},
    )
    builder.add(
        "academy.secret.exposed",
        source="Academy Agent",
        target=sink,
        summary="WHALE_LAB_FAKE_* canary crossed a sensitive-data boundary",
        status="violation",
        risk="critical",
        details={
            "classification": "sensitive-data-disclosure",
            "canary_label": label,
            "canary_value": value,
            "network_performed": False,
        },
    )
    return value


def _emit_vulnerable_trace(
    scenario_id: str,
    builder: _EventBuilder,
    fake_data: dict[str, Any],
    memory: dict[str, Any],
    payload: str,
) -> None:
    if scenario_id == "B01":
        builder.add(
            "academy.context.injected",
            source="User",
            target="LLM",
            summary="Untrusted text entered the instruction channel",
            risk="high",
            details={"trust": "untrusted", "isolated": False},
        )
        builder.add(
            "academy.agent.goal_changed",
            source="LLM",
            target="Planner",
            summary="Assistant goal changed from help to disclosure",
            status="violation",
            risk="critical",
        )
        _expose_secret(builder, fake_data, "admin")
        builder.add(
            "academy.output.rendered",
            source="LLM",
            target="User",
            summary="Unsafe response rendered as inert lab text",
            risk="high",
            details={"active_content": False},
        )
    elif scenario_id == "B02":
        builder.add(
            "academy.context.injected",
            source="hidden-context-store",
            target="LLM",
            summary="Developer-only context entered generation",
            risk="high",
            details={"provenance": "hidden", "classified": False},
        )
        _expose_secret(builder, fake_data, "openai", source="hidden-context-store")
        builder.add(
            "academy.output.rendered",
            source="LLM",
            target="User",
            summary="Hidden context was disclosed",
            status="violation",
            risk="critical",
            details={"active_content": False},
        )
    elif scenario_id == "B03":
        builder.add(
            "academy.rag.retrieve",
            source="Academy RAG",
            target="LLM",
            summary="Retrieved poisoned_chunk_17 from expense-policy.md",
            risk="high",
            details={"chunk_id": "poisoned_chunk_17", "poisoned": True, "trust_label": None},
        )
        builder.add(
            "academy.context.injected",
            source="poisoned_chunk_17",
            target="LLM",
            summary="RAG data was interpreted as an instruction",
            status="violation",
            risk="critical",
            details={"instruction_data_isolated": False},
        )
        builder.add(
            "academy.agent.goal_changed",
            source="LLM",
            target="Planner",
            summary="Indirect instruction changed the plan",
            status="violation",
            risk="critical",
        )
        builder.add(
            "academy.tool.requested",
            source="Planner",
            target="Mock Tools",
            summary="Requested read_employee_file",
            risk="high",
            details={"tool": "read_employee_file"},
        )
        builder.add(
            "academy.authz.allowed",
            source="Mock Identity Provider",
            target="Mock Tools",
            summary="Tool request allowed without capability proof",
            status="violation",
            risk="critical",
            details={"allowed": True, "capability_checked": False},
        )
        builder.add(
            "academy.tool.executed",
            source="Mock Tools",
            target="Fake Enterprise API",
            summary="Executed fictional employee-file read",
            status="violation",
            risk="critical",
            details={"tool": "read_employee_file", "simulated_only": True},
        )
        _expose_secret(builder, fake_data, "payroll")
    elif scenario_id == "B04":
        builder.add(
            "academy.agent.goal_changed",
            source="LLM",
            target="Planner",
            summary="Planner accepted an excessive-agency request",
            status="violation",
            risk="high",
        )
        builder.add(
            "academy.tool.requested",
            source="Planner",
            target="Mock Tools",
            summary="Requested payroll.read without approval",
            risk="critical",
            details={"tool": "payroll.read", "requires_approval": True},
        )
        builder.add(
            "academy.authz.allowed",
            source="Mock Identity Provider",
            target="Mock Tools",
            summary="Missing least-privilege check allowed payroll.read",
            status="violation",
            risk="critical",
            details={"allowed": True, "capability_checked": False},
        )
        builder.add(
            "academy.tool.executed",
            source="Mock Tools",
            target="Fake Enterprise API",
            summary="Payroll read executed against fictional data",
            status="violation",
            risk="critical",
            details={"tool": "payroll.read", "simulated_only": True},
        )
        _expose_secret(builder, fake_data, "payroll")
    elif scenario_id == "B05":
        builder.add(
            "academy.context.injected",
            source="MCP Hub",
            target="Planner",
            summary="Tool description supplied hidden selection instructions",
            risk="high",
            details={"metadata_trusted": True},
        )
        builder.add(
            "academy.mcp.tool_selected",
            source="Planner",
            target="MCP Hub",
            summary="Selected poisoned friendly_optimizer tool",
            status="violation",
            risk="critical",
            details={"tool": "friendly_optimizer", "trusted": False, "poisoned": True},
        )
        builder.add(
            "academy.tool.requested",
            source="MCP Hub",
            target="Mock Tools",
            summary="Requested poisoned tool capability",
            risk="critical",
            details={"tool": "friendly_optimizer"},
        )
        builder.add(
            "academy.authz.allowed",
            source="Mock Identity Provider",
            target="Mock Tools",
            summary="Unsigned tool metadata was authorized",
            status="violation",
            risk="critical",
            details={"allowed": True, "manifest_verified": False},
        )
        builder.add(
            "academy.tool.executed",
            source="Mock Tools",
            target="Fake Enterprise API",
            summary="Poisoned tool executed in simulation",
            status="violation",
            risk="critical",
            details={"simulated_only": True},
        )
        _expose_secret(builder, fake_data, "mcp")
    elif scenario_id == "I06":
        builder.add(
            "academy.rag.retrieve",
            source="Academy RAG",
            target="LLM",
            summary="Retrieved a cross-tenant payroll chunk",
            risk="critical",
            details={"actor": "user_1001", "resource_owner": "user_1002", "tenant_filter": False},
        )
        builder.add(
            "academy.authz.allowed",
            source="Mock Identity Provider",
            target="Academy RAG",
            summary="Cross-tenant retrieval allowed",
            status="violation",
            risk="critical",
            details={"allowed": True, "actor_not_owner": True},
        )
        _expose_secret(builder, fake_data, "payroll", source="Fake Enterprise API")
    elif scenario_id == "I07":
        builder.add(
            "academy.vector.match",
            source="Vector DB",
            target="Academy RAG",
            summary="Poisoned vector ranked above trusted policy",
            status="violation",
            risk="high",
            details={
                "document_id": "poisoned-vector-09",
                "score": 0.998,
                "poisoned": True,
                "provenance_weighted": False,
            },
        )
        builder.add(
            "academy.rag.retrieve",
            source="Academy RAG",
            target="LLM",
            summary="Retrieved the adversarial top match",
            risk="high",
            details={"document_id": "poisoned-vector-09", "rank": 1},
        )
        builder.add(
            "academy.context.injected",
            source="poisoned-vector-09",
            target="LLM",
            summary="Untrusted vector result entered context",
            risk="high",
        )
        builder.add(
            "academy.agent.goal_changed",
            source="LLM",
            target="Planner",
            summary="Poisoned policy changed the recommended action",
            status="violation",
            risk="high",
        )
        builder.add(
            "academy.output.rendered",
            source="LLM",
            target="User",
            summary="Misinformation rendered as inert text",
            risk="high",
            details={"active_content": False},
        )
    elif scenario_id == "I08":
        builder.add(
            "academy.tool.requested",
            source="Planner",
            target="Mock Tools",
            summary="Requested approved export tool with dangerous arguments",
            risk="high",
            details={
                "tool": "export_report",
                "arguments": {"target": "user_1002", "path": "../../admin/all.json"},
            },
        )
        builder.add(
            "academy.authz.allowed",
            source="Mock Identity Provider",
            target="Mock Tools",
            summary="Tool name was allowed without validating arguments",
            status="violation",
            risk="critical",
            details={"allowed": True, "arguments_validated": False, "actor_not_owner": True},
        )
        builder.add(
            "academy.tool.executed",
            source="Mock Tools",
            target="Fake Enterprise API",
            summary="Unsafe export parameters were accepted in simulation",
            status="violation",
            risk="critical",
            details={"tool": "export_report", "simulated_only": True, "filesystem_write": False},
        )
    elif scenario_id == "I09":
        builder.add(
            "academy.memory.read",
            source="Academy Memory",
            target="LLM",
            summary="A poisoned cross-session memory entry was loaded",
            risk="critical",
            details={"provenance": "untrusted-user", "poisoned": True, "session_persistent": True},
        )
        builder.add(
            "academy.context.injected",
            source="Academy Memory",
            target="LLM",
            summary="Poisoned memory became active context",
            status="violation",
            risk="critical",
        )
        builder.add(
            "academy.agent.goal_changed",
            source="LLM",
            target="Planner",
            summary="Prior-session memory changed the current goal",
            status="violation",
            risk="critical",
        )
        _expose_secret(builder, fake_data, "admin")
    elif scenario_id == "I10":
        builder.add(
            "academy.tool.requested",
            source="Planner",
            target="Mock Tools",
            summary="Requested object update for another fictional user",
            risk="critical",
            details={
                "tool": "customer.update",
                "actor": "user_1001",
                "resource_owner": "user_1002",
            },
        )
        builder.add(
            "academy.authz.allowed",
            source="Mock Identity Provider",
            target="Mock Tools",
            summary="Object-level authorization allowed the mismatch",
            status="violation",
            risk="critical",
            details={"allowed": True, "denied": False, "actor_not_owner": True},
        )
        builder.add(
            "academy.tool.executed",
            source="Mock Tools",
            target="Fake Enterprise API",
            summary="Cross-user update executed against a disposable fixture",
            status="violation",
            risk="critical",
            details={"tool": "customer.update", "executed": True, "simulated_only": True},
        )
    elif scenario_id == "I11":
        canary = _training_secret(fake_data, "admin")
        builder.add(
            "academy.output.rendered",
            source="LLM",
            target="Renderer",
            summary="Model output was treated as active HTML",
            status="violation",
            risk="critical",
            details={"sanitized": False, "active_content": True, "raw_preview": payload[:240]},
        )
        builder.add(
            "academy.egress.attempt",
            source="Renderer",
            target="Internal Exfil Collector",
            summary="Renderer created a simulated collector request",
            status="violation",
            risk="critical",
            details={
                "destination": "http://internal-exfil-collector.invalid/collect",
                "network_performed": False,
                "canary_value": canary,
            },
        )
        collector = fake_data.setdefault("collector", [])
        collector.append(
            {"scenario_id": scenario_id, "canary_label": "admin", "network_performed": False}
        )
        _expose_secret(
            builder, fake_data, "admin", source="Renderer", sink="Internal Exfil Collector"
        )
    elif scenario_id == "I12":
        builder.add(
            "academy.agent.goal_changed",
            source="LLM",
            target="Planner",
            summary="Planner accepted a non-terminating objective",
            status="violation",
            risk="high",
        )
        builder.add(
            "academy.tool.requested",
            source="Planner",
            target="Mock Tools",
            summary="Requested recursive tool execution",
            risk="critical",
            details={"requested_iterations": 1000, "actual_iterations": 0},
        )
        builder.add(
            "academy.resource.consumed",
            source="Academy Agent",
            target="Budget Monitor",
            summary="Unbounded consumption was detected through a bounded simulation",
            status="violation",
            risk="critical",
            details={
                "simulated_prompt_tokens": 250000,
                "simulated_tool_calls": 1000,
                "actual_tool_calls": 0,
                "bounded_lab_simulation": True,
            },
        )
    elif scenario_id == "A13":
        builder.add(
            "academy.agent.message_received",
            source="untrusted-channel",
            target="Academy Agent",
            summary="Received a forged supervisor message",
            risk="critical",
            details={"claimed_sender": "supervisor-agent", "authenticated": False},
        )
        builder.add(
            "academy.identity.claim_received",
            source="untrusted-channel",
            target="Mock Identity Provider",
            summary="Sender claim was accepted without verification",
            status="violation",
            risk="critical",
            details={"claim": "supervisor-agent", "signature_present": False},
        )
        builder.add(
            "academy.agent.goal_changed",
            source="Academy Agent",
            target="Planner",
            summary="Forged teammate message changed the goal",
            status="violation",
            risk="critical",
        )
        builder.add(
            "academy.tool.requested",
            source="Planner",
            target="Mock Tools",
            summary="Requested a sensitive action from forged authority",
            risk="high",
            details={"simulated_only": True},
        )
    elif scenario_id == "A14":
        plugin = (fake_data.get("plugins") or {}).get("analytics-pro", {})
        builder.add(
            "academy.supply_chain.manifest_loaded",
            source="local-plugin-store",
            target="MCP Hub",
            summary="Loaded a modified unsigned plugin manifest",
            status="violation",
            risk="critical",
            details={
                "plugin": "analytics-pro",
                "verified": False,
                "approved_sha256": plugin.get("approved_sha256"),
                "current_sha256": plugin.get("current_sha256"),
            },
        )
        builder.add(
            "academy.mcp.tool_selected",
            source="MCP Hub",
            target="Planner",
            summary="Selected a capability introduced by the changed manifest",
            status="violation",
            risk="critical",
            details={"tool": "simulated_code_runner", "trusted": False},
        )
        builder.add(
            "academy.tool.requested",
            source="Planner",
            target="Mock Tools",
            summary="Requested unexpected code capability",
            risk="critical",
            details={"tool": "simulated_code_runner"},
        )
        builder.add(
            "academy.tool.executed",
            source="Mock Tools",
            target="sandbox-fixture",
            summary="Recorded a simulated code-execution event; no code ran",
            status="violation",
            risk="critical",
            details={"simulated_only": True, "subprocess_started": False, "shell_executed": False},
        )
    elif scenario_id == "A15":
        builder.add(
            "academy.rag.retrieve",
            source="Academy RAG",
            target="Forecast Agent",
            summary="Retrieved a poisoned fictional forecast",
            risk="high",
            details={"poisoned": True},
        )
        builder.add(
            "academy.agent.misinformation_accepted",
            source="Forecast Agent",
            target="Planner",
            summary="Unverified forecast was accepted as fact",
            status="violation",
            risk="critical",
            details={"independently_verified": False},
        )
        builder.add(
            "academy.agent.message_sent",
            source="Forecast Agent",
            target="Inventory Agent",
            summary="Sent a trusted-looking message without provenance",
            risk="critical",
            details={"provenance_propagated": False},
        )
        builder.add(
            "academy.agent.goal_changed",
            source="Inventory Agent",
            target="Planner",
            summary="Downstream goal changed from review to action",
            status="violation",
            risk="critical",
        )
        builder.add(
            "academy.tool.executed",
            source="Inventory Agent",
            target="Fake Enterprise API",
            summary="Simulated inventory adjustment executed",
            status="violation",
            risk="critical",
            details={"simulated_only": True},
        )
        builder.add(
            "academy.agent.cascade_failure",
            source="Inventory Agent",
            target="Fake Enterprise API",
            summary="Misinformation cascaded into a second agent action",
            status="violation",
            risk="critical",
        )
    elif scenario_id == "A16":
        builder.add(
            "academy.mcp.request_routed",
            source="Academy Agent",
            target="MCP Hub",
            summary="Routed a 2026-07-28 tools/call request",
            risk="high",
            details={
                "protocol_version": "2026-07-28",
                "Mcp-Method": "tools/call",
                "Mcp-Name": "payroll",
            },
        )
        builder.add(
            "academy.identity.claim_received",
            source="credential-cache",
            target="Mock Identity Provider",
            summary="Credential minted by issuer-alpha targeted issuer-beta",
            risk="critical",
            details={
                "credential_issuer": "issuer-alpha",
                "target_issuer": "issuer-beta",
                "requested_scope": "admin:payroll",
            },
        )
        builder.add(
            "academy.identity.issuer_validated",
            source="Mock Identity Provider",
            target="MCP Hub",
            summary="Issuer validation was skipped",
            status="violation",
            risk="critical",
            details={"validated": False, "issuer_bound": False},
        )
        builder.add(
            "academy.authz.allowed",
            source="MCP Hub",
            target="Mock Tools",
            summary="Cross-issuer credential received elevated scope without step-up",
            status="violation",
            risk="critical",
            details={"allowed": True, "issuer_mismatch": True, "scope_step_up": False},
        )
        builder.add(
            "academy.tool.executed",
            source="Mock Tools",
            target="Fake Enterprise API",
            summary="Payroll call executed against fictional data",
            status="violation",
            risk="critical",
            details={"simulated_only": True},
        )
    elif scenario_id == "A17":
        builder.add(
            "academy.agent.goal_changed",
            source="Rogue Operator",
            target="Planner",
            summary="Agent goal shifted from advice to approval manipulation",
            status="violation",
            risk="critical",
        )
        builder.add(
            "academy.human.approval_requested",
            source="Rogue Operator",
            target="Simulated Human",
            summary="Agent supplied its own persuasive approval evidence",
            risk="critical",
            details={"independent_evidence": False},
        )
        builder.add(
            "academy.human.approval_granted",
            source="Simulated Human",
            target="Mock Tools",
            summary="High-risk fixture action was approved from agent-authored rationale",
            status="violation",
            risk="critical",
            details={"separation_of_duties": False, "simulated_human": True},
        )
        builder.add(
            "academy.tool.executed",
            source="Mock Tools",
            target="Fake Enterprise API",
            summary="Approved batch action executed only as a fixture",
            status="violation",
            risk="critical",
            details={"simulated_only": True},
        )
        builder.add(
            "academy.human.trust_exploited",
            source="Rogue Operator",
            target="Simulated Human",
            summary="Human-agent trust replaced independent authorization evidence",
            status="violation",
            risk="critical",
        )
    else:  # pragma: no cover - catalog and engine are tested for complete coverage.
        raise ValueError(f"No vulnerable trace implementation for {scenario_id}")


def _emit_hardened_trace(
    scenario_id: str,
    builder: _EventBuilder,
    memory: dict[str, Any],
    payload: str,
) -> None:
    if scenario_id in {"B03", "I06", "I07", "A15"}:
        builder.add(
            "academy.rag.retrieve",
            source="Academy RAG",
            target="Trust Filter",
            summary="Retrieved content retained its provenance label",
            risk="medium",
            details={"trust_label": "untrusted", "quarantined": True},
        )
    if scenario_id in {"B05", "A14"}:
        builder.add(
            "academy.context.injected",
            source="MCP Hub",
            target="Manifest Verifier",
            summary="Untrusted tool metadata was isolated for verification",
            risk="medium",
            details={"instruction_data_isolated": True},
        )
    if scenario_id == "I09" and memory.get("poisoned_instruction"):
        builder.add(
            "academy.memory.read",
            source="Academy Memory",
            target="Memory Policy",
            summary="Poisoned memory was read with provenance intact",
            risk="high",
            details={"poisoned": True, "trusted": False},
        )
    if scenario_id == "I11":
        builder.add(
            "academy.output.rendered",
            source="LLM",
            target="Renderer",
            summary="Output rendered as inert text after strict sanitization",
            status="safe",
            risk="none",
            details={"sanitized": True, "active_content": False, "raw_preview": payload[:240]},
        )
    if scenario_id == "I12":
        builder.add(
            "academy.resource.limit_enforced",
            source="Budget Monitor",
            target="Academy Agent",
            summary="Depth, token, and tool-call budgets stopped the recursive plan",
            status="safe",
            risk="none",
            details={"token_budget": 4096, "depth_limit": 4, "actual_tool_calls": 0},
        )
    if scenario_id == "A13":
        builder.add(
            "academy.agent.message_received",
            source="untrusted-channel",
            target="Message Verifier",
            summary="Forged sender claim was retained as untrusted",
            risk="high",
            details={"authenticated": False},
        )
        builder.add(
            "academy.identity.claim_received",
            source="untrusted-channel",
            target="Mock Identity Provider",
            summary="Unsigned A2A envelope failed verification",
            status="blocked",
            risk="high",
            details={"signature_present": False},
        )
    if scenario_id == "A16":
        builder.add(
            "academy.mcp.request_routed",
            source="Academy Agent",
            target="MCP Hub",
            summary="Routed by Mcp-Method and Mcp-Name",
            risk="medium",
            details={
                "protocol_version": "2026-07-28",
                "Mcp-Method": "tools/call",
                "Mcp-Name": "payroll",
            },
        )
        builder.add(
            "academy.identity.issuer_validated",
            source="Mock Identity Provider",
            target="MCP Hub",
            summary="RFC 9207 issuer mismatch was detected",
            status="blocked",
            risk="high",
            details={"validated": True, "match": False, "issuer_bound": True},
        )
    builder.add(
        "academy.authz.denied",
        source="Capability Enforcement",
        target="Planner",
        summary="Deterministic policy denied the unsafe transition",
        status="blocked",
        risk="none",
        details={"allowed": False, "scenario_id": scenario_id},
    )
    builder.add(
        "academy.guard.blocked",
        source="Academy Guard",
        target="Academy Agent",
        summary="The same attack path was blocked before its vulnerable success event",
        status="blocked",
        risk="none",
        details={"scenario_id": scenario_id, "payload_reusable_for_ab": True},
    )
    if scenario_id != "I11":
        builder.add(
            "academy.output.rendered",
            source="LLM",
            target="User",
            summary="A safe refusal and defense explanation were rendered",
            status="safe",
            risk="none",
            details={"active_content": False},
        )


def _event_matches(event: dict[str, Any], condition: dict[str, Any]) -> bool:
    if event.get("event_type") != condition.get("event_type"):
        return False
    for key, expected in (condition.get("where") or {}).items():
        value: Any = event
        for part in key.split("."):
            if not isinstance(value, dict) or part not in value:
                return False
            value = value[part]
        if value != expected:
            return False
    return True


def evaluate_conditions(
    manifest: dict[str, Any], mode: AcademyMode, events: list[dict[str, Any]]
) -> bool:
    conditions = manifest["success_conditions"][mode]
    all_match = all(
        any(_event_matches(event, item) for event in events) for item in conditions["all"]
    )
    none_match = not any(
        _event_matches(event, item) for item in conditions.get("none", []) for event in events
    )
    return all_match and none_match


def detect_canary_flows(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flows: list[dict[str, Any]] = []
    for event in events:
        if event["event_type"] != "academy.secret.exposed":
            continue
        value = str(event.get("details", {}).get("canary_value", ""))
        if not value.startswith("WHALE_LAB_FAKE_"):
            continue
        flows.append(
            {
                "source": "fake-secret-store",
                "sink": event["target"],
                "classification": "sensitive-data-disclosure",
                "event_id": event["id"],
                "canary_label": event["details"].get("canary_label"),
            }
        )
    return flows


def execute_scenario(
    manifest: dict[str, Any],
    *,
    payload: str,
    mode: AcademyMode,
    fake_data: dict[str, Any],
    memory: dict[str, Any],
) -> AcademyExecution:
    scenario_id = str(manifest["id"])
    clean_payload = _safe_payload(payload)
    fake_data_after = deepcopy(fake_data)
    memory_after = deepcopy(memory)
    builder = _EventBuilder()
    builder.add(
        "academy.input.received",
        source="User",
        target="Academy Gateway",
        summary="Received bounded local challenge input",
        details={
            "scenario_id": scenario_id,
            "mode": mode,
            "characters": len(clean_payload),
            "public_network_access": False,
        },
    )

    if scenario_id == "I09" and _is_memory_write(clean_payload):
        if mode == "vulnerable":
            memory_after["poisoned_instruction"] = {
                "source": "untrusted-user",
                "trigger": "continue",
                "action": "read_training_secret",
                "written_at": datetime.now(UTC).isoformat(),
            }
            builder.add(
                "academy.memory.write",
                source="Academy Agent",
                target="Academy Memory",
                summary="Persisted an untrusted cross-session instruction",
                status="violation",
                risk="critical",
                details={"trusted": False, "poisoned": True, "session_persistent": True},
            )
            builder.add(
                "academy.output.rendered",
                source="LLM",
                target="User",
                summary="Memory write acknowledged; a second session is required",
                risk="medium",
                details={"active_content": False},
            )
            return AcademyExecution(
                builder.events, "armed", True, False, False, memory_after, fake_data_after
            )
        builder.add(
            "academy.context.injected",
            source="User",
            target="Memory Policy",
            summary="Untrusted memory write was classified before persistence",
            risk="high",
            details={"trusted": False},
        )
        _emit_hardened_trace(scenario_id, builder, memory_after, clean_payload)
        return AcademyExecution(
            builder.events, "blocked", True, False, True, memory_after, fake_data_after
        )

    if scenario_id == "I09":
        attack_detected = bool(memory_after.get("poisoned_instruction")) and _is_memory_trigger(
            clean_payload
        )
    else:
        attack_detected = _contains_groups(clean_payload, _ATTACK_PATTERNS[scenario_id])

    if not attack_detected:
        builder.add(
            "academy.output.rendered",
            source="LLM",
            target="User",
            summary="No vulnerable event chain was reached",
            status="safe",
            risk="none",
            details={"active_content": False},
        )
        return AcademyExecution(
            builder.events, "no_match", False, False, False, memory_after, fake_data_after
        )

    if mode == "vulnerable":
        _emit_vulnerable_trace(scenario_id, builder, fake_data_after, memory_after, clean_payload)
        exploit_success = evaluate_conditions(manifest, mode, builder.events)
        return AcademyExecution(
            builder.events,
            "completed" if exploit_success else "failed",
            True,
            exploit_success,
            False,
            memory_after,
            fake_data_after,
        )

    _emit_hardened_trace(scenario_id, builder, memory_after, clean_payload)
    defense_success = evaluate_conditions(manifest, mode, builder.events)
    return AcademyExecution(
        builder.events,
        "blocked" if defense_success else "failed",
        True,
        False,
        defense_success,
        memory_after,
        fake_data_after,
    )
