# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 风格，并使用[语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

## [0.2.0] - 2026-09-01

WhaleGuard AI RedLab v0.2.0 Beginner Experience / Academy 正式发布版本。

### Added

- 增加默认 Beginner Mode、完整 Advanced Mode 和账号级体验偏好；首次登录通过 4 步 Onboarding 检查真实系统状态并直接进入第一课或网站体检。
- 新手首页围绕“继续学习 / 检查我的网站 / 查看最近结果”，隐藏底层工程对象，同时保留高级工作台原有能力。
- Academy 增加 10 个中文微课程、视觉学习路线、三级 Hint、独立完整解法、Attack Story、Vulnerable/Hardened 对照、受限鲸鱼导师、三题知识回顾、10 维技能进度和明确下一课。
- 17 个场景使用独立 metadata 映射 OWASP GenAI LLM Top 10 2026 与 OWASP Top 10 for Agentic Applications 2026。
- 增加新手 Finding 五问视图和折叠技术详情。
- 增加面向新手的 API、Database、Redis、Worker、Labs 与 AI Provider 系统状态接口。

### Changed

- 网站体检简化为“输入网址 → 确认授权 → 安全只读检查 → 查看报告”；Project 与精确 URL Scope 可由向导安全创建，真实模型改为可选增强。
- Windows 一键启动可识别并安全接管同一仓库的旧 Compose 项目，避免路径哈希项目与历史卷并存导致端口冲突。
- Academy 的“重置本关”只重置易失实验状态，保留总进度、Session、Finding、Evidence、Report、Project 和 Docker volume。

### Fixed

- DeepSeek/OpenAI-compatible AI 解读支持 JSON Mode、代码围栏、JSON 前后文字和分段文本；使用严格 Pydantic Schema 分类脱敏解析失败，绝不覆盖确定性 Finding。
- 增加“只重新生成 AI 解读”接口；不会重新请求被测网站。
- Windows Docker Desktop 4.88.x 的受限陈旧零字节 AF_UNIX socket 可在严格归属验证后进行可恢复隔离，不删除用户数据或 volume。
- SBOM/镜像清单在 Docker Desktop containerd 镜像存储下按 OCI index 对应的平台 manifest 验证运行容器，分别记录索引、manifest 与容器 config digest，不再把不同层级的合法 SHA-256 误判为镜像漂移。

### Security

- 新手网站向导仍要求明确授权、逐跳 Scope Guard 与 RBAC；默认仅允许安全只读级别，不扩大域名、路径或协议范围。
- 自动项目、Scope、AI 重试、偏好修改和实验重置均写入审计；AI 错误和 Provider 响应保持脱敏。
- Scope Guard 改为所有目标显式授权，loopback、RFC1918 与 ULA 也不再隐式放行；仅保留三个固定、只读且响应有界的内置健康检查例外，以及默认 Demo Lab 的三个精确 URL Scope。
- MCP 配置与响应序列化统一执行规范化递归脱敏，覆盖大小写、Unicode、分隔符、`Authorization: Bearer`、赋值字符串和 `{name,value}` 结构，避免旧记录或替代字段形状回传敏感值。
- AgentArena 响应限制为 1 MiB，并严格校验 JSON 对象、metrics 与 trace/tool 数组的嵌套类型；损坏、超限或结构异常的上游响应失败关闭。
- 登录 `next` 参数使用稳定解码和本地绝对路径白名单，拒绝协议相对 URL、反斜杠、控制字符、超长值与多层编码外部跳转。
- Windows Compose 项目接管新增当前仓库绑定的持久选择标记；即使新版 Compose 省略可选 environment-file 标签，仍必须通过工作目录、配置文件、服务拓扑和 volume 归属的完整匹配。

## [0.1.1] - 2026-08-31

WhaleGuard AI RedLab v0.1.1 Hardening 正式发布版本。

### Added

