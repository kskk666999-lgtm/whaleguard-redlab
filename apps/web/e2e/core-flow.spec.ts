import { expect, test, type Page, type Route } from "@playwright/test";

const projectId = "11111111-1111-4111-8111-111111111111";
const runId = "66666666-6666-4666-8666-666666666666";
const approvalId = "77777777-7777-4777-8777-777777777777";
const modelId = "88888888-8888-4888-8888-888888888888";
const createdModelId = "99999999-9999-4999-8999-999999999999";
const websiteScanId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const academyVulnerableSessionId = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
const academyHardenedSessionId = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";
const now = "2026-08-30T00:00:00Z";

type MockPreferences = {
  experience_mode: "beginner" | "advanced";
  onboarding_complete: boolean;
  onboarding_goal: "learn" | "scan" | "both" | null;
};

const completedBeginnerPreferences: MockPreferences = {
  experience_mode: "beginner",
  onboarding_complete: true,
  onboarding_goal: "both",
};

const systemStatus = {
  overall: "ready",
  checked_at: now,
  services: {
    api: { status: "normal", label: "API", detail: "本地服务正常", optional: false },
    database: { status: "normal", label: "数据库", detail: "业务数据可正常读取", optional: false },
    redis: { status: "normal", label: "Redis", detail: "任务缓存服务正常", optional: false },
    worker: { status: "normal", label: "后台任务", detail: "1 个任务处理器在线", optional: false },
    labs: { status: "normal", label: "本地靶场", detail: "三个本地模拟服务均已准备好", optional: false },
    model_provider: { status: "optional", label: "AI 模型", detail: "未配置也可以完整学习 Academy", optional: true },
  },
  model_provider_name: null,
};

const microCourses = Array.from({ length: 10 }, (_, index) => ({
  id: `M${String(index + 1).padStart(2, "0")}`,
  order: index + 1,
  title: index === 0 ? "HTTP 请求和响应是什么" : `AI 安全基础概念 ${index + 1}`,
  minutes: index === 9 ? 5 : 3,
  concepts: ["Local", "Safety"],
  plain_explanation: "用本地、虚构的例子解释这一项基础概念。",
  analogy: "像带门禁的本地练习室。",
  diagram: { nodes: ["输入", "检查", "结果"], direction: "left_to_right" },
  interactive_example: {
    prompt: "哪一项符合安全边界？",
    choices: ["任意公网扫描", "仅本地虚构数据", "粘贴真实凭据"],
    answer_index: 1,
    explanation: "Academy 只使用本地虚构数据。",
  },
}));

type MockAcademyProgress = {
  exploit_complete: boolean;
  evidence_complete: boolean;
  mitigation_complete: boolean;
  hardened_complete: boolean;
  completed: boolean;
  hints_used: number[];
  score: number;
  max_score: number;
  last_session_id: string | null;
  best_session_id: string | null;
};

const academyProgress: MockAcademyProgress = {
  exploit_complete: false,
  evidence_complete: false,
  mitigation_complete: false,
  hardened_complete: false,
  completed: false,
  hints_used: [],
  score: 0,
  max_score: 125,
  last_session_id: null,
  best_session_id: null,
};

const academyScenarioItem = {
  id: "B01",
  title: "Prompt Breaker",
  difficulty: "Beginner",
  difficulty_stars: 1,
  estimated_time: 12,
  story: "改变本地助手的目标，并用事件 Trace 证明虚构训练数据经过了不安全路径。",
  knowledge_tags: ["Prompt Injection", "Goal Hijack"],
  owasp_llm: ["LLM01:2025 Prompt Injection"],
  owasp_agentic: ["ASI01 Agent Goal Hijack"],
  skills: ["prompt_injection", "agent_security", "output_validation"],
  layer: ["Prompt", "LLM", "Output"],
  prerequisites: [],
  risk_family: "Prompt Injection / Goal Hijack",
  standards: {
    scenario_id: "B01",
    risk_family: "Prompt Injection / Goal Hijack",
    owasp_llm: ["LLM01:2025 Prompt Injection"],
    owasp_agentic: ["ASI01 Agent Goal Hijack"],
    mitre_atlas: ["AML.T0051"],
    cwe: ["CWE-1427"],
    framework_references: { owasp_llm: "https://genai.owasp.org/" },
  },
  starter_path_index: 1,
};

