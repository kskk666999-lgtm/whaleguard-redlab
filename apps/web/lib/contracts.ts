export type ScopeForm = {
  name: string;
  target_type: "domain" | "ip" | "cidr";
  target_value: string;
  expires_at: string;
  is_authorized: boolean;
};

export function scopeCreatePayload(form: ScopeForm) {
  return {
    name: form.name,
    target_type: form.target_type,
    target_value: form.target_value,
    allowed_request_types: ["http", "https"] as const,
    is_authorized: form.is_authorized,
    expires_at: new Date(form.expires_at).toISOString(),
  };
}

export function agentCreatePayload(form: {
  project_id: string;
  name: string;
  description: string;
  endpoint_url: string;
  agent_type: string;
  enabled: boolean;
  risk_level: string;
}) {
  return { ...form, config: {} };
}

export function mcpServerCreatePayload(projectId: string, form: { name: string; transport: string; command: string; url: string; enabled: boolean }) {
  return {
    project_id: projectId,
    name: form.name,
    transport: form.transport,
    endpoint_url: form.transport === "stdio" ? undefined : form.url,
    config: form.transport === "stdio" ? { command: form.command, args: [] } : {},
    enabled: form.enabled,
    tools: [],
  };
}

export function mcpImportPayload(projectId: string, config: unknown) {
  return { project_id: projectId, config };
}

export function reportCreatePayload(form: { project_id: string; name: string; format: "html" | "markdown" | "json" }) {
  return { project_id: form.project_id, name: form.name, formats: [form.format] };
}

export function websiteScanCreatePayload(form: {
  project_id?: string;
  target_url: string;
  model_channel_id?: string;
  authorization_confirmed: true;
  generate_report: true;
  safety_level: "safe_read_only";
}) {
  return {
    ...(form.project_id ? { project_id: form.project_id } : {}),
    target_url: form.target_url.trim(),
    authorization_confirmed: form.authorization_confirmed,
    ...(form.model_channel_id ? { model_channel_id: form.model_channel_id } : {}),
    generate_report: form.generate_report,
    safety_level: form.safety_level,
  };
}

export function websiteModelChannelCreatePayload(form: {
  project_id: string;
  name: string;
  provider: "openai-compatible" | "deepseek-compatible" | "glm-compatible" | "qwen-compatible";
  base_url: string;
  api_key: string;
  model: string;
  authorization_confirmed: true;
}) {
  return {
    ...form,
    base_url: form.base_url.trim(),
    api_key: form.api_key,
    model: form.model.trim(),
    enabled: true,
    timeout: 60,
    max_tokens: 2048,
    temperature: 0,
  };
}

export function runCreatePayload(form: {
  project_id: string;
  suite_id: string;
  target_type: "agent" | "model";
  agent_target_id?: string;
  model_channel_id?: string;
  evaluation_mode: "rules" | "rules_with_llm_judge";
  judge_model_channel_id?: string;
  max_concurrency: number;
}) {
  const { agent_target_id, model_channel_id, ...shared } = form;
  return form.target_type === "agent"
    ? { ...shared, agent_target_id }
    : { ...shared, model_channel_id };
}

export function testCaseCreatePayload(form: {
  id: string;
  name: string;
  category: string;
  severity: string;
  description: string;
  input: string;
  context: string;
  expected_behavior: string;
  forbidden_behavior: string;
  evaluator: string;
}, tags: string) {
  return {
    id: form.id,
    name: form.name,
    category: form.category,
    severity: form.severity,
    description: form.description,
    input: { prompt: form.input },
    context: form.context ? { text: form.context } : {},
    expected_behavior: form.expected_behavior,
    forbidden_behavior: form.forbidden_behavior,
    evaluator: { type: form.evaluator },
    tags: tags.split(",").map((item) => item.trim()).filter(Boolean),
    references: [],
  };
}
