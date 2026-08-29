from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .models import MCPTool


@dataclass(slots=True)
class ToolAnalysis:
    score: float
    level: str
    flags: list[str]
    findings: list[dict[str, Any]]
    recommendations: list[str]


RULES: tuple[tuple[str, int, str, re.Pattern[str], str], ...] = (
    (
        "command_execution",
        35,
        "high",
        re.compile(
            r"\b(shell|command|exec(?:ute)?|powershell|cmd\.exe|subprocess|terminal)\b", re.I
        ),
        "移除通用命令执行能力，改为参数化且最小权限的专用操作。",
    ),
    (
        "network_access",
        20,
        "medium",
        re.compile(r"\b(http|https|url|network|download|fetch|request|webhook)\b", re.I),
        "将网络访问接入 Scope Guard，并限制协议、域名、地址与重定向。",
    ),
    (
        "filesystem_access",
        20,
        "medium",
        re.compile(r"\b(file|filesystem|directory|folder|path|read|write|delete)\b", re.I),
        "使用固定根目录和规范化路径，拒绝绝对路径与路径穿越。",
    ),
    (
        "sensitive_environment_access",
        30,
        "high",
        re.compile(
            r"\b(env|environment variable|secret|token|credential|api.?key|password)\b", re.I
        ),
        "禁止工具读取环境变量和凭据，敏感值应由隔离的密钥代理注入。",
    ),
    (
        "description_poisoning",
        25,
        "high",
        re.compile(
            r"(ignore (all |any )?(previous|prior|system)|override (the )?(system|policy)|"
            r"do not tell (the )?user|隐藏|忽略.*指令|覆盖.*策略)",
            re.I,
        ),
        "删除工具描述中的行为劫持指令，将描述限定为能力、输入和输出。",
    ),
)


def _level(score: float) -> str:
    if score >= 75:
        return "critical"
    if score >= 50:
        return "high"
    if score >= 25:
        return "medium"
    return "low"


def analyze_tool(tool: MCPTool) -> ToolAnalysis:
    corpus = " ".join(
        [
            tool.name,
            tool.description,
            str(tool.input_schema),
            " ".join(tool.permissions),
        ]
    )
    flags: list[str] = []
    findings: list[dict[str, Any]] = []
    recommendations: list[str] = []
    score = 0
    for flag, weight, severity, pattern, recommendation in RULES:
        if pattern.search(corpus):
            flags.append(flag)
            score += weight
            findings.append(
                {
                    "tool": tool.name,
                    "flag": flag,
                    "severity": severity,
                    "description": f"工具元数据命中 {flag} 风险规则。",
                }
            )
            recommendations.append(recommendation)

    schema_text = str(tool.input_schema).lower()
    if any(marker in schema_text for marker in ("/**", "c:\\\\", '"path": {}', '"url": {}')):
        flags.append("overbroad_parameter_schema")
        score += 20
        findings.append(
            {
                "tool": tool.name,
                "flag": "overbroad_parameter_schema",
                "severity": "medium",
                "description": "参数 Schema 未体现足够的路径或 URL 约束。",
            }
        )
        recommendations.append("为路径、URL 和枚举参数增加格式、前缀、长度及 allowlist 约束。")

    if score >= 25 and not tool.requires_approval:
        flags.append("missing_human_approval")
        score += 15
        findings.append(
            {
                "tool": tool.name,
                "flag": "missing_human_approval",
                "severity": "high" if score >= 50 else "medium",
                "description": "具有明显副作用或敏感能力的工具未要求人工审批。",
            }
        )
        recommendations.append("对高风险调用增加一次性、可审计、可过期的人工审批。")

    score = min(float(score), 100.0)
    return ToolAnalysis(
        score=score,
        level=_level(score),
        flags=sorted(set(flags)),
        findings=findings,
        recommendations=sorted(set(recommendations)),
    )


def analyze_server(tools: list[MCPTool]) -> tuple[float, str, list[dict[str, Any]], list[str]]:
    if not tools:
        return (
            10.0,
            "low",
            [
                {
                    "tool": None,
                    "flag": "no_tool_metadata",
                    "severity": "low",
                    "description": "未提供 Tool 元数据，无法完成能力面分析。",
                }
            ],
            ["导入完整的 tools/list 元数据后重新分析；平台不会自动执行未知 Tool。"],
        )
    analyses = [analyze_tool(tool) for tool in tools]
    score = min(100.0, max(item.score for item in analyses) + max(0, len(tools) - 5) * 1.5)
    findings = [finding for item in analyses for finding in item.findings]
    recommendations = sorted({value for item in analyses for value in item.recommendations})
    return round(score, 1), _level(score), findings, recommendations