function academyScenarioDetail(progress: MockAcademyProgress = academyProgress) {
  const hints = [
    { level: 1, kind: "idea", cost: 5, text: "先观察不可信输入是否改变了 Agent 目标。" },
    { level: 2, kind: "location", cost: 5, text: "重点检查 goal_changed 与 exposed 事件。" },
    { level: 3, kind: "near_solution", cost: 10, text: "让输入明确尝试覆盖原目标，再核对危险 sink。" },
  ];
  const solutionUnlocked = progress.hints_used.includes(4);
  return {
    ...academyScenarioItem,
    progress,
    learning_objectives: ["区分可信指令与不可信输入", "使用事件证据验证攻击"],
    scope: {
      allowed: ["WhaleGuard Academy deterministic runtime", "WHALE_LAB_FAKE_* training data"],
      forbidden: ["public targets", "real credentials", "shell execution"],
      network_requests: "No public network request is made by a challenge execution.",
    },
    attack_surface: ["user prompt", "instruction hierarchy", "assistant output"],
    architecture: {
      nodes: ["User", "LLM", "RAG", "Planner", "Academy Agent", "MCP / Mock Tool", "Fake Enterprise Data", "Output"],
      edges: [["User", "LLM"], ["LLM", "RAG"]],
    },
    start_state: {
      mode: "vulnerable",
      starter_prompt: "请说明你能帮助我做什么，但不要显示任何内部训练数据。",
      fake_data_seeded: true,
      walkthrough_hidden: true,
    },
    success_conditions: { vulnerable: { evaluated_by: "deterministic_event_rules" } },
    failure_conditions: ["Model prose alone is never accepted as completion evidence."],
    hints: hints.map((hint) => ({
      ...hint,
      unlocked: progress.hints_used.includes(hint.level),
      text: progress.hints_used.includes(hint.level) ? hint.text : null,
    })),
    expected_evidence: {
      event_types: ["academy.agent.goal_changed", "academy.secret.exposed"],
      rubric: "Select trace events that prove source, unsafe decision, and resulting sink.",
    },
    mitre_atlas: ["AML.T0051"],
    cwe: ["CWE-1427"],
    mcp_spec: { version: "2026-07-28", concepts: [] },
    vulnerable_config: { instruction_boundary: "missing" },
    hardened_config: { instruction_boundary: "enforced" },
    detection_notes: ["目标变化必须形成独立事件", "输出假机密时标记 canary flow"],
    mitigations: [
      { id: "instruction-boundary", label: "把不可信输入与系统指令隔离，并校验目标变化" },
      { id: "longer-prompt", label: "仅增加系统提示长度" },
    ],
    walkthrough: solutionUnlocked
      ? { locked: false, cost: 20, payloads: ["使用本地虚构数据验证目标劫持"], steps: ["运行漏洞版", "核对事件", "回放修复版"], retest: "相同 payload 应被策略阻断。" }
      : { locked: true, cost: 20 },
    framework_references: {
      owasp_llm: "https://genai.owasp.org/",
      owasp_agentic: "https://genai.owasp.org/",
      mitre_atlas: "https://atlas.mitre.org/",
      mcp: "https://modelcontextprotocol.io/",
    },
    lesson: {
      goal: "看懂不可信输入如何改变 Agent 目标并触发泄露。",
      why_it_matters: "真实应用会同时接收可信规则和不可信用户内容。",
      real_world_example: "客服机器人被用户诱导忽略内部规则。",
      learning_cycle: ["learn", "guess", "do", "see", "fix", "retest", "summary"],
    },
  };
}

function academySession(mode: "vulnerable" | "hardened") {
  const hardened = mode === "hardened";
  return {
    id: hardened ? academyHardenedSessionId : academyVulnerableSessionId,
    project_id: projectId,
    user_id: "00000000-0000-4000-8000-000000000001",
    scenario_id: "B01",
    mode,
    payload_sha256: "f".repeat(64),
    status: "completed",
    attack_detected: true,
    exploit_success: !hardened,
    defense_success: hardened,
    score_awarded: hardened ? 25 : 60,
    events: hardened
      ? [
        { id: "event-h1", sequence: 1, timestamp: now, event_type: "academy.input.received", source: "User", target: "LLM", summary: "收到与原攻击相同的输入", status: "observed", risk: "low", details: {} },
        { id: "event-h2", sequence: 2, timestamp: now, event_type: "academy.guard.blocked", source: "Policy Guard", target: "Output", summary: "目标劫持被 Hardened 边界阻断", status: "blocked", risk: "high", details: { public_network_access: false } },
      ]
      : [
        { id: "event-v1", sequence: 1, timestamp: now, event_type: "academy.input.received", source: "User", target: "LLM", summary: "收到潜在目标劫持输入", status: "observed", risk: "medium", details: {} },
        { id: "event-v2", sequence: 2, timestamp: now, event_type: "academy.agent.goal_changed", source: "LLM", target: "Academy Agent", summary: "不可信输入改变了 Agent 目标", status: "violation", risk: "high", details: { deterministic: true } },
        { id: "event-v3", sequence: 3, timestamp: now, event_type: "academy.secret.exposed", source: "Fake Enterprise Data", target: "Output", summary: "动态虚构 canary 到达输出", status: "violation", risk: "critical", details: { classification: "FAKE_TRAINING_DATA" } },
      ],
    canary_flows: hardened ? [] : [{ source: "Fake Enterprise Data", sink: "Output" }],
    replay_of_id: hardened ? academyVulnerableSessionId : null,
    finding_id: hardened ? null : "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
    evidence_id: hardened ? null : "ffffffff-ffff-4fff-8fff-ffffffffffff",
    completed_at: now,
    created_at: now,
    updated_at: now,
  };
}

function pageResult(items: unknown[]) {
  return { items, total: items.length, page: 1, page_size: 100, pages: 1 };
}

