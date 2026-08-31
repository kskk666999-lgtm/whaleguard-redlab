# WhaleGuard AI RedLab

> **Learn AI Security · Check Your Own AI App · Local-first · Safe by Default**

鲸盾 AI 安全红队实验平台面向本地实验环境、自有系统和获得明确授权的目标。第一次打开不需要理解 Project、Scope、Run、Finding 或 Docker：直接开始第一课，或者对自己的网站做安全只读体检。

学习内置 Academy 不需要 API Key、云服务器、Kali、Burp、Python 或 Node。切换到高级模式后，完整的 LLM/Agent 测试、MCPShield、Scope Guard、证据链、Finding、报告、RBAC、队列与审计能力仍然保留。

[GitHub 仓库](https://github.com/kskk666999-lgtm/whaleguard-redlab) · [Academy](docs/ACADEMY_RANGE.md) · [网站安全体检](docs/WEBSITE_SCAN_QUICKSTART.md) · [DeepSeek 可选增强](docs/DEEPSEEK.md) · [新手第一次运行](RUN_ME_FIRST.md) · [架构说明](docs/ARCHITECTURE.md) · [发布门禁](docs/RELEASE.md) · [截图资产](docs/screenshots/README.md)

## 当前状态

| 项目 | 状态 |
| --- | --- |
| 最新正式版本 | [`v0.2.0 Beginner Experience / Academy`](https://github.com/kskk666999-lgtm/whaleguard-redlab/releases/tag/v0.2.0)（2026-09-01） |
| 上一稳定基线 | `v0.1.1 Hardening` → `dbbbd000067b4c161d6ff9029882c77a226d8101`（2026-08-31） |
| 已验证运行状态 | Docker 8/8 healthy，API `/ready` 数据库 `ok`；完整回归、真实 RQ、17 关 V/H、网站体检、restart 与 down/up 持久化均通过 |
| 发布原则 | 只把 annotated tag 指向、CI、供应链扫描、附件回读均通过的版本称为正式 Release |

下面是本地演示环境的真实 Dashboard，不是设计稿。点击可查看原图。

<a href="docs/screenshots/dashboard-dark.png"><img src="docs/screenshots/dashboard-dark.png" alt="WhaleGuard 系统总览真实截图" width="900"></a>

## 新手 Quick Start

### Windows 11

1. Docker Desktop 已安装时，双击：

```powershell
.\START_WHALEGUARD.bat
```

2. 脚本会按需安全启动 Docker、恢复 WhaleGuard 并打开浏览器。
3. 从 `.local\first-run-credentials.txt` 获取随机管理员密码并登录。
4. 首页点击 **开始第一课**。只学习内置 Academy 时不需要配置 API Key。

若尚未安装 Docker Desktop，先双击 `INSTALL_WHALEGUARD_DOCKER.bat`，安装器会完成兼容检查和安全安装；不会默认配置开机自启动。

### Linux / WSL2

```bash
make docker-up
```

启动完成后访问 <http://127.0.0.1:3000>。API 和 OpenAPI 分别位于 <http://127.0.0.1:8000>、<http://127.0.0.1:8000/docs>。

> [!WARNING]
> 本项目不提供 C2、WebShell、恶意载荷、凭据窃取、爆破、持久化、免杀、任意 Shell、未授权公网扫描或自动利用。只能用于你拥有或已取得明确授权的系统。

## 安装与启动细节

### Windows 11 首次安装

双击首次安装入口：

```powershell
.\INSTALL_WHALEGUARD_DOCKER.bat
```

入口先做宿主兼容预检，通过后申请一次 UAC；它不会自动重启。不满足 Windows/虚拟化兼容门禁时会在安装前停止并说明原因。只有提升阶段成功且确实需要重启时，才会注册当前用户 Startup 中有三次硬上限的一次性续作入口；手工恢复入口为 `RESUME_AFTER_REBOOT.bat`。流程会验证 WSL、Docker 官方安装器与同根 Desktop/CLI/Compose 签名、固定的本地 Docker Desktop named-pipe endpoint、Linux containers 和 `hello-world`，再构建并验证 WhaleGuard、真实 RQ 消费及 `restart`/`down-up` 数据持久化。已有符合安全门禁的当前用户 Docker Desktop 可直接双击 `START_WHALEGUARD.bat`。详见 [第一次运行指南](RUN_ME_FIRST.md)。

### Linux / WSL2

要求：Docker Engine 24+、Compose v2、至少 4 GB 可用内存。

```bash
python scripts/bootstrap_env.py
make docker-up
```

启动后：

- 控制台：<http://127.0.0.1:3000>
- API：<http://127.0.0.1:8000>
- OpenAPI：<http://127.0.0.1:8000/docs>

首次启动会创建用户名 `admin`（邮箱 `admin@whaleguard.local`）。随机一次性密码只写入被 Git 忽略的 `.local/first-run-credentials.txt`；服务日志只记录该文件路径，不输出密码：

```bash
cat .local/first-run-credentials.txt
```

Windows 首次 `.env` 由 Windows PowerShell 5.1 和系统加密随机数生成器原子创建，Docker 启动路径不要求宿主机安装 Python/Node。脚本阻断 Docker 客户端环境覆盖并忽略可变的用户 context，只探测两个 allowlist 内的本机 Docker Desktop named pipe；同时拒绝 Bake/Buildx 覆盖，并使用仓库路径哈希隔离 Compose 资源。安装/升级不会全局关闭 WSL，也不会在检测到活动 Docker 工作负载时继续。启动会等待全部 8 个服务 healthy 并检查数据库 readiness；脱敏运行日志位于 `.local/logs/`，安装日志位于 `.local/setup-logs/`。请限制凭据文件的访问范围；重置演示环境时会随机轮换密码。仓库和演示数据中不包含固定管理员密码或真实 API Key。

若 Docker Desktop 已安装但尚未运行，`START_WHALEGUARD.bat` 会先验证官方签名、固定安装路径和进程归属，再以隐藏窗口启动它并有界等待本地 Linux Engine；不会连接远程 context。

Linux/WSL 用户若 `id -u` 或 `id -g` 不是 `1000`，应在生成 `.env` 后把 `WHALEGUARD_APP_UID` / `WHALEGUARD_APP_GID` 改为当前非 root 用户的实际 UID/GID，再执行 `make docker-up`，否则 API 容器可能无法写入宿主机的 `.local` 目录。详见对应部署文档。

## 主要能力

- 默认新手模式只显示首页、Academy、网站体检、Findings、报告和帮助；用户偏好保存在账号中。高级模式完整保留原有安全工作台。
- WhaleGuard Academy 提供 10 个 3～5 分钟中文微课程与 17 个 LLM/RAG/Agent/MCP 实验；每关使用“学 → 猜 → 做 → 看 → 修 → 再测 → 总结”，并提供三级 Hint、主动完整解法、Attack Story、Vulnerable/Hardened 对照、受限鲸鱼导师、知识回顾、技能进度和下一课。
- 17 个实验独立映射到 OWASP GenAI LLM Top 10 2026 与 OWASP Top 10 for Agentic Applications 2026；不相关风险不会强行贴标签。
- Academy 的 Agent、RAG、MCP、Identity、Collector、Canary 与企业数据均为本项目私网中的虚构训练数据，不接受真实目标 URL，也不执行公网请求。
- “网站安全体检”只需输入网址、确认授权、选择安全只读级别并开始；后台自动建立隔离 Project、精确临时 Scope、Finding、Evidence 和 Report。真实模型是可选增强，解析失败不影响确定性结果，还可只重试 AI 解读而不重新访问目标。
- 项目、授权 Scope、模型渠道、Agent、测试集、运行、Finding、证据、报告、知识库与审计统一管理。
- 15 种安全公开测试模板；确定性规则评分优先，可选 LLM Judge。
- OpenAI-compatible 模型渠道，适配 OpenAI / DeepSeek / GLM / Qwen / Ollama 协议；密钥加密保存且 API 永不回传明文。
- MCPShield 仅导入配置和 Tool 元数据，识别描述投毒、命令/网络/文件/环境变量权限及缺少审批，不自动执行未知 Tool。
- AgentArena 提供 mock-llm、mock-agent、mock-mcp-server；敏感演示工具默认拒绝或等待审批。
- 本地网站被动体检靶页复用 `mock-agent`，容器内目标为 `http://mock-agent:8102/demo-site`；它只含虚构静态数据和刻意缺失的浏览器安全加固，不新增宿主端口或第九个服务。详见[靶页说明](docs/MOCK_WEBSITE_LAB.md)。
- Scope Guard 对公网、loopback 和私网目标一律要求当前项目内的显式精确授权，检查协议、目标、解析 IP、Scope、授权到期、请求类型、Tool 风险与人工审批；逐跳复检重定向并阻止混合 DNS 解析绕过。
- TestRun 支持队列状态、暂停、取消、失败重试和进度；事务型 Outbox、稳定 `delivery_id` 与数据库 receipt 负责幂等回调。
- 规范化 RunEvent 提供 SSE cursor、`Last-Event-ID` 与分页历史；事件递归脱敏并限制 payload 大小。证据记录 SHA-256 哈希。
- HTML、Markdown、JSON 报告；RBAC 角色为 Admin、Security Engineer、Reviewer、Viewer。

## Monorepo

```text
whaleguard-redlab/
├─ apps/
│  ├─ web/                 Next.js 控制台
│  ├─ api/                 FastAPI / SQLAlchemy / Alembic
│  └─ worker/              Redis + RQ 规则评估 worker
├─ packages/
│  ├─ shared/              跨服务 Schema 与枚举
│  └─ policy-engine/       独立 Scope Guard
├─ test-cases/             15 个安全内置模板
├─ labs/
│  ├─ mock-llm/
│  ├─ mock-agent/
│  └─ mock-mcp-server/
├─ infra/docker/           容器安全配置
├─ docs/                   架构、安全、API、开发与部署文档
├─ scripts/                初始化、验证与验收脚本
└─ docker-compose.yml
```

## 常用命令

```bash
make dev          # 生成本地 .env 并以前台方式启动
make test         # 后端、策略、worker 和前端组件测试
make lint         # Ruff、ESLint、TypeScript
make format       # Python/前端格式化
make seed         # 幂等创建本地 SQLite 演示数据
make reset        # 只重建本地 SQLite 数据与本地首次凭据
make docker-up
make docker-down
make docker-resilience  # PostgreSQL + Redis + 多 Worker 故障恢复专项
make verify       # 完整静态、测试、构建、Playwright 与 Compose 配置验收
```

`make seed` 是不依赖 Docker 的本机 SQLite 流程：数据库位于 `.local/whaleguard-dev.db`，随机凭据位于 `.local/local-first-run-credentials.txt`。Docker Compose 使用 PostgreSQL，首次凭据仍位于 `.local/first-run-credentials.txt`；两种凭据不可混用。

从 v0.1.0 升级时，旧 Redis AOF/RDB 可能由 root 拥有。`START_WHALEGUARD.bat`、`make dev` 和 `make docker-up` 会自动运行受限且幂等的所有权迁移，并把同一个受控项目名传给迁移与 Compose：Windows 一键流程继续使用仓库路径哈希，Linux/WSL Make 流程保留 v0.1.0 的 `whaleguard-redlab`，因此不会悄悄切到一套空卷。迁移只接受当前项目标签匹配的 `redis_data`，不会删除卷，常驻 Redis 仍全程以非 root 身份运行；不要绕过这些入口直接运行未带项目名的 Compose。

不使用 Make 时可直接运行文档中的等价命令。Windows 11 + WSL2 见 [部署说明](docs/deployment-windows-wsl2.md)，Linux 见 [Linux 部署](docs/deployment-linux.md)。

## 文档

- [版本变更记录](CHANGELOG.md)
- [架构说明](docs/ARCHITECTURE.md)
- [安全模型与 Scope Guard](docs/SECURITY_MODEL.md)
- [API 使用](docs/API.md)
- [Academy Range：17 关、边界与第一关](docs/ACADEMY_RANGE.md)
- [网站一键体检最简说明](docs/WEBSITE_SCAN_QUICKSTART.md)
- [DeepSeek 连接与 AI 解读](docs/DEEPSEEK.md)
- [开发与测试](docs/DEVELOPMENT.md)
- [演示指南](docs/DEMO_GUIDE.md)
- [本地网站被动体检靶页](docs/MOCK_WEBSITE_LAB.md)
- [发布手册与 v0.2.0 Checklist](docs/RELEASE.md)
- [实机截图资产清单](docs/screenshots/README.md)
- [故障排查](docs/TROUBLESHOOTING.md)
- [GitHub 示例报告](docs/examples/whaleguard-demo-report.md)

## 实机界面

以下截图来自本地运行的真实页面和虚构演示数据，不是设计稿。Dashboard 已在 README 第一屏展示。

![AgentArena 私网模拟服务与权限围栏](docs/screenshots/agentarena.png)

![MCPShield Tool 元数据](docs/screenshots/mcpshield.png)

![Finding 详情、修复建议与证据入口](docs/screenshots/finding-detail.png)

![HTML 安全评估报告预览](docs/screenshots/report-preview.png)

以下测试运行详情是规范化 RunEvent 与 SSE 事件流的补充画面：

![测试运行详情](docs/screenshots/runs.png)

v0.1.1 的公开截图矩阵：

- ✅ Dashboard：[`dashboard-dark.png`](docs/screenshots/dashboard-dark.png)
- ✅ AgentArena：[`agentarena.png`](docs/screenshots/agentarena.png)
- ✅ MCPShield：[`mcpshield.png`](docs/screenshots/mcpshield.png)
- ✅ Finding 详情：[`finding-detail.png`](docs/screenshots/finding-detail.png)
- ✅ HTML 报告预览：[`report-preview.png`](docs/screenshots/report-preview.png)
- ✅ 测试运行详情：[`runs.png`](docs/screenshots/runs.png)

尺寸、SHA-256 与捕获要求见[截图资产清单](docs/screenshots/README.md)。

## 参与贡献

欢迎提交聚焦、可验证的修复。请先阅读 [CONTRIBUTING](CONTRIBUTING.md) 与 [SECURITY](SECURITY.md)，在 PR 中如实填写实际测试、未运行项和安全边界。任何新手体验都不得绕过 Scope Guard、RBAC、审批或审计。

## 许可证

Apache License 2.0。详见 [LICENSE](LICENSE) 和 [NOTICE](NOTICE)。
