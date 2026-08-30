# WhaleGuard AI RedLab

> 鲸盾 AI 安全红队实验平台 — 面向本地实验环境、自有系统和获得明确授权目标的开源 AI 安全评估工作台。

**Local-first, auditable LLM / Agent / MCP security evaluation workbench.**

WhaleGuard 把 LLM/Agent 测试、MCP 元数据风险分析、Scope Guard、证据链、Finding 与多格式报告放在一套可审计的本地平台中。默认中文界面；内置演示目标位于 Docker 私有网络，任何网络测试都必须先经过授权范围与审批策略。

[5 分钟演示](docs/DEMO_GUIDE.md) · [架构说明](docs/ARCHITECTURE.md) · [v0.1.1 发布门禁](docs/RELEASE.md) · [截图资产](docs/screenshots/README.md)

## 当前状态

| 项目 | 状态 |
| --- | --- |
| 稳定基线 | `v0.1.0` → `a9746d65800e9ff5d590123d589282ecde09c409` |
| 基线运行证据 | 2026-08-31：Docker 8/8 healthy，API `/ready` 数据库 `ok`，smoke/RQ/restart/down-up 持久化已验证 |
| 开发版本 | `v0.1.1 Hardening`：可靠性、CI 与安全供应链；**NOT READY TO TAG** |
| 发布原则 | v0.1.1 必须在最终 commit 上重新跑完全部门禁，不继承 v0.1.0 的测试结果 |

下面是本地演示环境的真实 Dashboard，不是设计稿。点击可查看原图。

<a href="docs/screenshots/dashboard-dark.png"><img src="docs/screenshots/dashboard-dark.png" alt="WhaleGuard 系统总览真实截图" width="900"></a>

## 最短启动

Windows 11 已安装并启动 Docker Desktop：

```powershell
.\START_WHALEGUARD.bat
```

Linux / WSL2：

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

入口先做宿主兼容预检，通过后申请一次 UAC；它不会自动重启。不满足 Windows/虚拟化兼容门禁时会在安装前停止并说明原因。只有提升阶段成功且确实需要重启时，才会注册当前用户 Startup 中有三次硬上限的一次性续作入口；手工恢复入口为 `RESUME_AFTER_REBOOT.bat`。流程会验证 WSL、Docker 官方安装器与同根 Desktop/CLI/Compose 签名、隔离的本地 Docker context、Linux containers 和 `hello-world`，再构建并验证 WhaleGuard、真实 RQ 消费及 `restart`/`down-up` 数据持久化。已有符合安全门禁的当前用户 Docker Desktop 可直接双击 `START_WHALEGUARD.bat`。详见 [第一次运行指南](RUN_ME_FIRST.md)。

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

Windows 首次 `.env` 由 Windows PowerShell 5.1 和系统加密随机数生成器原子创建，Docker 启动路径不要求宿主机安装 Python/Node。脚本默认拒绝远程 Docker context 和 Bake/Buildx 覆盖，并使用仓库路径哈希隔离 Compose 资源；安装/升级不会全局关闭 WSL，也不会在检测到活动 Docker 工作负载时继续。启动会等待全部 8 个服务 healthy 并检查数据库 readiness；脱敏运行日志位于 `.local/logs/`，安装日志位于 `.local/setup-logs/`。请限制凭据文件的访问范围；重置演示环境时会随机轮换密码。仓库和演示数据中不包含固定管理员密码或真实 API Key。

Linux/WSL 用户若 `id -u` 或 `id -g` 不是 `1000`，应在生成 `.env` 后把 `WHALEGUARD_APP_UID` / `WHALEGUARD_APP_GID` 改为当前非 root 用户的实际 UID/GID，再执行 `make docker-up`，否则 API 容器可能无法写入宿主机的 `.local` 目录。详见对应部署文档。

## 主要能力

- 项目、授权 Scope、模型渠道、Agent、测试集、运行、Finding、证据、报告、知识库与审计统一管理。
- 15 种安全公开测试模板；确定性规则评分优先，可选 LLM Judge。
- OpenAI-compatible 模型渠道，适配 OpenAI / DeepSeek / GLM / Qwen / Ollama 协议；密钥加密保存且 API 永不回传明文。
- MCPShield 仅导入配置和 Tool 元数据，识别描述投毒、命令/网络/文件/环境变量权限及缺少审批，不自动执行未知 Tool。
- AgentArena 提供 mock-llm、mock-agent、mock-mcp-server；敏感演示工具默认拒绝或等待审批。
- Scope Guard 检查协议、目标、解析 IP、Scope、授权到期、请求类型、Tool 风险与人工审批；逐跳复检重定向并阻止混合 DNS 解析绕过。
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
- [开发与测试](docs/DEVELOPMENT.md)
- [演示指南](docs/DEMO_GUIDE.md)
- [发布手册与 v0.1.1 Checklist](docs/RELEASE.md)
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

欢迎提交聚焦、可验证的修复。请先阅读 [CONTRIBUTING](CONTRIBUTING.md) 与 [SECURITY](SECURITY.md)，在 PR 中如实填写实际测试、未运行项和安全边界。v0.1.1 只接收可靠性、CI、安全供应链和必要文档；真实大模型与动态 Agent/MCP Benchmark 属于后续版本。

## 许可证

Apache License 2.0。详见 [LICENSE](LICENSE) 和 [NOTICE](NOTICE)。
