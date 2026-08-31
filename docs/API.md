# API

运行后以 <http://127.0.0.1:8000/docs> 的 OpenAPI 文档为精确契约，以 <http://127.0.0.1:8000/openapi.json> 供代码生成。

版本边界：`v0.2.0 Beginner Experience / Academy` 是当前正式版本，`v0.1.1 Hardening` 是上一稳定基线。本文不固定写死路径与 Schema 数量，以当前运行实例的 OpenAPI 为准。

## 认证约定

```http
POST /api/v1/auth/login
Content-Type: application/json

{"username":"admin","password":"<first-run password>"}
```

`username` 字段也接受管理员邮箱。Docker Compose 的首次密码从仓库根目录被忽略的 `.local/first-run-credentials.txt` 获取；本机 `make seed` 使用独立 SQLite 数据库及 `.local/local-first-run-credentials.txt`。密码不会出现在服务日志中。后续请求使用 `Authorization: Bearer <access_token>`。浏览器的写操作还携带服务端签发的 CSRF token。模型渠道响应中的 `api_key_masked` 只显示首尾少量字符，任何接口均不返回原密钥。

登录响应与 `GET /api/v1/auth/me` 均包含当前用户偏好：

- `experience_mode`：`beginner` 或 `advanced`
- `onboarding_complete`：是否完成新手引导
- `onboarding_goal`：`learn`、`scan`、`both` 或 `null`

`GET /api/v1/auth/preferences` 读取偏好；`PATCH /api/v1/auth/preferences` 只更新显式提交的字段，并写入审计日志。体验模式只改变 Web 导航与首页密度，不改变 RBAC、Scope Guard 或审批策略。

## 新手系统状态

`GET /api/v1/system/status` 返回当前登录用户可见的真实状态摘要：API、数据库、Redis、worker、本地靶场和可选模型渠道。`overall` 为 `ready` 或 `degraded`；单项状态为 `normal`、`not_started`、`optional` 或 `abnormal`。

该接口会用受限请求检查三个本地 Mock 服务，但不会扫描其他目标；没有模型渠道时模型项是 `optional`，不阻止 Academy 学习。

## 资源组

