# WhaleGuard AI RedLab

> 鲸盾 AI 安全红队实验平台 — 面向本地实验环境、自有系统和获得明确授权目标的开源 AI 安全评估工作台。

WhaleGuard 把 LLM/Agent 测试、MCP 元数据风险分析、Scope Guard、证据链、Finding 与多格式报告放在一套可审计的本地平台中。默认中文界面，内置演示目标均在 Docker 私有网络中，任何网络测试都必须先经过授权范围与审批策略。

> [!WARNING]
> 本项目不提供 C2、WebShell、恶意载荷、凭据窃取、爆破、持久化、免杀、任意 Shell、未授权公网扫描或自动利用。只能用于你拥有或已取得明确授权的系统。

## 快速启动

要求：Docker Engine 24+ / Docker Desktop、Compose v2、至少 4 GB 可用内存。

```bash
python scripts/bootstrap_env.py
docker compose up --build
```

启动后：

- 控制台：<http://127.0.0.1:3000>
- API：<http://127.0.0.1:8000>
- OpenAPI：<http://127.0.0.1:8000/docs>

首次启动会创建用户名 `admin`（邮箱 `admin@whaleguard.local`）。随机一次性密码只写入被 Git 忽略的 `.local/first-run-credentials.txt`；服务日志只记录该文件路径，不输出密码：

```bash
cat .local/first-run-credentials.txt
```

Windows 用户可直接双击 `START_WHALEGUARD.bat`，然后按终端显示的路径打开该文件。请限制凭据文件的访问范围；重置演示环境时会随机轮换密码。仓库和演示数据中不包含固定管理员密码或真实 API Key。

Linux/WSL 用户若 `id -u` 或 `id -g` 不是 `1000`，应在生成 `.env` 后把 `WHALEGUARD_APP_UID` / `WHALEGUARD_APP_GID` 改为当前非 root 用户的实际 UID/GID，再执行 `docker compose up --build`，否则 API 容器可能无法写入宿主机的 `.local` 目录。详见对应部署文档。

## 主要能力

- 项目、授权 Scope、模型渠道、Agent、测试集、运行、Finding、证据、报告、知识库与审计统一管理。
- 15 种安全公开测试模板；确定性规则评分优先，可选 LLM Judge。
- OpenAI-compatible 模型渠道，适配 OpenAI / DeepSeek / GLM / Qwen / Ollama 协议；密钥加密保存且 API 永不回传明文。
- MCPShield 仅导入配置和 Tool 元数据，识别描述投毒、命令/网络/文件/环境变量权限及缺少审批，不自动执行未知 Tool。
- AgentArena 提供 mock-llm、mock-agent、mock-mcp-server；敏感演示工具默认拒绝或等待审批。
- Scope Guard 检查协议、目标、解析 IP、Scope、授权到期、请求类型、Tool 风险与人工审批；逐跳复检重定向并阻止混合 DNS 解析绕过。
- TestRun 支持队列状态、暂停、取消、失败重试、进度和 SSE 事件流；证据记录 SHA-256 哈希。
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
make verify       # 完整静态、测试、构建、Playwright 与 Compose 配置验收
```

`make seed` 是不依赖 Docker 的本机 SQLite 流程：数据库位于 `.local/whaleguard-dev.db`，随机凭据位于 `.local/local-first-run-credentials.txt`。Docker Compose 使用 PostgreSQL，首次凭据仍位于 `.local/first-run-credentials.txt`；两种凭据不可混用。

不使用 Make 时可直接运行文档中的等价命令。Windows 11 + WSL2 见 [部署说明](docs/deployment-windows-wsl2.md)，Linux 见 [Linux 部署](docs/deployment-linux.md)。

## 文档

- [架构说明](docs/ARCHITECTURE.md)
- [安全模型与 Scope Guard](docs/SECURITY_MODEL.md)
- [API 使用](docs/API.md)
- [开发与测试](docs/DEVELOPMENT.md)
- [演示指南](docs/DEMO_GUIDE.md)
- [故障排查](docs/TROUBLESHOOTING.md)
- [GitHub 示例报告](docs/examples/whaleguard-demo-report.md)
- [最终验收状态](FINAL_STATUS.md)

## 实机界面

以下截图来自本地运行的真实页面和演示数据，不是设计稿：

![WhaleGuard 系统总览](docs/screenshots/dashboard-dark.png)

![MCPShield Tool 元数据](docs/screenshots/mcpshield.png)

![测试运行详情](docs/screenshots/runs.png)

## 许可证

Apache License 2.0。详见 [LICENSE](LICENSE) 和 [NOTICE](NOTICE)。
