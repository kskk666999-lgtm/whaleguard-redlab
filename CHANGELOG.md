# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 风格；首次稳定发布前版本可能快速演进。

## [Unreleased]

### Added

- WhaleGuard AI RedLab monorepo：FastAPI、Next.js、RQ worker、Scope Guard 与 AgentArena。
- 20 个核心数据库模型、Alembic、RBAC、JWT/CSRF、Argon2 和加密模型密钥。
- 15 个无破坏性安全测试模板、规则评分、Finding、证据和多格式报告。
- OpenAI-compatible 模型调用适配、显式可选 LLM Judge 与安全降级到规则评分。
- MCPShield 静态元数据风险分析，不执行未知 Tool。
- mock-llm、mock-agent、mock-mcp-server 本地演示服务。
- Docker Compose 私有网络、Windows 一键脚本、Linux/WSL 文档与统一验收脚本。
- 17 个可操作中文页面、暗/亮主题、响应式导航、ECharts 与 React Flow 可视化。
- 本地端到端烟测、Playwright 流程和三张浏览器实测截图。

### Security

- 默认阻止未授权公网目标、非 HTTP(S) 协议、云元数据地址、IPv4-mapped IPv6 绕过和重定向逃逸。
- 默认服务端口仅绑定 `127.0.0.1`，AgentArena 服务不发布宿主机端口。

### Fixed

- Compose 自定义 `API_PORT` / `WEB_PORT` 时同步更新前端 API 地址和 API CORS 来源。
- API 与 Worker 统一使用同一 `RQ_QUEUE`，避免自定义队列时任务无人消费。
