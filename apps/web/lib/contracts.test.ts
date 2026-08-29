import { agentCreatePayload, mcpImportPayload, mcpServerCreatePayload, reportCreatePayload, scopeCreatePayload, testCaseCreatePayload } from "@/lib/contracts";
import { modelChannelInputSchema, runInputSchema, scopeInputSchema } from "@/lib/schemas";

const uuid = "11111111-1111-4111-8111-111111111111";

describe("API contract payloads", () => {
  it("使用后端精确的模型 provider 枚举", () => {
    const base = { name: "本地模型", base_url: "http://127.0.0.1:11434/v1", model: "demo", timeout: 30, max_tokens: 1024, temperature: 0, enabled: true };
    expect(modelChannelInputSchema.safeParse({ ...base, provider: "ollama-compatible" }).success).toBe(true);
    expect(modelChannelInputSchema.safeParse({ ...base, provider: "ollama" }).success).toBe(false);
  });

  it("构造 ScopeCreate 精确字段并拒绝危险协议", () => {
    const form = { name: "本地范围", target_type: "ip" as const, target_value: "127.0.0.1", expires_at: "2030-01-01T08:00", is_authorized: true };
    expect(scopeInputSchema.safeParse({ ...form, project_id: uuid }).success).toBe(true);
    expect(scopeCreatePayload(form)).toEqual({ name: "本地范围", target_type: "ip", target_value: "127.0.0.1", allowed_request_types: ["http", "https"], is_authorized: true, expires_at: expect.stringContaining("2030-01-01") });
    expect(scopeInputSchema.safeParse({ ...form, project_id: uuid, target_value: "file:///etc/passwd" }).success).toBe(false);
  });

  it("构造 Agent、MCP、Report 与 TestCase 写入合同", () => {
    const agent = agentCreatePayload({ project_id: uuid, name: "Mock Agent", description: "demo", endpoint_url: "http://mock-agent:8102", agent_type: "mock-local", enabled: true, risk_level: "medium" });
    expect(agent).toMatchObject({ agent_type: "mock-local", risk_level: "medium", config: {} });
    expect(agent).not.toHaveProperty("target_type");

    expect(mcpServerCreatePayload(uuid, { name: "demo", transport: "stdio", command: "python -m demo", url: "", enabled: true })).toEqual({ project_id: uuid, name: "demo", transport: "stdio", endpoint_url: undefined, config: { command: "python -m demo", args: [] }, enabled: true, tools: [] });
    expect(mcpImportPayload(uuid, { mcpServers: {} })).toEqual({ project_id: uuid, config: { mcpServers: {} } });
    expect(reportCreatePayload({ project_id: uuid, name: "报告", format: "html" })).toEqual({ project_id: uuid, name: "报告", formats: ["html"] });

    const testCase = testCaseCreatePayload({ id: "safe-001", name: "Safe Probe", category: "refusal", severity: "medium", description: "安全模拟", input: "虚构输入", context: "虚构上下文", expected_behavior: "拒绝越权", forbidden_behavior: "执行越权", evaluator: "rules" }, "safe, rule-first");
    expect(testCase).toMatchObject({ input: { prompt: "虚构输入" }, context: { text: "虚构上下文" }, evaluator: { type: "rules" }, tags: ["safe", "rule-first"] });
  });

  it("运行合同仅接受 agent/model 并要求对应目标 UUID", () => {
    const rules = runInputSchema.safeParse({ project_id: uuid, suite_id: uuid, target_type: "agent", agent_target_id: uuid, evaluation_mode: "rules", judge_model_channel_id: "", max_concurrency: 2 });
    expect(rules.success).toBe(true);
    if (rules.success) expect(rules.data).toMatchObject({ evaluation_mode: "rules", judge_model_channel_id: undefined });
    expect(runInputSchema.safeParse({ project_id: uuid, suite_id: uuid, target_type: "mock_agent", max_concurrency: 2 }).success).toBe(false);
    expect(runInputSchema.safeParse({ project_id: uuid, suite_id: uuid, target_type: "model", model_channel_id: "", max_concurrency: 2 }).success).toBe(false);
    expect(runInputSchema.safeParse({ project_id: uuid, suite_id: uuid, target_type: "agent", agent_target_id: uuid, evaluation_mode: "rules_with_llm_judge", judge_model_channel_id: "", max_concurrency: 2 }).success).toBe(false);
    expect(runInputSchema.safeParse({ project_id: uuid, suite_id: uuid, target_type: "agent", agent_target_id: uuid, evaluation_mode: "rules_with_llm_judge", judge_model_channel_id: uuid, max_concurrency: 2 }).success).toBe(true);
  });
});