- 增加 WhaleGuard Academy Range：17 个 LLM/RAG/Agent/MCP 教学场景、Vulnerable/Hardened A/B、确定性事件判定、Attack Trace、Hint/Walkthrough、学习评分、动态 `WHALE_LAB_FAKE_*` canary、Reset/Replay，以及 Finding/Evidence/Report 闭环。
- `mock-agent` 增加八个 Academy 私网逻辑组件：Agent、RAG、Vector DB、MCP Hub、Mock Tools、Fake Enterprise API、Mock Identity Provider 与 Internal Collector；全部使用 action allow-list 且不执行公网网络或 Shell。
- 增加 `OutboxEvent`、`DeliveryReceipt` 和 `RunEvent` 数据模型，以及冻结的 `0001`、事件存储 `0002` 与 Outbox 所属关系 `0003` 迁移，为 at-least-once 投递、幂等消费和可分页事件流建立持久化基础。
- `delivery_receipts` 使用 `(run_id, delivery_id)` 唯一约束并记录 payload hash；`run_events` 使用 `(run_id, sequence)` 唯一约束，Outbox 增加调度与聚合查询索引。
- 增加事务提交后的 Outbox dispatcher 与周期泵；Redis 暂时不可用时事件保持 `pending`，按有界退避重新投递。
- Worker 使用 Outbox UUID 作为稳定 `delivery_id`，RQ 作业按 `1, 2, 5, 10, 30` 秒执行最多 5 次受限重试。
- 增加 `RunEvent` 历史游标 API；SSE 支持 `cursor` 和 `Last-Event-ID` 断点续读，每批最多读取 100 条，不一次加载完整历史。
- 增加 GitHub Actions `CI`：分别运行后端/Scope Guard/Worker/API、前端、PostgreSQL+Redis+RQ、八服务 Docker smoke 和 Playwright 关键流程。
- 增加 `Supply Chain Security`：Dependency Review、pip/npm 审计、Trivy 文件系统/Secret/配置/镜像扫描，以及 Syft 源码与八服务镜像 SPDX/CycloneDX SBOM。
- 增加手工触发的无签名 Release Candidate 工作流；在不创建 tag 或 GitHub Release 的前提下生成源码包、release metadata、源码 SBOM、Trivy 报告和 `SHA256SUMS`。
- 增加 Docker resilience 验收入口：三 Worker 注册与真实消费、Redis 暂停/恢复、API 停机回调重试、Worker 重启、20 路重复 callback、不同 delivery 独立处理，并在结束时恢复标准单 Worker/八服务拓扑。
- 增加幂等的 Redis v0.1.0 命名卷所有权迁移入口；它只接受当前 Compose 项目唯一且标签匹配、无 local-driver bind 选项的 `redis_data`，以无网络、只读根文件系统、仅含 `CHOWN` 与 `DAC_READ_SEARCH` 能力的一次性 helper 修复旧 root-owned AOF/RDB，绝不删除受管卷。

### Changed

- 迁移会按 sequence/时间顺序将旧 `TestRun.event_log` 回填到 `run_events`；旧 JSON 字段暂时保留以兼容现有 API，不扩大历史 payload。
- `RunEvent` 成为事件权威来源；载荷在持久化前递归脱敏并限制为 64 KiB，旧 `TestRun.event_log` 在 OpenAPI 中标记 deprecated。
- API、Worker、Policy Engine、Web 和三个 AgentArena Mock 服务的版本元数据统一为 `0.1.1`；开发分支仍保持 `[Unreleased]`，不代表正式 tag 已创建。
- Redis 主服务固定以 `redis` 用户、`cap_drop: ALL` 和 `no-new-privileges` 运行；Windows 一键启动与 `make dev` / `make docker-up` 会在主服务启动前自动执行旧卷兼容迁移。

### Fixed

- Worker callback 在同一数据库事务中完成业务写入与 `DeliveryReceipt`：只接受该 Run 已签发的 Outbox `delivery_id`；相同 ID/相同内容重复投递返回幂等成功且不重复改变评分或事件；相同 ID/不同内容返回 `409` 并记录拒绝审计；事务回滚后仍可安全重试。
- Worker 对短暂 API/DNS/限流/5xx 故障执行 6 次有界回调尝试（累计退避 25 秒，每次请求超时 10 秒），保持同一 `delivery_id`，超限后再交由 RQ Retry 兜底。
- Outbox 通过外键绑定所属 Run 并级联清理；dispatcher 在入队前再次拒绝孤儿事件，避免删除 Run 后残留 payload 被重新投递。
- 人工审批与运行启动改为数据库行锁保护的原子状态迁移；并发批准只会调度一次，`execute_run` 只领取 `queued` 运行，异常事务会先回滚再独立记录失败，且不会覆盖已完成、已取消或等待审批状态。
- Windows 启动入口从当前 PowerShell 运行时的绝对模块路径加载 Authenticode cmdlet，避免父进程污染 `PSModulePath` 时误载 PowerShell 7 同名模块或命令 shadow，仍保持 Docker 二进制签名的 fail-closed 校验。
- Windows Docker 目标解析不再依赖可能陈旧或指向远端的用户 context；签名 CLI 只探测两个 allowlist 内的本地 Docker Desktop named pipe，环境覆盖仍一律阻断。
- `START_WHALEGUARD.bat` 会在验证官方签名、安装路径和现有进程归属后按需隐藏启动 Docker Desktop，并有界等待本地 Linux Engine；其他停止、检查和重置入口仍不会隐式启动 Docker。
- 单次 Docker Engine named-pipe readiness probe 增加 5 秒进程级硬超时；后端 socket 存在但不响应时会有界终止探针并继续受总启动时限约束，不再无限等待进程或输出流。
- Windows Redis 迁移门禁把 Docker inspect 的 `CapAdd: null` 严格规范化为空能力集合；任何非空或未知 capability 仍会 fail-closed 拒绝执行。
- Redis 迁移脚本经 UTF-8/Base64 固定执行器传给 Docker，并继续对编码后的完整命令做精确元数据校验，避免 Windows PowerShell 5.1 截断含引号的原生命令参数。

### Security

