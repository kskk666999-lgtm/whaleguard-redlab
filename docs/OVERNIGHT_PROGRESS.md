# WhaleGuard AI RedLab 历史通宵续作进度

> [!NOTE]
> 本文件是 2026-08-30 Docker 安装完成前的过程快照。后续 v0.1.0 已通过 Docker 运行验收，v0.1.1 已正式发布；当前状态见 [README](../README.md)，后续版本发布判定见 [RELEASE](RELEASE.md)。

最近更新：2026-08-30 06:12 +08:00

## 结论

当前工作区已从空目录完成到可运行、可测试、可继续扩展的单一 monorepo。代码、迁移、演示数据、Windows/Linux 启动入口、17 个产品页面、Scope Guard、MCPShield、AgentArena、规则评分与可选 LLM Judge 均已落地；本机 SQLite/受限内联任务后端的完整业务链路已真实运行。Windows 还新增了容器兼容预检、一键安装和重启后续作入口。完整 Docker 产品链路仍处于发布门禁 **BLOCKED**，不能宣称全部验证完成。

2026-08-30 04:21–04:24 +08:00 的首次提升尝试和随后只读核查确认：本机是 Windows 11 家庭中文版 23H2 build 22631，并安装了 VirtualBox 5.2.30；两者均未通过当前一键安装器的兼容门禁。用户已接受首轮 UAC，但 WSL web-download 返回 HTTP 403，VirtualMachinePlatform 仅被暂存、没有重启，提升阶段也没有成功注册自动续作入口；Docker CLI/Desktop/Engine 仍未安装。因此镜像 build/up、PostgreSQL/Redis/RQ 容器运行、Docker smoke 与重启持久化均未执行。此前的官方 Compose v5.5.0 `config --quiet` 和网络/权限静态不变量校验不等价于容器运行通过。

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
- `INSTALL_WHALEGUARD_DOCKER.bat` 提供 Windows 首次安装入口：兼容预检通过后只申请一次 UAC，不自动重启，仅在提升阶段成功且确实需要重启时注册当前用户 Startup 一次性快捷方式；内嵌引导先计数、第三次先删除自启动，`RESUME_AFTER_REBOOT.bat` 提供人工恢复。
- UAC 管理员阶段只执行父进程内存中构造并经 Parser 校验的 EncodedCommand，以及真实 System32 下的 DISM/WSL；不会从用户可写仓库加载脚本，也不信任可变 `SystemRoot`/`APPDATA` 路径。
- Docker 供应链门禁把 Desktop、CLI、Compose 作为同根当前用户 bundle 验证；最低版本为 Desktop/Installer 4.88.1、CLI 29.2.0、Compose 5.1.0，并使用隔离、无 BOM、无高优先级 shadow 目录的客户端配置执行 Compose 与镜像拉取。
- 受管 Compose 项目名包含规范仓库根路径的稳定哈希，隔离不同检出目录的容器、卷和网络；`.env` 与进程环境中的 `COMPOSE_BAKE` / `BUILDX_BAKE_*` 均被拒绝。
- Windows 续作不执行全局 `wsl --shutdown`；Docker 安装、修复或升级前发现活动 Desktop/Engine/容器会 fail closed，避免误停其他 WSL 或 Docker 工作负载。
- Windows 启动链路默认拒绝远程 Docker context，原生安全并原子生成 `.env`；只有 8 个服务全部 running/healthy 且 API `/ready` 数据库为 `ok` 才报告启动成功，诊断日志统一脱敏。
- Docker smoke 成功后会保存无凭据的精确对象检查点；自动续作会分别执行 Compose `restart` 与不删除卷的 `down/up`，重新登录并核对原项目、TestRun、15 个 TestResult、Finding、Evidence 数量及其精确 ID/project/run/finding 关联、类型、SHA-256、审计 ID 和报告 SHA-256。

## 验证结果