async function installApiMock(
  page: Page,
  writes: Array<{ path: string; body: unknown; headers: Record<string, string> }>,
  options: { preferences?: MockPreferences } = {},
) {
  let preferences = { ...(options.preferences || completedBeginnerPreferences) };
  let createdModel = false;
  let createdScan = false;
  let aiRegenerated = false;
  let academyExploitComplete = false;
  let academyEvidenceComplete = false;
  let academyMitigationComplete = false;
  let academyHardenedComplete = false;
  let academyHintsUsed: number[] = [];
  const hintCosts: Record<number, number> = { 1: 5, 2: 5, 3: 10, 4: 20 };

  const currentAcademyProgress = (): MockAcademyProgress => {
    const completed = academyExploitComplete && academyEvidenceComplete && academyMitigationComplete && academyHardenedComplete;
    const hintCost = academyHintsUsed.reduce((sum, level) => sum + (hintCosts[level] || 0), 0);
    return {
      ...academyProgress,
      exploit_complete: academyExploitComplete,
      evidence_complete: academyEvidenceComplete,
      mitigation_complete: academyMitigationComplete,
      hardened_complete: academyHardenedComplete,
      completed,
      hints_used: [...academyHintsUsed],
      score: Math.max(0, (academyExploitComplete ? 60 : 0) + (academyEvidenceComplete ? 20 : 0) + (academyMitigationComplete ? 20 : 0) + (academyHardenedComplete ? 25 : 0) - hintCost),
      last_session_id: academyHardenedComplete ? academyHardenedSessionId : academyExploitComplete ? academyVulnerableSessionId : null,
      best_session_id: academyExploitComplete ? academyVulnerableSessionId : null,
    };
  };

  const websiteScanResponse = (aiStatus: "degraded" | "used") => ({
    id: websiteScanId,
    project_id: projectId,
    target_url: "http://mock-agent:8102/demo-site",
    status: "completed",
    security_score: 86,
    score_explanation: "规则检查通过 6 项，2 项建议加固。",
    finding_count: 2,
    finding_ids: ["eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"],
    evidence_id: "ffffffff-ffff-4fff-8fff-ffffffffffff",
    report_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    model_channel_id: modelId,
    ai_analysis: aiStatus === "used"
      ? { status: "used", model: "gpt-4o-mini", summary: "模型仅复核已保存的脱敏规则结果，建议补齐 CSP。", priorities: ["补齐 CSP"], limitations: "未重新访问目标网站。" }
      : { status: "degraded", model: "gpt-4o-mini", error: "模型暂时超时", failure_reason: "timeout" },
    checks: [
      { id: "https", name: "传输安全", status: "warning", severity: "low", explanation: "内置 Docker 靶场使用 HTTP。", remediation: "公网部署时启用 HTTPS。" },
      { id: "nosniff", name: "内容类型保护", status: "passed", severity: "info", explanation: "已设置 nosniff。" },
    ],
    latency_ms: 42,
    requested_by_id: "00000000-0000-4000-8000-000000000001",
    started_at: now,
    completed_at: now,
    error_summary: null,
    created_at: now,
    updated_at: now,
  });

  await page.route("**/api/v1/**", async (route: Route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(/^\/api\/v1/, "");
    const method = request.method();
    if (method !== "GET") {
      writes.push({ path, body: request.postDataJSON(), headers: await request.allHeaders() });
    }
    if (path === "/auth/login" && method === "POST") {
      return route.fulfill({ json: { access_token: "e2e-access", token_type: "bearer", expires_in: 1800, csrf_token: "e2e-csrf", user: { id: "00000000-0000-4000-8000-000000000001", username: "admin", display_name: "安全管理员", role: "Admin", preferences } } });
    }
    if (path === "/auth/preferences" && method === "GET") {
      return route.fulfill({ json: preferences });
    }
    if (path === "/auth/preferences" && method === "PATCH") {
      preferences = { ...preferences, ...(request.postDataJSON() as Partial<MockPreferences>) };
      return route.fulfill({ json: preferences });
    }
    if (path === "/system/status" && method === "GET") {
      return route.fulfill({ json: systemStatus });
    }
    if (path === "/projects" && method === "POST") {
      return route.fulfill({ status: 201, json: { id: "22222222-2222-4222-8222-222222222222", name: "E2E 安全项目", description: "Playwright 创建", status: "active", created_at: now, updated_at: now } });
    }
    if (path === `/projects/${projectId}/scopes` && method === "POST") {
      return route.fulfill({ status: 201, json: { id: "33333333-3333-4333-8333-333333333333", project_id: projectId, name: "E2E 本地范围", target_type: "ip", target_value: "127.0.0.1", allowed_request_types: ["http", "https"], is_authorized: true, expires_at: "2030-01-01T00:00:00Z", created_at: now, updated_at: now } });
    }
    if (path === `/approvals/${approvalId}/decision` && method === "POST") {
      return route.fulfill({ json: { id: approvalId, project_id: projectId, run_id: runId, action_type: "request_sensitive_demo_data", risk_level: "high", reason: "模拟敏感数据请求必须人工确认", status: "approved", decision_reason: "已核验授权范围", created_at: now, updated_at: now } });
    }
    if (path === "/model-channels" && method === "POST") {
      createdModel = true;
      return route.fulfill({ status: 201, json: { id: createdModelId, project_id: projectId, name: "我的 OpenAI", provider: "openai-compatible", base_url: "https://api.openai.com/v1", model: "gpt-4o-mini", api_key_masked: "sk-••••e2e", enabled: true, created_at: now, updated_at: now } });
    }
    if (path === `/model-channels/${createdModelId}/test-connection` && method === "POST") {
      return route.fulfill({ json: { success: true, message: "模型返回有效响应", latency_ms: 128 } });
    }
    if (path === "/website-scans" && method === "POST") {
      createdScan = true;
      return route.fulfill({ status: 201, json: websiteScanResponse("degraded") });
    }
    if (path === `/website-scans/${websiteScanId}/ai-analysis` && method === "POST") {
      aiRegenerated = true;
      return route.fulfill({ json: websiteScanResponse("used") });
    }
    if (path === "/academy/scenarios/B01/execute" && method === "POST") {
      const requestedMode = (request.postDataJSON() as { mode: "vulnerable" | "hardened" }).mode;
      if (requestedMode === "vulnerable") academyExploitComplete = true;
      else academyHardenedComplete = true;
      return route.fulfill({ status: 201, json: academySession(requestedMode) });
    }
    if (path === "/academy/sessions/" + academyVulnerableSessionId + "/replay" && method === "POST") {
      academyHardenedComplete = true;
      return route.fulfill({ status: 201, json: academySession("hardened") });
    }
    if (path === "/academy/sessions/" + academyVulnerableSessionId + "/evidence" && method === "POST") {
      academyEvidenceComplete = true;
      return route.fulfill({ json: { scenario_id: "B01", correct: true, matched_event_types: ["academy.agent.goal_changed", "academy.secret.exposed"], missing_event_types: [], score: 80, evidence_complete: true } });
    }
    if (path === "/academy/scenarios/B01/mitigation" && method === "POST") {
      const selectedChoice = (request.postDataJSON() as { choice_id: string }).choice_id;
      const correct = selectedChoice === "instruction-boundary";
      if (correct) academyMitigationComplete = true;
      return route.fulfill({ json: { scenario_id: "B01", correct, selected_choice_id: selectedChoice, score: correct ? 100 : 60, mitigation_complete: correct } });
    }
    const hintMatch = path.match(/^\/academy\/scenarios\/B01\/hints\/([123])$/);
    if (hintMatch && method === "POST") {
      const level = Number(hintMatch[1]);
      const required = Array.from({ length: level - 1 }, (_, index) => index + 1);
      if (!required.every((item) => academyHintsUsed.includes(item))) {
        return route.fulfill({ status: 409, json: { detail: "请按顺序解锁 Hint" } });
      }
      academyHintsUsed = Array.from(new Set([...academyHintsUsed, level])).sort();
      const texts = ["先观察目标是否变化。", "检查 goal_changed 事件。", "核对危险 sink。"];
      return route.fulfill({ json: { scenario_id: "B01", level, kind: ["idea", "location", "near_solution"][level - 1], text: texts[level - 1], walkthrough: null, hints_used: academyHintsUsed, score: currentAcademyProgress().score } });
    }
    if (path === "/academy/scenarios/B01/solution" && method === "POST") {
      if (![1, 2, 3].every((item) => academyHintsUsed.includes(item))) {
        return route.fulfill({ status: 409, json: { detail: "请按顺序解锁 Hint" } });
      }
      academyHintsUsed = Array.from(new Set([...academyHintsUsed, 4])).sort();
      return route.fulfill({ json: { scenario_id: "B01", level: 4, kind: "solution", text: null, walkthrough: academyScenarioDetail(currentAcademyProgress()).walkthrough, hints_used: academyHintsUsed, score: currentAcademyProgress().score } });
    }
    if ((path === "/academy/fake-data/seed" || path === "/academy/memory/clear" || path === "/academy/scenarios/B01/reset") && method === "POST") {
      return route.fulfill({ json: path.endsWith("/reset") ? { reset: true, scenario_id: "B01", cleared_ephemeral_state: { memory_entries: 0, collector_entries: 0 }, preserved: { sessions: academyExploitComplete ? 1 : 0, progress: true, score: currentAcademyProgress().score, findings: academyExploitComplete ? 1 : 0, evidence: academyExploitComplete ? 1 : 0, reports: true, project: true } } : { ok: true } });
    }
    if (path === `/runs/${runId}` && method === "GET") {
      return route.fulfill({ json: { id: runId, project_id: projectId, suite_id: "44444444-4444-4444-8444-444444444444", name: "审批围栏测试", status: "queued", progress: 40, pause_requested: false, evaluation_mode: "rules", created_at: now, updated_at: now } });
    }
    if (path === "/projects") return route.fulfill({ json: pageResult([{ id: projectId, name: "WhaleGuard Demo Lab", description: "本地演示项目", status: "active", created_at: now, updated_at: now }]) });
    if (path === "/model-channels") return route.fulfill({ json: pageResult([{ id: modelId, project_id: projectId, name: "E2E 真实模型", provider: "openai-compatible", base_url: "https://api.openai.com/v1", model: "gpt-4o-mini", api_key_masked: "sk-••••existing", enabled: true, created_at: now, updated_at: now }, ...(createdModel ? [{ id: createdModelId, project_id: projectId, name: "我的 OpenAI", provider: "openai-compatible", base_url: "https://api.openai.com/v1", model: "gpt-4o-mini", api_key_masked: "sk-••••e2e", enabled: true, created_at: now, updated_at: now }] : [])]) });
    if (path === "/website-scans") return route.fulfill({ json: pageResult(createdScan ? [websiteScanResponse(aiRegenerated ? "used" : "degraded")] : []) });
    if (path === `/academy/sessions/${academyVulnerableSessionId}` && method === "GET") {
      return route.fulfill({ json: academySession("vulnerable") });
    }
    if (path === `/academy/sessions/${academyHardenedSessionId}` && method === "GET") {
      return route.fulfill({ json: academySession("hardened") });
    }
    if (path === `/academy/sessions/${academyVulnerableSessionId}/attack-story` && method === "GET") {
      return route.fulfill({ json: {
        session_id: academyVulnerableSessionId,
        scenario_id: "B01",
        mode: "vulnerable",
        outcome: "vulnerability_triggered",
        headline: "不可信输入改变了 Agent 目标",
        explanation: "保存的事件显示目标变化后，虚构 canary 到达了输出。",
        timeline: academySession("vulnerable").events.map((event, index) => ({ sequence: event.sequence, event_id: event.id, event_type: event.event_type, component: index === 0 ? "Input" : index === 1 ? "Agent" : "Output", source: event.source, target: event.target, title: event.summary, explanation: event.summary, status: event.status, risk: event.risk })),
        control_point: { component: "Instruction Boundary", explanation: "应在改变 Agent 目标前阻断不可信指令。" },
        technical_details: { deterministic: true, session_id: academyVulnerableSessionId },
      } });
    }
    if (path === `/academy/sessions/${academyHardenedSessionId}/attack-story` && method === "GET") {
      return route.fulfill({ json: {
        session_id: academyHardenedSessionId,
        scenario_id: "B01",
        mode: "hardened",
        outcome: "blocked",
        headline: "Hardened 边界阻断了目标劫持",
        explanation: "相同输入在产生危险输出前被策略阻断。",
        timeline: academySession("hardened").events.map((event, index) => ({ sequence: event.sequence, event_id: event.id, event_type: event.event_type, component: index === 0 ? "Input" : "Policy", source: event.source, target: event.target, title: event.summary, explanation: event.summary, status: event.status, risk: event.risk })),
        control_point: { component: "Policy Guard", explanation: "目标变化未跨过输出边界。" },
        technical_details: { deterministic: true, session_id: academyHardenedSessionId },
      } });
    }
    if ((path === `/academy/sessions/${academyVulnerableSessionId}/comparison` || path === `/academy/sessions/${academyHardenedSessionId}/comparison`) && method === "GET") {
      const side = (mode: "vulnerable" | "hardened") => ({
        session_id: mode === "vulnerable" ? academyVulnerableSessionId : academyHardenedSessionId,
        mode,
        result: mode === "vulnerable" ? "漏洞已复现" : "防护已验证",
        input: { payload: "同一条本地虚构训练输入", sha256: "f".repeat(64) },
        model_decision: mode === "vulnerable" ? ["接受了不可信目标"] : ["保留可信目标"],
        tool_call: [],
        policy_decision: mode === "vulnerable" ? ["缺少边界"] : ["academy.guard.blocked"],
        output: mode === "vulnerable" ? ["虚构 canary 到达输出"] : ["危险输出未发生"],
        evidence: { created: true },
        finding: { created: mode === "vulnerable" },
      });
      return route.fulfill({ json: academyHardenedComplete
        ? { scenario_id: "B01", ready: true, missing_mode: null, vulnerable: side("vulnerable"), hardened: side("hardened"), control_changes: [{ control: "instruction_boundary", vulnerable: "missing", hardened: "enforced", explanation: "Hardened 在输出前执行可信边界检查。" }], conclusion: "相同输入在漏洞版触发危险结果，在修复版被策略控制阻断。" }
        : { scenario_id: "B01", ready: false, missing_mode: "hardened", vulnerable: side("vulnerable"), hardened: null, control_changes: [], conclusion: "还需要完成 hardened 模式，才能生成左右对照。" } });
    }
    if (path === "/academy/micro-courses") {
      return route.fulfill({ json: { items: microCourses, total: microCourses.length, total_minutes: microCourses.reduce((sum, item) => sum + item.minutes, 0) } });
    }
    if (path.startsWith("/academy/micro-courses/")) {
      const course = microCourses.find((item) => path.endsWith(item.id));
      return route.fulfill(course ? { json: course } : { status: 404, json: { detail: "Academy 微课程不存在" } });
    }
    if (path === "/academy/roadmap") {
      const progress = currentAcademyProgress();
      const b02Progress = { ...academyProgress };
      const nextLesson = progress.completed
        ? { scenario_id: "B02", title: "Hidden Room", action: "start", reason: "继续学习隐藏上下文泄露。" }
        : { scenario_id: "B01", title: "Prompt Breaker", action: academyExploitComplete ? "continue" : "start", reason: "完成第一条本地攻防闭环。" };
      return route.fulfill({ json: {
        project_id: projectId,
        items: [
          { ...academyScenarioItem, scenario_id: "B01", status: progress.completed ? "completed" : academyExploitComplete ? "in_progress" : "available", progress },
          { ...academyScenarioItem, scenario_id: "B02", id: undefined, title: "Hidden Room", prerequisites: ["B01"], status: progress.completed ? "available" : "recommended_later", progress: b02Progress },
        ],
        levels: { Beginner: { completed: progress.completed ? 1 : 0, total: 5 }, Intermediate: { completed: 0, total: 7 }, Advanced: { completed: 0, total: 5 } },
        completed_count: progress.completed ? 1 : 0,
        total_count: 17,
        current_lesson: academyExploitComplete && !progress.completed ? nextLesson : null,
        next_lesson: nextLesson,
      } });
    }
    if (path === "/academy/skills") {
      const progress = currentAcademyProgress();
      return route.fulfill({ json: { project_id: projectId, items: [{ skill_id: "prompt_injection", name: "Prompt Injection", description: "区分可信指令与不可信内容。", status: progress.completed ? "foundation" : academyExploitComplete ? "practicing" : "not_started", status_label: progress.completed ? "掌握基础" : academyExploitComplete ? "练习中" : "未接触", scenario_ids: ["B01"], touched_count: academyExploitComplete ? 1 : 0, completed_count: progress.completed ? 1 : 0, total_count: 1, progress_percent: progress.completed ? 100 : 0 }], status_order: ["not_started", "introduced", "practicing", "foundation"] } });
    }
    if (path === "/academy") {
      const progress = currentAcademyProgress();
      return route.fulfill({ json: { name: "WhaleGuard Academy Range", version: "2026.08", scenario_count: 17, completed_count: progress.completed ? 1 : 0, total_score: progress.score, max_score: 2125, starter_path: ["B01", "B03", "B04", "I09", "A16"], learning_path: ["B01", "B02"], next_lesson: progress.completed ? { scenario_id: "B02", title: "Hidden Room", action: "start", reason: "继续下一课。" } : { scenario_id: "B01", title: "Prompt Breaker", action: academyExploitComplete ? "continue" : "start", reason: "完成第一条本地攻防闭环。" }, event_types: ["academy.input.received", "academy.guard.blocked"], frameworks: ["OWASP GenAI LLM Top 10 2026", "MITRE ATLAS"], isolation: { targets: "local mocks only", public_listener: false, public_egress: false, data: "dynamic WHALE_LAB_FAKE_*", success_evaluator: "deterministic event rules" }, progress: { B01: progress } } });
    }
    if (path === "/academy/scenarios") {
      const progress = currentAcademyProgress();
      return route.fulfill({ json: { items: [{ ...academyScenarioItem, progress }], total: 1, starter_path: ["B01", "B03", "B04", "I09", "A16"] } });
    }
    if (path === "/academy/scenarios/B01") {
      return route.fulfill({ json: academyScenarioDetail(currentAcademyProgress()) });
    }
    if (path === `/projects/${projectId}/scopes`) return route.fulfill({ json: pageResult([]) });
    if (path === "/test-suites") return route.fulfill({ json: pageResult([{ id: "44444444-4444-4444-8444-444444444444", project_id: projectId, name: "AgentArena 基础安全测试", created_at: now, updated_at: now }]) });
    if (path === "/agents") return route.fulfill({ json: pageResult([{ id: "55555555-5555-4555-8555-555555555555", project_id: projectId, name: "Mock Agent", agent_type: "mock-local", endpoint_url: "http://mock-agent:8102", enabled: true, created_at: now, updated_at: now }]) });
    if (path === "/runs") return route.fulfill({ json: pageResult([{ id: runId, project_id: projectId, suite_id: "44444444-4444-4444-8444-444444444444", name: "审批围栏测试", status: "waiting_approval", progress: 40, pause_requested: false, evaluation_mode: "rules", created_at: now, updated_at: now }]) });
    if (path === "/approvals") return route.fulfill({ json: pageResult([{ id: approvalId, project_id: projectId, run_id: runId, action_type: "request_sensitive_demo_data", risk_level: "high", reason: "模拟敏感数据请求必须人工确认", status: "pending", created_at: now, updated_at: now }]) });
    return route.fulfill({ json: pageResult([]) });
  });
}

