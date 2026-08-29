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
