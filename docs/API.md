# API

运行后以 <http://127.0.0.1:8000/docs> 的 OpenAPI 文档为精确契约，以 <http://127.0.0.1:8000/openapi.json> 供代码生成。

当前验证构建包含 53 条路径、81 个操作和 72 个组件 Schema；以后续运行实例的 OpenAPI 为准。

## 认证约定

```http
POST /api/v1/auth/login
Content-Type: application/json

{"username":"admin","password":"<first-run password>"}
```

`username` 字段也接受管理员邮箱。Docker Compose 的首次密码从仓库根目录被忽略的 `.local/first-run-credentials.txt` 获取；本机 `make seed` 使用独立 SQLite 数据库及 `.local/local-first-run-credentials.txt`。密码不会出现在服务日志中。后续请求使用 `Authorization: Bearer <access_token>`。浏览器的写操作还携带服务端签发的 CSRF token。模型渠道响应中的 `api_key_masked` 只显示首尾少量字符，任何接口均不返回原密钥。

## 资源组

- `/api/v1/projects`：项目与成员上下文
- `/api/v1/projects/{project_id}/scopes`、`/api/v1/scopes/{scope_id}`：授权范围、到期和授权确认
- `/api/v1/model-channels`：模型渠道与连接测试
- `/api/v1/agents`：Agent 目标
- `/api/v1/mcp/servers`、`/api/v1/mcp/servers/{server_id}/analyze`：MCP 元数据导入与静态分析
- `/api/v1/test-suites`、`/api/v1/test-cases`：测试资产
- `/api/v1/runs`：批量运行、暂停、取消、重试和 SSE 事件
- `/api/v1/findings`、`/api/v1/evidence`：风险与证据链
- `/api/v1/reports`：HTML / Markdown / JSON 报告
- `/api/v1/approvals`：高风险 Tool 人工审批
- `/api/v1/audit-logs`：只读审计
- `/api/v1/knowledge-documents`、`/api/v1/settings`：知识库和系统设置

API 错误使用统一 `request_id`，响应不包含堆栈、SQL 或密钥。具体状态码和 Schema 请以当前 OpenAPI 为准。