- Academy 拒绝高置信度真实凭证格式且校验错误不回显输入；场景执行不接受目标 URL，Collector 只记录虚构训练标记，Docker `arena` 仍为 internal 且 Mock 服务不发布宿主端口。
- 所有 GitHub Actions 使用只读顶层权限、job timeout 和完整 commit SHA 固定第三方 Action；策略检查拒绝 `pull_request_target`、仓库 secrets 引用和浮动 Action 标签。
- Trivy 采用 deny-by-default；当前唯一例外是 `apps/api/Dockerfile` 上有负责人、影响说明和到期日的路径级 DS-0031 误报。其余未忽略的 High/Critical 阻断，Medium/Low、Secret、许可证与完整审计报告继续保留。

### Documentation

- 增加 Academy 17 关状态表、架构、安全边界、API、评分规则、第一关流程与验收命令。
- 增加 v0.1.1 发布手册、阻断式验收清单、GitHub PR/Release 模板和自动生成 Release Notes 的分类配置。
- README 第一屏改为产品定位、稳定基线、最短启动方式与真实界面预览。
- 演示指南增加可复用的 5 分钟讲解节奏、演示前检查和不夸大现场状态的规则。
- 首次运行指南同步 v0.1.0 Docker 验收事实；早期阻塞记录标记为历史快照，避免与当前状态混淆。
- 建立截图资产清单；补齐 AgentArena、Finding 和报告三张真实环境截图并登记尺寸与 SHA-256，不使用设计稿或伪造占位图。

## [0.1.0] - 2026-08-31

### Added

- WhaleGuard AI RedLab monorepo：FastAPI、Next.js、RQ worker、Scope Guard 与 AgentArena。
- 20 个核心数据库模型、Alembic、RBAC、JWT/CSRF、Argon2 和加密模型密钥。
- 15 个无破坏性安全测试模板、规则评分、Finding、证据和多格式报告。
- OpenAI-compatible 模型调用适配、显式可选 LLM Judge 与安全降级到规则评分。
- MCPShield 静态元数据风险分析，不执行未知 Tool。
- mock-llm、mock-agent、mock-mcp-server 本地演示服务。
- Docker Compose 私有网络、Windows 一键脚本、Linux/WSL 文档与统一验收脚本。
- `INSTALL_WHALEGUARD_DOCKER.bat` Windows 首次安装入口、一次 UAC 提升、有界且崩溃安全的当前用户 Startup 续作和 `RESUME_AFTER_REBOOT.bat` 人工恢复入口。
- Docker Desktop/CLI/Compose 同根签名与安全版本门禁、官方安装器逐次刷新和旧版/不完整 bundle 修复；隔离 Docker 客户端配置阻断远程 context、环境覆盖、凭据 helper 与 Compose 插件 shadow。
- Windows 宿主兼容预检、Docker 安装包签名检查、Linux containers/`hello-world` 门禁，以及逐服务 Doctor 诊断和脱敏操作日志。
- RQ Worker 注册、心跳 TTL 与队列一致性健康检查，以及 `restart`、`down/up` 两阶段精确持久化验收。
- 17 个可操作中文页面、暗/亮主题、响应式导航、ECharts 与 React Flow 可视化。
- 本地端到端烟测、Playwright 流程和三张浏览器实测截图。

### Security

- 默认阻止未授权公网目标、非 HTTP(S) 协议、云元数据地址、IPv4-mapped IPv6 绕过和重定向逃逸。
- 默认服务端口仅绑定 `127.0.0.1`，AgentArena 服务不发布宿主机端口。
- Windows 脚本默认拒绝远程 Docker context；`.env` 使用系统加密随机数和同目录原子移动生成，已有文件不会被静默覆盖。
- 一键安装器不自动重启；不满足 Windows 构建或 VirtualBox 兼容门禁时在安装前安全停止。
- 受管 Compose 项目名按规范仓库路径哈希隔离；拒绝 `.env` 和进程环境中的 Bake/Buildx 覆盖，且安装/升级不会全局关闭 WSL 或打断已运行的 Docker 工作负载。
- UAC 前置阶段改用内存 Parser 校验的 EncodedCommand 和真实 System32 可执行文件，消除高完整性进程加载用户可写仓库代码及 `SystemRoot`/`APPDATA` 环境重定向。

### Fixed

- Compose 自定义 `API_PORT` / `WEB_PORT` 时同步更新前端 API 地址和 API CORS 来源。
- API 与 Worker 统一使用同一 `RQ_QUEUE`，避免自定义队列时任务无人消费。
- 启动成功门禁覆盖全部 8 个 Compose 服务，并额外验证 API `/ready` 的数据库状态；缺失或未知 health 状态按失败处理。
- 验证与 smoke 脚本改为显式 `Docker` / `Local` 模式，分别使用私有网络和回环 Mock LLM 地址及对应凭据文件。
- Windows 启动、检查和验证输出统一脱敏，避免 URL userinfo、Bearer、Cookie、Token 或密钥进入操作日志。
- Docker smoke 保存无凭据的对象检查点，并以原项目、Run、Result、Finding、审计 ID 和报告 SHA-256 阻止持久化假阳性。
