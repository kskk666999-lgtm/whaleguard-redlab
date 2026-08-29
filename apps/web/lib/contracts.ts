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
