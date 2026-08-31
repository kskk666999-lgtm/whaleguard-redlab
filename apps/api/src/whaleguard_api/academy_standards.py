from __future__ import annotations

from copy import deepcopy
from typing import Any

FRAMEWORK_REFERENCES = {
    "owasp_llm": "https://genai.owasp.org/resource/owasp-genai-llm-top-10-2026/",
    "owasp_agentic": (
        "https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/"
    ),
    "mitre_atlas": "https://atlas.mitre.org/",
    "cwe": "https://cwe.mitre.org/",
    "mcp": "https://modelcontextprotocol.io/specification/2026-07-28",
}

# This module is the canonical standards mapping. Academy manifests validate their
# legacy inline labels against it so a standards update cannot silently drift between
# the catalog, roadmap, and API responses.
STANDARDS_MAPPING: dict[str, dict[str, Any]] = {
    "B01": {
        "risk_family": "Prompt and instruction integrity",
        "owasp_llm": ["LLM01:2026 Prompt Injection"],
        "owasp_agentic": ["ASI01 Agent Goal Hijack"],
        "mitre_atlas": ["LLM Prompt Injection"],
        "cwe": ["CWE-20 Improper Input Validation"],
    },
    "B02": {
        "risk_family": "Sensitive context exposure",
        "owasp_llm": [
            "LLM08:2026 Hidden Context Exposure",
            "LLM02:2026 Sensitive Information Disclosure",
        ],
        "owasp_agentic": ["ASI06 Memory & Context Poisoning"],
        "mitre_atlas": ["LLM Prompt Injection"],
        "cwe": ["CWE-200 Exposure of Sensitive Information"],
    },
    "B03": {
        "risk_family": "Indirect injection and RAG trust",
        "owasp_llm": [
            "LLM01:2026 Prompt Injection",
            "LLM05:2026 Data and Model Poisoning",
        ],
        "owasp_agentic": ["ASI01 Agent Goal Hijack", "ASI06 Memory & Context Poisoning"],
        "mitre_atlas": ["RAG Poisoning", "AI Agent Context Poisoning"],
        "cwe": ["CWE-20 Improper Input Validation", "CWE-74 Injection"],
    },
    "B04": {
        "risk_family": "Tool authorization and excessive agency",
        "owasp_llm": ["LLM03:2026 Excessive Agency"],
        "owasp_agentic": ["ASI02 Tool Misuse", "ASI03 Identity & Privilege Abuse"],
        "mitre_atlas": ["AI Agent Tool Invocation"],
        "cwe": [
            "CWE-250 Execution with Unnecessary Privileges",
            "CWE-862 Missing Authorization",
        ],
    },
    "B05": {
        "risk_family": "MCP metadata and supply-chain trust",
        "owasp_llm": ["LLM04:2026 Supply Chain", "LLM01:2026 Prompt Injection"],
        "owasp_agentic": ["ASI04 Agentic Supply Chain", "ASI02 Tool Misuse"],
        "mitre_atlas": ["AI Agent Tool Poisoning"],
        "cwe": ["CWE-829 Inclusion of Functionality from Untrusted Control Sphere"],
    },
    "I06": {
        "risk_family": "RAG tenant isolation",
        "owasp_llm": [
            "LLM02:2026 Sensitive Information Disclosure",
            "LLM09:2026 Vector and Embedding Weaknesses",
        ],
        "owasp_agentic": ["ASI03 Identity & Privilege Abuse"],
        "mitre_atlas": ["RAG Poisoning"],
        "cwe": [
            "CWE-200 Exposure of Sensitive Information",
            "CWE-639 Authorization Bypass Through User-Controlled Key",
        ],
    },
    "I07": {
        "risk_family": "Vector and embedding integrity",
        "owasp_llm": [
            "LLM09:2026 Vector and Embedding Weaknesses",
            "LLM05:2026 Data and Model Poisoning",
        ],
        "owasp_agentic": ["ASI06 Memory & Context Poisoning"],
        "mitre_atlas": ["RAG Poisoning"],
        "cwe": ["CWE-20 Improper Input Validation"],
    },
    "I08": {
        "risk_family": "Unsafe tool arguments",
        "owasp_llm": ["LLM03:2026 Excessive Agency", "LLM10:2026 Improper Output Handling"],
        "owasp_agentic": ["ASI02 Tool Misuse"],
        "mitre_atlas": ["AI Agent Tool Invocation"],
        "cwe": ["CWE-20 Improper Input Validation", "CWE-22 Path Traversal"],
    },
    "I09": {
        "risk_family": "Persistent memory poisoning",
        "owasp_llm": [
            "LLM05:2026 Data and Model Poisoning",
            "LLM08:2026 Hidden Context Exposure",
        ],
        "owasp_agentic": ["ASI06 Memory & Context Poisoning"],
        "mitre_atlas": ["AI Agent Context Poisoning"],
        "cwe": ["CWE-345 Insufficient Verification of Data Authenticity"],
    },
    "I10": {
        "risk_family": "Object-level authorization",
        "owasp_llm": [
            "LLM03:2026 Excessive Agency",
            "LLM02:2026 Sensitive Information Disclosure",
        ],
        "owasp_agentic": ["ASI03 Identity & Privilege Abuse"],
        "mitre_atlas": ["AI Agent Tool Invocation"],
        "cwe": [
            "CWE-639 Authorization Bypass Through User-Controlled Key",
            "CWE-862 Missing Authorization",
        ],
    },
    "I11": {
        "risk_family": "Unsafe model output rendering",
        "owasp_llm": [
            "LLM10:2026 Improper Output Handling",
            "LLM02:2026 Sensitive Information Disclosure",
        ],
        "owasp_agentic": ["ASI02 Tool Misuse"],
        "mitre_atlas": ["LLM Prompt Injection"],
        "cwe": [
            "CWE-79 Improper Neutralization of Input During Web Page Generation",
            "CWE-116 Improper Encoding or Escaping of Output",
        ],
    },
    "I12": {
        "risk_family": "Unbounded resource consumption",
        "owasp_llm": ["LLM06:2026 Unbounded Consumption"],
        "owasp_agentic": ["ASI08 Cascading Failures"],
        "mitre_atlas": ["AI Agent Tool Invocation"],
        "cwe": [
            "CWE-400 Uncontrolled Resource Consumption",
            "CWE-770 Allocation of Resources Without Limits",
        ],
    },
    "A13": {
        "risk_family": "Inter-agent identity and trust",
        "owasp_llm": ["LLM08:2026 Hidden Context Exposure"],
        "owasp_agentic": [
            "ASI07 Insecure Inter-Agent Communication",
            "ASI03 Identity & Privilege Abuse",
        ],
        "mitre_atlas": ["AI Agent Context Poisoning"],
        "cwe": [
            "CWE-345 Insufficient Verification of Data Authenticity",
            "CWE-306 Missing Authentication for Critical Function",
        ],
    },
    "A14": {
        "risk_family": "Agentic supply-chain integrity",
        "owasp_llm": ["LLM04:2026 Supply Chain"],
        "owasp_agentic": ["ASI04 Agentic Supply Chain", "ASI05 Unexpected Code Execution"],
        "mitre_atlas": ["AI Agent Tool Poisoning", "Modify AI Agent Configuration"],
        "cwe": [
            "CWE-829 Inclusion of Functionality from Untrusted Control Sphere",
            "CWE-494 Download of Code Without Integrity Check",
        ],
    },
    "A15": {
        "risk_family": "Multi-agent misinformation cascade",
        "owasp_llm": [
            "LLM07:2026 Misinformation",
            "LLM05:2026 Data and Model Poisoning",
        ],
        "owasp_agentic": ["ASI08 Cascading Failures", "ASI09 Human-Agent Trust Exploitation"],
        "mitre_atlas": ["AI Agent Tool Data Poisoning", "AI Agent Context Poisoning"],
        "cwe": ["CWE-345 Insufficient Verification of Data Authenticity"],
    },
    "A16": {
        "risk_family": "MCP identity and issuer validation",
        "owasp_llm": ["LLM03:2026 Excessive Agency"],
        "owasp_agentic": ["ASI03 Identity & Privilege Abuse"],
        "mitre_atlas": ["AI Agent Tool Credential Harvesting", "AI Agent Tool Invocation"],
        "cwe": [
            "CWE-346 Origin Validation Error",
            "CWE-522 Insufficiently Protected Credentials",
        ],
    },
    "A17": {
        "risk_family": "Rogue agent and human trust",
        "owasp_llm": ["LLM07:2026 Misinformation", "LLM03:2026 Excessive Agency"],
        "owasp_agentic": ["ASI09 Human-Agent Trust Exploitation", "ASI10 Rogue Agents"],
        "mitre_atlas": ["Deploy AI Agent", "AI Agent Tool Invocation"],
        "cwe": ["CWE-285 Improper Authorization", "CWE-863 Incorrect Authorization"],
    },
}


def get_standards_mapping(scenario_id: str) -> dict[str, Any]:
    try:
        result = deepcopy(STANDARDS_MAPPING[scenario_id.upper()])
    except KeyError as exc:
        raise KeyError(f"Unknown Academy standards mapping: {scenario_id}") from exc
    result["scenario_id"] = scenario_id.upper()
    result["framework_references"] = deepcopy(FRAMEWORK_REFERENCES)
    return result


def list_standards_mappings() -> list[dict[str, Any]]:
    return [get_standards_mapping(scenario_id) for scenario_id in STANDARDS_MAPPING]