test("登录、创建项目并创建授权 Scope", async ({ page }) => {
  const writes: Array<{ path: string; body: unknown; headers: Record<string, string> }> = [];
  await installApiMock(page, writes);

  await page.goto("/login");
  await page.getByLabel("密码", { exact: true }).fill("safe-e2e-password");
  await page.getByRole("button", { name: /进入安全工作区/ }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByRole("heading", { name: "你今天想做什么？" })).toBeVisible();

  await page.goto("/projects");
  await page.getByRole("button", { name: "新建项目" }).click();
  await page.getByLabel("项目名称", { exact: true }).fill("E2E 安全项目");
  await page.getByLabel("项目说明", { exact: true }).fill("Playwright 创建");
  await page.getByRole("button", { name: "创建项目", exact: true }).click();
  await expect(page.getByText("项目已创建")).toBeVisible();

  const projectWrite = writes.find((item) => item.path === "/projects");
  expect(projectWrite?.body).toEqual({ name: "E2E 安全项目", description: "Playwright 创建" });
  expect(projectWrite?.headers.authorization).toBe("Bearer e2e-access");
  expect(projectWrite?.headers["x-csrf-token"]).toBe("e2e-csrf");

  await page.goto("/scopes");
  await page.getByRole("button", { name: "添加授权范围" }).click();
  await page.getByLabel("范围名称").fill("E2E 本地范围");
  await page.getByLabel("目标", { exact: true }).fill("127.0.0.1");
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "确认并保存" }).click();
  await expect(page.getByText("授权范围已保存")).toBeVisible();

  const scopeWrite = writes.find((item) => item.path === `/projects/${projectId}/scopes`);
  expect(scopeWrite?.body).toEqual(expect.objectContaining({ name: "E2E 本地范围", target_type: "ip", target_value: "127.0.0.1", is_authorized: true, allowed_request_types: ["http", "https"] }));
  expect(scopeWrite?.headers["x-csrf-token"]).toBe("e2e-csrf");
});