| 检查 | 结果 |
|---|---|
| 前一稳定检查点的本机产品链路 | SQLite/回环 Mock 的迁移、API、前端、浏览器和端到端 smoke 均有通过证据；旧数字不作为本轮最终计数 |
| Windows 脚本专项 | 33 passed；当前 12 个 PowerShell 脚本通过 Windows PowerShell 5.1 与 PowerShell 7 解析 |
| Ruff / 脚本文档链接 | 通过 |
| 本轮代码回归 | **137 passed，0 failed**：Python 90 + Windows 33 + 前端组件 11 + Playwright 3 |
| Alembic / Next.js | 23 张表 upgrade/downgrade/upgrade；Next.js 16.3.3 生产构建 20 路由，均通过 |
| Compose 官方 CLI `config --quiet` | v5.5.0 退出码 0，SHA-256 与官方 release checksum 一致；仅代表静态解析 |
| Windows 一键安装现场 | 首轮 UAC 已接受；WSL web-download HTTP 403；VMP 仅暂存；未重启；无自动续作入口；Docker 未安装 |
| Docker build/up、8 服务 healthy、Docker smoke、重启持久化 | **NOT RUN** |

前一稳定检查点的烟测产物已保存在本机忽略目录和 SQLite 演示数据中；本文件不把旧运行 ID 当作本轮最终回归结果。

## 本轮发现并修复的真实问题

- 修复 SQLAlchemy 关联表声明导致 API 无法导入的问题。
- 修复 Scope Guard resolver 在函数定义时绑定，导致受控 DNS 测试不能替换的问题。
- 修复前后端 Scope、模型渠道、Agent、MCP、Report 和 Run 字段契约不一致。
- 修复审批通过后运行未恢复、暂停按钮误调用取消、模型渠道测试状态未刷新的交互问题。
- 修复显式授权公网测试误用保留地址，避免把安全拒绝错误改弱。
- 修复烟测审计断言只读第一页而漏掉早期登录事件的问题。
- 浏览器实测发现 MCP Server 列表把 5 个持久化 Tool 显示为 0；现已由 API 返回 `tool_count` 并复验为 5。
- 修复 Docker/local 首次凭据文件互相覆盖的风险；两种运行方式使用独立凭据文件。
- 修复 Compose 自定义 `API_PORT` / `WEB_PORT` 时前端 API 地址和 CORS 仍固定为 8000/3000 的问题。
- 修复自定义 `RQ_QUEUE` 仅进入 API、Worker 仍固定监听 `whaleguard` 导致队列分叉的问题。
- 新增 Windows 宿主兼容预检、一键 UAC 提升、可审计续作状态和人工恢复入口；不满足 Windows/VirtualBox 门禁时 fail closed。
- 修复 Windows `.env` 生成依赖宿主 Python、非原子写入和可能覆盖现有文件的问题。
- 修复启动仅检查 API/Web、未验证全部 Compose 服务与数据库 readiness 的问题，并让缺失 health 字段 fail closed。
- 修复验证脚本自动猜 Docker/Local 凭据和 Mock LLM 地址的问题，改为显式运行模式。
- 增加远程 Docker context 拒绝、逐服务 Doctor 诊断和持久化日志脱敏。
- 增加真实 RQ Worker 注册/心跳/队列健康检查，并要求 smoke 等到 15 个 Worker 回调及持久化结果。
- 增加精确持久化检查点，自动验证同一批数据库对象、Evidence 数量及精确身份/关联/哈希、审计 ID 和报告哈希在 Compose `restart` 与 `down/up` 后保持不变。

## 剩余非关键项

- **发布关键项：** 先升级 Windows 23H2 build 22631，并升级或卸载 VirtualBox 5.2.30；通过兼容门禁后重新运行一键安装，再补跑完整镜像构建、8 服务启动、PostgreSQL/Redis/RQ、Docker smoke、重启和 down/up 持久化。
- 使用用户自有且明确授权的兼容渠道做可选 provider 兼容性矩阵；仓库不会附带真实 API Key。
- 扩展报告 PDF、组织级 SSO、分布式对象存储和多节点 worker。这些不影响当前本地实验闭环。

最终交付摘要见根目录 [`FINAL_STATUS.md`](../FINAL_STATUS.md)。
