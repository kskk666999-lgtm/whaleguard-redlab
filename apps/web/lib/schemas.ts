import { z } from "zod";

function hasAmbiguousUrlPath(value: string) {
  const rawPath = value.replace(/^[a-z][a-z0-9+.-]*:\/\/[^/\\?#]*/i, "").split(/[?#]/, 1)[0] || "/";
  let decoded = rawPath;
  try {
    for (let index = 0; index < 8; index += 1) {
      const next = decodeURIComponent(decoded);
      if (next === decoded) break;
      decoded = next;
    }
  } catch {
    return true;
  }
  return decoded.includes("\\") || decoded.split("/").some((segment) => segment === "." || segment === "..");
}

export const loginInputSchema = z.object({
  username: z.string().min(1, "请输入用户名"),
  password: z.string().min(8, "密码至少 8 位"),
});

export const loginResponseSchema = z.object({
  access_token: z.string(),
  token_type: z.string().default("bearer"),
  expires_in: z.number().optional(),
  csrf_token: z.string().optional(),
  user: z
    .object({
      id: z.string().optional(),
      username: z.string(),
      display_name: z.string().optional(),
      role: z.union([z.string(), z.object({ name: z.string() }).transform((value) => value.name)]).optional(),
    })
    .passthrough(),
});

export const userPreferencesSchema = z.object({
  experience_mode: z.enum(["beginner", "advanced"]),
  onboarding_complete: z.boolean(),
  onboarding_goal: z.enum(["learn", "scan", "both"]).nullable(),
});

export const userPreferencesUpdateSchema = userPreferencesSchema.partial();

export const systemServiceStatusSchema = z.object({
  status: z.enum(["normal", "not_started", "optional", "abnormal"]),
  label: z.string(),
  detail: z.string(),
  optional: z.boolean(),
});

export const systemStatusSchema = z.object({
  overall: z.enum(["ready", "degraded"]),
  checked_at: z.string(),
  services: z.record(systemServiceStatusSchema),
  model_provider_name: z.string().nullable(),
});

export const projectInputSchema = z.object({
  name: z.string().min(2, "项目名称至少 2 个字符").max(80),
  description: z.string().max(500).default(""),
});

export const scopeInputSchema = z
  .object({
    project_id: z.string().uuid("请选择项目"),
    name: z.string().min(1, "请输入范围名称").max(200),
    target_value: z.string().min(1, "请输入域名、IP 或 CIDR"),
    target_type: z.enum(["domain", "ip", "cidr"]),
    expires_at: z.string().min(1, "请选择授权到期时间"),
    is_authorized: z.literal(true, {
      errorMap: () => ({ message: "必须确认已获得明确授权" }),
    }),
  })
  .superRefine((value, ctx) => {
    if (/^(file|gopher|ftp|dict):/i.test(value.target_value)) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, message: "不允许的协议", path: ["target_value"] });
    }
  });

export const modelChannelInputSchema = z.object({
  name: z.string().min(2),
  provider: z.enum(["openai-compatible", "deepseek-compatible", "glm-compatible", "qwen-compatible", "ollama-compatible"]),
  base_url: z.string().url(),
  api_key: z.string().optional(),
  model: z.string().min(1),
  timeout: z.coerce.number().min(1).max(300).default(60),
  max_tokens: z.coerce.number().min(1).max(32768).default(2048),
  temperature: z.coerce.number().min(0).max(2).default(0),
  enabled: z.boolean().default(true),
});

export const reportInputSchema = z.object({
  project_id: z.string().uuid(),
  name: z.string().min(2).max(120),
  format: z.enum(["html", "markdown", "json"]),
});