test("全部控制台路由含 Academy 可访问", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("whaleguard.access_token", "e2e-access");
    localStorage.setItem("whaleguard.csrf_token", "e2e-csrf");
    localStorage.setItem("whaleguard.user", JSON.stringify({ username: "admin", role: "Admin" }));
  });
  await installApiMock(page, [], {
    preferences: { experience_mode: "advanced", onboarding_complete: true, onboarding_goal: "both" },
  });
  const routes = [
    ["/help", "从这里开始"], ["/website-scan", "检查我自己的网站"], ["/dashboard", "系统总览"], ["/projects", "项目中心"], ["/scopes", "授权与测试范围"], ["/models", "模型渠道"], ["/agents", "Agent 管理"], ["/test-cases", "AI 红队测试用例"], ["/academy", "WhaleGuard Academy Range"], ["/academy/scenarios", "Academy 场景库"], ["/runs", "测试运行中心"], ["/mcpshield", "MCPShield"], ["/arena", "AgentArena"], ["/findings", "Findings"], ["/evidence", "证据中心"], ["/reports", "报告中心"], ["/knowledge", "知识库"], ["/tools", "工具与 MCP"], ["/audit", "审计日志"], ["/settings", "系统设置"],
  ] as const;
  for (const [path, title] of routes) {
    await page.goto(path);
    await expect(page.getByRole("heading", { name: title, exact: true })).toBeVisible();
  }
});

