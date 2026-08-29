# WhaleGuard AI RedLab 通宵续作进度

最近更新：2026-08-30 02:30 +08:00

## 结论

当前工作区已从空目录完成到可运行、可测试、可继续扩展的单一 monorepo。代码、迁移、演示数据、Windows/Linux 启动入口、17 个产品页面、Scope Guard、MCPShield、AgentArena、规则评分与可选 LLM Judge 均已落地；本机 SQLite/受限内联任务后端的完整业务链路已真实运行。

当前主机没有可用 Docker Engine，因此不能诚实宣称镜像 build/up、PostgreSQL/Redis/RQ 容器运行已验证。Docker Compose 已用官方 Compose v5.5.0 执行 `config --quiet`，并通过仓库的网络/权限静态不变量校验。

## 已完成能力

- FastAPI 提供 53 条 OpenAPI 路径、81 个操作、72 个 Schema；20 个要求的核心 ORM 模型均带 UUID、时间戳、索引、外键和删除策略，迁移共创建 23 张表（含关联表和 `alembic_version`）。
- RBAC、Argon2、短期 JWT、CSRF、严格 CORS、请求大小限制、上传内容嗅探、文件名清理、路径穿越防护、日志/错误脱敏和不可变审计入口已经实现。
- OpenAI-compatible 适配层支持 OpenAI / DeepSeek / GLM / Qwen / Ollama 兼容渠道；API Key 与额外 Header 加密保存，响应只返回掩码；连接测试和显式 LLM Judge 已通过本地 mock 实跑。
- Scope Guard 在每次受控请求前检查协议、授权状态/时效、解析后 IP、请求类型、Tool 风险与审批；阻止公网默认访问、云元数据、特殊地址、IPv4-mapped IPv6、NAT64/6to4/Teredo、混合 DNS、DNS Rebinding 和重定向逃逸。
- MCPShield 只分析配置与元数据，识别命令、网络、文件、环境变量、描述投毒和缺少审批等风险；未知 Tool 没有执行入口。
- AgentArena 三个 mock 服务实现安全的本地 LLM、Agent 轨迹和五个演示 Tool；`request_sensitive_demo_data` 必须拒绝或进入审批。
- 15 个公开、虚构、无破坏性的测试模板全部可执行；规则评分默认优先，可显式启用 LLM Judge，评分包含指标和解释。
- 运行引擎覆盖 `pending / queued / running / waiting_approval / completed / failed / cancelled`，提供并发、超时、暂停、恢复、取消、重试、进度和 SSE 事件。
- Findings、证据 SHA-256、原始输入/输出、Tool Call、Policy Decision、审计记录及 HTML/Markdown/JSON 报告链路已真实跑通。
- Next.js 中文控制台包含登录和 16 个业务页面；暗/亮主题、桌面/移动布局、搜索/过滤/分页、加载/错误/空状态和业务按钮已实现。
- Compose 恰好包含 8 个服务；arena/backend 使用内部网络，只有 API 作为受控桥接，Mock 服务不发布宿主端口，应用容器非 root、禁止提权并移除 Linux capabilities。

## 验证结果

| 检查 | 结果 |
|---|---|
| Python 格式与 Ruff | 通过，67 个 Python 文件 |
| policy-engine | 19 passed |
| worker | 16 passed |
| FastAPI 单元/API 集成 | 19 passed |
| mock-llm / mock-agent / mock-mcp-server | 9 / 16 / 9 passed |
| Python 小计 | 88 passed |
| Alembic upgrade → downgrade → upgrade | 通过，23 张表 |
| Vitest 组件/契约 | 11 passed |
| ESLint / TypeScript | 通过 |
| Next.js 16.3.3 production build | 通过，17 个产品页面（构建生成 20 页） |
| Playwright Chromium | 3 passed |
| 自动化测试总计 | 102 passed |
| 真实本机产品烟测 | 11/11 通过 |
| 浏览器实机 QA | 登录、主题、390px 导航、总览、MCPShield、运行详情通过；0 warning/error |
| Compose 官方 CLI `config --quiet` | 通过（v5.5.0） |
| Docker build/up | 未执行：本机无 Docker Engine |

最近一次真实烟测产物：Agent run `96b8b25b-adf2-4834-964e-9887afe5cd56`，Model/Judge run `9f2e55ac-2fda-41f9-98ab-ef1b531457f4`，Report `4f4f4459-b7a6-4ece-b451-57d0ee3e19fb`。下载的 HTML 位于被 Git 忽略的 `.local/smoke-report.html`。

## 本轮发现并修复的真实问题

- 修复 SQLAlchemy 关联表声明导致 API 无法导入的问题。
- 修复 Scope Guard resolver 在函数定义时绑定，导致受控 DNS 测试不能替换的问题。
- 修复前后端 Scope、模型渠道、Agent、MCP、Report 和 Run 字段契约不一致。
- 修复审批通过后运行未恢复、暂停按钮误调用取消、模型渠道测试状态未刷新的交互问题。
- 修复显式授权公网测试误用保留地址，避免把安全拒绝错误改弱。
- 修复烟测审计断言只读第一页而漏掉早期登录事件的问题。
- 浏览器实测发现 MCP Server 列表把 5 个持久化 Tool 显示为 0；现已由 API 返回 `tool_count` 并复验为 5。
- 修复 Docker/local 首次凭据文件互相覆盖的风险；两种运行方式使用独立凭据文件。

## 剩余非关键项

- 在安装 Docker Engine 的主机上补跑完整镜像构建、8 服务启动、PostgreSQL/Redis/RQ 运行时和容器健康检查。
- 使用用户自有且明确授权的兼容渠道做可选 provider 兼容性矩阵；仓库不会附带真实 API Key。
- 扩展报告 PDF、组织级 SSO、分布式对象存储和多节点 worker。这些不影响当前本地实验闭环。

最终交付摘要见根目录 [`FINAL_STATUS.md`](../FINAL_STATUS.md)。