export const websiteScanInputSchema = z
  .object({
    project_id: z.preprocess((value) => value === "" ? undefined : value, z.string().uuid().optional()),
    target_url: z.string().min(1, "请输入靶场网址").max(2048, "网址过长").url("请输入完整网址，例如 http://127.0.0.1:8080"),
    model_channel_id: z.preprocess((value) => value === "" ? undefined : value, z.string().uuid().optional()),
    authorization_confirmed: z.literal(true, {
      errorMap: () => ({ message: "必须确认目标归你所有或已获得明确授权" }),
    }),
    generate_report: z.literal(true),
    safety_level: z.literal("safe_read_only"),
  })
  .superRefine((value, ctx) => {
    try {
      const target = new URL(value.target_url);
      if (!['http:', 'https:'].includes(target.protocol)) {
        ctx.addIssue({ code: z.ZodIssueCode.custom, message: "只允许 HTTP 或 HTTPS 网址", path: ["target_url"] });
      }
      if (target.username || target.password) {
        ctx.addIssue({ code: z.ZodIssueCode.custom, message: "网址中不能包含用户名或密码", path: ["target_url"] });
      }
      if (target.search || target.hash) {
        ctx.addIssue({ code: z.ZodIssueCode.custom, message: "请填写不含查询参数或片段的网址", path: ["target_url"] });
      }
      if (hasAmbiguousUrlPath(value.target_url)) {
        ctx.addIssue({ code: z.ZodIssueCode.custom, message: "网址路径不能包含点号跳转或反斜杠", path: ["target_url"] });
      }
    } catch {
      // `url()` already provides the user-facing validation message.
    }
  });

export const websiteModelSetupSchema = z.object({
  project_id: z.string().uuid("请选择项目"),
  name: z.string().min(2, "渠道名称至少 2 个字符").max(200),
  provider: z.enum(["openai-compatible", "deepseek-compatible", "glm-compatible", "qwen-compatible"]),
  base_url: z.string().url("请输入完整的模型 API 地址").superRefine((value, ctx) => {
    try {
      const target = new URL(value);
      if (!["http:", "https:"].includes(target.protocol)) {
        ctx.addIssue({ code: z.ZodIssueCode.custom, message: "模型 API 地址只允许 HTTP 或 HTTPS" });
      }
      if (target.username || target.password) {
        ctx.addIssue({ code: z.ZodIssueCode.custom, message: "模型 API 地址不能包含用户名或密码" });
      }
      if (target.search || target.hash) {
        ctx.addIssue({ code: z.ZodIssueCode.custom, message: "模型 API 地址不能包含查询参数或片段" });
      }
    } catch {
      // `url()` already reports the malformed value.
    }
  }),
  api_key: z.string().min(8, "请输入有效的 API Key").max(4096),
  model: z.string().min(1, "请输入模型名称").max(200),
  authorization_confirmed: z.literal(true),
});

export const mcpImportSchema = z.object({
  config: z.string().min(2, "请粘贴 MCP JSON 配置").transform((value, ctx) => {
    try {
      return JSON.parse(value) as unknown;
    } catch {
      ctx.addIssue({ code: z.ZodIssueCode.custom, message: "JSON 格式无效" });
      return z.NEVER;
    }
  }),
});

export const runInputSchema = z.object({
  project_id: z.string().uuid(),
  suite_id: z.string().uuid(),
  target_type: z.enum(["agent", "model"]),
  agent_target_id: z.preprocess((value) => value === "" ? undefined : value, z.string().uuid().optional()),
  model_channel_id: z.preprocess((value) => value === "" ? undefined : value, z.string().uuid().optional()),
  evaluation_mode: z.enum(["rules", "rules_with_llm_judge"]).default("rules"),
  judge_model_channel_id: z.preprocess((value) => value === "" ? undefined : value, z.string().uuid().optional()),
  max_concurrency: z.coerce.number().min(1).max(8).default(2),
}).superRefine((value, ctx) => {
  if (value.target_type === "agent" && !value.agent_target_id) ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["agent_target_id"], message: "请选择 Agent 目标" });
  if (value.target_type === "model" && !value.model_channel_id) ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["model_channel_id"], message: "请选择模型渠道" });
  if (value.evaluation_mode === "rules_with_llm_judge" && !value.judge_model_channel_id) ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["judge_model_channel_id"], message: "请选择 Judge 模型渠道" });
});

export const apiEntitySchema = z
  .object({
    id: z.string(),
    created_at: z.string().optional(),
    updated_at: z.string().optional(),
  })
  .passthrough();

export const pageSchema = z.object({
  items: z.array(apiEntitySchema),
  total: z.number(),
  page: z.number().default(1),
  page_size: z.number().default(20),
  pages: z.number().default(1),
});