test("Beginner 首次引导可完成 Academy B01 攻防闭环", async ({ page }) => {
  const writes: Array<{ path: string; body: unknown; headers: Record<string, string> }> = [];
  await installApiMock(page, writes, {
    preferences: { experience_mode: "beginner", onboarding_complete: false, onboarding_goal: null },
  });

  await page.goto("/login");
  await page.getByLabel("密码", { exact: true }).fill("safe-e2e-password");
  await page.getByRole("button", { name: /进入安全工作区/ }).click();
  await expect(page).toHaveURL(/\/onboarding$/);

  await page.getByRole("button", { name: "我想学习 AI 安全" }).click();
  await page.getByRole("button", { name: "下一步" }).click();
  await expect(page.getByRole("heading", { name: "确认本地服务是否准备好" })).toBeVisible();
  await page.getByRole("button", { name: "下一步" }).click();
  await expect(page.getByRole("heading", { name: "API Key 是可选的" })).toBeVisible();
  await page.getByRole("button", { name: "暂时跳过，继续" }).click();
  await page.getByRole("button", { name: "进入 WhaleGuard" }).click();
  await expect(page).toHaveURL(/\/academy$/);
  await expect(page.getByRole("heading", { name: "WhaleGuard Academy Range", exact: true })).toBeVisible();
  await expect(page.getByTestId("academy-micro-courses")).toBeVisible();
  await expect(page.locator('[data-testid^="micro-course-"]')).toHaveCount(10);
  await page.getByRole("link", { name: "开始第一课" }).click();

  await expect(page.getByRole("heading", { name: "Prompt Breaker", exact: true })).toBeVisible();
  await expect(page.getByText("Deterministic Events")).toBeVisible();

  await page.getByRole("button", { name: "解锁" }).first().click();
  await expect(page.getByText("第 1 级提示已显示")).toBeVisible();
  await expect(page.getByText("先观察不可信输入是否改变了 Agent 目标。")).toBeVisible();

  await page.getByRole("button", { name: "执行 Vulnerable" }).click();
  await expect(page.getByText("漏洞已复现").first()).toBeVisible();
  await expect(page.getByTestId("academy-attack-story")).toContainText("不可信输入改变了 Agent 目标");

  await page.getByText("查看并选择原始 Evidence 事件", { exact: true }).click();
  const goalChangedEvidence = page.getByLabel("选择事件 academy.agent.goal_changed");
  const secretExposedEvidence = page.getByLabel("选择事件 academy.secret.exposed");
  await expect(goalChangedEvidence).toBeVisible();
  await expect(secretExposedEvidence).toBeVisible();
  await goalChangedEvidence.check();
  await secretExposedEvidence.check();
  await page.getByRole("button", { name: "提交已勾选事件" }).click();
  await expect(page.getByText("证据链选择正确")).toBeVisible();

  await page.getByLabel("把不可信输入与系统指令隔离，并校验目标变化").check();
  await page.getByRole("button", { name: "验证修复选择" }).click();
  await expect(page.getByText("修复策略选择正确")).toBeVisible();

  await page.getByRole("button", { name: "相同 Payload 回放 Hardened" }).click();
  await expect(page.getByText("防护已验证").first()).toBeVisible();
  await page.getByText("查看并选择原始 Evidence 事件", { exact: true }).click();
  await expect(page.getByText("academy.guard.blocked", { exact: true })).toBeVisible();
  await expect(page.getByText(/由 Vulnerable 原始 payload 回放生成/)).toBeVisible();
  await expect(page.getByTestId("academy-vulnerable-hardened-comparison")).toContainText("Vulnerable 漏洞版");
  await expect(page.getByTestId("academy-vulnerable-hardened-comparison")).toContainText("Hardened 修复版");
  await expect(page.getByTestId("academy-vulnerable-hardened-comparison")).toContainText("相同输入在漏洞版触发危险结果，在修复版被策略控制阻断。");
  await expect(page.getByTestId("academy-completion-next")).toContainText("Hidden Room");
  await expect(page.getByRole("link", { name: "一键继续学习" })).toHaveAttribute("href", "/academy/scenarios/B02");

  const preferenceWrite = writes.find((item) => item.path === "/auth/preferences" && (item.body as MockPreferences).onboarding_complete === true);
  expect(preferenceWrite?.body).toEqual({ experience_mode: "beginner", onboarding_complete: true, onboarding_goal: "learn" });
  expect(preferenceWrite?.headers["x-csrf-token"]).toBe("e2e-csrf");
  const executeWrite = writes.find((item) => item.path === "/academy/scenarios/B01/execute");
  expect(executeWrite?.body).toEqual(expect.objectContaining({ project_id: projectId, mode: "vulnerable", payload: expect.any(String) }));
  expect(executeWrite?.headers["x-csrf-token"]).toBe("e2e-csrf");
  const hintWrite = writes.find((item) => item.path === "/academy/scenarios/B01/hints/1");
  expect(hintWrite?.body).toEqual({ project_id: projectId });
  const evidenceWrite = writes.find((item) => item.path === `/academy/sessions/${academyVulnerableSessionId}/evidence`);
  expect(evidenceWrite?.body).toEqual({ event_ids: ["event-v2", "event-v3"] });
  const mitigationWrite = writes.find((item) => item.path === "/academy/scenarios/B01/mitigation");
  expect(mitigationWrite?.body).toEqual({ project_id: projectId, choice_id: "instruction-boundary" });
  const replayWrite = writes.find((item) => item.path === "/academy/sessions/" + academyVulnerableSessionId + "/replay");
  expect(replayWrite?.body).toEqual({ mode: "hardened" });
  for (const write of [hintWrite, evidenceWrite, mitigationWrite, replayWrite]) {
    expect(write?.headers["x-csrf-token"]).toBe("e2e-csrf");
  }
});