- `/api/v1/projects`：项目与成员上下文
- `/api/v1/projects/{project_id}/scopes`、`/api/v1/scopes/{scope_id}`：授权范围、到期和授权确认
- `/api/v1/model-channels`：模型渠道与连接测试
- `/api/v1/auth/preferences`、`/api/v1/system/status`：新手体验偏好与真实系统状态
- `/api/v1/academy`、`/api/v1/academy/scenarios`、`/api/v1/academy/standards`：Academy 总览、17 关 manifest、进度与标准映射
- `/api/v1/academy/micro-courses`、`/api/v1/academy/micro-courses/{course_id}`：10 个零基础微课
- `/api/v1/academy/roadmap`、`/api/v1/academy/skills`：按项目计算的路线、下一课和十类技能进度
- `/api/v1/academy/scenarios/{scenario_id}/execute`、`/api/v1/academy/sessions/{session_id}/replay`：本地确定性场景执行与相同 payload A/B 回放
- `/api/v1/academy/sessions/{session_id}/attack-story`、`/api/v1/academy/sessions/{session_id}/comparison`：Attack Story 与 Vulnerable/Hardened 结构化对照
- `/api/v1/academy/sessions/{session_id}/evidence`、`/api/v1/academy/scenarios/{scenario_id}/mitigation`：事件证据与防护选择
- `/api/v1/academy/scenarios/{scenario_id}/hints/{level}`、`/api/v1/academy/scenarios/{scenario_id}/solution`：三层提示与独立完整答案
- `/api/v1/academy/scenarios/{scenario_id}/tutor`：只接受当前课程五类防御解释意图；可自动使用当前项目最近成功连接的模型，失败时返回确定性解释
- `/api/v1/academy/scenarios/{scenario_id}/reset`：只清理本关易失状态，保留 Session、进度、Finding、Evidence、Report 与 Project
- `/api/v1/academy/fake-data/seed`、`/api/v1/academy/memory/clear`、`/api/v1/academy/reset-all`：虚构训练数据、跨会话记忆与显式全量进度维护
- `/api/v1/website-scans`：自有或明确授权网站的一次性只读规则体检；`project_id` 可省略，平台在权限允许时自动复用或建立“我的网站体检”项目，并建立 24 小时精确 URL Scope
- `/api/v1/website-scans/{scan_id}/ai-analysis`：只基于已保存的脱敏规则结果重新生成可选 AI 解读，不重新请求目标网站
- `/api/v1/agents`：Agent 目标
- `/api/v1/mcp/servers`、`/api/v1/mcp/servers/{server_id}/analyze`：MCP 元数据导入与静态分析
- `/api/v1/test-suites`、`/api/v1/test-cases`：测试资产
- `/api/v1/runs`：批量运行、暂停、取消和重试
- `/api/v1/runs/{run_id}/events`：从规范化 `RunEvent` 表读取 SSE；支持 `cursor` 与 `Last-Event-ID` 断点续读
- `/api/v1/runs/{run_id}/event-history`：`after_sequence` + `page_size` 游标分页事件历史
- `/api/v1/runs/{run_id}/delivery-receipts`：分页查询 Worker 幂等回执，可按 `delivery_id` 或 `event_type` 过滤
- `/api/v1/findings`、`/api/v1/evidence`：风险与证据链
- `/api/v1/reports`：HTML / Markdown / JSON 报告
- `/api/v1/approvals`：高风险 Tool 人工审批
- `/api/v1/audit-logs`：只读审计
- `/api/v1/knowledge-documents`、`/api/v1/settings`：知识库和系统设置

API 错误使用统一 `request_id`，响应不包含堆栈、SQL 或密钥。具体状态码和 Schema 请以当前 OpenAPI 为准。

## Website Scan 的重要语义

`POST /api/v1/website-scans` 要求：

- `authorization_confirmed` 必须为 `true`
- `safety_level` 只能为 `safe_read_only`
- 调用者同时具备 `runs.execute` 与 `scopes.write`
- 未传 `project_id` 时，自动建项目还要求 `projects.write`

规则阶段发出一条有大小限制的只读 GET，不跟随重定向，不保存响应正文、Cookie 名称/值或凭据。未选择模型渠道时，规则分数、Evidence、Finding 与可选 Report 仍会正常生成。若 AI 阶段降级，`POST /website-scans/{scan_id}/ai-analysis` 只重试模型解释；该接口要求规则体检已完成，并要求 `runs.execute` 与 `models.test`。

## Academy 的提示与重置语义

- Hint 1、2、3 必须依次解锁；完整答案使用独立 `/solution` 端点，内部作为第 4 级计分成本处理。
- Attack Story 由已保存事件生成，不执行新的攻击。
- Comparison 只有同时存在 Vulnerable 和 Hardened 记录时 `ready=true`；严格 A/B 应使用 replay 生成 Hardened 记录。
- 单关 reset 不删除历史证据链；`reset-all` 会删除当前用户在该项目中的 Academy Session、进度及关联 Finding/Evidence，应由客户端明确区分。

`TestRun.event_log` 仍在响应中保留以兼容 v0.1.0 客户端，但已在 OpenAPI 标记 deprecated。新客户端不得把它作为完整历史来源。

Worker 内部回调 `/api/v1/internal/runs/{run_id}/result` 不公开在 OpenAPI，必须携带 Worker token 和该 Run 已签发、已投递的 Outbox UUID `delivery_id`。未签发或尚未就绪返回可重试的 `425`；同一投递重复到达会返回 `{"accepted": true, "duplicate": true}`；同一 ID 的业务内容不一致时返回 `409`，且不会覆盖首次结果。
