import { z } from "zod";

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