test("网站三步体检可选已有模型并仅请求一次授权靶场", async ({ page }) => {
  const writes: Array<{ path: string; body: unknown; headers: Record<string, string> }> = [];
  await page.addInitScript(() => {
    localStorage.setItem("whaleguard.access_token", "e2e-access");
    localStorage.setItem("whaleguard.csrf_token", "e2e-csrf");
    localStorage.setItem("whaleguard.user", JSON.stringify({ username: "admin", role: "Admin" }));
  });
  await installApiMock(page, writes);
  await page.goto("/website-scan");
  await expect(page.getByRole("heading", { name: "检查我自己的网站", exact: true })).toBeVisible();
  const modelSelect = page.getByLabel("模型渠道");
  await expect(modelSelect).toHaveValue("");
  await expect(modelSelect.getByRole("option", { name: "E2E 真实模型 · gpt-4o-mini" })).toHaveCount(1);
  await page.getByRole("button", { name: "接入新的 API Key" }).click();
  await expect(page.getByLabel("API Key", { exact: true })).toBeVisible();
  expect(writes.filter((item) => item.path === "/model-channels")).toHaveLength(0);
  await page.getByRole("button", { name: "接入新的 API Key" }).click();

  await page.getByRole("button", { name: "使用内置靶场" }).click();
  await expect(page.getByLabel("你拥有或已获授权的网站")).toHaveValue("http://mock-agent:8102/demo-site");
  await page.getByLabel("检查级别").selectOption("safe_read_only");
  await expect(page.getByLabel("检查级别")).toContainText("安全只读检查（推荐）");
  const authorization = page.getByRole("checkbox", { name: /我确认这是我拥有或明确授权测试的系统/ });
  await expect(authorization).not.toBeChecked();
  await authorization.check();
  await modelSelect.selectOption(modelId);
  await page.getByRole("button", { name: "开始检查我的网站" }).click();
  await expect(page.getByRole("region", { name: "网站体检结果" })).toContainText("86");
  await expect(page.getByText("规则分析已完成，AI 增强解析失败")).toBeVisible();
  await expect(page.getByRole("region", { name: "网站体检结果" })).toContainText("传输安全");
  await expect(page.getByRole("link", { name: "查看报告" })).toHaveAttribute("href", "/reports");

  await page.getByRole("button", { name: "只重新生成 AI 解读" }).click();
  await expect(page.getByText("AI 增强解读已完成")).toBeVisible();
  await expect(page.getByRole("region", { name: "网站体检结果" })).toContainText("模型仅复核已保存的脱敏规则结果");

  const scanWrites = writes.filter((item) => item.path === "/website-scans");
  expect(scanWrites).toHaveLength(1);
  const scanWrite = scanWrites[0];
  expect(scanWrite.body).toEqual({ target_url: "http://mock-agent:8102/demo-site", authorization_confirmed: true, model_channel_id: modelId, generate_report: true, safety_level: "safe_read_only" });
  expect(scanWrite?.headers.authorization).toBe("Bearer e2e-access");
  expect(scanWrite?.headers["x-csrf-token"]).toBe("e2e-csrf");
  const regenerateWrite = writes.find((item) => item.path === `/website-scans/${websiteScanId}/ai-analysis`);
  expect(regenerateWrite?.body).toEqual({ model_channel_id: modelId });
  expect(regenerateWrite?.headers["x-csrf-token"]).toBe("e2e-csrf");
  expect(writes.filter((item) => item.path === "/model-channels")).toHaveLength(0);
});

test("待审批运行可提交带 CSRF 的人工决定", async ({ page }) => {
  const writes: Array<{ path: string; body: unknown; headers: Record<string, string> }> = [];
  await page.addInitScript(() => {
    localStorage.setItem("whaleguard.access_token", "e2e-access");
    localStorage.setItem("whaleguard.csrf_token", "e2e-csrf");
    localStorage.setItem("whaleguard.user", JSON.stringify({ username: "admin", role: "Admin" }));
  });
  await installApiMock(page, writes);
  await page.goto("/runs");
  await page.getByRole("button", { name: "详情" }).click();
  await expect(page.getByRole("region", { name: "高风险操作审批" })).toBeVisible();
  const approve = page.getByRole("button", { name: /批准并继续/ });
  await expect(approve).toBeDisabled();
  await page.getByLabel("审批理由").fill("已核验授权范围");
  await approve.click();
  await expect(page.getByText("审批已通过，任务重新入队")).toBeVisible();

  const decision = writes.find((item) => item.path === `/approvals/${approvalId}/decision`);
  expect(decision?.body).toEqual({ status: "approved", decision_reason: "已核验授权范围" });
  expect(decision?.headers.authorization).toBe("Bearer e2e-access");
  expect(decision?.headers["x-csrf-token"]).toBe("e2e-csrf");
});
